#!/usr/bin/env python3
"""Render one XYZ point cloud as a publication-style PNG."""

from __future__ import annotations

import argparse
from pathlib import Path

if __package__:
    from .utils import (
        CAMERA_PRESETS,
        COLOR_THEMES,
        RenderConfig,
        load_camera,
        normalize_points,
        read_xyz,
        render_point_cloud,
        resolve_color,
        resolve_sphere_radius,
    )
else:
    from utils import (
        CAMERA_PRESETS,
        COLOR_THEMES,
        RenderConfig,
        load_camera,
        normalize_points,
        read_xyz,
        render_point_cloud,
        resolve_color,
        resolve_sphere_radius,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Input .xyz file")
    parser.add_argument("--output", type=Path, required=True, help="Output .png file")
    parser.add_argument("--mode", choices=("glyph", "fast", "smooth"), default="glyph")
    parser.add_argument(
        "--sphere-radius",
        "--sphere_radius",
        type=float,
        default=None,
        help="Manual world-space radius; default estimates scale and density",
    )
    parser.add_argument(
        "--size-scale",
        "--size_scale",
        type=float,
        default=1.0,
        help="Weak point-size multiplier; recommended range: 0.85 to 1.15",
    )
    parser.add_argument(
        "--point-size", "--point_size", type=float, default=6.0, help="Pixel size in fast/smooth mode"
    )
    parser.add_argument(
        "--sphere-resolution", "--sphere_resolution", type=int, default=12, help="Glyph sphere resolution"
    )
    parser.add_argument("--theme", choices=tuple(COLOR_THEMES), default="blue")
    parser.add_argument("--color", default=None, help="Explicit PyVista color, e.g. '#90AEDD'")
    parser.add_argument("--bg-color", "--bg_color", "--background", dest="bg_color", default="#FAFAFC")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1600)
    parser.add_argument("--shadow-mode", "--shadow_mode", choices=("none", "simple", "soft"))
    parser.add_argument("--shadow", action="store_const", const="soft", dest="shadow_mode", help=argparse.SUPPRESS)
    parser.add_argument("--no-shadow", action="store_const", const="none", dest="shadow_mode", help=argparse.SUPPRESS)
    parser.add_argument("--shadow-opacity", "--shadow_opacity", type=float, default=0.11)
    parser.add_argument(
        "--shadow-blur",
        "--shadow_blur",
        type=float,
        default=32.0,
        help="Gaussian radius at 1600 px; scaled for other resolutions",
    )
    parser.add_argument("--light-preset", "--light_preset", choices=("soft", "studio"), default="soft")
    parser.add_argument("--view", choices=tuple(CAMERA_PRESETS), default="iso")
    parser.add_argument("--azimuth", type=float, default=None, help="Camera azimuth in degrees")
    parser.add_argument("--elevation", type=float, default=None, help="Camera elevation in degrees")
    parser.add_argument("--roll", type=float, default=None, help="Camera roll in degrees")
    parser.add_argument(
        "--camera-scale",
        "--camera_scale",
        type=float,
        default=None,
        help="Override automatic orthographic framing; larger zooms out",
    )
    parser.add_argument("--padding", type=float, default=0.12, help="Fractional image margin")
    parser.add_argument("--transparent-background", "--transparent_background", action="store_true")
    parser.add_argument("--no-normalize", "--no_normalize", action="store_true", help="Keep input coordinates unchanged")
    parser.add_argument("--save-camera", "--save_camera", type=Path, default=None)
    parser.add_argument("--load-camera", "--load_camera", type=Path, default=None)
    parser.set_defaults(shadow_mode="soft")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.load_camera is not None and any(
        value is not None for value in (args.azimuth, args.elevation, args.roll, args.camera_scale)
    ):
        raise SystemExit("--load_camera cannot be combined with angle or --camera_scale overrides")
    loaded_camera = load_camera(args.load_camera) if args.load_camera is not None else None
    config = RenderConfig(
        width=args.width,
        height=args.height,
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
    points = read_xyz(args.input)
    render_points = points if args.no_normalize else normalize_points(points)[0]
    resolved_radius = resolve_sphere_radius(render_points, config)
    render_point_cloud(
        render_points,
        args.output,
        config=config,
        normalize=False,
        camera=loaded_camera,
        sphere_radius=resolved_radius,
        save_camera_path=args.save_camera,
    )
    print(
        f"rendered {len(points)} points -> {args.output} "
        f"({args.width}x{args.height}, mode={args.mode}, view={args.view}, "
        f"shadow={args.shadow_mode}, light={args.light_preset}, "
        f"radius={resolved_radius:.6g}, size_scale={args.size_scale:g})"
    )
    if args.save_camera is not None:
        print(f"saved camera -> {args.save_camera}")


if __name__ == "__main__":
    main()
