from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


SUBJECTS = ["语文", "数学", "英语", "物理", "化学", "生物"]

KIND_TO_DIR = {
    "笔记": "笔记",
    "作业": "作业改错",
    "作业改错": "作业改错",
    "试卷": "试卷",
    "测验": "试卷",
    "晨练": "试卷",
    "待确认": "待确认",
}

LOG_HEADER = "| 批次 | 处理日期 | 原始文件 | 识别学科 | 识别类型 | 目标位置 | 状态 | 说明 |\n|---|---|---|---|---|---|---|---|\n"


@dataclass
class PlannedMove:
    files: list[str]
    subject: str
    kind: str
    note: str = ""
    grade: str | None = None
    date_label: str | None = None
    status: str = "已归档"


def configure_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def default_root() -> Path:
    return Path.cwd()


def today_string() -> str:
    return date.today().isoformat()


def date_label_from_iso(text: str) -> str:
    dt = datetime.strptime(text, "%Y-%m-%d").date()
    return f"{dt.month}.{dt.day}"


def default_grade(on_date: str) -> str:
    dt = datetime.strptime(on_date, "%Y-%m-%d").date()
    if dt < date(2026, 9, 1):
        return "高一下"
    if dt < date(2027, 3, 1):
        return "高二上"
    if dt < date(2027, 9, 1):
        return "高二下"
    if dt < date(2028, 3, 1):
        return "高三上"
    return "高三下"


def inbox(root: Path) -> Path:
    return root / "临时文件" / "待处理"


def confirm_dir(root: Path) -> Path:
    return root / "临时文件" / "待确认"


def log_path(root: Path) -> Path:
    return root / "临时文件" / "处理日志.md"


def ensure_log(root: Path, reset: bool = False) -> None:
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if reset or not path.exists() or not path.read_text(encoding="utf-8", errors="ignore").strip():
        path.write_text(LOG_HEADER, encoding="utf-8")


def next_batch_id(root: Path, on_date: str) -> str:
    ensure_log(root)
    text = log_path(root).read_text(encoding="utf-8", errors="ignore")
    nums = [int(x) for x in re.findall(rf"{re.escape(on_date)}-第(\d+)批", text)]
    return f"{on_date}-第{max(nums, default=0) + 1}批"


def list_inbox_files(root: Path) -> list[Path]:
    path = inbox(root)
    if not path.exists():
        return []
    return sorted([p for p in path.iterdir() if p.is_file()], key=lambda p: p.name.lower())


def unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_重复{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def markdown_code_list(values: list[str]) -> str:
    return "、".join(f"`{x}`" for x in values)


def append_log(
    root: Path,
    batch: str,
    process_date: str,
    original_files: list[str],
    subject: str,
    kind: str,
    target: Path,
    status: str,
    note: str,
) -> None:
    ensure_log(root)
    row = (
        f"| {batch} | {process_date} | {markdown_code_list(original_files)} | "
        f"{subject or '-'} | {kind} | `{target}` | {status} | {note or '-'} |\n"
    )
    with log_path(root).open("a", encoding="utf-8") as f:
        f.write(row)


def parse_plan(path: Path) -> list[PlannedMove]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    items = data.get("items", data if isinstance(data, list) else [])
    moves: list[PlannedMove] = []
    for raw in items:
        files = raw.get("files") or raw.get("file")
        if isinstance(files, str):
            files = [files]
        if not files:
            raise ValueError(f"计划项缺少 files：{raw}")
        moves.append(
            PlannedMove(
                files=[str(x) for x in files],
                subject=str(raw.get("subject") or ""),
                kind=str(raw.get("kind") or raw.get("type") or ""),
                note=str(raw.get("note") or raw.get("说明") or ""),
                grade=raw.get("grade"),
                date_label=raw.get("date_label"),
                status=str(raw.get("status") or "已归档"),
            )
        )
    return moves


def normalize_kind(kind: str) -> str:
    if kind not in KIND_TO_DIR:
        raise ValueError(f"未知类型：{kind}；可用：{', '.join(KIND_TO_DIR)}")
    return KIND_TO_DIR[kind]


def target_dir_for(root: Path, move: PlannedMove, process_date: str) -> Path:
    folder = normalize_kind(move.kind)
    if folder == "待确认":
        return confirm_dir(root)
    if move.subject not in SUBJECTS:
        raise ValueError(f"未知学科：{move.subject}；可用：{', '.join(SUBJECTS)}")
    grade = move.grade or default_grade(process_date)
    label = move.date_label or date_label_from_iso(process_date)
    return root / move.subject / folder / grade / label


def resolve_source(root: Path, filename: str) -> Path:
    path = Path(filename)
    if path.is_absolute():
        return path
    return inbox(root) / filename


def apply_moves(
    root: Path,
    moves: list[PlannedMove],
    *,
    process_date: str,
    batch: str,
    dry_run: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for move in moves:
        target_dir = target_dir_for(root, move, process_date)
        moved_paths: list[str] = []
        missing: list[str] = []
        planned_targets: list[str] = []

        for filename in move.files:
            src = resolve_source(root, filename)
            if not src.exists():
                missing.append(filename)
                continue
            dst = unique_target(target_dir / src.name)
            planned_targets.append(str(dst))
            if not dry_run:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
            moved_paths.append(str(dst))

        status = "待确认" if normalize_kind(move.kind) == "待确认" else move.status
        if missing:
            status = "部分缺失" if moved_paths else "缺失"
        if not dry_run:
            append_log(
                root,
                batch,
                process_date,
                move.files,
                move.subject,
                move.kind,
                target_dir,
                status,
                move.note + (f"；缺失：{','.join(missing)}" if missing else ""),
            )
        results.append(
            {
                "files": move.files,
                "subject": move.subject,
                "kind": move.kind,
                "target_dir": str(target_dir),
                "targets": planned_targets,
                "missing": missing,
                "status": status,
            }
        )
    return results


def cmd_scan(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    files = list_inbox_files(root)
    if args.json:
        payload = {
            "root": str(root),
            "inbox": str(inbox(root)),
            "count": len(files),
            "files": [{"name": p.name, "size": p.stat().st_size} for p in files],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"待处理目录：{inbox(root)}")
    print(f"文件数：{len(files)}")
    for p in files:
        print(f"- {p.name} ({p.stat().st_size} bytes)")
    return 0


def cmd_apply_plan(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    process_date = args.date or today_string()
    batch = args.batch or next_batch_id(root, process_date)
    ensure_log(root, reset=args.reset_log)
    moves = parse_plan(args.plan)
    results = apply_moves(root, moves, process_date=process_date, batch=batch, dry_run=args.dry_run)

    print(json.dumps({"batch": batch, "dry_run": args.dry_run, "results": results}, ensure_ascii=False, indent=2))
    return 0


def cmd_sample_plan(args: argparse.Namespace) -> int:
    sample = {
        "items": [
            {
                "files": ["example1.jpg", "example2.jpg"],
                "subject": "化学",
                "kind": "笔记",
                "note": "化学平衡课堂笔记",
            },
            {
                "files": ["unclear.jpg"],
                "subject": "",
                "kind": "待确认",
                "note": "照片模糊，看不清学科",
            },
        ]
    }
    print(json.dumps(sample, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="处理 xuelema 临时文件待处理区")
    parser.add_argument("--root", type=Path, default=default_root(), help="学习资料库根目录")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="列出待处理文件")
    scan.add_argument("--json", action="store_true")
    scan.set_defaults(func=cmd_scan)

    apply_plan = sub.add_parser("apply-plan", help="按 JSON 计划移动文件并写处理日志")
    apply_plan.add_argument("plan", type=Path, help="处理计划 JSON")
    apply_plan.add_argument("--date", help="处理日期 YYYY-MM-DD，默认今天")
    apply_plan.add_argument("--batch", help="批次号，默认自动生成")
    apply_plan.add_argument("--dry-run", action="store_true", help="只预览，不移动不写日志")
    apply_plan.add_argument("--reset-log", action="store_true", help="先重写处理日志表头")
    apply_plan.set_defaults(func=cmd_apply_plan)

    sample = sub.add_parser("sample-plan", help="输出计划 JSON 示例")
    sample.set_defaults(func=cmd_sample_plan)

    return args_func(parser.parse_args())


def args_func(args: argparse.Namespace) -> int:
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
