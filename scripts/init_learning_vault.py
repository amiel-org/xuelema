from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def configure_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def template_root() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "learning-vault-template"


def copy_template(source: Path, target: Path, overwrite: bool) -> list[Path]:
    if not source.exists():
        raise FileNotFoundError(f"template not found: {source}")
    target.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for item in source.rglob("*"):
        rel = item.relative_to(source)
        dst = target / rel
        if item.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        if item.name == ".gitkeep":
            continue
        if dst.exists() and not overwrite:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dst)
        copied.append(dst)
    return copied


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="初始化 xuelema 学习资料库空模板")
    parser.add_argument("--target", type=Path, required=True, help="要创建或补齐的学习资料库目录")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的模板文件")
    parser.add_argument("--skip-question-banks", action="store_true", help="只复制基础模板，不初始化六科题库骨架")
    args = parser.parse_args()

    source = template_root()
    target = args.target.resolve()
    copied = copy_template(source, target, args.overwrite)
    if not args.skip_question_banks:
        import setup_all_subject_question_banks as qbank

        qbank.ROOT = target
        (target / "题库总控").mkdir(parents=True, exist_ok=True)
        for subject, cfg in qbank.SUBJECTS.items():
            qbank.create_subject(subject, cfg)
    print(f"template: {source}")
    print(f"target: {target}")
    print(f"copied_files: {len(copied)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
