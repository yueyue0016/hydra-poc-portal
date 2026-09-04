#!/usr/bin/env python3
"""In-sandbox tooling agent for Hydra PoC dynamic sessions.

Reachable only via the pool data plane (Entra-gated) + nginx /agent/ proxy,
and requires the X-Exec-Token shared secret. Runs as root so the agent can
apt-get install packages and invoke CLI tools (ffmpeg, imagemagick, ...).
Outputs are written under the XFCE Desktop (/config/Desktop) and chowned to
the desktop user (abc, 911:911) so the requester sees them as desktop files.
"""
import json
import os
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("EXEC_TOKEN", "")
DESK = "/config/Desktop"
UID = GID = 911
MAX_UPLOAD = 3 * 1024 * 1024 * 1024  # 3 GB


def chown_tree(path):
    try:
        os.chown(path, UID, GID)
    except OSError:
        pass
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            try:
                os.chown(os.path.join(root, n), UID, GID)
            except OSError:
                pass


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _authed(self):
        return bool(TOKEN) and self.headers.get("X-Exec-Token", "") == TOKEN

    def _read(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        if self.path.startswith("/agent/health"):
            tools = {t: bool(shutil.which(t)) for t in
                     ("ffmpeg", "ffprobe", "convert", "sox", "python3", "bash",
                      "apt-get", "curl", "git")}
            return self._json(200, {"ok": True, "tools": tools})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._authed():
            return self._json(401, {"error": "unauthorized"})
        body = self._read()

        if self.path.startswith("/agent/exec"):
            try:
                d = json.loads(body or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "bad json"})
            cmd = d.get("cmd", "")
            if not cmd:
                return self._json(400, {"error": "missing cmd"})
            wd = d.get("workdir") or DESK
            to = int(d.get("timeout", 180))
            os.makedirs(DESK, exist_ok=True)
            try:
                p = subprocess.run(
                    ["bash", "-c", cmd],
                    cwd=wd if os.path.isdir(wd) else DESK,
                    capture_output=True, timeout=to)
                chown_tree(DESK)
                return self._json(200, {
                    "code": p.returncode,
                    "stdout": p.stdout.decode("utf-8", "replace")[-20000:],
                    "stderr": p.stderr.decode("utf-8", "replace")[-8000:]})
            except subprocess.TimeoutExpired:
                return self._json(200, {"code": 124, "stdout": "",
                                        "stderr": f"timeout after {to}s"})
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"error": str(e)})

        if self.path.startswith("/agent/upload"):
            if len(body) > MAX_UPLOAD:
                return self._json(413, {"error": "too large"})
            fn = self.headers.get("X-Filename", "")
            if not fn or "/" in fn or "\\" in fn or fn.startswith("."):
                return self._json(400, {"error": "bad filename"})
            sub = "".join(c for c in self.headers.get("X-Subdir", "")
                          if c.isalnum() or c in "-_")
            dst_dir = os.path.join(DESK, sub) if sub else DESK
            os.makedirs(dst_dir, exist_ok=True)
            path = os.path.join(dst_dir, fn)
            with open(path, "wb") as f:
                f.write(body)
            chown_tree(dst_dir)
            return self._json(200, {"path": path, "size": len(body)})

        self._json(404, {"error": "not found"})

    def log_message(self, *a):  # silence
        pass


if __name__ == "__main__":
    os.makedirs(DESK, exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", 8090), Handler).serve_forever()
