"""Install a skill through a verified staging directory; retain the old copy."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

SKILL_NAME = "xuelema"
SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".playwright-cli", ".venv", "venv", "tmp", "output", "任务记录"}
FORBIDDEN_SUFFIXES = {".pdf", ".docx", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".xlsx", ".mp4", ".wav"}
INSTALL_RECEIPT = ".installation.json"


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()


def source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def destination_root(explicit: Path | None) -> Path:
    return explicit.expanduser().resolve() if explicit else (codex_home() / "skills" / SKILL_NAME).resolve()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root: Path) -> dict[str, str]:
    root = root.resolve()
    rows = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in SKIP_PARTS for part in rel.parts) or path.name == INSTALL_RECEIPT or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_file():
            if not path.resolve().is_relative_to(root) or path.is_symlink():
                raise ValueError(f"技能包含目录外链接：{rel}")
            if path.suffix.lower() in FORBIDDEN_SUFFIXES:
                raise ValueError(f"技能包不得混入真实材料或生成件：{rel}")
            rows[rel.as_posix()] = digest(path)
    if "SKILL.md" not in rows or "version.json" not in rows:
        raise ValueError("缺 SKILL.md/version.json，不能作为本版安装源")
    return rows


def compare(source: Path, target: Path) -> dict:
    expected = inventory(source)
    if not target.is_dir():
        return {"match": False, "missing": sorted(expected), "changed": [], "extra": [], "target": str(target)}
    try:
        actual = inventory(target)
    except ValueError as exc:
        return {"match": False, "reason": str(exc), "target": str(target)}
    missing, extra = sorted(expected.keys() - actual.keys()), sorted(actual.keys() - expected.keys())
    changed = sorted(k for k in expected.keys() & actual.keys() if expected[k] != actual[k])
    return {"match": not (missing or extra or changed), "missing": missing, "changed": changed, "extra": extra,
            "source": str(source), "target": str(target),
            "version": json.loads((source / "version.json").read_text(encoding="utf-8-sig"))["version"], "files": len(expected)}


def checked_paths(source: Path, target: Path) -> tuple[Path, Path, Path]:
    source, target = source.resolve(), target.resolve()
    if target.name != SKILL_NAME or target.parent.name != "skills":
        raise ValueError("安装目标必须是明确的 .../skills/xuelema，不能指向资料库或任意目录")
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("安装源与目标不能重合或互相包含")
    if target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
        raise ValueError("安装目标不能是符号链接或目录联接")
    if target.exists():
        skill_file = target / "SKILL.md"
        if not skill_file.is_file() or "name: xuelema" not in skill_file.read_text(encoding="utf-8-sig")[:1000]:
            raise ValueError("现有目标无法确认是学了么技能，停止覆盖")
    # Backups are outside skills discovery, so an old SKILL.md is not reloaded.
    maintenance = target.parent.parent / "skill-install-history"
    if maintenance.resolve().is_relative_to(source):
        raise ValueError("安装备份不得进入维护源")
    return source, target, maintenance.resolve()


def install(source: Path, target: Path, overwrite: bool = False) -> dict:
    source, target, maintenance = checked_paths(source, target)
    expected = inventory(source)
    if target.exists() and not overwrite:
        raise ValueError("安装目标已存在；已授权升级可使用 --overwrite，旧版将被保留")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    job = maintenance / (SKILL_NAME + "-" + stamp)
    stage, previous = job / "staged", job / "previous"
    job.mkdir(parents=True)
    stage.mkdir()
    for rel in expected:
        src, dst = source / rel, stage / rel
        if not dst.resolve().is_relative_to(stage.resolve()):
            raise ValueError("非法安装相对路径")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    if inventory(stage) != expected:
        raise ValueError(f"暂存版本指纹不一致，已保留检查现场：{job}")
    target.parent.mkdir(parents=True, exist_ok=True)
    moved_old = False
    try:
        # Verify the final absolute paths immediately before each directory move.
        _, checked_target, checked_maintenance = checked_paths(source, target)
        if checked_target != target or not previous.resolve().is_relative_to(checked_maintenance):
            raise ValueError("安装路径校验失败")
        if target.exists():
            target.rename(previous)
            moved_old = True
        if not stage.resolve().is_relative_to(checked_maintenance) or target.parent.name != "skills":
            raise ValueError("暂存路径校验失败")
        stage.rename(target)
        result = compare(source, target)
        if not result["match"]:
            raise ValueError("安装后指纹比对失败")
        receipt = {"source": str(source), "version": result["version"], "installed_at": datetime.now().isoformat(),
                   "files": expected, "previous": str(previous) if moved_old else None}
        (target / INSTALL_RECEIPT).write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["previous"] = receipt["previous"]
        result["next"] = "读取已安装 SKILL.md；新任务重新发现技能。若界面元数据仍旧，重开应用后再用。"
        return result
    except Exception:
        if target.exists():
            failed = job / "failed-install"
            if not failed.resolve().is_relative_to(maintenance) or target.parent.name != "skills":
                raise ValueError("回滚路径校验失败")
            target.rename(failed)
        if moved_old and previous.exists():
            if not previous.resolve().is_relative_to(maintenance) or target.parent.name != "skills":
                raise ValueError("旧版恢复路径校验失败")
            previous.rename(target)
        raise


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description="核对/安装学了么，先校验暂存包，保留旧版且不递归删除目标")
    parser.add_argument("--dest", type=Path, help="默认为 CODEX_HOME/skills/xuelema；自定义也须位于 skills/xuelema")
    parser.add_argument("--overwrite", action="store_true", help="替换已确认的旧技能，保留旧版")
    parser.add_argument("--check", action="store_true", help="只读核对维护源与已安装文件指纹")
    args = parser.parse_args()
    try:
        source, target = source_root(), destination_root(args.dest)
        result = compare(source, target) if args.check else install(source, target, args.overwrite)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("match") else 1
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
