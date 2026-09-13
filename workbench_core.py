"""Session, shared cameras, pixel ROIs and paper comparison export.

The web UI is deliberately independent of VTK: this module runs in one spawned
worker process, so every VTK render executes on that process's main thread.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import uuid
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from utils import (RenderConfig, CameraSpec, read_xyz, normalize_points,
                   resolve_shared_sphere_radius, fit_camera_to_points,
                   render_point_cloud, save_camera, load_camera, load_camera_metadata)
from publication_utils import export_image_pdf, load_font, sanitize_filename

ROI_COLORS = ["#F07832", "#E45464", "#259CCA", "#7970CE"]
DEFAULT_STYLE = dict(color="#90AEDD", background="#FFFFFF", size_scale=1.0,
                     light_preset="soft", shadow_mode="soft", shadow_opacity=0.09,
                     shadow_blur=32.0, padding=0.12)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.parent / (
        f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )

    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8"
    )

    try:
        for i in range(20):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if i == 19:
                    raise
                time.sleep(0.05)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def roi_pixels(roi, width, height):
    """Normalized top-left ROI -> half-open Pillow pixel bounds."""
    x, y, w, h = [float(roi[k]) for k in ("x", "y", "w", "h")]
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
        raise ValueError("ROI width/height must be finite and positive")
    if x < 0 or y < 0 or x + w > 1.000001 or y + h > 1.000001:
        raise ValueError("ROI must lie inside the image")
    return (min(width-1, round(x*width)), min(height-1, round(y*height)),
            min(width, max(round(x*width)+1, round((x+w)*width))),
            min(height, max(round(y*height)+1, round((y+h)*height))))


class Workspace:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.session_path = self.directory / "session.json"
        self.session = dict(version=1, methods=[], targets=[], objects={}, style=dict(DEFAULT_STYLE))
        self.cloud_cache = {}

    def save(self):
        write_json(self.session_path, self.session)

    def load(self, path):
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        if value.get("version") != 1 or not isinstance(value.get("objects"), dict):
            raise ValueError("Not a workbench v1 session")
        self.session = value
        self.cloud_cache.clear()
        self.save()
        return self.session

    def setup(self, methods, targets=None):
        if not methods or len(methods) > 24:
            raise ValueError("Load between 1 and 24 methods")
        names = [m["name"].strip() for m in methods]
        if any(not n for n in names) or len(set(names)) != len(names):
            raise ValueError("Method names must be nonempty and unique")
        indices, warnings = [], []
        normalized_methods = []
        for method in methods:
            directory = Path(method["directory"]).expanduser().resolve()
            index = {}
            if directory.is_dir():
                for path in sorted(directory.rglob("*")):
                    if path.is_file() and path.suffix.lower() == ".xyz":
                        key = path.name
                        if key in index:
                            warnings.append(f"Ambiguous {key} in {directory}; using {index[key]}")
                        else:
                            index[key] = str(path)
            else:
                warnings.append(f"Directory missing: {directory}")
            indices.append(index)
            normalized_methods.append(dict(name=method["name"].strip(), directory=str(directory),
                                           visible=True, label=method.get("label", method["name"])))
        targets = targets or sorted(set().union(*(set(i) for i in indices)))
        targets = list(dict.fromkeys(targets))
        if not targets:
            raise ValueError("No .xyz files found")
        objects = {}
        for target in targets:
            files = {m["name"]: idx.get(target) for m, idx in zip(normalized_methods, indices)}
            if not any(files.values()):
                warnings.append(f"No method has {target}")
                continue
            objects[target] = dict(files=files, rois=[], metrics={}, color=None,
                azimuth=-52., elevation=27., roll=0., zoom=1., pan_x=0., pan_y=0.,
                camera=None, normalization=None, radius=None, enabled=True)
        if not objects:
            raise ValueError("None of the requested objects exists")
        self.session = dict(version=1, methods=normalized_methods, targets=list(objects),
                            objects=objects, style=dict(DEFAULT_STYLE), warnings=warnings)
        self.cloud_cache.clear()
        self.save()
        return self.session

    def clouds(self, target):
        obj = self.session["objects"][target]
        if target not in self.cloud_cache:
            raw, errors = {}, []
            for name, path in obj["files"].items():
                if path:
                    try:
                        raw[name] = read_xyz(path)
                    except (OSError, ValueError) as exc:
                        errors.append(f"{name}: {exc}")
            if not raw:
                raise ValueError("No readable clouds: " + "; ".join(errors))
            if obj["normalization"] is None:
                ref = next((name for pref in ("gt", "ours") for name in raw if name.lower() == pref), next(iter(raw)))
                _, transform = normalize_points(raw[ref])
                obj["normalization"] = dict(center=transform.center.tolist(), scale=transform.scale, reference=ref)
            tr = obj["normalization"]
            clouds = {name: normalize_points(p, center=tr["center"], scale=tr["scale"])[0] for name, p in raw.items()}
            self.cloud_cache[target] = clouds
            obj["errors"] = errors
        return self.cloud_cache[target]

    def config(self, target, size):
        style = {**DEFAULT_STYLE, **self.session["style"]}
        if self.session["objects"][target].get("color"):
            style["color"] = self.session["objects"][target]["color"]
        cfg = RenderConfig(width=size, height=size, mode="glyph", **style)
        cfg.validate()
        return cfg

    def camera(self, target, cfg, clouds):
        obj = self.session["objects"][target]
        if obj["radius"] is None:
            obj["radius"] = resolve_shared_sphere_radius(list(clouds.values()), replace(cfg, size_scale=1.))
        if obj["camera"] is None:
            cfg = replace(cfg, azimuth=obj["azimuth"], elevation=obj["elevation"], roll=obj["roll"])
            cam = fit_camera_to_points(np.vstack(list(clouds.values())), cfg,
                sphere_radius=obj["radius"] * cfg.size_scale)
            from shadow_utils import camera_basis
            right, up, _ = camera_basis(cam.position, cam.focal_point, cam.view_up)
            shift = right * obj["pan_x"] + up * obj["pan_y"]
            cam = replace(cam, parallel_scale=cam.parallel_scale / obj["zoom"],
                position=tuple(np.asarray(cam.position)+shift), focal_point=tuple(np.asarray(cam.focal_point)+shift))
            obj["camera"] = asdict(cam)
        return CameraSpec(**obj["camera"])

    def geometry(self, target):
        """Normalized coordinates for local interactive preview, never for export."""
        clouds = self.clouds(target)
        return {name: p[np.linspace(0, len(p)-1, min(len(p), 20000), dtype=int)].round(7).tolist()
                for name, p in clouds.items()}

    def undo_rois(self, target):
        obj = self.session["objects"][target]
        history = obj.setdefault("roi_history", [])
        if history:
            obj["rois"] = history.pop()
        self.save()
        return self.session

    def export_assets(self, **kwargs):
        from workbench_export import export_assets
        return export_assets(self, **kwargs)

    def render(self, target, size=480, progress=None):
        if not 96 <= int(size) <= 4096:
            raise ValueError("Render size must be 96..4096")
        clouds = self.clouds(target)
        cfg = self.config(target, int(size))
        cam = self.camera(target, cfg, clouds)
        obj = self.session["objects"][target]
        radius = obj["radius"] * cfg.size_scale
        result = []
        for method in self.session["methods"]:
            name = method["name"]
            if not method["visible"]:
                continue
            if progress:
                progress(f"渲染 {target} / {name}", False)
            if name not in clouds:
                result.append(dict(name=name, label=method["label"], image=None, error="Missing/unreadable"))
                if progress:
                    progress(f"跳过缺失方法 {name}", True)
                continue
            raw_file = Path(obj["files"][name])
            key = hashlib.sha256(json.dumps(dict(target=target, name=name,
                file=str(raw_file), mtime=raw_file.stat().st_mtime_ns,
                normalization=obj["normalization"], config=asdict(cfg), camera=asdict(cam), radius=radius),
                sort_keys=True).encode()).hexdigest()
            path = self.directory / "cache" / (key + ".png")
            if not path.exists():
                render_point_cloud(clouds[name], path, config=cfg, normalize=False, camera=cam, sphere_radius=radius)
            result.append(dict(name=name, label=method["label"], image="/files/cache/"+path.name,
                               path=str(path), points=len(clouds[name])))
            if progress:
                progress(f"已渲染 {target} / {name}", True)
        self.save()
        return dict(panels=result, object=obj, size=size, radius=radius)

    def update(self, data):
        target = data.get("target")
        if "style" in data:
            style = {**self.session["style"], **data["style"]}
            RenderConfig(**style).validate()
            self.session["style"] = style
        if "methods" in data:
            proposed = data["methods"]
            if sorted(m["name"] for m in proposed) != sorted(m["name"] for m in self.session["methods"]):
                raise ValueError("Method list must retain every loaded method")
            previous = {m["name"]: m for m in self.session["methods"]}
            self.session["methods"] = [{**previous[m["name"]], "visible": bool(m["visible"]),
                                         "label": str(m.get("label", m["name"]))} for m in proposed]
        if target:
            obj = self.session["objects"][target]
            patch = data.get("object", {})
            if "camera" in patch:
                cam = CameraSpec(**patch["camera"])
                vectors = np.asarray([cam.position, cam.focal_point, cam.view_up], dtype=float)
                if vectors.shape != (3, 3) or not np.isfinite(vectors).all() or not math.isfinite(cam.parallel_scale) or cam.parallel_scale <= 0:
                    raise ValueError("Invalid interactive camera")
                if np.linalg.norm(vectors[0]-vectors[1]) < 1e-8 or np.linalg.norm(np.cross(vectors[1]-vectors[0], vectors[2])) < 1e-8:
                    raise ValueError("Degenerate camera basis")
            if "rois" in patch:
                if len(patch["rois"]) > 4:
                    raise ValueError("At most four ROIs per object")
                for roi in patch["rois"]:
                    roi_pixels(roi, 1600, 1600)
            for k in ("azimuth", "elevation", "roll", "zoom", "pan_x", "pan_y"):
                if k in patch and not math.isfinite(float(patch[k])):
                    raise ValueError("Camera values must be finite")
            if "zoom" in patch and not 0.2 <= float(patch["zoom"]) <= 8:
                raise ValueError("Zoom must be 0.2..8")
            if "elevation" in patch and not -89 <= float(patch["elevation"]) <= 89:
                raise ValueError("Elevation must be -89..89")
            if "rois" in patch and patch["rois"] != obj["rois"]:
                history = obj.setdefault("roi_history", [])
                history.append(json.loads(json.dumps(obj["rois"])))
                del history[:-30]
            permitted = {"rois", "metrics", "color", "enabled", "azimuth", "elevation", "roll", "zoom", "pan_x", "pan_y"}
            obj.update({k: v for k, v in patch.items() if k in permitted})
            if any(k in patch for k in ("azimuth", "elevation", "roll", "zoom", "pan_x", "pan_y")):
                obj["camera"] = None
            if "camera" in patch:
                obj["camera"] = asdict(cam)
        self.save()
        return self.session

    def camera_file(self, target, path=None, load=False):
        obj = self.session["objects"][target]
        if load:
            camera = load_camera(path)
            meta = load_camera_metadata(path)
            if "normalization" in meta:
                tr = meta["normalization"]
                center = np.asarray(tr["center"], dtype=float)
                if center.shape != (3,) or not np.isfinite(center).all() or not math.isfinite(float(tr["scale"])) or float(tr["scale"]) <= 0:
                    raise ValueError("Invalid normalization metadata")
                obj["normalization"] = tr
                self.cloud_cache.pop(target, None)
            if "base_radius" in meta:
                radius = float(meta["base_radius"])
                if not math.isfinite(radius) or radius <= 0:
                    raise ValueError("Invalid radius metadata")
                obj["radius"] = radius
            obj["camera"] = asdict(camera)
        else:
            camera = self.camera(target, self.config(target, 480), self.clouds(target))
            path = Path(path) if path else self.directory / "cameras" / (sanitize_filename(target)+".json")
            save_camera(camera, path, metadata=dict(normalization=obj["normalization"], base_radius=obj["radius"]))
        self.save()
        return dict(path=str(Path(path).resolve()), object=obj)

    def export(self, size=1600, cell=480, pdf=True):
        size, cell = int(size), int(cell)
        if not 128 <= cell <= 1600 or not 96 <= size <= 4096:
            raise ValueError("Invalid export resolution")
        targets = [t for t in self.session["targets"] if self.session["objects"][t]["enabled"]]
        methods = [m for m in self.session["methods"] if m["visible"]]
        if not targets or not methods:
            raise ValueError("Select at least one object and one method")
        if len(targets) * len(methods) * cell * cell > 100_000_000:
            raise ValueError("Figure too large; reduce cell size or object count")
        directory = self.directory / "exports" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        directory.mkdir(parents=True)
        bg = self.session["style"]["background"]
        gap, margin, header = 20, 28, 54
        widths = len(methods)*cell + (len(methods)-1)*gap
        row_heights = [cell + (round(cell*.48)+18 if self.session["objects"][t]["rois"] else 0) + 52 for t in targets]
        figure = Image.new("RGB", (widths+2*margin, sum(row_heights)+2*margin+header), bg)
        draw = ImageDraw.Draw(figure)
        font = load_font(None, max(16, round(cell*.055)))
        small = load_font(None, max(14, round(cell*.042)))
        for i, method in enumerate(methods):
            centered(draw, method["label"], margin+i*(cell+gap), 18, cell, font)
        records, y = [], margin+header
        for row_index, target in enumerate(targets):
            obj = self.session["objects"][target]
            rendered = self.render(target, size)
            panels = {p["name"]: p for p in rendered["panels"]}
            object_dir = directory / f"{row_index:02d}_{sanitize_filename(Path(target).stem)}"
            object_dir.mkdir()
            camera_path = object_dir / "camera.json"
            save_camera(CameraSpec(**obj["camera"]), camera_path,
                        metadata=dict(normalization=obj["normalization"], base_radius=obj["radius"]))
            record = dict(target=target, camera=str(camera_path), radius=rendered["radius"],
                          normalization=obj["normalization"], rois=obj["rois"], methods=[])
            for i, method in enumerate(methods):
                x = margin+i*(cell+gap)
                panel = panels[method["name"]]
                if not panel["image"]:
                    centered(draw, "Missing", x, y+cell//2, cell, small)
                    record["methods"].append(dict(name=method["name"], status="missing"))
                    continue
                clean = Image.open(panel["path"]).convert("RGB")
                stem = f"{i:02d}_{sanitize_filename(method['name'])}"
                single = object_dir / (stem+".png")
                clean.save(single)
                annotated = clean.copy()
                ad = ImageDraw.Draw(annotated)
                crops = []
                for j, roi in enumerate(obj["rois"]):
                    box = roi_pixels(roi, size, size)
                    color = ROI_COLORS[j]
                    ad.rectangle((box[0], box[1], box[2]-1, box[3]-1), outline=color, width=max(2, round(size/400)))
                    crop = clean.crop(box)
                    crop_path = object_dir / f"{stem}_roi_{j+1}.png"
                    crop.save(crop_path)
                    crops.append(dict(path=str(crop_path), pixels=list(box)))
                    n = len(obj["rois"])
                    cw, ch = (cell-(n-1)*8)//n, round(cell*.48)
                    tile = Image.new("RGB", (cw, ch), bg)
                    scale = min((cw-4)/crop.width, (ch-4)/crop.height)
                    thumb = crop.resize((max(1, round(crop.width*scale)), max(1, round(crop.height*scale))), Image.Resampling.LANCZOS)
                    tx, ty = (cw-thumb.width)//2, (ch-thumb.height)//2
                    tile.paste(thumb, (tx, ty))
                    ImageDraw.Draw(tile).rectangle((tx-1, ty-1, tx+thumb.width, ty+thumb.height), outline=color, width=2)
                    figure.paste(tile, (x+j*(cw+8), y+cell+8))
                annotated.save(object_dir/(stem+"_annotated.png"))
                figure.paste(annotated.resize((cell, cell), Image.Resampling.LANCZOS), (x, y))
                metric = str(obj["metrics"].get(method["name"], ""))
                centered(draw, metric, x, y+row_heights[row_index]-34, cell, small)
                record["methods"].append(dict(name=method["name"], input=obj["files"][method["name"]],
                    single=str(single), crops=crops, metric=metric))
            records.append(record)
            y += row_heights[row_index]
        png = directory/"comparison.png"
        figure.save(png)
        if pdf:
            export_image_pdf(figure, directory/"comparison.pdf", background=bg)
        write_json(directory/"session.json", self.session)
        write_json(directory/"manifest.json", dict(version=1, objects=records, style=self.session["style"],
            pixel_origin="top-left", crop_bounds="left, top, right-exclusive, bottom-exclusive",
            single_size=size, cell_size=cell, output=str(png)))
        return dict(directory=str(directory), png="/files/"+str(png.relative_to(self.directory)),
                    pdf="/files/"+str((directory/"comparison.pdf").relative_to(self.directory)) if pdf else None)


def centered(draw, text, x, y, width, font):
    # Prevent a long metric or method label from leaking into adjacent columns.
    text = str(text)
    measured = draw.textlength(text, font=font)
    if measured > width-6:
        font = load_font(None, max(7, int(getattr(font, "size", 20) * (width-6)/measured)))
    draw.text((x+(width-draw.textlength(text, font=font))/2, y), text, fill="#252D39", font=font)
