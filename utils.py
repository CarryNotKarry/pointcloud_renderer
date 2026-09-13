"""Shared I/O, normalization, camera, shadow, and PyVista rendering helpers."""

from __future__ import annotations

import os
import json
import math
import shutil
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image

if __package__:
    from .shadow_utils import camera_basis, composite_render
else:
    from shadow_utils import camera_basis, composite_render

# This must be set before constructing any VTK render window.
os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")


COLOR_THEMES = {
    "blue": "#90AEDD",
    "grayblue": "#8FA3B8",
    "teal": "#79B7B2",
    "green": "#9BC9B7",
    "orange": "#E7B07A",
    "purple": "#B7A6DA",
}

CAMERA_PRESETS = {
    "iso": ((1.75, -2.20, 1.45), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "front": ((0.0, -3.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "side": ((3.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, 3.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
}


@dataclass(frozen=True)
class NormalizationInfo:
    """Affine transform used by :func:`normalize_points`."""

    center: np.ndarray
    scale: float


@dataclass(frozen=True)
class CameraSpec:
    """A reproducible orthographic camera definition."""

    position: tuple[float, float, float]
    focal_point: tuple[float, float, float]
    view_up: tuple[float, float, float]
    parallel_scale: float = 0.72


@dataclass(frozen=True)
class RenderConfig:
    """Paper-style renderer settings shared by single and grid rendering."""

    width: int = 1600
    height: int = 1600
    color: str = COLOR_THEMES["blue"]
    background: str = "#FAFAFC"
    mode: str = "glyph"
    sphere_radius: float | None = None
    size_scale: float = 1.0
    point_size: float = 6.0
    sphere_resolution: int = 12
    view: str = "iso"
    azimuth: float | None = None
    elevation: float | None = None
    roll: float | None = None
    camera_scale: float | None = None
    padding: float = 0.12
    shadow_mode: str = "soft"
    shadow_opacity: float = 0.11
    shadow_blur: float = 32.0
    light_preset: str = "soft"
    transparent_background: bool = False

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")
        if self.mode not in {"glyph", "fast", "smooth"}:
            raise ValueError("mode must be one of: glyph, fast, smooth")
        if self.view not in CAMERA_PRESETS:
            raise ValueError(f"unknown view {self.view!r}")
        if self.sphere_radius is not None and self.sphere_radius <= 0:
            raise ValueError("sphere_radius must be positive when specified")
        if self.point_size <= 0 or self.size_scale <= 0:
            raise ValueError("point_size and size_scale must be positive")
        if not 0.85 <= self.size_scale <= 1.15:
            warnings.warn(
                f"--size_scale={self.size_scale:g} is outside the recommended range "
                "[0.85, 1.15]; large changes can weaken qualitative-comparison fairness.",
                UserWarning,
            )
        if self.sphere_resolution < 4:
            raise ValueError("sphere_resolution must be at least 4")
        if self.camera_scale is not None and self.camera_scale <= 0:
            raise ValueError("camera_scale must be positive")
        if not 0.0 <= self.padding < 0.4:
            raise ValueError("padding must be in [0, 0.4)")
        if self.shadow_mode not in {"none", "simple", "soft"}:
            raise ValueError("shadow_mode must be one of: none, simple, soft")
        if not 0.0 <= self.shadow_opacity <= 1.0:
            raise ValueError("shadow_opacity must be in [0, 1]")
        if self.shadow_blur < 0:
            raise ValueError("shadow_blur must be non-negative")
        if self.light_preset not in {"soft", "studio"}:
            raise ValueError("light_preset must be one of: soft, studio")
        for name, angle in (("azimuth", self.azimuth), ("elevation", self.elevation), ("roll", self.roll)):
            if angle is not None and not math.isfinite(angle):
                raise ValueError(f"{name} must be finite")
        if self.elevation is not None and not -90.0 <= self.elevation <= 90.0:
            raise ValueError("elevation must be in [-90, 90] degrees")


def read_xyz(path: str | Path) -> np.ndarray:
    """Read the first three whitespace-separated columns of an XYZ file."""

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"XYZ file does not exist: {path}")

    rows: list[tuple[float, float, float]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.split("#", maxsplit=1)[0].strip()
            if not line:
                continue
            fields = line.replace(",", " ").split()
            if len(fields) < 3:
                raise ValueError(f"{path}:{line_number}: expected at least 3 columns")
            try:
                xyz = (float(fields[0]), float(fields[1]), float(fields[2]))
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: invalid XYZ coordinate") from exc
            rows.append(xyz)

    if not rows:
        raise ValueError(f"XYZ file contains no points: {path}")

    points = np.asarray(rows, dtype=np.float32)
    if not np.isfinite(points).all():
        raise ValueError(f"XYZ file contains NaN or infinite coordinates: {path}")
    return points


def normalize_points(
    points: np.ndarray,
    target_extent: float = 1.0,
    *,
    center: Sequence[float] | None = None,
    scale: float | None = None,
) -> tuple[np.ndarray, NormalizationInfo]:
    """Center a cloud at its bounding-box center and scale its largest side."""

    points = _validate_points(points)
    if target_extent <= 0:
        raise ValueError("target_extent must be positive")

    bounds_min = points.min(axis=0)
    bounds_max = points.max(axis=0)
    used_center = np.asarray(center, dtype=np.float64) if center is not None else (bounds_min + bounds_max) / 2.0
    largest_extent = float(np.max(bounds_max - bounds_min))
    used_scale = float(scale) if scale is not None else largest_extent / target_extent
    if not np.isfinite(used_scale) or used_scale <= np.finfo(np.float64).eps:
        raise ValueError("cannot normalize a point cloud with zero spatial extent")

    normalized = (points.astype(np.float64) - used_center) / used_scale
    return normalized.astype(np.float32), NormalizationInfo(used_center, used_scale)


def normalize_point_sets(
    point_sets: Sequence[np.ndarray], mode: str = "per-shape"
) -> list[np.ndarray]:
    """Normalize clouds independently, with one shared transform, or not at all."""

    if not point_sets:
        return []
    if mode == "none":
        return [_validate_points(points).astype(np.float32, copy=True) for points in point_sets]
    if mode == "per-shape":
        return [normalize_points(points)[0] for points in point_sets]
    if mode == "shared":
        validated = [_validate_points(points) for points in point_sets]
        all_min = np.min(np.vstack([points.min(axis=0) for points in validated]), axis=0)
        all_max = np.max(np.vstack([points.max(axis=0) for points in validated]), axis=0)
        center = (all_min + all_max) / 2.0
        scale = float(np.max(all_max - all_min))
        if scale <= np.finfo(np.float64).eps:
            raise ValueError("cannot normalize point clouds with zero spatial extent")
        return [normalize_points(points, center=center, scale=scale)[0] for points in validated]
    raise ValueError("normalization mode must be one of: per-shape, shared, none")


def estimate_point_spacing(
    points: np.ndarray,
    *,
    max_queries: int = 1024,
    max_references: int = 8192,
) -> float:
    """Estimate median nearest-neighbor spacing without an extra KD-tree dependency."""

    points = _validate_points(points).astype(np.float32, copy=False)
    if len(points) < 2:
        raise ValueError("at least two points are required to estimate point spacing")
    bounds_min = points.min(axis=0)
    extent = float(np.max(points.max(axis=0) - bounds_min))
    if extent <= np.finfo(np.float32).eps:
        raise ValueError("cannot estimate spacing for a zero-extent point cloud")
    normalized = (points - bounds_min) / extent

    query_indices = np.linspace(0, len(points) - 1, min(len(points), max_queries), dtype=np.int64)
    reference_indices = np.linspace(0, len(points) - 1, min(len(points), max_references), dtype=np.int64)
    references = normalized[reference_indices]
    nearest_squared: list[np.ndarray] = []

    for start in range(0, len(query_indices), 128):
        batch_indices = query_indices[start : start + 128]
        differences = normalized[batch_indices, None, :] - references[None, :, :]
        distances_squared = np.einsum("qri,qri->qr", differences, differences)
        self_matches = batch_indices[:, None] == reference_indices[None, :]
        distances_squared[self_matches] = np.inf
        nearest_squared.append(distances_squared.min(axis=1))

    nearest = np.sqrt(np.concatenate(nearest_squared))
    nearest = nearest[np.isfinite(nearest) & (nearest > 0)]
    if len(nearest) == 0:
        raise ValueError("could not estimate a non-zero point spacing")
    return float(np.median(nearest) * extent)


def estimate_sphere_radius(points: np.ndarray) -> float:
    """Estimate a conservative sphere radius from cloud scale and density."""

    points = _validate_points(points)
    extent = float(np.max(points.max(axis=0) - points.min(axis=0)))
    spacing = estimate_point_spacing(points)
    # Keep density adaptation deliberately bounded so it preserves the visual
    # distinction between sparse and dense point clouds.
    return float(np.clip(0.30 * spacing, 0.0040 * extent, 0.0060 * extent))


def resolve_sphere_radius(points: np.ndarray, config: RenderConfig) -> float:
    """Resolve auto/manual radius and apply the weak visual size multiplier."""

    base_radius = config.sphere_radius if config.sphere_radius is not None else estimate_sphere_radius(points)
    return float(base_radius * config.size_scale)


def resolve_shared_sphere_radius(point_sets: Sequence[np.ndarray], config: RenderConfig) -> float:
    """Resolve one identical radius for all panels in a fair comparison grid."""

    if not point_sets:
        raise ValueError("at least one point cloud is required")
    if config.sphere_radius is not None:
        return float(config.sphere_radius * config.size_scale)
    estimates = [estimate_sphere_radius(points) for points in point_sets]
    return float(np.median(estimates) * config.size_scale)


def camera_from_view(
    view: str,
    parallel_scale: float = 0.72,
    *,
    azimuth: float | None = None,
    elevation: float | None = None,
    roll: float | None = None,
) -> CameraSpec:
    """Return a preset camera, optionally overridden by spherical angles."""

    try:
        preset_position, focal_point, preset_up = CAMERA_PRESETS[view]
    except KeyError as exc:
        raise ValueError(f"unknown view {view!r}; choose from {sorted(CAMERA_PRESETS)}") from exc
    if azimuth is None and elevation is None and roll is None:
        return CameraSpec(preset_position, focal_point, preset_up, parallel_scale)

    focal = np.asarray(focal_point, dtype=np.float64)
    preset_offset = np.asarray(preset_position, dtype=np.float64) - focal
    distance = float(np.linalg.norm(preset_offset))
    preset_azimuth = math.degrees(math.atan2(preset_offset[1], preset_offset[0]))
    preset_elevation = math.degrees(math.asin(preset_offset[2] / distance))
    used_azimuth = preset_azimuth if azimuth is None else float(azimuth)
    used_elevation = preset_elevation if elevation is None else float(elevation)
    used_roll = 0.0 if roll is None else float(roll)

    azimuth_radians = math.radians(used_azimuth)
    elevation_radians = math.radians(used_elevation)
    offset_direction = np.asarray(
        (
            math.cos(elevation_radians) * math.cos(azimuth_radians),
            math.cos(elevation_radians) * math.sin(azimuth_radians),
            math.sin(elevation_radians),
        ),
        dtype=np.float64,
    )
    position = focal + distance * offset_direction
    view_direction = -offset_direction
    up_hint = np.asarray((0.0, 0.0, 1.0), dtype=np.float64)
    if abs(float(np.dot(view_direction, up_hint))) > 0.995:
        up_hint = np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
    right = np.cross(view_direction, up_hint)
    right /= np.linalg.norm(right)
    view_up = np.cross(right, view_direction)
    view_up /= np.linalg.norm(view_up)
    if used_roll:
        view_up = _rotate_about_axis(view_up, view_direction, used_roll)
    return CameraSpec(tuple(position), tuple(focal), tuple(view_up), parallel_scale)


def fit_camera_to_points(
    points: np.ndarray,
    config: RenderConfig,
    *,
    sphere_radius: float | None = None,
) -> CameraSpec:
    """Fit a fixed-direction orthographic camera to a projected point-cloud box."""

    points = _validate_points(points).astype(np.float64, copy=False)
    base = camera_from_view(
        config.view,
        azimuth=config.azimuth,
        elevation=config.elevation,
        roll=config.roll,
    )
    right, up, view_direction = camera_basis(base.position, base.focal_point, base.view_up)

    framing_points = points
    if config.shadow_mode != "none":
        shadow_points, _ = project_shadow(points)
        framing_points = np.vstack((points, shadow_points))

    relative = framing_points - np.asarray(base.focal_point, dtype=np.float64)
    screen_x = relative @ right
    screen_y = relative @ up
    used_radius = resolve_sphere_radius(points, config) if sphere_radius is None else sphere_radius
    radius_padding = used_radius * 1.2 if config.mode == "glyph" else 0.0
    x_min = float(screen_x.min() - radius_padding)
    x_max = float(screen_x.max() + radius_padding)
    y_min = float(screen_y.min() - radius_padding)
    y_max = float(screen_y.max() + radius_padding)
    x_extent = max(x_max - x_min, 1e-6)
    y_extent = max(y_max - y_min, 1e-6)
    aspect = config.width / config.height
    usable_fraction = 1.0 - 2.0 * config.padding

    if config.camera_scale is None:
        parallel_scale = max(
            y_extent / (2.0 * usable_fraction),
            x_extent / (2.0 * aspect * usable_fraction),
        )
    else:
        parallel_scale = config.camera_scale * max(1.0, 1.0 / aspect)

    # Center the projected content and set a safe camera distance. In parallel
    # projection the visual occupancy is governed by parallel_scale; distance is
    # still adapted to keep clipping robust for non-normalized expert inputs.
    x_center = 0.5 * (x_min + x_max)
    y_center = 0.5 * (y_min + y_max)
    shift = right * x_center + up * y_center
    focal_array = np.asarray(base.focal_point) + shift
    diagonal = float(np.linalg.norm(np.ptp(framing_points, axis=0)))
    camera_distance = max(3.0, 2.5 * diagonal)
    position = tuple((focal_array - view_direction * camera_distance).tolist())
    focal_point = tuple(focal_array.tolist())
    return CameraSpec(position, focal_point, base.view_up, float(parallel_scale))


def save_camera(
    camera: CameraSpec,
    path: str | Path,
    *,
    metadata: dict | None = None,
) -> Path:
    """Save a complete orthographic camera to a portable JSON file."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": 1,
        "projection": "orthographic",
        "position": list(camera.position),
        "focal_point": list(camera.focal_point),
        "view_up": list(camera.view_up),
        "parallel_scale": camera.parallel_scale,
    }
    if metadata:
        payload["metadata"] = metadata
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def load_camera_metadata(path: str | Path) -> dict:
    """Return optional metadata from a camera JSON without changing camera semantics."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"camera file does not exist: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid camera JSON: {source}") from exc
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("camera JSON metadata must be an object")
    return metadata


def load_camera(path: str | Path) -> CameraSpec:
    """Load and validate a camera JSON written by :func:`save_camera`."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"camera file does not exist: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid camera JSON: {source}") from exc
    if payload.get("projection") != "orthographic":
        raise ValueError("camera JSON must use projection='orthographic'")

    position = _camera_vector(payload, "position")
    focal_point = _camera_vector(payload, "focal_point")
    view_up = _camera_vector(payload, "view_up")
    try:
        parallel_scale = float(payload["parallel_scale"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("camera JSON has an invalid parallel_scale") from exc
    if not math.isfinite(parallel_scale) or parallel_scale <= 0:
        raise ValueError("camera parallel_scale must be finite and positive")
    if np.linalg.norm(np.asarray(position) - np.asarray(focal_point)) <= 1e-8:
        raise ValueError("camera position and focal_point must differ")
    if np.linalg.norm(view_up) <= 1e-8:
        raise ValueError("camera view_up must be non-zero")
    view_direction = np.asarray(focal_point) - np.asarray(position)
    if np.linalg.norm(np.cross(view_direction, np.asarray(view_up))) <= 1e-8:
        raise ValueError("camera view_up cannot be parallel to the viewing direction")
    camera_basis(position, focal_point, view_up)
    return CameraSpec(position, focal_point, view_up, parallel_scale)


def _rotate_about_axis(vector: np.ndarray, axis: np.ndarray, degrees: float) -> np.ndarray:
    radians = math.radians(degrees)
    axis = axis / np.linalg.norm(axis)
    return (
        vector * math.cos(radians)
        + np.cross(axis, vector) * math.sin(radians)
        + axis * np.dot(axis, vector) * (1.0 - math.cos(radians))
    )


def _camera_vector(payload: dict, key: str) -> tuple[float, float, float]:
    try:
        values = tuple(float(value) for value in payload[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"camera JSON has an invalid {key}") from exc
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError(f"camera {key} must contain three finite numbers")
    return values


def project_shadow(
    points: np.ndarray,
    *,
    ground_offset: float = 0.035,
    light_direction: Sequence[float] = (0.20, -0.24, -1.0),
) -> tuple[np.ndarray, float]:
    """Project points onto a horizontal plane along a fixed light direction."""

    points = _validate_points(points).astype(np.float64, copy=False)
    direction = np.asarray(light_direction, dtype=np.float64)
    if direction.shape != (3,) or abs(direction[2]) < 1e-8:
        raise ValueError("light_direction must be length 3 with a non-zero z component")
    ground_z = float(points[:, 2].min() - ground_offset)
    amount = (ground_z - points[:, 2]) / direction[2]
    shadow = points + amount[:, None] * direction[None, :]
    shadow[:, 2] = ground_z + 0.001
    return shadow.astype(np.float32), ground_z


def render_point_cloud(
    points: np.ndarray,
    output_path: str | Path | None = None,
    *,
    config: RenderConfig | None = None,
    normalize: bool = True,
    camera: CameraSpec | None = None,
    sphere_radius: float | None = None,
    save_camera_path: str | Path | None = None,
) -> np.ndarray:
    """Render one cloud off-screen, post-process it, and optionally write PNG."""

    config = config or RenderConfig()
    config.validate()
    points = _validate_points(points)
    if normalize:
        points = normalize_points(points)[0]
    else:
        points = points.astype(np.float32, copy=False)

    output = Path(output_path) if output_path is not None else None
    if output is not None and output.suffix.lower() != ".png":
        raise ValueError("output file must use the .png extension")
    resolved_radius = resolve_sphere_radius(points, config) if sphere_radius is None else float(sphere_radius)
    if resolved_radius <= 0 or not math.isfinite(resolved_radius):
        raise ValueError("resolved sphere radius must be finite and positive")
    resolved_point_size = config.point_size * config.size_scale
    render_camera = camera or fit_camera_to_points(points, config, sphere_radius=resolved_radius)

    pv = _load_pyvista()
    _prepare_headless(pv)

    plotter = pv.Plotter(
        off_screen=True,
        window_size=(config.width, config.height),
        lighting="none",
        border=False,
    )
    try:
        plotter.set_background(config.background)
        _enable_anti_aliasing(plotter)
        _configure_camera(plotter, render_camera)

        if config.shadow_mode == "simple":
            _add_simple_shadow(
                plotter,
                points,
                config,
                render_camera,
                sphere_radius=resolved_radius,
                point_size=resolved_point_size,
            )

        _add_lights(plotter, pv, config.light_preset)
        _add_point_actor(
            plotter,
            pv,
            points,
            config,
            sphere_radius=resolved_radius,
            point_size=resolved_point_size,
        )
        plotter.reset_camera_clipping_range()

        # Always render RGBA internally. This lets the continuous shadow sit
        # behind the subject instead of darkening points where they overlap.
        subject_rgba = plotter.screenshot(
            filename=None,
            transparent_background=True,
            return_img=True,
        )
        if subject_rgba is None:
            raise RuntimeError("PyVista did not return a screenshot")
        soft_shadow = project_shadow(points)[0] if config.shadow_mode == "soft" else None
        final_image = composite_render(
            np.asarray(subject_rgba),
            background=config.background,
            transparent_background=config.transparent_background,
            shadow_points=soft_shadow,
            camera_position=render_camera.position,
            focal_point=render_camera.focal_point,
            view_up=render_camera.view_up,
            parallel_scale=render_camera.parallel_scale,
            sphere_radius=resolved_radius,
            shadow_opacity=config.shadow_opacity,
            shadow_blur=config.shadow_blur,
        )
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(final_image).save(output, format="PNG", optimize=True)
        if save_camera_path is not None:
            save_camera(render_camera, save_camera_path)
        return final_image
    finally:
        plotter.close()


def _validate_points(points: np.ndarray) -> np.ndarray:
    array = np.asarray(points)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError(f"expected an Nx3 point array, got shape {array.shape}")
    if array.shape[0] == 0:
        raise ValueError("point cloud is empty")
    if not np.issubdtype(array.dtype, np.number):
        raise ValueError("point coordinates must be numeric")
    if not np.isfinite(array).all():
        raise ValueError("point cloud contains NaN or infinite coordinates")
    return array


def _load_pyvista():
    try:
        import pyvista as pv
    except ImportError as exc:
        raise RuntimeError(
            "PyVista/VTK is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc
    pv.OFF_SCREEN = True
    return pv


def _prepare_headless(pv) -> None:
    # Standard VTK wheels may need Xvfb on display-less Linux machines. EGL/OSMesa
    # builds work without it, so this fallback is only used when Xvfb is present.
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and shutil.which("Xvfb"):
        try:
            pv.start_xvfb(wait=0.1)
        except Exception:
            # Let VTK try its native EGL/OSMesa backend and report any real error.
            pass


def _configure_camera(plotter, camera: CameraSpec) -> None:
    plotter.camera_position = [camera.position, camera.focal_point, camera.view_up]
    plotter.enable_parallel_projection()
    plotter.camera.parallel_scale = camera.parallel_scale


def _enable_anti_aliasing(plotter) -> None:
    try:
        plotter.enable_anti_aliasing("ssaa")
    except (AttributeError, TypeError, ValueError):
        try:
            plotter.enable_anti_aliasing("fxaa")
        except (AttributeError, TypeError, ValueError):
            pass


def _add_lights(plotter, pv, preset: str) -> None:
    if preset == "studio":
        specifications = (
            ((-3.4, -4.5, 6.2), "#FFFDF8", 0.96),
            ((4.2, -0.8, 2.2), "#EAF2FF", 0.20),
            ((0.8, 4.2, 4.8), "#FFFFFF", 0.24),
        )
    else:
        specifications = (
            ((-3.2, -4.2, 5.8), "#FFFDF8", 0.84),
            ((4.0, -0.6, 2.5), "#EAF2FF", 0.28),
            ((0.8, 4.0, 4.6), "#FFFFFF", 0.14),
        )

    for position, color, intensity in specifications:
        light = pv.Light(
            position=position,
            focal_point=(0.0, 0.0, 0.0),
            color=color,
            intensity=intensity,
            light_type="scene light",
            positional=False,
        )
        plotter.add_light(light)


def _add_point_actor(
    plotter,
    pv,
    points: np.ndarray,
    config: RenderConfig,
    *,
    sphere_radius: float,
    point_size: float,
) -> None:
    if config.light_preset == "studio":
        ambient, diffuse, specular = 0.32, 0.75, 0.040
    else:
        ambient, diffuse, specular = 0.44, 0.64, 0.020

    point_rgb = _height_tinted_rgb(points, pv, config.color)
    material = dict(
        scalars="point_rgb",
        rgb=True,
        ambient=ambient,
        diffuse=diffuse,
        specular=specular,
        specular_power=18.0,
        show_scalar_bar=False,
    )

    if config.mode == "glyph":
        cloud = pv.PolyData(points)
        cloud["point_rgb"] = point_rgb
        sphere = pv.Sphere(
            radius=sphere_radius,
            theta_resolution=config.sphere_resolution,
            phi_resolution=config.sphere_resolution,
        )
        glyphs = cloud.glyph(geom=sphere, orient=False, scale=False)
        plotter.add_mesh(glyphs, smooth_shading=True, **material)
    elif config.mode == "fast":
        cloud = pv.PolyData(points)
        cloud["point_rgb"] = point_rgb
        plotter.add_points(
            cloud,
            style="points",
            point_size=point_size,
            render_points_as_spheres=True,
            **material,
        )
    else:
        cloud = pv.PolyData(points)
        cloud["point_rgb"] = point_rgb
        plotter.add_points(
            cloud,
            style="points_gaussian",
            point_size=point_size,
            render_points_as_spheres=False,
            emissive=False,
            opacity=0.98,
            **material,
        )


def _height_tinted_rgb(points: np.ndarray, pv, color: str) -> np.ndarray:
    base = np.asarray(pv.Color(color).float_rgb, dtype=np.float64)
    z_values = points[:, 2].astype(np.float64)
    z_range = float(np.ptp(z_values))
    normalized_height = (z_values - z_values.min()) / z_range if z_range > 1e-8 else np.full(len(points), 0.5)
    shade = 0.94 + 0.06 * normalized_height[:, None]
    highlight = 0.035 * normalized_height[:, None]
    colors = base[None, :] * shade + (1.0 - base[None, :]) * highlight
    return np.clip(np.rint(colors * 255.0), 0, 255).astype(np.uint8)


def _add_simple_shadow(
    plotter,
    points: np.ndarray,
    config: RenderConfig,
    camera: CameraSpec,
    *,
    sphere_radius: float,
    point_size: float,
) -> None:
    shadow, _ = project_shadow(points)
    pixel_diameter = sphere_radius * config.height / max(camera.parallel_scale, 1e-6)
    shadow_size = max(point_size, pixel_diameter * 0.9, 3.0)
    plotter.add_points(
        shadow,
        style="points",
        color="#747B87",
        point_size=shadow_size,
        opacity=min(config.shadow_opacity * 0.55, 0.12),
        render_points_as_spheres=True,
        lighting=False,
        show_scalar_bar=False,
    )


def resolve_color(theme: str, color: str | None) -> str:
    """Resolve a named built-in theme unless an explicit color was supplied."""

    if color:
        return color
    try:
        return COLOR_THEMES[theme]
    except KeyError as exc:
        raise ValueError(f"unknown theme {theme!r}; choose from {sorted(COLOR_THEMES)}") from exc


def discover_xyz_files(input_dir: str | Path, recursive: bool = False) -> list[Path]:
    """Find XYZ files in deterministic, case-insensitive order."""

    input_dir = Path(input_dir)
    if not input_dir.is_dir():
        raise NotADirectoryError(f"input directory does not exist: {input_dir}")
    iterator: Iterable[Path] = input_dir.rglob("*") if recursive else input_dir.iterdir()
    files = [path for path in iterator if path.is_file() and path.suffix.lower() == ".xyz"]
    return sorted(files, key=lambda path: (str(path.relative_to(input_dir)).lower(), str(path)))
