"""Reusable multi-view preview generation for camera selection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image

if __package__:
    from .publication_utils import autocrop_image, compose_labeled_grid, export_image_pdf, save_png
    from .utils import CameraSpec, RenderConfig, fit_camera_to_points, render_point_cloud, save_camera
else:
    from publication_utils import autocrop_image, compose_labeled_grid, export_image_pdf, save_png
    from utils import CameraSpec, RenderConfig, fit_camera_to_points, render_point_cloud, save_camera


@dataclass(frozen=True)
class PreviewView:
    """One deterministic candidate camera direction."""

    azimuth: float
    elevation: float
    roll: float = 0.0


@dataclass(frozen=True)
class PreviewRecord:
    """Files and camera parameters produced for one candidate view."""

    index: int
    view: PreviewView
    image_path: Path
    camera_path: Path
    camera: CameraSpec


@dataclass(frozen=True)
class PreviewResult:
    """Complete preview-sheet result."""

    records: tuple[PreviewRecord, ...]
    sheet_png: Path
    sheet_pdf: Path | None


DEFAULT_PREVIEW_VIEWS: tuple[PreviewView, ...] = (
    PreviewView(-52.0, 27.0),
    PreviewView(-28.0, 22.0),
    PreviewView(0.0, 22.0),
    PreviewView(28.0, 22.0),
    PreviewView(52.0, 27.0),
    PreviewView(-38.0, 38.0),
    PreviewView(0.0, 38.0),
    PreviewView(38.0, 38.0),
)


def generate_multiview_preview(
    subject_points: np.ndarray,
    *,
    output_dir: str | Path,
    object_stem: str,
    config: RenderConfig,
    sphere_radius: float,
    framing_points: np.ndarray | None = None,
    views: Sequence[PreviewView] = DEFAULT_PREVIEW_VIEWS,
    preview_size: int = 640,
    columns: int = 4,
    label_size: int = 24,
    font_path: str | Path | None = None,
    selected_index: int | None = None,
    save_pdf: bool = True,
    pdf_dpi: float = 150.0,
    autocrop: bool = True,
    crop_padding: int = 24,
    camera_metadata: dict | None = None,
) -> PreviewResult:
    """Render camera candidates, their camera JSON files, and a preview sheet."""

    if not views:
        raise ValueError("at least one preview view is required")
    if preview_size <= 0 or columns <= 0:
        raise ValueError("preview_size and columns must be positive")
    if selected_index is not None and not 0 <= selected_index < len(views):
        raise ValueError(f"selected_index must be in [0, {len(views) - 1}]")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    framing = subject_points if framing_points is None else framing_points
    images: list[Image.Image] = []
    labels: list[str] = []
    records: list[PreviewRecord] = []

    for index, view in enumerate(views):
        view_config = replace(
            config,
            width=preview_size,
            height=preview_size,
            azimuth=view.azimuth,
            elevation=view.elevation,
            roll=view.roll,
            camera_scale=None,
        )
        camera = fit_camera_to_points(framing, view_config, sphere_radius=sphere_radius)
        image_path = destination / f"view_{index:02d}.png"
        camera_path = destination / f"view_{index:02d}_camera.json"
        image_array = render_point_cloud(
            subject_points,
            image_path,
            config=view_config,
            normalize=False,
            camera=camera,
            sphere_radius=sphere_radius,
        )
        metadata = dict(camera_metadata or {})
        metadata["preview_view"] = {
            "index": index,
            "azimuth": view.azimuth,
            "elevation": view.elevation,
            "roll": view.roll,
        }
        save_camera(camera, camera_path, metadata=metadata)
        images.append(Image.fromarray(image_array))
        labels.append(
            f"view_{index:02d} | az {view.azimuth:g}, el {view.elevation:g}, roll {view.roll:g}"
        )
        records.append(PreviewRecord(index, view, image_path, camera_path, camera))

    sheet = compose_labeled_grid(
        images,
        labels,
        columns=min(columns, len(images)),
        cell_width=preview_size,
        cell_height=preview_size,
        gap=max(12, preview_size // 36),
        margin=max(20, preview_size // 24),
        label_size=label_size,
        label_gap=max(6, label_size // 4),
        font_path=font_path,
        background=config.background,
        selected_index=selected_index,
    )
    if autocrop:
        sheet = autocrop_image(sheet, background=config.background, padding=crop_padding)
    sheet_png = save_png(sheet, destination / f"{object_stem}_preview_sheet.png")
    sheet_pdf = None
    if save_pdf:
        sheet_pdf = export_image_pdf(
            sheet,
            destination / f"{object_stem}_preview_sheet.pdf",
            dpi=pdf_dpi,
            background=config.background,
        )
    return PreviewResult(tuple(records), sheet_png, sheet_pdf)
