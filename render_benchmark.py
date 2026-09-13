#!/usr/bin/env python3
"""Render same-object results from multiple method directories for a paper figure."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, ImageColor

if __package__:
    from .preview_utils import DEFAULT_PREVIEW_VIEWS, PreviewResult, generate_multiview_preview
    from .publication_utils import autocrop_image, compose_labeled_grid, export_image_pdf, sanitize_filename, save_png
    from .utils import (
        CAMERA_PRESETS,
        COLOR_THEMES,
        CameraSpec,
        NormalizationInfo,
        RenderConfig,
        fit_camera_to_points,
        load_camera,
        load_camera_metadata,
        normalize_points,
        read_xyz,
        render_point_cloud,
        resolve_color,
        resolve_shared_sphere_radius,
        save_camera,
    )
else:
    from preview_utils import DEFAULT_PREVIEW_VIEWS, PreviewResult, generate_multiview_preview
    from publication_utils import autocrop_image, compose_labeled_grid, export_image_pdf, sanitize_filename, save_png
    from utils import (
        CAMERA_PRESETS,
        COLOR_THEMES,
        CameraSpec,
        NormalizationInfo,
        RenderConfig,
        fit_camera_to_points,
        load_camera,
        load_camera_metadata,
        normalize_points,
        read_xyz,
        render_point_cloud,
        resolve_color,
        resolve_shared_sphere_radius,
        save_camera,
    )


DEFAULT_METHOD_COLORS = {
    "input": "#B8BEC8",
    "repkpu": "#E4B382",
    "grad-pu": "#91C4A8",
    "apu-ldi": "#B1A0D0",
    "ours": "#90AEDD",
    "gt": "#5F708A",
}


@dataclass(frozen=True)
class MethodSpec:
    """One method directory and its figure label."""

    name: str
    label: str
    directory: Path


@dataclass
class MatchedMethod:
    """A successfully loaded method result."""

    spec: MethodSpec
    input_path: Path
    raw_points: np.ndarray
    points: np.ndarray | None = None
    color: str = "#90AEDD"
    single_path: Path | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--method-dirs", "--method_dirs", nargs="+", type=Path)
    source.add_argument("--root-dir", "--root_dir", type=Path)
    parser.add_argument(
        "--method-names",
        "--method_names",
        nargs="+",
        help="Names paired with --method_dirs; defaults to directory names",
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        help="Ordered method subdirectories paired with --root_dir",
    )
    parser.add_argument(
        "--method-labels",
        "--method_labels",
        nargs="+",
        help="Optional display labels in the same order as the methods",
    )
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument("--target", type=Path)
    targets.add_argument("--targets", nargs="+", type=Path)
    parser.add_argument("--output-dir", "--output_dir", type=Path, required=True)
    parser.add_argument(
        "--reference-method",
        "--reference_method",
        default=None,
        help="Method used to define normalization and the preview subject; defaults to GT/Ours/first",
    )

    parser.add_argument("--preview-only", "--preview_only", action="store_true")
    parser.add_argument("--skip-preview", "--skip_preview", action="store_true")
    parser.add_argument("--camera-index", "--camera_index", type=int, default=0)
    parser.add_argument(
        "--load-camera",
        "--load_camera",
        type=Path,
        default=None,
        help="Camera JSON, directory of object camera JSONs, or a path containing {object}",
    )
    parser.add_argument("--preview-size", "--preview_size", type=int, default=640)
    parser.add_argument("--preview-columns", "--preview_columns", type=int, default=4)
    parser.add_argument("--preview-mode", "--preview_mode", choices=("glyph", "fast", "smooth"), default="fast")

    parser.add_argument("--single-size", "--single_size", type=int, default=1600)
    parser.add_argument("--cell-size", "--cell_size", type=int, default=720)
    parser.add_argument(
        "--comparison-columns",
        "--comparison_columns",
        type=int,
        default=0,
        help="0 places every available method in one row",
    )
    parser.add_argument("--gap", type=int, default=24)
    parser.add_argument("--margin", type=int, default=32)
    parser.add_argument("--label-size", "--label_size", type=int, default=30)
    parser.add_argument("--font", type=Path, default=None)
    parser.add_argument("--crop-padding", "--crop_padding", type=int, default=28)
    parser.add_argument("--no-autocrop", "--no_autocrop", action="store_true")
    parser.add_argument("--no-pdf", "--no_pdf", action="store_true")
    parser.add_argument("--pdf-dpi", "--pdf_dpi", type=float, default=150.0)

    parser.add_argument("--mode", choices=("glyph", "fast", "smooth"), default="glyph")
    parser.add_argument("--sphere-radius", "--sphere_radius", type=float, default=None)
    parser.add_argument("--size-scale", "--size_scale", type=float, default=1.0)
    parser.add_argument("--point-size", "--point_size", type=float, default=6.0)
    parser.add_argument("--sphere-resolution", "--sphere_resolution", type=int, default=12)
    parser.add_argument("--theme", choices=("blue", "grayblue", "teal", "orange", "purple"), default="blue")
    parser.add_argument("--color", default=None, help="Explicit unified color; overrides --theme")
    parser.add_argument("--color-mode", "--color_mode", choices=("unified", "per_method"), default="unified")
    parser.add_argument("--method-color-config", "--method_color_config", type=Path, default=None)
    parser.add_argument("--bg-color", "--bg_color", default="#FAFAFC")
    parser.add_argument("--shadow-mode", "--shadow_mode", choices=("none", "simple", "soft"), default="soft")
    parser.add_argument("--shadow-opacity", "--shadow_opacity", type=float, default=0.11)
    parser.add_argument("--shadow-blur", "--shadow_blur", type=float, default=32.0)
    parser.add_argument("--light-preset", "--light_preset", choices=("soft", "studio"), default="soft")
    parser.add_argument("--view", choices=tuple(CAMERA_PRESETS), default="iso")
    parser.add_argument("--azimuth", type=float, default=None)
    parser.add_argument("--elevation", type=float, default=None)
    parser.add_argument("--roll", type=float, default=None)
    parser.add_argument("--camera-scale", "--camera_scale", type=float, default=None)
    parser.add_argument("--padding", type=float, default=0.12)
    return parser.parse_args()


def build_method_specs(args: argparse.Namespace) -> list[MethodSpec]:
    """Resolve both supported directory syntaxes to one ordered method list."""

    if args.method_dirs is not None:
        if args.methods is not None:
            raise SystemExit("--methods is only valid with --root_dir")
        directories = list(args.method_dirs)
        names = list(args.method_names or [path.name for path in directories])
        if len(names) != len(directories):
            raise SystemExit("--method_names must have the same length as --method_dirs")
    else:
        if args.method_names is not None:
            raise SystemExit("--method_names is only valid with --method_dirs")
        if not args.methods:
            raise SystemExit("--root_dir requires --methods")
        names = list(args.methods)
        directories = [args.root_dir / name for name in names]

    labels = list(args.method_labels or names)
    if len(labels) != len(names):
        raise SystemExit("--method_labels must have the same length as the method list")
    if len({name.casefold() for name in names}) != len(names):
        raise SystemExit("method names must be unique (case-insensitive)")
    return [MethodSpec(name, label, directory) for name, label, directory in zip(names, labels, directories)]


def find_target(directory: Path, target: Path) -> Path | None:
    """Find a target directly first, then recursively by case-insensitive basename."""

    if not directory.is_dir():
        warnings.warn(f"method directory does not exist: {directory}", UserWarning)
        return None
    direct = directory / target
    if direct.is_file():
        return direct
    matches = sorted(
        (
            path
            for path in directory.rglob("*")
            if path.is_file()
            and path.suffix.casefold() == ".xyz"
            and path.name.casefold() == target.name.casefold()
        ),
        key=lambda path: (len(path.parts), str(path).casefold()),
    )
    if not matches:
        warnings.warn(f"{target.name} not found under {directory}", UserWarning)
        return None
    if len(matches) > 1:
        warnings.warn(
            f"multiple matches for {target.name} under {directory}; using {matches[0]}",
            UserWarning,
        )
    return matches[0]


def load_color_config(path: Path | None) -> dict[str, str]:
    """Load either a flat method-color mapping or a {'methods': ...} object."""

    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"method color config does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid color JSON: {path}") from exc
    mapping = payload.get("methods", payload) if isinstance(payload, dict) else None
    if not isinstance(mapping, dict):
        raise ValueError("method color config must be a JSON object")
    colors: dict[str, str] = {}
    for key, value in mapping.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("method color names and values must be strings")
        try:
            ImageColor.getrgb(value)
        except ValueError as exc:
            raise ValueError(f"invalid color for method {key!r}: {value!r}") from exc
        colors[key.casefold()] = value
    return colors


def resolve_method_color(
    spec: MethodSpec,
    *,
    color_mode: str,
    unified_color: str,
    configured_colors: dict[str, str],
) -> str:
    if color_mode == "unified":
        return unified_color
    for key in (spec.name.casefold(), spec.label.casefold()):
        if key in configured_colors:
            return configured_colors[key]
        if key in DEFAULT_METHOD_COLORS:
            return DEFAULT_METHOD_COLORS[key]
    return unified_color


def select_reference(methods: Sequence[MatchedMethod], requested: str | None) -> MatchedMethod:
    """Choose a stable normalization/preview reference."""

    if requested:
        key = requested.casefold()
        for method in methods:
            if key in {method.spec.name.casefold(), method.spec.label.casefold()}:
                return method
        warnings.warn(
            f"reference method {requested!r} is unavailable; using automatic fallback",
            UserWarning,
        )
    for preferred in ("gt", "ours"):
        for method in methods:
            if preferred in {method.spec.name.casefold(), method.spec.label.casefold()}:
                return method
    return methods[0]


def resolve_camera_input(path: Path | None, object_stem: str) -> Path | None:
    """Resolve a direct camera, a directory, or a {object} path template."""

    if path is None:
        return None
    raw = str(path)
    if "{object}" in raw:
        resolved = Path(raw.format(object=object_stem))
    elif path.is_dir():
        candidates = (
            path / f"{object_stem}_view_best.json",
            path / f"{object_stem}.json",
            path / object_stem / "cameras" / f"{object_stem}_view_best.json",
        )
        resolved = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    else:
        resolved = path
    if not resolved.is_file():
        raise FileNotFoundError(f"camera JSON does not exist for {object_stem}: {resolved}")
    return resolved


def normalization_from_camera(path: Path | None) -> NormalizationInfo | None:
    """Recover benchmark normalization metadata when a saved camera contains it."""

    if path is None:
        return None
    metadata = load_camera_metadata(path)
    payload = metadata.get("normalization")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("camera normalization metadata must be an object")
    try:
        center = np.asarray(payload["center"], dtype=np.float64)
        scale = float(payload["scale"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("camera normalization metadata is invalid") from exc
    if center.shape != (3,) or not np.isfinite(center).all() or not np.isfinite(scale) or scale <= 0:
        raise ValueError("camera normalization metadata must contain finite center[3] and positive scale")
    return NormalizationInfo(center=center, scale=scale)


def make_render_config(args: argparse.Namespace, color: str) -> RenderConfig:
    return RenderConfig(
        width=args.single_size,
        height=args.single_size,
        color=color,
        background=args.bg_color,
        mode=args.mode,
        sphere_radius=args.sphere_radius,
        size_scale=args.size_scale,
        point_size=args.point_size,
        sphere_resolution=args.sphere_resolution,
        view=args.view,
        azimuth=args.azimuth,
        elevation=args.elevation,
        roll=args.roll,
        camera_scale=args.camera_scale,
        padding=args.padding,
        shadow_mode=args.shadow_mode,
        shadow_opacity=args.shadow_opacity,
        shadow_blur=args.shadow_blur,
        light_preset=args.light_preset,
    )


def process_object(
    target: Path,
    *,
    specs: Sequence[MethodSpec],
    args: argparse.Namespace,
    object_dir: Path,
    configured_colors: dict[str, str],
) -> bool:
    """Run the complete preview/singles/comparison workflow for one object."""

    object_stem = target.stem
    preview_dir = object_dir / "preview"
    singles_dir = object_dir / "singles"
    comparison_dir = object_dir / "comparison"
    cameras_dir = object_dir / "cameras"
    for directory in (preview_dir, singles_dir, comparison_dir, cameras_dir):
        directory.mkdir(parents=True, exist_ok=True)

    unified_color = resolve_color(args.theme, args.color)
    matched: list[MatchedMethod] = []
    method_manifest: list[dict] = []
    for spec in specs:
        source = find_target(spec.directory, target)
        if source is None:
            method_manifest.append(
                {
                    "name": spec.name,
                    "label": spec.label,
                    "method_dir": str(spec.directory.resolve()),
                    "status": "missing",
                    "input": None,
                    "single": None,
                }
            )
            continue
        try:
            raw_points = read_xyz(source)
        except (OSError, ValueError) as exc:
            warnings.warn(f"failed to read {source}: {exc}", UserWarning)
            method_manifest.append(
                {
                    "name": spec.name,
                    "label": spec.label,
                    "method_dir": str(spec.directory.resolve()),
                    "status": "read_error",
                    "input": str(source.resolve()),
                    "error": str(exc),
                    "single": None,
                }
            )
            continue
        matched.append(
            MatchedMethod(
                spec=spec,
                input_path=source,
                raw_points=raw_points,
                color=resolve_method_color(
                    spec,
                    color_mode=args.color_mode,
                    unified_color=unified_color,
                    configured_colors=configured_colors,
                ),
            )
        )
        method_manifest.append(
            {
                "name": spec.name,
                "label": spec.label,
                "method_dir": str(spec.directory.resolve()),
                "status": "matched",
                "input": str(source.resolve()),
                "single": None,
            }
        )

    manifest_path = object_dir / "manifest.json"
    if not matched:
        payload = {
            "format_version": 1,
            "object": object_stem,
            "target": str(target),
            "status": "no_inputs",
            "methods": method_manifest,
        }
        _write_manifest(manifest_path, payload)
        warnings.warn(f"no usable method result found for {target}; skipping", UserWarning)
        return False

    loaded_camera_path = resolve_camera_input(args.load_camera, object_stem)
    reference = select_reference(matched, args.reference_method)
    normalization = normalization_from_camera(loaded_camera_path)
    normalization_source = "loaded_camera" if normalization is not None else f"reference:{reference.spec.name}"
    if normalization is None:
        _, normalization = normalize_points(reference.raw_points)
    for method in matched:
        method.points = normalize_points(
            method.raw_points,
            center=normalization.center,
            scale=normalization.scale,
        )[0]

    clouds = [method.points for method in matched if method.points is not None]
    framing_points = np.vstack(clouds)
    base_config = make_render_config(args, unified_color)
    base_config.validate()
    shared_radius = resolve_shared_sphere_radius(clouds, base_config)
    normalization_payload = {
        "strategy": "shared_reference",
        "source": normalization_source,
        "reference_method": reference.spec.name,
        "center": [float(value) for value in normalization.center],
        "scale": float(normalization.scale),
    }
    camera_metadata = {
        "object": object_stem,
        "normalization": normalization_payload,
        "render": {
            "resolved_sphere_radius": shared_radius,
            "size_scale": args.size_scale,
            "padding": args.padding,
            "shadow_mode": args.shadow_mode,
            "light_preset": args.light_preset,
        },
    }

    preview_result: PreviewResult | None = None
    if not args.skip_preview:
        preview_config = replace(
            base_config,
            width=args.preview_size,
            height=args.preview_size,
            mode=args.preview_mode,
            color=reference.color,
        )
        print(f"[{object_stem}] rendering {len(DEFAULT_PREVIEW_VIEWS)} preview views from {reference.spec.name}")
        preview_result = generate_multiview_preview(
            reference.points,
            output_dir=preview_dir,
            object_stem=object_stem,
            config=preview_config,
            sphere_radius=shared_radius,
            framing_points=framing_points,
            views=DEFAULT_PREVIEW_VIEWS,
            preview_size=args.preview_size,
            columns=args.preview_columns,
            label_size=max(18, int(round(args.label_size * 0.82))),
            font_path=args.font,
            selected_index=(
                args.camera_index
                if loaded_camera_path is None
                and args.azimuth is None
                and args.elevation is None
                and args.roll is None
                and args.camera_scale is None
                else None
            ),
            save_pdf=not args.no_pdf,
            pdf_dpi=args.pdf_dpi,
            autocrop=not args.no_autocrop,
            crop_padding=args.crop_padding,
            camera_metadata=camera_metadata,
        )

    selected_source: str
    selected_view: dict | None = None
    if loaded_camera_path is not None:
        selected_camera = load_camera(loaded_camera_path)
        selected_source = f"loaded:{loaded_camera_path.resolve()}"
    elif any(value is not None for value in (args.azimuth, args.elevation, args.roll, args.camera_scale)):
        selected_camera = fit_camera_to_points(framing_points, base_config, sphere_radius=shared_radius)
        selected_source = "manual_angles"
        selected_view = {
            "index": None,
            "azimuth": args.azimuth,
            "elevation": args.elevation,
            "roll": args.roll,
        }
    elif preview_result is not None:
        if not 0 <= args.camera_index < len(preview_result.records):
            raise SystemExit(
                f"--camera_index must be in [0, {len(preview_result.records) - 1}]"
            )
        record = preview_result.records[args.camera_index]
        selected_camera = record.camera
        selected_source = f"preview:{record.index}"
        selected_view = {
            "index": record.index,
            "azimuth": record.view.azimuth,
            "elevation": record.view.elevation,
            "roll": record.view.roll,
        }
    else:
        selected_camera = fit_camera_to_points(framing_points, base_config, sphere_radius=shared_radius)
        selected_source = f"preset:{args.view}"

    best_camera_path = cameras_dir / f"{object_stem}_view_best.json"
    best_metadata = dict(camera_metadata)
    best_metadata["selection"] = {"source": selected_source, "view": selected_view}
    save_camera(selected_camera, best_camera_path, metadata=best_metadata)

    outputs: dict[str, str | None] = {
        "preview_sheet_png": _absolute_or_none(preview_result.sheet_png if preview_result else None),
        "preview_sheet_pdf": _absolute_or_none(preview_result.sheet_pdf if preview_result else None),
        "comparison_png": None,
        "comparison_pdf": None,
    }
    if not args.preview_only:
        rendered_images: list[Image.Image] = []
        used_stems: set[str] = set()
        for index, method in enumerate(matched, start=1):
            safe_stem = _unique_stem(sanitize_filename(method.spec.name, f"method_{index:02d}"), used_stems)
            method.single_path = singles_dir / f"{safe_stem}.png"
            method_config = replace(base_config, color=method.color)
            print(f"[{object_stem} {index}/{len(matched)}] rendering {method.spec.label}")
            image_array = render_point_cloud(
                method.points,
                method.single_path,
                config=method_config,
                normalize=False,
                camera=selected_camera,
                sphere_radius=shared_radius,
            )
            rendered_images.append(Image.fromarray(image_array))

        columns = args.comparison_columns or len(rendered_images)
        comparison = compose_labeled_grid(
            rendered_images,
            [method.spec.label for method in matched],
            columns=min(columns, len(rendered_images)),
            cell_width=args.cell_size,
            cell_height=args.cell_size,
            gap=args.gap,
            margin=args.margin,
            label_size=args.label_size,
            label_gap=max(8, args.label_size // 3),
            font_path=args.font,
            background=args.bg_color,
        )
        if not args.no_autocrop:
            comparison = autocrop_image(
                comparison,
                background=args.bg_color,
                padding=args.crop_padding,
            )
        comparison_png = save_png(
            comparison,
            comparison_dir / f"{object_stem}_comparison.png",
        )
        comparison_pdf = None
        if not args.no_pdf:
            comparison_pdf = export_image_pdf(
                comparison,
                comparison_dir / f"{object_stem}_comparison.pdf",
                dpi=args.pdf_dpi,
                background=args.bg_color,
            )
        outputs["comparison_png"] = str(comparison_png.resolve())
        outputs["comparison_pdf"] = _absolute_or_none(comparison_pdf)

    present_by_name = {method.spec.name.casefold(): method for method in matched}
    for entry in method_manifest:
        method = present_by_name.get(entry["name"].casefold())
        if method is not None:
            entry.update(_method_manifest_entry(method))
    known_names = {entry["name"].casefold() for entry in method_manifest}
    for method in matched:
        if method.spec.name.casefold() not in known_names:
            method_manifest.append(_method_manifest_entry(method))

    preview_views = []
    if preview_result is not None:
        preview_views = [
            {
                "index": record.index,
                "azimuth": record.view.azimuth,
                "elevation": record.view.elevation,
                "roll": record.view.roll,
                "image": str(record.image_path.resolve()),
                "camera": str(record.camera_path.resolve()),
            }
            for record in preview_result.records
        ]
    manifest = {
        "format_version": 1,
        "object": object_stem,
        "target": str(target),
        "status": "preview_only" if args.preview_only else "complete",
        "methods": method_manifest,
        "reference_method": reference.spec.name,
        "normalization": normalization_payload,
        "camera": {
            "path": str(best_camera_path.resolve()),
            "loaded_from": _absolute_or_none(loaded_camera_path),
            "selection_source": selected_source,
            "position": list(selected_camera.position),
            "focal_point": list(selected_camera.focal_point),
            "view_up": list(selected_camera.view_up),
            "parallel_scale": selected_camera.parallel_scale,
        },
        "render": {
            "mode": args.mode,
            "resolved_sphere_radius": shared_radius,
            "manual_sphere_radius": args.sphere_radius,
            "size_scale": args.size_scale,
            "color_mode": args.color_mode,
            "theme": args.theme,
            "background": args.bg_color,
            "light_preset": args.light_preset,
            "shadow_mode": args.shadow_mode,
            "shadow_opacity": args.shadow_opacity,
            "shadow_blur": args.shadow_blur,
            "padding": args.padding,
        },
        "preview": {
            "enabled": not args.skip_preview,
            "selected_index": selected_view.get("index") if selected_view else None,
            "views": preview_views,
        },
        "outputs": outputs,
    }
    _write_manifest(manifest_path, manifest)
    print(f"[{object_stem}] manifest -> {manifest_path}")
    return True


def _method_manifest_entry(method: MatchedMethod) -> dict:
    return {
        "name": method.spec.name,
        "label": method.spec.label,
        "method_dir": str(method.spec.directory.resolve()),
        "status": "rendered" if method.single_path is not None else "matched",
        "input": str(method.input_path.resolve()),
        "point_count": int(len(method.raw_points)),
        "color": method.color,
        "single": _absolute_or_none(method.single_path),
    }


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _absolute_or_none(path: Path | None) -> str | None:
    return str(path.resolve()) if path is not None else None


def _unique_stem(stem: str, used: set[str]) -> str:
    candidate = stem
    suffix = 2
    while candidate.casefold() in used:
        candidate = f"{stem}_{suffix}"
        suffix += 1
    used.add(candidate.casefold())
    return candidate


def validate_args(args: argparse.Namespace, targets: Sequence[Path]) -> None:
    if args.preview_only and args.skip_preview:
        raise SystemExit("--preview_only cannot be combined with --skip_preview")
    if args.load_camera is not None and any(
        value is not None for value in (args.azimuth, args.elevation, args.roll, args.camera_scale)
    ):
        raise SystemExit("--load_camera cannot be combined with manual camera overrides")
    if args.camera_index < 0:
        raise SystemExit("--camera_index must be non-negative")
    for name in ("preview_size", "preview_columns", "single_size", "cell_size", "label_size"):
        if getattr(args, name) <= 0:
            raise SystemExit(f"--{name.replace('_', '-')} must be positive")
    if args.comparison_columns < 0:
        raise SystemExit("--comparison_columns must be non-negative")
    if args.gap < 0 or args.margin < 0 or args.crop_padding < 0:
        raise SystemExit("--gap, --margin, and --crop_padding must be non-negative")
    if args.pdf_dpi <= 0:
        raise SystemExit("--pdf_dpi must be positive")
    if any(target.suffix.casefold() != ".xyz" for target in targets):
        raise SystemExit("every target must use the .xyz extension")
    if any(target.is_absolute() or ".." in target.parts for target in targets):
        raise SystemExit("targets must be relative paths inside each method directory")
    if len({target.stem.casefold() for target in targets}) != len(targets):
        raise SystemExit("target stems must be unique because they name output directories")


def main() -> None:
    args = parse_args()
    specs = build_method_specs(args)
    targets = [args.target] if args.target is not None else list(args.targets)
    validate_args(args, targets)
    configured_colors = load_color_config(args.method_color_config)

    multi_object = len(targets) > 1
    completed = 0
    for index, target in enumerate(targets, start=1):
        object_dir = args.output_dir / target.stem if multi_object else args.output_dir
        print(f"\n=== object {index}/{len(targets)}: {target.name} ===")
        if process_object(
            target,
            specs=specs,
            args=args,
            object_dir=object_dir,
            configured_colors=configured_colors,
        ):
            completed += 1
    print(f"\nfinished {completed}/{len(targets)} object(s) -> {args.output_dir}")
    if completed == 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
