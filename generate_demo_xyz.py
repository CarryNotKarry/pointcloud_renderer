#!/usr/bin/env python3
"""Generate deterministic surface-sampled XYZ point clouds for the renderer demo."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def sample_box_surface(
    rng: np.random.Generator, size: tuple[float, float, float], count: int
) -> np.ndarray:
    """Sample a cuboid surface with probabilities proportional to face area."""

    sx, sy, sz = size
    areas = np.asarray([sy * sz, sy * sz, sx * sz, sx * sz, sx * sy, sx * sy])
    face_ids = rng.choice(6, size=count, p=areas / areas.sum())
    points = rng.uniform(-0.5, 0.5, size=(count, 3)) * np.asarray(size)
    for face_id, (axis, sign) in enumerate(((0, -1), (0, 1), (1, -1), (1, 1), (2, -1), (2, 1))):
        mask = face_ids == face_id
        points[mask, axis] = sign * size[axis] / 2.0
    return points


def sample_cylinder_surface(
    rng: np.random.Generator, radius: float, height: float, count: int
) -> np.ndarray:
    """Sample the lateral surface and both circular caps of a cylinder."""

    areas = np.asarray([2.0 * np.pi * radius * height, np.pi * radius**2, np.pi * radius**2])
    surface_ids = rng.choice(3, size=count, p=areas / areas.sum())
    points = np.empty((count, 3), dtype=np.float64)

    side = surface_ids == 0
    theta = rng.uniform(0.0, 2.0 * np.pi, side.sum())
    points[side, 0] = radius * np.cos(theta)
    points[side, 1] = radius * np.sin(theta)
    points[side, 2] = rng.uniform(-height / 2.0, height / 2.0, side.sum())

    for surface_id, z_value in ((1, height / 2.0), (2, -height / 2.0)):
        mask = surface_ids == surface_id
        theta = rng.uniform(0.0, 2.0 * np.pi, mask.sum())
        radial = radius * np.sqrt(rng.random(mask.sum()))
        points[mask, 0] = radial * np.cos(theta)
        points[mask, 1] = radial * np.sin(theta)
        points[mask, 2] = z_value
    return points


def sample_triangle_mesh_surface(
    rng: np.random.Generator, triangles: np.ndarray, count: int
) -> np.ndarray:
    """Uniformly sample an explicit triangle mesh by triangle area."""

    edge_a = triangles[:, 1] - triangles[:, 0]
    edge_b = triangles[:, 2] - triangles[:, 0]
    areas = 0.5 * np.linalg.norm(np.cross(edge_a, edge_b), axis=1)
    triangle_ids = rng.choice(len(triangles), size=count, p=areas / areas.sum())
    selected = triangles[triangle_ids]
    root_u = np.sqrt(rng.random(count))
    v = rng.random(count)
    weights = np.column_stack((1.0 - root_u, root_u * (1.0 - v), root_u * v))
    return np.sum(selected * weights[:, :, None], axis=1)


def wedge_triangles() -> np.ndarray:
    """Build a triangular-prism mesh with an inclined upper face."""

    half_depth = 0.38
    cross_section = [(-0.65, -0.40), (0.65, -0.40), (-0.65, 0.46)]
    vertices = []
    for y in (-half_depth, half_depth):
        vertices.extend((x, y, z) for x, z in cross_section)
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = [
        (0, 2, 1),
        (3, 4, 5),
        (0, 1, 4),
        (0, 4, 3),
        (1, 2, 5),
        (1, 5, 4),
        (2, 0, 3),
        (2, 3, 5),
    ]
    return vertices[np.asarray(faces)]


def _quad_triangles(corners: list[tuple[float, float, float]]) -> list[np.ndarray]:
    quad = np.asarray(corners, dtype=np.float64)
    return [quad[[0, 1, 2]], quad[[0, 2, 3]]]


def bracket_triangles() -> np.ndarray:
    """Build a simple extruded U bracket as a concave triangle mesh."""

    width, height, depth = 1.30, 1.00, 0.34
    arm, bottom = 0.25, 0.24
    x0, x1 = -width / 2.0, width / 2.0
    z0, z1 = -height / 2.0, height / 2.0
    inner_left, inner_right = x0 + arm, x1 - arm
    inner_bottom = z0 + bottom
    y0, y1 = -depth / 2.0, depth / 2.0

    triangles: list[np.ndarray] = []
    face_rectangles = [
        (x0, x1, z0, inner_bottom),
        (x0, inner_left, inner_bottom, z1),
        (inner_right, x1, inner_bottom, z1),
    ]
    for y in (y0, y1):
        for xa, xb, za, zb in face_rectangles:
            triangles.extend(
                _quad_triangles([(xa, y, za), (xb, y, za), (xb, y, zb), (xa, y, zb)])
            )

    perimeter = [
        (x0, z0),
        (x1, z0),
        (x1, z1),
        (inner_right, z1),
        (inner_right, inner_bottom),
        (inner_left, inner_bottom),
        (inner_left, z1),
        (x0, z1),
    ]
    for index, (xa, za) in enumerate(perimeter):
        xb, zb = perimeter[(index + 1) % len(perimeter)]
        triangles.extend(
            _quad_triangles([(xa, y0, za), (xb, y0, zb), (xb, y1, zb), (xa, y1, za)])
        )
    return np.asarray(triangles)


def generate_shapes(rng: np.random.Generator, count: int) -> dict[str, np.ndarray]:
    """Generate all demo shapes before adding scanner-like coordinate noise."""

    return {
        "box": sample_box_surface(rng, (1.25, 0.82, 0.72), count),
        "cylinder": sample_cylinder_surface(rng, radius=0.48, height=1.18, count=count),
        "wedge": sample_triangle_mesh_surface(rng, wedge_triangles(), count),
        "thin_plate": sample_box_surface(rng, (1.34, 0.86, 0.065), count),
        "bracket": sample_triangle_mesh_surface(rng, bracket_triangles(), count),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("demo_data"))
    parser.add_argument("--num-points", type=int, default=2200)
    parser.add_argument("--noise", type=float, default=0.002, help="Gaussian coordinate noise std")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.num_points < 10:
        raise SystemExit("--num-points must be at least 10")
    if args.noise < 0:
        raise SystemExit("--noise must be non-negative")

    rng = np.random.default_rng(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, points in generate_shapes(rng, args.num_points).items():
        if args.noise:
            points = points + rng.normal(0.0, args.noise, size=points.shape)
        output_path = args.output_dir / f"{name}.xyz"
        np.savetxt(output_path, points, fmt="%.7f")
        print(f"wrote {len(points):5d} points -> {output_path}")


if __name__ == "__main__":
    main()
