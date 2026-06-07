from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


SUBJECTS = ["语文", "数学", "英语", "物理", "化学", "生物"]

SUBJECT_DIRS = ["笔记", "试卷", "作业改错"]
OPTIONAL_SUBJECT_DIRS = ["题库", "北京一模二模真题", "高考北京卷真题"]

ROOT_FILES_ANY = [
    "高中学习总索引.md",
    "学习总索引.md",
]

ROOT_DIRS = [
    "长期记忆",
    "临时文件",
    "打印版",
    "周复盘",
]

INBOX_DIRS = [
    "临时文件/待处理",
    "临时文件/待确认",
]

INBOX_FILES = [
    "临时文件/处理日志.md",
]

LONG_MEMORY_FILES = [
    "总索引.md",
    "知识点追踪.md",
    "错因追踪.md",
    "笔记追踪.md",
    "作业改错追踪.md",
    "知识点总索引.md",
    "错题-笔记联动表.md",
    "关键词别名表.md",
    "复盘日志.md",
    "当前重点看板.md",
    "规则变更记录.md",
    "临时文件处理规范.md",
    "三线联动学习闭环.md",
    "试卷技能规范.md",
    "学生打印版规范.md",
    "练习题源与核验规范.md",
]

QUESTION_BANK_FILES = [
    "题库/README.md",
    "题库/一模二模题目标签索引.json",
    "题库/一模二模题目标签索引.csv",
    "题库/一模二模AI筛题核验队列.md",
    "题库/一模二模AI筛题核验队列.json",
    "题库/一模二模AI筛题核验队列.csv",
]


@dataclass
class Check:
    level: str
    path: str
    message: str


def configure_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def default_root() -> Path:
    # In the current workspace this script lives under <root>/工具脚本.
    return Path.cwd()


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def check_exists(
    checks: list[Check],
    root: Path,
    relative: str,
    *,
    kind: str,
    required: bool = True,
) -> None:
    path = root / relative
    ok = path.is_dir() if kind == "dir" else path.is_file()
    if ok:
        return
    level = "error" if required else "warning"
    noun = "目录" if kind == "dir" else "文件"
    checks.append(Check(level, relative, f"缺少{noun}"))


def check_root(root: Path) -> list[Check]:
    checks: list[Check] = []
    if not root.exists():
        return [Check("error", str(root), "根目录不存在")]
    if not root.is_dir():
        return [Check("error", str(root), "根路径不是目录")]

    if not any((root / name).is_file() for name in ROOT_FILES_ANY):
        checks.append(
            Check(
                "error",
                " / ".join(ROOT_FILES_ANY),
                "缺少学习总索引文件，二选一即可",
            )
        )

    for relative in ROOT_DIRS:
        check_exists(checks, root, relative, kind="dir", required=True)
    for relative in INBOX_DIRS:
        check_exists(checks, root, relative, kind="dir", required=True)
    for relative in INBOX_FILES:
        check_exists(checks, root, relative, kind="file", required=False)

    memory_root = root / "长期记忆"
    for name in LONG_MEMORY_FILES:
        required = name in {"总索引.md", "知识点追踪.md", "错因追踪.md", "复盘日志.md"}
        check_exists(checks, memory_root, name, kind="file", required=required)

    for subject in SUBJECTS:
        subject_root = root / subject
        check_exists(checks, root, subject, kind="dir", required=True)
        for dirname in SUBJECT_DIRS:
            check_exists(checks, subject_root, dirname, kind="dir", required=True)
        for dirname in OPTIONAL_SUBJECT_DIRS:
            check_exists(checks, subject_root, dirname, kind="dir", required=False)
        for filename in QUESTION_BANK_FILES:
            check_exists(checks, subject_root, filename, kind="file", required=False)

    check_exists(checks, root, "题库总控", kind="dir", required=False)
    return checks


def write_text_report(root: Path, checks: Iterable[Check], strict: bool) -> int:
    rows = list(checks)
    errors = [x for x in rows if x.level == "error"]
    warnings = [x for x in rows if x.level == "warning"]
    fatal = errors or (strict and warnings)

    print(f"根目录：{root}")
    print(f"错误：{len(errors)}，提醒：{len(warnings)}")
    if not rows:
        print("结论：资料库结构完整。")
        return 0

    print("")
    print("| 级别 | 路径 | 说明 |")
    print("|---|---|---|")
    for item in rows:
        print(f"| {item.level} | `{item.path}` | {item.message} |")

    if fatal:
        print("")
        print("结论：存在必须处理的问题。")
        return 1
    print("")
    print("结论：没有致命问题；提醒项可按需要补齐。")
    return 0


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="校验 xuelema 学习资料库结构")
    parser.add_argument("--root", type=Path, default=default_root(), help="学习资料库根目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--strict", action="store_true", help="把 warning 也视为失败")
    args = parser.parse_args()

    root = args.root.resolve()
    checks = check_root(root)
    errors = [x for x in checks if x.level == "error"]
    warnings = [x for x in checks if x.level == "warning"]
    exit_code = 1 if errors or (args.strict and warnings) else 0

    if args.json:
        payload = {
            "root": str(root),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "strict": args.strict,
            "checks": [asdict(x) for x in checks],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return exit_code

    return write_text_report(root, checks, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
