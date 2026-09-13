#!/usr/bin/env python3
"""Render all XYZ files in a directory and compose a paper-style comparison grid."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

if __package__:
    from .utils import (
        CAMERA_PRESETS,
        COLOR_THEMES,
        RenderConfig,
        discover_xyz_files,
        fit_camera_to_points,
        load_camera,
        normalize_point_sets,
        read_xyz,
        render_point_cloud,
        resolve_color,
        resolve_shared_sphere_radius,
        save_camera,
    )
else:
    from utils import (
        CAMERA_PRESETS,
        COLOR_THEMES,
        RenderConfig,
        discover_xyz_files,
        fit_camera_to_points,
        load_camera,
        normalize_point_sets,
        read_xyz,
        render_point_cloud,
        resolve_color,
        resolve_shared_sphere_radius,
        save_camera,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", "--input_dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--columns", type=int, default=3)
    parser.add_argument("--cell-width", "--cell_width", type=int, default=720)
    parser.add_argument("--cell-height", "--cell_height", type=int, default=720)
    parser.add_argument("--gap", type=int, default=24)
    parser.add_argument("--margin", type=int, default=32)
    parser.add_argument("--labels", action="store_true", help="Show each file stem below its image")
    parser.add_argument("--label-size", "--label_size", type=int, default=30)
    parser.add_argument("--font", type=Path, default=None, help="Optional .ttf/.otf font")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--normalization", choices=("per-shape", "shared", "none"), default="per-shape")
    parser.add_argument("--mode", choices=("glyph", "fast", "smooth"), default="glyph")
    parser.add_argument(
        "--sphere-radius",
        "--sphere_radius",
        type=float,
        default=None,
        help="Manual radius; default estimates one shared grid radius",
    )
    parser.add_argument(
        "--size-scale",
        "--size_scale",
        type=float,
        default=1.0,
        help="Weak point-size multiplier; recommended range: 0.85 to 1.15",
    )
    parser.add_argument("--point-size", "--point_size", type=float, default=6.0)
    parser.add_argument("--sphere-resolution", "--sphere_resolution", type=int, default=12)
    parser.add_argument("--theme", choices=tuple(COLOR_THEMES), default="blue")
    parser.add_argument("--color", default=None)
    parser.add_argument("--bg-color", "--bg_color", "--background", dest="bg_color", default="#FAFAFC")
    parser.add_argument("--shadow-mode", "--shadow_mode", choices=("none", "simple", "soft"))
    parser.add_argument("--shadow", action="store_const", const="soft", dest="shadow_mode", help=argparse.SUPPRESS)
    parser.add_argument("--no-shadow", action="store_const", const="none", dest="shadow_mode", help=argparse.SUPPRESS)
    parser.add_argument("--shadow-opacity", "--shadow_opacity", type=float, default=0.11)
    parser.add_argument(
        "--shadow-blur",
        "--shadow_blur",
        type=float,
        default=32.0,
        help="Gaussian radius at 1600 px; scaled for cell size",
    )
    parser.add_argument("--light-preset", "--light_preset", choices=("soft", "studio"), default="soft")
    parser.add_argument("--view", choices=tuple(CAMERA_PRESETS), default="iso")
    parser.add_argument("--azimuth", type=float, default=None)
    parser.add_argument("--elevation", type=float, default=None)
    parser.add_argument("--roll", type=float, default=None)
    parser.add_argument("--camera-scale", "--camera_scale", type=float, default=None)
    parser.add_argument("--padding", type=float, default=0.12)
    parser.add_argument("--transparent-background", "--transparent_background", action="store_true")
    parser.add_argument("--save-camera", "--save_camera", type=Path, default=None)
    parser.add_argument("--load-camera", "--load_camera", type=Path, default=None)
    parser.set_defaults(shadow_mode="soft")
    return parser.parse_args()


def load_font(path: Path | None, size: int) -> ImageFont.ImageFont:
    if path is not None:
        return ImageFont.truetype(str(path), size=size)
    for candidate in ("DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def compose_grid(
    images: list[np.ndarray],
    labels: list[str],
    *,
    columns: int,
    cell_width: int,
    cell_height: int,
    gap: int,
    margin: int,
    show_labels: bool,
    label_size: int,
    font_path: Path | None,
    background: str,
    transparent: bool,
) -> Image.Image:
    rows = math.ceil(len(images) / columns)
    label_height = int(label_size * 1.8) if show_labels else 0
    canvas_width = 2 * margin + columns * cell_width + (columns - 1) * gap
    canvas_height = 2 * margin + rows * (cell_height + label_height) + (rows - 1) * gap
    rgb = ImageColor.getrgb(background)
    mode = "RGBA" if transparent else "RGB"
    fill = (*rgb, 0) if transparent else rgb
    canvas = Image.new(mode, (canvas_width, canvas_height), fill)
    draw = ImageDraw.Draw(canvas)
    font = load_font(font_path, label_size)

    for index, (array, label) in enumerate(zip(images, labels)):
        row, column = divmod(index, columns)
        x = margin + column * (cell_width + gap)
        y = margin + row * (cell_height + label_height + gap)
        tile = Image.fromarray(array.astype(np.uint8, copy=False))
        if mode == "RGBA":
            canvas.alpha_composite(tile.convert("RGBA"), dest=(x, y))
        else:
            canvas.paste(tile.convert("RGB"), (x, y))
        if show_labels:
            box = draw.textbbox((0, 0), label, font=font)
            text_width = box[2] - box[0]
            text_x = x + (cell_width - text_width) / 2.0
            text_y = y + cell_height + max(4, int(label_size * 0.18))
            text_color = (48, 53, 64, 255) if transparent else (48, 53, 64)
            draw.text((text_x, text_y), label, fill=text_color, font=font)
    return canvas


def main() -> None:
    args = parse_args()
    if args.columns <= 0 or args.cell_width <= 0 or args.cell_height <= 0:
        raise SystemExit("--columns and cell dimensions must be positive")
    if args.gap < 0 or args.margin < 0 or args.label_size <= 0:
        raise SystemExit("--gap/--margin must be non-negative and --label-size positive")
    if args.load_camera is not None and any(
        value is not None for value in (args.azimuth, args.elevation, args.roll, args.camera_scale)
    ):
        raise SystemExit("--load_camera cannot be combined with angle or --camera_scale overrides")

    paths = discover_xyz_files(args.input_dir, recursive=args.recursive)
    if not paths:
        raise SystemExit(f"no .xyz files found in {args.input_dir}")

    clouds = normalize_point_sets([read_xyz(path) for path in paths], mode=args.normalization)
    config = RenderConfig(
        width=args.cell_width,
        height=args.cell_height,
        color=resolve_color(args.theme, args.color),
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
        transparent_background=args.transparent_background,
    )
    config.validate()
    shared_radius = resolve_shared_sphere_radius(clouds, config)

    # Shared normalization means method outputs are aligned; use one exact camera
    # too, so differences cannot be introduced by per-panel auto framing.
    shared_camera = load_camera(args.load_camera) if args.load_camera is not None else None
    if shared_camera is None and args.normalization == "shared":
        shared_camera = fit_camera_to_points(np.vstack(clouds), config, sphere_radius=shared_radius)
    if args.save_camera is not None and shared_camera is None:
        if len(clouds) == 1:
            shared_camera = fit_camera_to_points(clouds[0], config, sphere_radius=shared_radius)
        else:
            raise SystemExit(
                "--save_camera needs one reusable camera; use --normalization shared "
                "or provide --load_camera"
            )

    rendered = []
    for index, (path, points) in enumerate(zip(paths, clouds), start=1):
        print(f"[{index}/{len(paths)}] rendering {path.name}")
        rendered.append(
            render_point_cloud(
                points,
                config=config,
                normalize=False,
                camera=shared_camera,
                sphere_radius=shared_radius,
            )
        )

    if args.save_camera is not None:
        save_camera(shared_camera, args.save_camera)
        print(f"saved camera -> {args.save_camera}")

    grid = compose_grid(
        rendered,
        [path.stem for path in paths],
        columns=args.columns,
        cell_width=args.cell_width,
        cell_height=args.cell_height,
        gap=args.gap,
        margin=args.margin,
        show_labels=args.labels,
        label_size=args.label_size,
        font_path=args.font,
        background=args.bg_color,
        transparent=args.transparent_background,
    )
    if args.output.suffix.lower() != ".png":
        raise SystemExit("--output must use the .png extension")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    grid.save(args.output, format="PNG", optimize=True)
    print(
        f"wrote {len(paths)} panels -> {args.output} ({grid.width}x{grid.height}, "
        f"shared_radius={shared_radius:.6g}, size_scale={args.size_scale:g})"
    )


if __name__ == "__main__":
    main()
