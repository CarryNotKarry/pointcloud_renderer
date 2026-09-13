"""Pillow/reportlab helpers for publication-style sheets and PDF export."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont


def load_font(path: str | Path | None, size: int) -> ImageFont.ImageFont:
    """Load a readable cross-platform label font with safe fallbacks."""

    if size <= 0:
        raise ValueError("font size must be positive")
    if path is not None:
        return ImageFont.truetype(str(path), size=size)
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans.ttf",
        "Arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def sanitize_filename(value: str, fallback: str = "item") -> str:
    """Convert a display label to a deterministic, filesystem-safe stem."""

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    return cleaned or fallback


def compose_labeled_grid(
    images: Sequence[Image.Image | np.ndarray],
    labels: Sequence[str],
    *,
    columns: int,
    cell_width: int,
    cell_height: int,
    gap: int = 24,
    margin: int = 32,
    label_size: int = 28,
    label_gap: int = 10,
    font_path: str | Path | None = None,
    background: str = "#FAFAFC",
    selected_index: int | None = None,
) -> Image.Image:
    """Compose equal-sized panels with restrained centered labels."""

    if not images:
        raise ValueError("at least one image is required")
    if len(images) != len(labels):
        raise ValueError("images and labels must have the same length")
    if columns <= 0 or cell_width <= 0 or cell_height <= 0:
        raise ValueError("columns and cell dimensions must be positive")
    if gap < 0 or margin < 0 or label_gap < 0:
        raise ValueError("gap, margin, and label_gap must be non-negative")

    rows = (len(images) + columns - 1) // columns
    label_height = int(round(label_size * 1.65)) + label_gap
    width = 2 * margin + columns * cell_width + max(0, columns - 1) * gap
    height = 2 * margin + rows * (cell_height + label_height) + max(0, rows - 1) * gap
    background_rgb = ImageColor.getrgb(background)
    canvas = Image.new("RGB", (width, height), background_rgb)
    draw = ImageDraw.Draw(canvas)
    font = load_font(font_path, label_size)

    for index, (source, label) in enumerate(zip(images, labels)):
        row, column = divmod(index, columns)
        x = margin + column * (cell_width + gap)
        y = margin + row * (cell_height + label_height + gap)
        tile = Image.fromarray(source) if isinstance(source, np.ndarray) else source
        tile = _fit_tile(tile.convert("RGBA"), cell_width, cell_height, background_rgb)
        canvas.paste(tile.convert("RGB"), (x, y))

        display_label = label
        label_font = _fit_text_font(
            draw,
            display_label,
            font_path=font_path,
            preferred_size=label_size,
            maximum_width=max(1, cell_width - 12),
            fallback=font,
        )
        box = draw.textbbox((0, 0), display_label, font=label_font)
        text_width = box[2] - box[0]
        text_x = x + max(0.0, (cell_width - text_width) / 2.0)
        text_y = y + cell_height + label_gap
        color = (37, 44, 56) if index == selected_index else (55, 61, 72)
        draw.text((text_x, text_y), display_label, fill=color, font=label_font)
        if index == selected_index:
            line_width = max(2, cell_width // 260)
            draw.rounded_rectangle(
                (x, y, x + cell_width - 1, y + cell_height - 1),
                radius=max(4, cell_width // 80),
                outline=(96, 119, 156),
                width=line_width,
            )

    return canvas


def autocrop_image(
    image: Image.Image,
    *,
    background: str = "#FAFAFC",
    tolerance: int = 5,
    padding: int = 24,
) -> Image.Image:
    """Crop uniform outer background while retaining an exact pixel margin."""

    if tolerance < 0 or padding < 0:
        raise ValueError("tolerance and padding must be non-negative")
    rgba = np.asarray(image.convert("RGBA"), dtype=np.int16)
    if image.mode == "RGBA" and np.any(rgba[..., 3] < 255):
        foreground = rgba[..., 3] > tolerance
    else:
        bg = np.asarray(ImageColor.getrgb(background), dtype=np.int16)
        foreground = np.max(np.abs(rgba[..., :3] - bg[None, None, :]), axis=2) > tolerance
    locations = np.argwhere(foreground)
    if locations.size == 0:
        return image.copy()
    y_min, x_min = locations.min(axis=0)
    y_max, x_max = locations.max(axis=0)
    left = max(0, int(x_min) - padding)
    top = max(0, int(y_min) - padding)
    right = min(image.width, int(x_max) + padding + 1)
    bottom = min(image.height, int(y_max) + padding + 1)
    return image.crop((left, top, right, bottom))


def save_png(image: Image.Image, path: str | Path) -> Path:
    """Write an optimized PNG, creating parent directories as needed."""

    output = Path(path)
    if output.suffix.lower() != ".png":
        raise ValueError("PNG output path must end with .png")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)
    return output


def export_image_pdf(
    image: Image.Image,
    path: str | Path,
    *,
    dpi: float = 150.0,
    background: str = "#FAFAFC",
) -> Path:
    """Export a raster figure to a page-matched PDF without resampling it."""

    if dpi <= 0:
        raise ValueError("dpi must be positive")
    output = Path(path)
    if output.suffix.lower() != ".pdf":
        raise ValueError("PDF output path must end with .pdf")
    try:
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError(
            "PDF export needs reportlab. Install project dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc

    flattened = _flatten_image(image, background)
    buffer = io.BytesIO()
    flattened.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    page_width = flattened.width * 72.0 / dpi
    page_height = flattened.height * 72.0 / dpi
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output), pagesize=(page_width, page_height), pageCompression=1)
    pdf.drawImage(
        ImageReader(buffer),
        0,
        0,
        width=page_width,
        height=page_height,
        preserveAspectRatio=True,
        mask="auto",
    )
    pdf.showPage()
    pdf.save()
    return output


def _fit_tile(
    image: Image.Image,
    width: int,
    height: int,
    background_rgb: tuple[int, int, int],
) -> Image.Image:
    if image.size == (width, height):
        return image
    scale = min(width / image.width, height / image.height)
    resized_size = (
        max(1, int(round(image.width * scale))),
        max(1, int(round(image.height * scale))),
    )
    resized = image.resize(resized_size, Image.Resampling.LANCZOS)
    tile = Image.new("RGBA", (width, height), (*background_rgb, 255))
    destination = ((width - resized.width) // 2, (height - resized.height) // 2)
    tile.alpha_composite(resized, dest=destination)
    return tile


def _fit_text_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font_path: str | Path | None,
    preferred_size: int,
    maximum_width: int,
    fallback: ImageFont.ImageFont,
) -> ImageFont.ImageFont:
    """Reduce label size only when needed to keep it inside one panel."""

    if draw.textlength(text, font=fallback) <= maximum_width:
        return fallback
    minimum_size = min(preferred_size, 11)
    for size in range(preferred_size - 1, minimum_size - 1, -1):
        candidate = load_font(font_path, size)
        if draw.textlength(text, font=candidate) <= maximum_width:
            return candidate
    return load_font(font_path, minimum_size)


def _flatten_image(image: Image.Image, background: str) -> Image.Image:
    rgba = image.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, (*ImageColor.getrgb(background), 255))
    canvas.alpha_composite(rgba)
    return canvas.convert("RGB")
