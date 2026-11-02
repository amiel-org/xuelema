"""Local, read-only dashboard for xuelema learning projections.

The bundled dataset is fictional. Personal data is loaded only from an explicit
--data file; the server never changes learning states or releases exercises.
"""
from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE = Path(__file__).resolve().parent
DATA: dict = {}
DATA_PATH = BASE / "sample-data.json"
ALLOWED_STATUSES = {"good", "improve", "have", "wait", "linked", "none"}


def validate(data: dict) -> dict:
    """Check referential integrity and fail closed on release claims."""
    required = {"meta", "locks", "subjects", "targets", "records", "reviews", "tasks"}
    if not isinstance(data, dict) or not required <= data.keys():
        raise ValueError("数据缺少必需模块：" + "、".join(sorted(required - set(data or {}))))
    locks = data["locks"]
    if any(locks.get(key) is not False for key in (
        "learning_state_changed", "child_ready", "formal_bank_release", "student_release"
    )):
        raise ValueError("看板数据不得声明已修改学情或已放行学生练习")
    subjects = {row["name"] for row in data["subjects"]}
    if len(subjects) != len(data["subjects"]):
        raise ValueError("学科名称重复")
    target_ids = set()
    for row in data["targets"]:
        if row["id"] in target_ids or row["subject"] not in subjects:
            raise ValueError("目标ID重复或学科无效")
        if row["status"] not in ALLOWED_STATUSES:
            raise ValueError(f"无效学情状态：{row['status']}")
        target_ids.add(row["id"])
    record_ids = {row["id"] for row in data["records"]}
    if len(record_ids) != len(data["records"]):
        raise ValueError("题录ID重复")
    for row in data["records"]:
        if row["subject"] not in subjects or not set(row["target_ids"]) <= target_ids:
            raise ValueError(f"题录关联无效：{row.get('id')}")
        for target_id in row["target_ids"]:
            target = next(item for item in data["targets"] if item["id"] == target_id)
            if target["subject"] != row["subject"]:
                raise ValueError("题录不能跨学科关联目标")
    for row in data["targets"]:
        if not set(row.get("records", [])) <= record_ids:
            raise ValueError(f"目标题录关联无效：{row['id']}")
    return data


def load(path: Path | None = None) -> dict:
    global DATA, DATA_PATH
    DATA_PATH = (path or BASE / "sample-data.json").resolve()
    DATA = validate(json.loads(DATA_PATH.read_text(encoding="utf-8")))
    return DATA


class Handler(BaseHTTPRequestHandler):
    server_version = "XuelemaDashboard/0.8"

    def send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, value: object) -> None:
        self.send_bytes(json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def send_error_json(self, message: str, status: int = 400) -> None:
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path in {"/", "/index.html"}:
                self.send_bytes((BASE / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif parsed.path == "/assets/app.js":
                self.send_bytes((BASE / "app.js").read_bytes(), "text/javascript; charset=utf-8")
            elif parsed.path == "/assets/style.css":
                self.send_bytes((BASE / "style.css").read_bytes(), "text/css; charset=utf-8")
            elif parsed.path == "/api/dashboard":
                self.send_json(DATA)
            elif parsed.path == "/api/health":
                self.send_json({"ok": True, "mode": DATA["meta"].get("mode", "demo"), "data_file": DATA_PATH.name})
            else:
                self.send_error_json("页面不存在", 404)
        except (OSError, ValueError, KeyError) as exc:
            self.send_error_json(str(exc), 500)

    def do_POST(self) -> None:  # noqa: N802
        self.send_error_json("此公开看板为只读模式；学情更新须走资料处理、审核与发布流程。", 405)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[看板] {self.address_string()} {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="启动学了么本地学情看板")
    parser.add_argument("--data", type=Path, help="可选：个人看板JSON；默认使用虚构示例")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    load(args.data)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"学了么看板：{url}\n数据：{DATA_PATH}\n按 Ctrl+C 停止。只读展示，不修改学情。")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
