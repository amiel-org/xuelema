from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


SKILL_NAME = "xuelema"


def configure_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def codex_home() -> Path:
    raw = None
    try:
        import os

        raw = os.environ.get("CODEX_HOME")
    except Exception:
        raw = None
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / ".codex"


def source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def destination_root(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    return (codex_home() / "skills" / SKILL_NAME).resolve()


def should_skip(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return ".git" in parts or "__pycache__" in parts or "tmp" in parts or "output" in parts


def copy_tree(source: Path, target: Path) -> int:
    copied = 0
    for item in source.rglob("*"):
        if should_skip(item):
            continue
        rel = item.relative_to(source)
        dst = target / rel
        if item.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dst)
        copied += 1
    return copied


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="把当前 xuelema 目录安装到本机 Codex skills 目录")
    parser.add_argument("--dest", type=Path, help="目标技能目录；默认安装到 ~/.codex/skills/xuelema")
    parser.add_argument("--overwrite", action="store_true", help="目标已存在时先删除再重装")
    args = parser.parse_args()

    source = source_root()
    target = destination_root(args.dest)

    if target.exists():
        if not args.overwrite:
            raise SystemExit(f"target exists: {target}；如需覆盖请加 --overwrite")
        shutil.rmtree(target)

    target.mkdir(parents=True, exist_ok=True)
    copied = copy_tree(source, target)
    print(f"source: {source}")
    print(f"target: {target}")
    print(f"copied_files: {copied}")
    print("restart_codex: yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
