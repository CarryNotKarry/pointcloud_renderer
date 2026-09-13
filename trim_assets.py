from pathlib import Path
import argparse
import shutil

import fitz
import numpy as np
from PIL import Image


SUPPORTED_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".pdf",
}


def image_for_detection(image):
    """
    把图片转换成用于检测边界的 RGB 图。

    对带透明通道的 PNG：
    透明区域按照白色背景处理。
    """
    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")

        bg = Image.new(
            "RGBA",
            rgba.size,
            (255, 255, 255, 255)
        )

        merged = Image.alpha_composite(bg, rgba)

        return merged.convert("RGB")

    return image.convert("RGB")


def find_content_bbox(
    image,
    tolerance=0,
    padding=1,
):
    """
    找到非白色内容的最小包围框。

    参数
    ----------
    image:
        PIL Image

    tolerance:
        白色容差。

        tolerance=0:
            只有 (255,255,255) 才视为白色。

        tolerance=2:
            RGB 三个通道都 >= 253 时视为白色。
            主要用于 JPG 压缩噪声。

    padding:
        找到内容后额外向外保留多少像素。
        默认 1。

    返回
    ----------
    (left, top, right, bottom)

    PIL crop 规则：
        right / bottom 为 exclusive。
    """

    img = image_for_detection(image)

    arr = np.asarray(img)

    white_limit = 255 - tolerance

    # 只要任意 RGB 通道低于 white_limit，
    # 就认为这个像素属于内容。
    #
    # tolerance = 0 时：
    # (255,255,255) -> 白
    # (254,255,255) -> 内容
    #
    # tolerance = 2 时：
    # 253~255      -> 白
    # <=252        -> 内容
    content_mask = np.any(
        arr < white_limit,
        axis=2
    )

    ys, xs = np.where(content_mask)

    if len(xs) == 0:
        return None

    left = int(xs.min())
    right = int(xs.max()) + 1

    top = int(ys.min())
    bottom = int(ys.max()) + 1

    # 向外多留 padding 像素
    left = max(
        0,
        left - padding
    )

    top = max(
        0,
        top - padding
    )

    right = min(
        img.width,
        right + padding
    )

    bottom = min(
        img.height,
        bottom + padding
    )

    return (
        left,
        top,
        right,
        bottom,
    )


def trim_image(
    src,
    dst,
    padding=1,
    jpg_tolerance=2,
):
    """
    裁剪 PNG/JPG/JPEG。
    """

    ext = src.suffix.lower()

    with Image.open(src) as image:

        original_size = image.size

        if ext in {
            ".jpg",
            ".jpeg",
        }:
            tolerance = jpg_tolerance
        else:
            tolerance = 0

        bbox = find_content_bbox(
            image,
            tolerance=tolerance,
            padding=padding,
        )

        dst.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        if bbox is None:
            print(
                f"[BLANK] {src}"
            )

            shutil.copy2(
                src,
                dst
            )

            return

        cropped = image.crop(bbox)

        if ext in {
            ".jpg",
            ".jpeg",
        }:
            cropped = cropped.convert("RGB")

            cropped.save(
                dst,
                quality=98,
                subsampling=0,
            )

        elif ext == ".png":

            cropped.save(
                dst,
                optimize=True,
            )

        else:

            cropped.save(dst)

        print(
            f"[IMAGE] {src.name}"
        )

        print(
            f"        "
            f"{original_size[0]} x "
            f"{original_size[1]}"
            f"  ->  "
            f"{cropped.width} x "
            f"{cropped.height}"
        )

        print(
            f"        bbox = {bbox}"
        )


def trim_pdf(
    src,
    dst,
    padding=1,
    dpi=300,
):
    """
    裁剪 PDF 白边。

    注意：
    PDF 只通过渲染图判断内容范围，
    最终不会把 PDF 重新栅格化。

    修改的是 PDF 页面 CropBox，
    因而保留原 PDF 内容质量。
    """

    doc = fitz.open(src)

    changed = False

    try:

        for page_index in range(len(doc)):

            page = doc[page_index]

            original_rect = page.rect

            pix = page.get_pixmap(
                dpi=dpi,
                alpha=False,
            )

            image = Image.frombytes(
                "RGB",
                (
                    pix.width,
                    pix.height,
                ),
                pix.samples,
            )

            bbox = find_content_bbox(
                image,
                tolerance=0,
                padding=padding,
            )

            if bbox is None:

                print(
                    f"[PDF BLANK] "
                    f"{src.name} "
                    f"page {page_index + 1}"
                )

                continue

            left, top, right, bottom = bbox

            # raster pixel -> PDF point
            scale_x = (
                original_rect.width
                / pix.width
            )

            scale_y = (
                original_rect.height
                / pix.height
            )

            crop_rect = fitz.Rect(
                original_rect.x0
                + left * scale_x,

                original_rect.y0
                + top * scale_y,

                original_rect.x0
                + right * scale_x,

                original_rect.y0
                + bottom * scale_y,
            )

            # 限制在原始页面范围内
            crop_rect = (
                crop_rect
                & original_rect
            )

            if (
                crop_rect.width <= 0
                or crop_rect.height <= 0
            ):
                print(
                    f"[PDF INVALID] "
                    f"{src.name} "
                    f"page {page_index + 1}"
                )

                continue

            page.set_cropbox(
                crop_rect
            )

            changed = True

            print(
                f"[PDF] {src.name} "
                f"page {page_index + 1}"
            )

            print(
                "      "
                f"{original_rect.width:.2f} x "
                f"{original_rect.height:.2f}"
                "  ->  "
                f"{crop_rect.width:.2f} x "
                f"{crop_rect.height:.2f}"
            )

        dst.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        if changed:

            doc.save(
                dst,
                garbage=4,
                deflate=True,
            )

        else:

            doc.close()

            shutil.copy2(
                src,
                dst
            )

            return

    finally:

        if not doc.is_closed:
            doc.close()


def collect_files(root):
    """
    递归获取所有支持的素材文件。
    """

    files = []

    for path in root.rglob("*"):

        if (
            path.is_file()
            and path.suffix.lower()
            in SUPPORTED_EXTS
        ):
            files.append(path)

    return sorted(files)


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Recursively remove pure-white borders "
            "from PNG/JPG/PDF assets."
        )
    )

    parser.add_argument(
        "input_dir",
        help="输入目录",
    )

    parser.add_argument(
        "output_dir",
        help="输出目录",
    )

    parser.add_argument(
        "--padding",
        type=int,
        default=1,
        help=(
            "找到第一个非白像素后，"
            "额外向外保留的像素数。"
            "默认 1。"
        ),
    )

    parser.add_argument(
        "--jpg-tolerance",
        type=int,
        default=2,
        help=(
            "JPG 白色容差。"
            "默认 2，即 RGB>=253 视为白色。"
        ),
    )

    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help=(
            "PDF 检测边界时使用的 DPI。"
            "默认 300。"
        ),
    )

    args = parser.parse_args()

    input_dir = Path(
        args.input_dir
    ).expanduser().resolve()

    output_dir = Path(
        args.output_dir
    ).expanduser().resolve()

    if not input_dir.exists():

        raise FileNotFoundError(
            f"输入目录不存在：{input_dir}"
        )

    if not input_dir.is_dir():

        raise ValueError(
            f"输入路径不是目录：{input_dir}"
        )

    if input_dir == output_dir:

        raise ValueError(
            "输入目录和输出目录不能相同。"
        )

    # 防止输出目录位于输入目录中时，
    # 第二次运行把自己再次递归处理。
    try:

        output_dir.relative_to(
            input_dir
        )

        output_inside_input = True

    except ValueError:

        output_inside_input = False

    files = collect_files(
        input_dir
    )

    if output_inside_input:

        files = [
            p
            for p in files
            if output_dir
            not in p.parents
        ]

    print()
    print("=" * 70)

    print(
        "Trim Assets"
    )

    print("=" * 70)

    print(
        f"Input  : {input_dir}"
    )

    print(
        f"Output : {output_dir}"
    )

    print(
        f"Files  : {len(files)}"
    )

    print(
        f"Padding: {args.padding}px"
    )

    print(
        f"PDF DPI: {args.dpi}"
    )

    print(
        "PNG/PDF white rule: "
        "exact RGB (255,255,255)"
    )

    print(
        "JPG tolerance: "
        f"{args.jpg_tolerance}"
    )

    print("=" * 70)
    print()

    success = 0
    failed = 0

    for index, src in enumerate(
        files,
        start=1,
    ):

        relative = src.relative_to(
            input_dir
        )

        dst = (
            output_dir
            / relative
        )

        print(
            f"[{index}/{len(files)}] "
            f"{relative}"
        )

        try:

            if (
                src.suffix.lower()
                == ".pdf"
            ):

                trim_pdf(
                    src,
                    dst,
                    padding=args.padding,
                    dpi=args.dpi,
                )

            else:

                trim_image(
                    src,
                    dst,
                    padding=args.padding,
                    jpg_tolerance=(
                        args.jpg_tolerance
                    ),
                )

            success += 1

        except Exception as exc:

            failed += 1

            print(
                f"[ERROR] {src}"
            )

            print(
                f"        {type(exc).__name__}: "
                f"{exc}"
            )

        print()

    print("=" * 70)

    print(
        "Finished"
    )

    print(
        f"Success : {success}"
    )

    print(
        f"Failed  : {failed}"
    )

    print(
        f"Output  : {output_dir}"
    )

    print("=" * 70)


if __name__ == "__main__":
    main()