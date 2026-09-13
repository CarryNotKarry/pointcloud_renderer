"""Image-space soft-shadow generation and final RGBA compositing."""

from __future__ import annotations

from typing import Sequence

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter


def camera_basis(
    position: Sequence[float], focal_point: Sequence[float], view_up: Sequence[float]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return normalized screen-right, screen-up, and view directions."""

    position_array = np.asarray(position, dtype=np.float64)
    focal_array = np.asarray(focal_point, dtype=np.float64)
    up_hint = np.asarray(view_up, dtype=np.float64)
    view = focal_array - position_array
    view /= np.linalg.norm(view)
    right = np.cross(view, up_hint)
    right /= np.linalg.norm(right)
    up = np.cross(right, view)
    up /= np.linalg.norm(up)
    return right, up, view


def project_to_screen(
    points: np.ndarray,
    *,
    camera_position: Sequence[float],
    focal_point: Sequence[float],
    view_up: Sequence[float],
    parallel_scale: float,
    width: int,
    height: int,
) -> np.ndarray:
    """Project world points to VTK-style orthographic image coordinates."""

    right, up, _ = camera_basis(camera_position, focal_point, view_up)
    relative = np.asarray(points, dtype=np.float64) - np.asarray(focal_point, dtype=np.float64)
    screen_x = relative @ right
    screen_y = relative @ up
    half_width = parallel_scale * (width / height)
    pixels_x = (screen_x / half_width + 1.0) * 0.5 * (width - 1)
    pixels_y = (1.0 - (screen_y / parallel_scale + 1.0) * 0.5) * (height - 1)
    return np.column_stack((pixels_x, pixels_y))


def make_soft_shadow_mask(
    shadow_points: np.ndarray,
    *,
    camera_position: Sequence[float],
    focal_point: Sequence[float],
    view_up: Sequence[float],
    parallel_scale: float,
    width: int,
    height: int,
    sphere_radius: float,
    opacity: float,
    blur: float,
) -> Image.Image:
    """Rasterize projected points into a connected, blurred alpha mask."""

    pixels = project_to_screen(
        shadow_points,
        camera_position=camera_position,
        focal_point=focal_point,
        view_up=view_up,
        parallel_scale=parallel_scale,
        width=width,
        height=height,
    )
    if len(pixels) > 30_000:
        # The blurred silhouette no longer benefits from every point at very
        # high densities; deterministic thinning keeps soft mode responsive.
        indices = np.linspace(0, len(pixels) - 1, 30_000, dtype=np.int64)
        pixels = pixels[indices]

    # blur is specified for a 1600 px reference image so grid cells retain the
    # same visual softness as full-resolution single renders.
    resolution_scale = min(width, height) / 1600.0
    blur_pixels = max(0.0, float(blur) * resolution_scale)
    sphere_diameter_pixels = sphere_radius * height / max(parallel_scale, 1e-8)
    seed_radius = max(1.0, 0.30 * blur_pixels, 0.42 * sphere_diameter_pixels)

    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for x, y in pixels:
        if -seed_radius <= x < width + seed_radius and -seed_radius <= y < height + seed_radius:
            draw.ellipse(
                (x - seed_radius, y - seed_radius, x + seed_radius, y + seed_radius),
                fill=230,
            )

    if blur_pixels > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=blur_pixels))

    values = np.asarray(mask, dtype=np.float32) / 255.0
    # A gentle density curve fills tiny sampling gaps without creating a hard,
    # opaque silhouette. The user opacity remains the strict upper bound.
    values = (1.0 - np.exp(-2.4 * values)) * float(opacity)
    alpha = np.clip(np.rint(values * 255.0), 0, 255).astype(np.uint8)
    return Image.fromarray(alpha)


def composite_render(
    subject_rgba: np.ndarray,
    *,
    background: str,
    transparent_background: bool,
    shadow_points: np.ndarray | None = None,
    camera_position: Sequence[float] | None = None,
    focal_point: Sequence[float] | None = None,
    view_up: Sequence[float] | None = None,
    parallel_scale: float | None = None,
    sphere_radius: float = 0.0055,
    shadow_opacity: float = 0.11,
    shadow_blur: float = 32.0,
    shadow_color: str = "#69717F",
) -> np.ndarray:
    """Place a soft shadow below an RGBA VTK render and add the final background."""

    subject = Image.fromarray(np.asarray(subject_rgba, dtype=np.uint8)).convert("RGBA")
    width, height = subject.size
    background_rgb = ImageColor.getrgb(background)
    background_alpha = 0 if transparent_background else 255
    canvas = Image.new("RGBA", subject.size, (*background_rgb, background_alpha))

    if shadow_points is not None:
        if camera_position is None or focal_point is None or view_up is None or parallel_scale is None:
            raise ValueError("camera parameters are required when compositing a soft shadow")
        mask = make_soft_shadow_mask(
            shadow_points,
            camera_position=camera_position,
            focal_point=focal_point,
            view_up=view_up,
            parallel_scale=parallel_scale,
            width=width,
            height=height,
            sphere_radius=sphere_radius,
            opacity=shadow_opacity,
            blur=shadow_blur,
        )
        shadow_layer = Image.new("RGBA", subject.size, (*ImageColor.getrgb(shadow_color), 0))
        shadow_layer.putalpha(mask)
        canvas.alpha_composite(shadow_layer)

    # The VTK alpha channel cleanly occludes the shadow wherever the subject is visible.
    canvas.alpha_composite(subject)
    if transparent_background:
        return np.asarray(canvas)
    return np.asarray(canvas.convert("RGB"))
