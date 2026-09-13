"""Independent, caption-free PDF/JPG/PNG assets and measurable export progress."""
import html
import json
import zipfile
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw
from publication_utils import export_image_pdf, sanitize_filename
from utils import CameraSpec, save_camera
from workbench_core import (ROI_COLORS, ROI_LINE_RATIO, roi_pixels, write_json,
                            draw_roi_frame, framed_roi)


def export_assets(workspace, size=1600, pdf=True, comparison=False, cell=480, progress_path=None):
    size = int(size)
    if not 96 <= size <= 4096:
        raise ValueError("Export size must be 96..4096")
    session = workspace.session
    targets = [t for t in session["targets"] if session["objects"][t]["enabled"]]
    methods = [m for m in session["methods"] if m["visible"]]
    if not targets or not methods:
        raise ValueError("Select at least one object and method")
    directory = workspace.directory/"exports"/datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    directory.mkdir(parents=True)
    total = len(targets)*len(methods)*2+2+int(comparison)
    completed = 0

    def progress(message, advance=False):
        nonlocal completed
        completed += int(advance)
        if progress_path:
            write_json(progress_path, dict(state="running", completed=completed, total=total,
                percent=min(99, int(completed/total*100)), message=message, directory=str(directory)))

    progress("准备导出独立素材")
    session["export_settings"] = dict(size=size, pdf=bool(pdf), jpg=True, png=True,
                                      roi_line_ratio=ROI_LINE_RATIO, roi_stroke="center",
                                      comparison=bool(comparison), cell=cell)
    workspace.save()
    index = []

    def save_asset(image, base):
        image = image.convert("RGB")
        paths = {}
        for ext in ("png", "jpg"):
            path = base.with_suffix("."+ext)
            image.save(path, **(dict(quality=98, subsampling=0) if ext == "jpg" else {}))
            paths[ext] = str(path.relative_to(directory))
        if pdf:
            path = base.with_suffix(".pdf")
            export_image_pdf(image, path, background=session["style"]["background"])
            paths["pdf"] = str(path.relative_to(directory))
        index.append(dict(name=str(base.relative_to(directory)), files=paths))
        return paths

    records = []
    for ti, target in enumerate(targets):
        obj = session["objects"][target]
        panels = workspace.render(target, size, progress=progress)
        by_name = {p["name"]: p for p in panels["panels"]}
        dest = directory/f"{ti:02d}_{sanitize_filename(Path(target).stem)}"
        dest.mkdir()
        save_camera(CameraSpec(**obj["camera"]), dest/"camera.json",
            metadata=dict(normalization=obj["normalization"], base_radius=obj["radius"]))
        write_json(dest/"regions.json", dict(normalized=obj["rois"], colors=ROI_COLORS,
            image_size=[size, size], line_width=size*ROI_LINE_RATIO, stroke="center",
            pixels=[roi_pixels(r, size, size) for r in obj["rois"]]))
        overlay = Image.new("RGBA", (size, size))
        od = ImageDraw.Draw(overlay)
        for j, roi in enumerate(obj["rois"]):
            a,b,c,d = roi_pixels(roi,size,size)
            draw_roi_frame(overlay, (a,b,c,d), ROI_COLORS[j], size*ROI_LINE_RATIO)
        overlay.save(dest/"roi_frames.png")
        record = dict(target=target, camera=obj["camera"], normalization=obj["normalization"],
                      radius=panels["radius"], color=obj.get("color") or session["style"]["color"], methods=[])
        for mi, method in enumerate(methods):
            name = method["name"]
            panel = by_name[name]
            if not panel["image"]:
                record["methods"].append(dict(name=name,status="missing"))
                progress(f"跳过 {target} / {name}", True)
                continue
            progress(f"保存 PDF/JPG：{target} / {name}")
            stem = f"{mi:02d}_{sanitize_filename(name)}"
            with Image.open(panel["path"]) as image:
                clean = image.convert("RGB")
            clean_files = save_asset(clean, dest/(stem+"_clean"))
            annotated = Image.alpha_composite(clean.convert("RGBA"),overlay).convert("RGB")
            framed_files = save_asset(annotated, dest/(stem+"_annotated"))
            crops = []
            for j, roi in enumerate(obj["rois"]):
                box = roi_pixels(roi,size,size)
                crop = clean.crop(box)
                raw_files = save_asset(crop,dest/f"{stem}_roi_{j+1}_clean")
                bordered, margin = framed_roi(crop, ROI_COLORS[j], size*ROI_LINE_RATIO,
                                              session["style"]["background"])
                default_files = save_asset(bordered,dest/f"{stem}_roi_{j+1}")
                border_files = save_asset(bordered,dest/f"{stem}_roi_{j+1}_framed")
                crops.append(dict(pixels=list(box), clean=raw_files, framed=border_files,
                                  default=default_files, image_offset=[margin, margin],
                                  line_width=size*ROI_LINE_RATIO, stroke="center"))
            record["methods"].append(dict(name=name,input=obj["files"][name],
                clean=clean_files, annotated=framed_files, crops=crops))
            progress(f"已保存 {target} / {name}",True)
        records.append(record)
    comparison_path = None
    if comparison:
        progress("生成可选拼接参考图")
        comparison_path = workspace.export(size=size,cell=cell,pdf=pdf)["directory"]
        progress("拼接参考图已完成",True)
    write_json(directory/"session.json",session)
    write_json(directory/"manifest.json",dict(version=2,objects=records,style=session["style"],
        exports=session["export_settings"], pixel_origin="top-left",bounds="left,top,right-exclusive,bottom-exclusive",
        files=index,comparison_directory=comparison_path))
    links = []
    for item in index:
        files = ' '.join(f'<a href="{html.escape(p,quote=True)}">{ext.upper()}</a>' for ext,p in item["files"].items())
        links.append(f'<li>{html.escape(item["name"])} — {files}</li>')
    (directory/"index.html").write_text('<!doctype html><meta charset="utf-8"><title>导出素材</title>'
        '<style>body{font:15px system-ui;padding:30px;line-height:2}a{margin:8px;color:#246c72}</style>'
        '<h1>独立素材 · PDF / JPG / PNG</h1><p>每张图不带标题，可直接放入 WPS 排版。</p>'
        '<a href="assets.zip">下载全部素材 ZIP</a><ul>'+''.join(links)+'</ul>',encoding="utf-8")
    progress("写入会话、选框和文件索引",True)
    with zipfile.ZipFile(directory/"assets.zip","w",compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.name != "assets.zip":
                archive.write(path,str(path.relative_to(directory)))
    progress("素材打包完成",True)
    url = "/files/"+str(directory.relative_to(workspace.directory))
    return dict(directory=str(directory),index=url+"/index.html",zip=url+"/assets.zip",
                file_count=len(index),comparison_directory=comparison_path)
