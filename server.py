#!/usr/bin/env python3
"""多平台网页游戏厅：静态资源 + ROM 上传/列表/删除。纯 stdlib，无依赖。"""
import json
import mimetypes
import os
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
ROMS_DIR = os.path.join(ROOT, "roms")
MAX_UPLOAD = 500 * 1024 * 1024  # 500MB 上限（PSP/PS1 镜像较大）

# 平台注册表：key = EmulatorJS 平台名（EJS_core 直接用这个值）
PLATFORMS = {
    "nes":     {"label": "FC 红白机",     "exts": ["nes", "fds", "zip", "7z"]},
    "snes":    {"label": "SFC 超任",      "exts": ["sfc", "smc", "zip", "7z"]},
    "gb":      {"label": "GB/GBC",        "exts": ["gb", "gbc", "zip", "7z"]},
    "gba":     {"label": "GBA",           "exts": ["gba", "zip", "7z"]},
    "segaMD":  {"label": "世嘉 MD",       "exts": ["md", "gen", "bin", "zip", "7z"]},
    "n64":     {"label": "N64",           "exts": ["n64", "z64", "v64", "zip", "7z"]},
    "nds":     {"label": "NDS",           "exts": ["nds", "zip", "7z"]},
    "psx":     {"label": "PS1",           "exts": ["chd", "cue", "bin", "pbp", "img", "iso", "zip", "7z"]},
    "psp":     {"label": "PSP",           "exts": ["iso", "cso", "pbp", "chd", "zip", "7z"]},
    "arcade":  {"label": "街机",           "exts": ["zip", "7z"]},
}

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/octet-stream", ".data")
for ext in ["gba", "nes", "sfc", "smc", "gb", "gbc", "md", "gen", "n64", "z64", "v64",
            "nds", "chd", "cue", "bin", "pbp", "img", "iso", "cso"]:
    mimetypes.add_type("application/octet-stream", "." + ext)
mimetypes.add_type("application/x-7z-compressed", ".7z")


def sanitize(name: str):
    """只留 basename，挡路径穿越。"""
    name = os.path.basename((name or "").strip())
    if not name or name.startswith(".") or "/" in name or "\\" in name:
        return None
    return name


def valid_platform(p: str):
    return p if p in PLATFORMS else None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def send_response(self, *args, **kwargs):
        super().send_response(*args, **kwargs)
        # 跨源隔离：PSP(ppsspp) 等线程内核需要 SharedArrayBuffer，
        # 页面必须带这两个头才会暴露。同源资源不受影响。
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")

    # ---------- helpers ----------
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _rom_path(self, platform, name):
        platform = valid_platform(platform)
        name = sanitize(name)
        if not platform or not name:
            return None
        fp = os.path.join(ROMS_DIR, platform, name)
        if not os.path.isfile(fp):
            return None
        return fp

    # ---------- GET ----------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/health":
            self._json(200, {"ok": True, "platforms": len(PLATFORMS)})
        elif path == "/api/roms":
            items = []
            counts = {p: 0 for p in PLATFORMS}
            for p in PLATFORMS:
                pdir = os.path.join(ROMS_DIR, p)
                if not os.path.isdir(pdir):
                    continue
                for n in os.listdir(pdir):
                    if n.startswith("."):
                        continue
                    fp = os.path.join(pdir, n)
                    if not os.path.isfile(fp):
                        continue
                    st = os.stat(fp)
                    counts[p] += 1
                    items.append({"platform": p, "name": n, "size": st.st_size, "mtime": int(st.st_mtime)})
            items.sort(key=lambda x: (-x["mtime"]))
            self._json(200, {"ok": True, "roms": items, "counts": counts})
        elif path.startswith("/roms/"):
            rest = urllib.parse.unquote(path[len("/roms/"):])
            parts = rest.split("/", 1)
            if len(parts) != 2:
                self._json(404, {"ok": False, "error": "not found"})
                return
            fp = self._rom_path(parts[0], parts[1])
            if not fp:
                self._json(404, {"ok": False, "error": "not found"})
                return
            size = os.path.getsize(fp)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(fp, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        else:
            super().do_GET()

    # ---------- POST /api/upload ----------
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/upload":
            self._json(404, {"ok": False})
            return
        qs = urllib.parse.parse_qs(parsed.query)
        platform = valid_platform(qs.get("platform", [""])[0])
        name = sanitize(qs.get("name", [""])[0])
        if not platform:
            self._json(400, {"ok": False, "error": "平台不合法"})
            return
        if not name:
            self._json(400, {"ok": False, "error": "文件名不合法"})
            return
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in PLATFORMS[platform]["exts"]:
            self._json(400, {"ok": False, "error": f"{PLATFORMS[platform]['label']} 不支持 .{ext} 文件"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_UPLOAD:
            self._json(400, {"ok": False, "error": f"文件大小不合法（上限 500MB）"})
            return
        pdir = os.path.join(ROMS_DIR, platform)
        os.makedirs(pdir, exist_ok=True)
        tmp = os.path.join(pdir, f".{name}.part")
        try:
            remaining = length
            with open(tmp, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 1 << 20))
                    if not chunk:
                        raise IOError("client aborted")
                    f.write(chunk)
                    remaining -= len(chunk)
            os.replace(tmp, os.path.join(pdir, name))
        except Exception as e:
            if os.path.exists(tmp):
                os.unlink(tmp)
            self._json(500, {"ok": False, "error": str(e)})
            return
        self._json(200, {"ok": True, "platform": platform, "name": name, "size": length})

    # ---------- DELETE /api/roms/<platform>/<name> ----------
    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/roms/"):
            self._json(404, {"ok": False})
            return
        rest = urllib.parse.unquote(parsed.path[len("/api/roms/"):])
        parts = rest.split("/", 1)
        fp = self._rom_path(parts[0], parts[1]) if len(parts) == 2 else None
        if not fp:
            self._json(404, {"ok": False, "error": "not found"})
            return
        os.unlink(fp)
        self._json(200, {"ok": True})

    def log_message(self, fmt, *args):
        pass  # 静默访问日志


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8188"))
    os.makedirs(ROMS_DIR, exist_ok=True)
    for p in PLATFORMS:
        os.makedirs(os.path.join(ROMS_DIR, p), exist_ok=True)
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"game-arcade listening on :{port}, platforms: {', '.join(PLATFORMS)}", flush=True)
    srv.serve_forever()
