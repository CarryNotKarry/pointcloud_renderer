#!/usr/bin/env python3
"""Local interactive workbench: python render_workbench.py --demo."""
from __future__ import annotations

import argparse
import json
import mimetypes
import multiprocessing
import threading
import webbrowser
import uuid
from concurrent.futures import ProcessPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

_workspace = None


def dispatch(directory, action, data):
    """Only this worker owns cloud caches and VTK OpenGL windows."""
    global _workspace
    from workbench_core import Workspace, write_json
    if _workspace is None:
        _workspace = Workspace(directory)
    w = _workspace
    if action == "state":
        return w.session
    if action == "setup":
        return w.setup(data["methods"], data.get("targets"))
    if action == "update":
        return w.update(data)
    if action == "render":
        return w.render(data["target"], data.get("size", 480))
    if action == "geometry":
        return w.geometry(data["target"])
    if action == "undo_rois":
        return w.undo_rois(data["target"])
    if action == "export":
        return w.export_assets(**data)
    if action == "camera":
        return w.camera_file(data["target"], data.get("path"), data.get("load", False))
    if action == "load":
        return w.load(data["path"])
    if action == "save":
        w.save()
        path = Path(data["path"]).expanduser() if data.get("path") else w.session_path
        write_json(path, w.session)
        return dict(path=str(path.resolve()))
    if action == "demo":
        import numpy as np
        # Bundled sample data is included in the repository. This demonstration
        # contains sampling variants, never results attributed to real methods.
        source = Path(__file__).parent/"demo_data"
        for name, stride in (("Demo-Input", 5), ("Demo-Dense", 1), ("GT", 1)):
            dest = Path(directory)/"demo"/name
            dest.mkdir(parents=True, exist_ok=True)
            for target in ("box.xyz", "bracket.xyz", "wedge.xyz"):
                cloud = np.loadtxt(source/target)
                np.savetxt(dest/target, cloud[::stride], fmt="%.7f")
        return w.setup([dict(name=n, directory=str(Path(directory)/"demo"/n))
                        for n in ("Demo-Input", "Demo-Dense", "GT")])
    raise ValueError("Unknown operation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).parent/"workbench_data")
    parser.add_argument("--session", type=Path)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--export-only", action="store_true", help="Re-export a saved session without starting the UI")
    parser.add_argument("--size", type=int, default=1600)
    parser.add_argument("--cell", type=int, default=480)
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument("--comparison", action="store_true", help="Also generate the optional assembled reference figure")
    parser.add_argument("--method_dirs", nargs="+", type=Path)
    parser.add_argument("--method_names", nargs="+")
    parser.add_argument("--targets", nargs="+")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    if args.method_names and (not args.method_dirs or len(args.method_names) != len(args.method_dirs)):
        parser.error("method_names must match method_dirs")
    if sum(bool(v) for v in (args.demo, args.session, args.method_dirs)) > 1:
        parser.error("choose one of --demo, --session, --method_dirs")
    directory = args.workspace.resolve()
    assets = Path(__file__).parent/"workbench_web"
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    lock = threading.Lock()

    def call(action, data):
        with lock:
            return pool.submit(dispatch, str(directory), action, data).result()

    if args.demo:
        call("demo", {})
    elif args.session:
        call("load", dict(path=str(args.session.resolve())))
    elif args.method_dirs:
        names = args.method_names or [p.name for p in args.method_dirs]
        call("setup", dict(methods=[dict(name=n, directory=str(p.resolve()))
             for n, p in zip(names, args.method_dirs)], targets=args.targets))
    elif (directory/"session.json").is_file():
        call("load", dict(path=str(directory/"session.json")))

    if args.export_only:
        try:
            print(json.dumps(call("export", dict(size=args.size, cell=args.cell, pdf=not args.no_pdf, comparison=args.comparison)), indent=2))
        finally:
            pool.shutdown(wait=True)
        return

    job_lock = threading.Lock()
    active_job = None

    def start_export(data):
        nonlocal active_job
        from workbench_core import write_json
        with job_lock:
            if active_job is not None:
                raise ValueError("An export is already running")
            job_id = uuid.uuid4().hex
            progress_path = directory/"jobs"/(job_id+".json")
            write_json(progress_path,dict(state="queued",percent=0,message="等待导出任务"))
            active_job = job_id

        def run():
            nonlocal active_job
            try:
                result = call("export", {**data,"progress_path":str(progress_path)})
                write_json(progress_path,dict(state="complete",percent=100,message="导出完成",result=result))
            except Exception as exc:
                write_json(progress_path,dict(state="failed",message=str(exc)))
            finally:
                with job_lock:
                    active_job = None
        threading.Thread(target=run,daemon=True).start()
        return dict(job_id=job_id)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *values):
            if args and len(values)>1 and str(values[1]).startswith("2"):
                return
            super().log_message(fmt, *values)

        def reply(self, value, status=200):
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def local_request(self):
            allowed = {f"127.0.0.1:{args.port}", f"localhost:{args.port}"}
            if self.headers.get("Host") not in allowed:
                self.reply({"error":"Invalid local host"}, 403)
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://"+h for h in allowed}:
                self.reply({"error":"Cross-origin requests are disabled"}, 403)
                return False
            return True

        def do_GET(self):
            if not self.local_request():
                return
            route = unquote(urlparse(self.path).path)
            if route.startswith("/api/jobs/"):
                job_id = route.rsplit("/",1)[-1]
                if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
                    self.reply({"error":"Invalid job ID"},400)
                    return
                path = directory/"jobs"/(job_id+".json")
                if not path.is_file():
                    self.reply({"error":"Export job not found"},404)
                else:
                    self.reply(json.loads(path.read_text()))
                return
            if route == "/api/state":
                try:
                    self.reply(call("state", {}))
                except Exception as exc:
                    self.reply({"error":str(exc)}, 400)
                return
            root, relative = (directory, route[7:]) if route.startswith("/files/") else (assets, route.lstrip("/") or "index.html")
            path = (root/relative).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                self.send_error(404)
                return
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if not self.local_request():
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self.reply({"error":"Expected application/json"}, 415)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 2_000_000:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                action = urlparse(self.path).path.removeprefix("/api/")
                self.reply(start_export(data) if action == "export" else call(action, data))
            except Exception as exc:
                self.reply({"error":str(exc)}, 400)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Point Cloud Workbench: {url}\nWorkspace: {directory}\nCtrl+C to stop.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        pool.shutdown(wait=True)


if __name__ == "__main__":
    main()
