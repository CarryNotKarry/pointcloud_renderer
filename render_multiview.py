#!/usr/bin/env python3
"""Render one XYZ file from several orthographic views as a preview sheet."""

from __future__ import annotations

import argparse
from pathlib import Path

if __package__:
    from .preview_utils import DEFAULT_PREVIEW_VIEWS, PreviewView, generate_multiview_preview
    from .utils import COLOR_THEMES, RenderConfig, normalize_points, read_xyz, resolve_color, resolve_sphere_radius, save_camera
else:
    from preview_utils import DEFAULT_PREVIEW_VIEWS, PreviewView, generate_multiview_preview
    from utils import COLOR_THEMES, RenderConfig, normalize_points, read_xyz, resolve_color, resolve_sphere_radius, save_camera


def parse_view(value: str) -> PreviewView:
    """Parse AZIMUTH,ELEVATION[,ROLL]."""

    fields = value.split(",")
    if len(fields) not in {2, 3}:
        raise argparse.ArgumentTypeError("view must be AZIMUTH,ELEVATION[,ROLL]")
    try:
        numbers = [float(field) for field in fields]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("view angles must be numbers") from exc
    return PreviewView(numbers[0], numbers[1], numbers[2] if len(numbers) == 3 else 0.0)


def parse_views(value: str) -> tuple[PreviewView, ...]:
    """Parse a semicolon-separated list of candidate views."""

    fields = [field.strip() for field in value.split(";") if field.strip()]
    if not fields:
        raise argparse.ArgumentTypeError("at least one view is required")
    return tuple(parse_view(field) for field in fields)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", "--output_dir", type=Path, required=True)
    parser.add_argument(
        "--views",
        type=parse_views,
        default=None,
        metavar="AZ,EL[,ROLL];...",
        help="Semicolon-separated candidate views; default provides eight directions",
    )
    parser.add_argument("--camera-index", "--camera_index", type=int, default=0)
    parser.add_argument("--save-camera", "--save_camera", type=Path, default=None)
    parser.add_argument("--preview-size", "--preview_size", type=int, default=640)
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--label-size", "--label_size", type=int, default=24)
    parser.add_argument("--font", type=Path, default=None)
    parser.add_argument("--mode", choices=("glyph", "fast", "smooth"), default="glyph")
    parser.add_argument("--sphere-radius", "--sphere_radius", type=float, default=None)
    parser.add_argument("--size-scale", "--size_scale", type=float, default=1.0)
    parser.add_argument("--point-size", "--point_size", type=float, default=6.0)
    parser.add_argument("--sphere-resolution", "--sphere_resolution", type=int, default=12)
    parser.add_argument("--theme", choices=tuple(COLOR_THEMES), default="blue")
    parser.add_argument("--color", default=None)
    parser.add_argument("--bg-color", "--bg_color", default="#FAFAFC")
    parser.add_argument("--shadow-mode", "--shadow_mode", choices=("none", "simple", "soft"), default="soft")
    parser.add_argument("--shadow-opacity", "--shadow_opacity", type=float, default=0.11)
    parser.add_argument("--shadow-blur", "--shadow_blur", type=float, default=32.0)
    parser.add_argument("--light-preset", "--light_preset", choices=("soft", "studio"), default="soft")
    parser.add_argument("--padding", type=float, default=0.12)
    parser.add_argument("--crop-padding", "--crop_padding", type=int, default=24)
    parser.add_argument("--pdf-dpi", "--pdf_dpi", type=float, default=150.0)
    parser.add_argument("--no-pdf", "--no_pdf", action="store_true")
    parser.add_argument("--no-autocrop", "--no_autocrop", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    views = args.views or DEFAULT_PREVIEW_VIEWS
    if not 0 <= args.camera_index < len(views):
        raise SystemExit(f"--camera_index must be in [0, {len(views) - 1}]")

    raw_points = read_xyz(args.input)
    points, normalization = normalize_points(raw_points)
    config = RenderConfig(
        width=args.preview_size,
        height=args.preview_size,
        color=resolve_color(args.theme, args.color),
        background=args.bg_color,
        mode=args.mode,
        sphere_radius=args.sphere_radius,
        size_scale=args.size_scale,
        point_size=args.point_size,
        sphere_resolution=args.sphere_resolution,
        padding=args.padding,
        shadow_mode=args.shadow_mode,
        shadow_opacity=args.shadow_opacity,
        shadow_blur=args.shadow_blur,
        light_preset=args.light_preset,
    )
    config.validate()
    radius = resolve_sphere_radius(points, config)
    metadata = {
        "object": args.input.stem,
        "input": str(args.input.resolve()),
        "normalization": {
            "center": [float(value) for value in normalization.center],
            "scale": float(normalization.scale),
        },
        "render": {
            "resolved_sphere_radius": radius,
            "size_scale": args.size_scale,
        },
    }
    result = generate_multiview_preview(
        points,
        output_dir=args.output_dir,
        object_stem=args.input.stem,
        config=config,
        sphere_radius=radius,
        views=views,
        preview_size=args.preview_size,
        columns=args.columns,
        label_size=args.label_size,
        font_path=args.font,
        selected_index=args.camera_index,
        save_pdf=not args.no_pdf,
        pdf_dpi=args.pdf_dpi,
        autocrop=not args.no_autocrop,
        crop_padding=args.crop_padding,
        camera_metadata=metadata,
    )
    selected = result.records[args.camera_index]
    best_path = args.save_camera or args.output_dir / f"{args.input.stem}_view_best.json"
    best_metadata = dict(metadata)
    best_metadata["selected_preview"] = {
        "index": selected.index,
        "azimuth": selected.view.azimuth,
        "elevation": selected.view.elevation,
        "roll": selected.view.roll,
    }
    save_camera(selected.camera, best_path, metadata=best_metadata)
    print(f"preview sheet -> {result.sheet_png}")
    if result.sheet_pdf is not None:
        print(f"preview PDF -> {result.sheet_pdf}")
    print(f"selected camera -> {best_path}")


if __name__ == "__main__":
    main()
