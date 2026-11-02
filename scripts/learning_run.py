"""Evidence-linked learning task records and a checked publication entry point.

This checks observable invariants. It cannot prove that an AI read a rule or
that an academic judgement is correct. Source/content/layout reviews remain
separate, recorded work, bound to the actual files that were reviewed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

SKILL = Path(__file__).resolve().parents[1]
SOURCE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff", ".pdf", ".md", ".txt", ".docx"}
MATERIAL_KINDS = {"notes", "homework", "exam", "reference"}
STUDENT_ROLES = {
    "student_md", "student_docx", "student_pdf",
    "student_review_md", "student_review_docx", "student_review_pdf",
    "student_practice_md", "student_practice_docx", "student_practice_pdf",
}
FEEDBACK_ROLES = {"feedback_md", "feedback_docx", "feedback_pdf"}
LEARNING_STATES = {"待观察", "薄弱", "反复薄弱", "已改善", "基本掌握"}
COVERAGE_STATES = {"仅接触", "待验证", "已有表现", "已改善", "薄弱", "反复薄弱", "基本掌握"}
ANSWER_MARKERS = re.compile(r"(?:^|\n)\s*(?:#{1,6}\s*)?(?:参考答案|标准答案|答案与解析|答案及解析|答案[：:]|解析[：:])", re.M)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def within(root: Path, raw: str | Path, *, exists: bool = False) -> Path:
    root = root.resolve()
    path = Path(raw)
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError(f"路径必须位于指定目录内：{raw}")
    if exists and not resolved.is_file():
        raise ValueError(f"文件不存在：{resolved}")
    return resolved


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def version() -> dict[str, Any]:
    return read_json(SKILL / "version.json")


def contract() -> dict[str, Any]:
    return read_json(SKILL / "references" / "workflow-contract.json")


def skill_digest() -> str:
    """Hash all behavior-bearing skill resources used by future tasks.

    Test caches and the regression test module are excluded so a test-only
    edit does not invalidate an already staged learning task. Templates and
    helper scripts are included because they can change the resulting output.
    """
    h = hashlib.sha256()
    skip_parts = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv", "tmp", "output", "任务记录"}
    for path in sorted(SKILL.rglob("*"), key=lambda item: item.relative_to(SKILL).as_posix()):
        rel = path.relative_to(SKILL)
        if not path.is_file() or any(part in skip_parts for part in rel.parts) or path.name in {".installation.json", "test_learning_run.py"} or path.suffix in {".pyc", ".pyo"}:
            continue
        h.update(rel.as_posix().encode("utf-8"))
        h.update(bytes.fromhex(sha256(path)))
    return h.hexdigest()


def rule_paths(root: Path, mode: str, scope: dict[str, Any] | None = None) -> list[str]:
    cfg = contract()
    index = "高中学习总索引.md" if (root / "高中学习总索引.md").is_file() else "学习总索引.md"
    # Keep the runtime contract progressive: triage only needs routing rules;
    # deeper modes load the evidence/validation rules explicitly.
    rows = [index, "AGENTS.md"] + cfg["modes"][mode]["rules"]
    if mode != "triage":
        rows += [p for p in cfg["common_rules"] if p not in rows]
    if mode == "inbox":
        for kind in (scope or {}).get("material_kinds", []):
            rows += cfg["modes"][kind]["rules"]
    if mode == "homework" and (scope or {}).get("followup") is True:
        rows += cfg["modes"][mode]["followup_rules"]
    settings_path = root / "长期记忆" / "学了么配置.json"
    if settings_path.is_file():
        settings = read_json(settings_path)
        rows.append(relative(root, settings_path))
        if mode != "triage" and settings.get("term_plan"):
            rows.append(settings["term_plan"])
    return list(dict.fromkeys(rows))


def snapshot_rules(root: Path, mode: str, scope: dict[str, Any] | None = None) -> list[dict[str, str]]:
    return [{"path": p, "sha256": sha256(within(root, p, exists=True))} for p in rule_paths(root, mode, scope)]


def enumerate_sources(root: Path, roots: list[str]) -> list[Path]:
    found: set[Path] = set()
    for raw in roots:
        source = within(root, raw)
        if not source.exists():
            raise ValueError(f"资料范围不存在：{raw}")
        candidates = [source] if source.is_file() else sorted(source.rglob("*"))
        for item in candidates:
            if item.is_file() and item.suffix.lower() in SOURCE_EXTENSIONS:
                found.add(within(root, item, exists=True))
    return sorted(found, key=lambda p: str(p).casefold())


def expected_artifacts(mode: str, subjects: list[str], scope: dict[str, Any] | None = None) -> list[dict[str, str]]:
    cfg = contract()["modes"][mode]
    rows = [(role, "") for role in cfg["global_artifacts"]]
    rows += [(role, subject) for subject in subjects for role in cfg["subject_artifacts"]]
    if mode == "homework" and (scope or {}).get("followup") is True:
        rows += [(role, subject) for subject in subjects for role in cfg["followup_subject_artifacts"]]
    return [{"id": f"A{i:03d}", "role": role, "subject": subject, "path": "", "destination": ""} for i, (role, subject) in enumerate(rows, 1)]


def start(root: Path, scope: dict[str, Any]) -> Path:
    root = root.resolve()
    mode = scope.get("mode")
    if mode not in contract()["modes"]:
        raise ValueError("mode 必须为 triage/inbox/notes/homework/exam/weekly/practice/review")
    if not scope.get("request") or not scope.get("source_roots"):
        raise ValueError("必须说明 request 和明确的 source_roots，不能空范围启动")
    subjects = scope.get("subjects", [])
    if not subjects or len(subjects) != len(set(subjects)) or any(not isinstance(x, str) or not x.strip() for x in subjects):
        raise ValueError("subjects 必须是非空、无重复的学科列表")
    period = scope.get("period", {})
    if mode in {"weekly", "review"}:
        first, last, as_of = (date.fromisoformat(period[k]) for k in ("start", "end", "as_of"))
        if first > last or as_of > date.today():
            raise ValueError("复盘范围须有有效起止日期，并明确不晚于今天的实际统计截止日")
        if mode == "weekly" and (first.weekday() != 0 or (last - first).days != 6 or not first <= as_of <= last):
            raise ValueError("周目录须为周一至周日，并明确本次实际统计截止日")
        if mode == "review" and as_of < last:
            raise ValueError("月度/学期复盘的核算日期不能早于统计区间截止日")
    for key in ("time_budget_minutes", "core_subject_limit"):
        if mode in {"weekly", "practice"} and (not isinstance(scope.get(key), int) or scope[key] <= 0):
            raise ValueError(f"{mode} 必须从当前计划确定正数 {key}")
    if mode == "inbox" and (not scope.get("material_kinds") or not set(scope["material_kinds"]).issubset({"notes", "homework", "exam"})):
        raise ValueError("inbox 先只读识别范围，再用 material_kinds 声明对应 notes/homework/exam 流程")
    if "followup" in scope and (not isinstance(scope["followup"], bool) or (scope["followup"] and mode != "homework")):
        raise ValueError("followup 须为布尔值，仅 homework 回做流程使用 true")
    if mode in {"notes", "homework", "exam", "inbox"} and not scope.get("index_paths"):
        raise ValueError("资料处理任务需在 index_paths 声明对应学科/学期索引；允许目标索引尚待创建")
    for raw in scope.get("index_paths", []):
        index_path = within(root, raw)
        if index_path.relative_to(root).parts[0] not in subjects or not index_path.name.endswith("索引.md"):
            raise ValueError("index_paths 只能是本批学科下的索引文件，不能用它覆盖规则或原始资料")
    settings_path = root / "长期记忆" / "学了么配置.json"
    if settings_path.is_file():
        expected = read_json(settings_path).get("expected_skill_version")
        actual = version().get("version")
        if expected and expected != actual:
            raise ValueError(f"学了么配置版本 {expected} 与维护源版本 {actual} 不一致；先同步版本再开始任务")
    rules = snapshot_rules(root, mode, scope)
    sources = enumerate_sources(root, scope["source_roots"])
    if not sources:
        raise ValueError("所选范围没有可处理资料；应报告无新资料，不创建空任务冒充完成")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + mode + "-" + uuid.uuid4().hex[:6]
    run_dir = within(root, f"任务记录/{run_id}")
    run_dir.mkdir(parents=True)
    (run_dir / "staged").mkdir()
    inputs, hash_to_id = [], {}
    for i, source in enumerate(sources, 1):
        digest, input_id = sha256(source), f"I{i:04d}"
        same = hash_to_id.get(digest, "")
        hash_to_id.setdefault(digest, input_id)
        inputs.append({"id": input_id, "original_path": relative(root, source), "path": relative(root, source), "sha256": digest,
                       "subject": "", "kind": "", "status": "pending", "event_id": "", "duplicate_of": same,
                       "reason": "", "artifact_ids": [], "topics": [], "deep_review": {}})
    update_paths = contract()["modes"][mode]["updates"] + scope.get("index_paths", [])
    if mode == "homework" and scope.get("followup") is True:
        update_paths += contract()["modes"][mode]["followup_updates"]
    if mode == "inbox":
        for kind in scope["material_kinds"]:
            update_paths += contract()["modes"][kind]["updates"]
    updates = []
    for raw in dict.fromkeys(update_paths):
        path = within(root, raw)
        updates.append({"path": relative(root, path), "before_sha256": sha256(path) if path.is_file() else None,
                        "decision": "pending", "staged_path": "", "reason": ""})
    baseline = {"schema_version": 1, "run_id": run_id, "root": str(root), "scope": scope,
                "skill_version": version()["version"], "skill_digest": skill_digest(), "rules": rules,
                "inputs": [{k: row[k] for k in ("id", "original_path", "sha256")} for row in inputs],
                "updates": [{k: row[k] for k in ("path", "before_sha256")} for row in updates]}
    manifest = {"schema_version": 1, "run_id": run_id, "status": "draft", "scope": scope,
                "subject_decisions": {s: {"status": "active", "reason": ""} for s in subjects},
                "inputs": inputs, "findings": [], "practice": [], "activities": [], "practice_limits": [],
                "artifacts": expected_artifacts(mode, subjects, scope), "updates": updates, "reviews": []}
    if mode == "homework" and scope.get("followup") is True:
        manifest["feedback"] = {"status": "pending", "reason": "", "items": []}
    if mode == "weekly":
        manifest["weekly_plan"] = {"previous_review": {"status": "pending", "source": {}, "summary": "", "evidence": []},
                                   "budget_note": "", "focuses": [], "no_required_reason": ""}
    if mode == "review":
        manifest["review_plan"] = {
            "parent_deliverable": "none",
            "time_policy": "evidence_driven",
            "coverage": [],
            "validation_tasks": [],
        }
    write_json(run_dir / "baseline.json", baseline)
    write_json(run_dir / "run.json", manifest)
    write_json(run_dir / "events.json", [{"time": datetime.now().isoformat(), "event": "started", "scope": scope}])
    return run_dir


def load_run(run_dir: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    run_dir = run_dir.resolve()
    baseline, manifest = read_json(run_dir / "baseline.json"), read_json(run_dir / "run.json")
    root = Path(baseline["root"]).resolve()
    within(root / "任务记录", run_dir)
    if baseline["run_id"] != run_dir.name or manifest.get("run_id") != baseline["run_id"]:
        raise ValueError("任务编号与目录不一致")
    return root, baseline, manifest


def read_rules(run_dir: Path) -> list[dict[str, str]]:
    """Read and record the exact rule files selected when the run started."""
    root, baseline, _ = load_run(run_dir)
    rows = []
    for row in baseline["rules"]:
        path = within(root, row["path"], exists=True)
        rows.append({"path": row["path"], "sha256": row["sha256"], "text": path.read_text(encoding="utf-8-sig")})
    events_path = run_dir / "events.json"
    events = read_json(events_path) if events_path.is_file() else []
    events.append({"time": datetime.now().isoformat(), "event": "rules_read",
                   "skill_digest": baseline["skill_digest"],
                   "rules": [{"path": row["path"], "sha256": row["sha256"]} for row in baseline["rules"]]})
    write_json(events_path, events)
    return rows


def artifact_file(root: Path, run_dir: Path, artifact: dict[str, Any]) -> Path:
    path = within(root, artifact.get("path", ""), exists=True)
    within(run_dir / "staged", path, exists=True)
    return path


def document_text(path: Path) -> tuple[str, int]:
    if path.suffix.lower() == ".docx":
        with zipfile.ZipFile(path) as archive:
            if "word/document.xml" not in archive.namelist():
                raise ValueError("不是有效 DOCX")
            text, media = [], 0
            for name in archive.namelist():
                if name.startswith("word/") and name.endswith(".xml"):
                    tree = ET.fromstring(archive.read(name))
                    text.extend(node.text or "" for node in tree.iter() if node.tag.endswith("}t"))
                if name.startswith("word/media/") and archive.getinfo(name).file_size > 0:
                    media += 1
            return "\n".join(text), media
    if path.suffix.lower() == ".pdf":
        import fitz
        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc), sum(len(p.get_images()) for p in doc)
    return path.read_text(encoding="utf-8-sig"), 0


def attached_sources(root: Path, manifest: dict[str, Any], artifact_ids: set[str]) -> list[Path]:
    rows = []
    global_target = any(a["id"] in artifact_ids and not a.get("subject") for a in manifest["artifacts"])
    for item in manifest["inputs"]:
        if artifact_ids.intersection(item.get("artifact_ids", [])) or (global_target and item.get("status") == "processed"):
            rows.append(within(root, item["path"], exists=True))
    for question in manifest["practice"]:
        if artifact_ids.intersection({question.get("student_artifact_id"), question.get("answer_artifact_id")}):
            for key in ("source", "answer_source"):
                rows.append(within(root, question[key]["path"], exists=True))
            rows.extend(within(root, p, exists=True) for p in question.get("figure_paths", []))
    inputs = {item["id"]: item for item in manifest["inputs"]}
    for item in manifest.get("feedback", {}).get("items", []):
        if artifact_ids.intersection(item.get("artifact_ids", [])):
            rows.append(within(root, inputs[item["input_id"]]["path"], exists=True))
            source = item.get("answer", {}).get("source", {})
            if source.get("path"):
                rows.append(within(root, source["path"], exists=True))
    if global_target and manifest["scope"]["mode"] == "weekly":
        previous_source = manifest.get("weekly_plan", {}).get("previous_review", {}).get("source", {})
        if previous_source.get("path"):
            rows.append(within(root, previous_source["path"], exists=True))
    return sorted(set(rows))


def record_review(run_dir: Path, kind: str, record: str, artifact_ids: list[str], *, rendered_pdf: str | None = None, page_images: list[str] | None = None) -> None:
    root, baseline, manifest = load_run(run_dir)
    if kind not in {"content", "source", "learning", "layout"}:
        raise ValueError("审核类型必须为 content/source/learning/layout")
    if manifest["status"] != "draft":
        raise ValueError("已交付任务不可再更改审核记录；修订须新建任务")
    record_path = within(run_dir, within(root, record, exists=True), exists=True)
    if len(record_path.read_text(encoding="utf-8-sig").strip()) < 40:
        raise ValueError("审核记录须说明核对对象、依据、发现及处理，不能只写已核验")
    by_id = {a["id"]: a for a in manifest["artifacts"]}
    if not artifact_ids or any(a not in by_id for a in artifact_ids):
        raise ValueError("须指定真实 artifact id")
    targets = [artifact_file(root, run_dir, by_id[a]) for a in artifact_ids]
    sources = attached_sources(root, manifest, set(artifact_ids))
    if kind in {"content", "learning", "source"} and not sources:
        raise ValueError("审核目标尚未关联原始资料")
    memory_drafts = [within(run_dir / "staged", within(root, u["staged_path"], exists=True), exists=True)
                     for u in manifest["updates"] if u.get("decision") == "update"]
    files = sorted(set(targets + sources + memory_drafts + [record_path]))
    review = {"id": "R" + uuid.uuid4().hex[:8], "kind": kind, "artifact_ids": artifact_ids,
              "record": relative(root, record_path), "method": "AI对照原始材料；审核结论见记录", "status": "pass",
              "manifest_digest": review_binding(manifest), "time": datetime.now().isoformat()}
    if kind == "layout":
        if len(artifact_ids) != 1:
            raise ValueError("每份正式文档单独记录其渲染结果，不能把一份PDF冒充多份文档的审核")
        if not rendered_pdf or not page_images:
            raise ValueError("版式审核须提供渲染 PDF 和逐页图片")
        import fitz
        pdf = within(run_dir, within(root, rendered_pdf, exists=True), exists=True)
        images = [within(run_dir, within(root, p, exists=True), exists=True) for p in page_images]
        with fitz.open(pdf) as doc:
            pages = len(doc)
        if pages == 0 or pages != len(images) or len(set(images)) != pages:
            raise ValueError("逐页图片与渲染 PDF 页数不匹配")
        for image in images:
            with fitz.open(image) as image_doc:
                if not len(image_doc):
                    raise ValueError("页图不可读取")
        review["rendered_pdf"] = relative(root, pdf)
        review["page_images"] = [relative(root, p) for p in images]
        review["pages"] = pages
        files += [pdf] + images
    review["files"] = [{"path": relative(root, p), "sha256": sha256(p)} for p in files]
    manifest["reviews"].append(review)
    write_json(run_dir / "run.json", manifest)


def review_binding(manifest: dict[str, Any]) -> str:
    keys = ("scope", "subject_decisions", "inputs", "findings", "practice", "activities", "practice_limits", "weekly_plan", "review_plan", "feedback", "artifacts", "updates")
    return hashlib.sha256(json.dumps({k: manifest.get(k) for k in keys}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_feedback(root: Path, manifest: dict[str, Any], valid_artifacts: dict[str, Path],
                      errors: list[str], limits: list[str]) -> set[str]:
    """Check returned-work coverage; academic correctness still needs review."""
    scope = manifest["scope"]
    followup = scope["mode"] == "homework" and scope.get("followup") is True
    feedback = manifest.get("feedback")
    if scope["mode"] == "weekly":
        if feedback is not None:
            errors.append("周打印阶段不得预生成做完后核对反馈；收到本周学生版回传后另开 homework + followup=true")
        return set()
    if not (followup or feedback is not None):
        return set()

    def require(condition: Any, message: str) -> None:
        if not condition:
            errors.append(message)

    require(isinstance(feedback, dict), "缺孩子反馈登记 feedback，系统更新不能代替孩子反馈")
    feedback = feedback if isinstance(feedback, dict) else {}
    inputs = {i["id"]: i for i in manifest["inputs"]}
    artifacts = {a["id"]: a for a in manifest["artifacts"]}
    required_inputs = {i["id"] for i in inputs.values() if i.get("status") == "processed"
                       and followup and i.get("kind") != "reference"}
    if followup:
        required_inputs.update(a.get("input_id") for f in manifest.get("findings", []) for a in f.get("attempts", []))
    items = feedback.get("items", [])
    require(isinstance(items, list), "孩子反馈 items 须为列表")
    items = items if isinstance(items, list) else []
    if feedback.get("status") == "no_submissions":
        require(not followup and not required_inputs and not items and feedback.get("reason"),
                "已有作答或回传不能免交孩子反馈；无作答须说明已查范围")
        require(not any(a.get("role") in FEEDBACK_ROLES and a.get("path") for a in artifacts.values()),
                "无作答状态不能同时发布未登记的孩子反馈")
        return set()
    require(feedback.get("status") == "provided" and items, "收到作答后须交付孩子反馈，不能只更新追踪表")
    covered, item_ids, positions, feedback_artifacts = set(), set(), set(), set()
    for item in items:
        if not isinstance(item, dict):
            errors.append("孩子反馈条目格式错误")
            continue
        fid = item.get("id")
        require(isinstance(fid, str) and fid.strip() and fid not in item_ids, "孩子反馈 id 为空或重复")
        if isinstance(fid, str):
            item_ids.add(fid)
        source = inputs.get(item.get("input_id"), {})
        require(source.get("status") == "processed" and source.get("subject") == item.get("subject")
                and source.get("kind") != "reference", f"{fid} 反馈须对应同科已处理的原始作答")
        covered.add(item.get("input_id"))
        for field in ("locator", "student_response", "observation", "next_step", "success_criteria"):
            require(isinstance(item.get(field), str) and item[field].strip(), f"{fid} 孩子反馈缺 {field}")
        position = (source.get("event_id"), item.get("subject"), item.get("locator"))
        require(position not in positions, f"{fid} 同一事件同题反馈重复，重拍应合并")
        positions.add(position)
        result = item.get("result")
        require(result in {"correct", "partial", "wrong", "incomplete", "uncertain"}, f"{fid} 缺明确对错/未完成/待核结果")
        require(item.get("independence") in {"independent", "prompted", "answer_seen", "unknown"},
                f"{fid} 须区分独立、提示、看过答案与独立性未知")
        if result in {"wrong", "partial", "incomplete"}:
            require(isinstance(item.get("error_point"), str) and item["error_point"].strip(), f"{fid} 缺具体错点或未完成步骤")
            cause = item.get("cause", {})
            require(isinstance(cause, dict) and cause.get("status") in {"confirmed", "hypothesis", "unknown"}
                    and isinstance(cause.get("explanation"), str) and cause["explanation"].strip(),
                    f"{fid} 缺错因及确定程度；不知道须写待验证，不能编造")
        answer = item.get("answer", {})
        answer = answer if isinstance(answer, dict) else {}
        if answer.get("status") == "verified":
            require(isinstance(answer.get("text"), str) and answer["text"].strip(), f"{fid} 缺正确答案或标准要点")
            ref = answer.get("source", {})
            ref = ref if isinstance(ref, dict) else {}
            require(ref.get("path") and ref.get("sha256") and ref.get("locator") and ref.get("citation"),
                    f"{fid} 标准答案缺可定位来源和指纹")
            try:
                path = within(root, ref.get("path", ""), exists=True)
                require(sha256(path) == ref.get("sha256"), f"{fid} 反馈答案来源已改变，须重新核验")
            except (OSError, ValueError) as exc:
                errors.append(f"{fid} 反馈答案来源：{exc}")
        else:
            require(answer.get("status") == "pending" and answer.get("reason") and not answer.get("text")
                    and result in {"uncertain", "incomplete"}, f"{fid} 未核答案不能判定对错或输出确定答案")
            limits.append(f"{fid} 反馈待核：{answer.get('reason', '缺答案依据')}")
        if result == "uncertain":
            limits.append(f"{fid} 作答结果待核：{item.get('observation', '')}")
        ids = item.get("artifact_ids", [])
        require(isinstance(ids, list) and ids, f"{fid} 缺面向孩子的反馈文件")
        ids = ids if isinstance(ids, list) else []
        roles = set()
        for aid in ids:
            art = artifacts.get(aid, {})
            require(aid in valid_artifacts and art.get("subject") == item.get("subject")
                    and art.get("role") in FEEDBACK_ROLES, f"{fid} 反馈只能关联同科独立反馈文件")
            roles.add(art.get("role"))
            feedback_artifacts.add(aid)
        require({"feedback_md", "feedback_docx"}.issubset(roles), f"{fid} 缺反馈归档 MD 或正式 DOCX")
    require(required_inputs.issubset(covered), "孩子反馈漏掉已处理作答/回传资料：" + ", ".join(sorted(str(i) for i in required_inputs - covered)))
    for art in artifacts.values():
        if art.get("role") in FEEDBACK_ROLES and art.get("path"):
            require(art["id"] in feedback_artifacts, f"{art['id']} 反馈文件没有逐项作答记录")
    student_paths = {p for aid, p in valid_artifacts.items() if artifacts[aid].get("role") in STUDENT_ROLES}
    for aid in feedback_artifacts:
        if aid in valid_artifacts:
            path = valid_artifacts[aid]
            require(path not in student_paths, f"{aid} 反馈与独立作答学生件必须分文件")
            require("做完后核对" in re.sub(r"\s+", "", document_text(path)[0]), f"{aid} 反馈须明确标注做完后核对")
    return feedback_artifacts


def validate(run_dir: Path) -> dict[str, Any]:
    root, baseline, m = load_run(run_dir)
    if m.get("status") in {"delivered", "delivered_with_limits"}:
        published = status(run_dir)
        return {"run_id": m["run_id"], "pass": not published["changed_since_delivery"],
                "errors": ["交付后文件变化：" + p for p in published["changed_since_delivery"]],
                "limits": m.get("delivery", {}).get("limits", []), "claim": "核对发布时指纹；不是按新规则追认旧交付"}
    errors: list[str] = []
    limits: list[str] = []
    def require(condition: Any, message: str) -> None:
        if not condition:
            errors.append(message)
    def verify_file(raw: str, digest: str | None = None) -> Path | None:
        try:
            path = within(root, raw, exists=True)
            require(digest is None or sha256(path) == digest, f"文件已改变，必须重新核对：{raw}")
            return path
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
            return None
    require(m.get("schema_version") == 1, "任务 schema_version 不支持")
    require(m.get("status") == "draft", "任务状态非法，不能手工标记完成")
    require(m.get("scope") == baseline["scope"], "不得静默缩减/更改原始任务范围；请新建有明确关联的修订任务")
    require(baseline["skill_digest"] == skill_digest(), "技能已变化，不能沿用旧任务的审核；需新建修订任务并复核")
    try:
        events = read_json(run_dir / "events.json")
    except (OSError, ValueError, json.JSONDecodeError):
        events = []
    expected_rules = [{"path": row["path"], "sha256": row["sha256"]} for row in baseline["rules"]]
    require(any(event.get("event") == "rules_read" and event.get("skill_digest") == baseline["skill_digest"] and event.get("rules") == expected_rules for event in events),
            "未登记本批规则读取；先运行 learning_run.py read-rules")
    for row in baseline["rules"]:
        verify_file(row["path"], row["sha256"])
    mode, subjects = baseline["scope"]["mode"], baseline["scope"]["subjects"]
    inputs, artifacts = m.get("inputs", []), m.get("artifacts", [])
    input_by_id = {row.get("id"): row for row in inputs}
    artifact_by_id = {row.get("id"): row for row in artifacts}
    require(len(input_by_id) == len(inputs), "input id 重复")
    require(len(artifact_by_id) == len(artifacts), "artifact id 重复")
    require(set(input_by_id) == {x["id"] for x in baseline["inputs"]}, "原始资料清单被删减或有未登记资料")
    identical_events: dict[str, set[str]] = {}
    for item in inputs:
        if item.get("status") == "processed":
            identical_events.setdefault(item.get("sha256", ""), set()).add(item.get("event_id", ""))
    require(all(len(events) <= 1 for events in identical_events.values()), "相同照片指纹不能拆成多个独立学习事件")
    locked_paths = {within(root, x["original_path"]) for x in baseline["inputs"]}
    observed_paths = set()
    for old in baseline["inputs"]:
        item = input_by_id.get(old["id"], {})
        require(item.get("original_path") == old["original_path"] and item.get("sha256") == old["sha256"], f"{old['id']} 原始身份被更改")
        path = verify_file(item.get("path", ""), old["sha256"])
        if path:
            observed_paths.add(path)
        input_status = item.get("status")
        require(input_status in {"processed", "duplicate", "deferred", "excluded"}, f"{old['id']} 尚未处理")
        if input_status == "processed":
            require(item.get("subject") in subjects, f"{old['id']} 学科未明确或不在范围内")
            require(item.get("kind") in MATERIAL_KINDS and item.get("event_id"), f"{old['id']} 缺资料类型/独立学习事件标识")
            ids = item.get("artifact_ids", [])
            require(ids and all(a in artifact_by_id for a in ids), f"{old['id']} 未对应到实际产物")
            if mode == "triage":
                require(item.get("route"), f"{old['id']} 分拣任务缺明确去向")
            else:
                require(item.get("topics"), f"{old['id']} 缺知识点覆盖记录")
            if mode == "review":
                deep = item.get("deep_review", {})
                require(isinstance(deep, dict), f"{old['id']} 月度复盘缺 deep_review 记录")
                deep = deep if isinstance(deep, dict) else {}
                require(deep.get("status") in {"completed", "reused_and_rechecked"},
                        f"{old['id']} 月度复盘必须完成深度处理或复用后重新核对；仅 triage 不能通过")
                require(deep.get("source_stage") in {"triage", "notes", "homework", "exam", "weekly", "inbox", "review"},
                        f"{old['id']} deep_review 缺来源阶段")
                require(isinstance(deep.get("work"), str) and deep["work"].strip(), f"{old['id']} deep_review 缺本批实际工作说明")
                locators = deep.get("evidence_locators", [])
                require(isinstance(locators, list) and locators and all(isinstance(x, str) and x.strip() for x in locators),
                        f"{old['id']} deep_review 缺原始证据位置")
                deep_artifacts = deep.get("artifact_ids", [])
                require(isinstance(deep_artifacts, list) and set(deep_artifacts).issubset(set(artifact_by_id)),
                        f"{old['id']} deep_review 产物关联无效")
                if deep.get("source_stage") == "triage":
                    require(deep.get("status") == "completed",
                            f"{old['id']} 只有 triage 预索引时必须在本批完成深度处理，不能直接标记复用")
            if mode == "inbox" and item.get("kind") in contract()["input_roles"]:
                roles = {artifact_by_id[a]["role"] for a in ids if a in artifact_by_id}
                require(set(contract()["input_roles"][item["kind"]]).issubset(roles), f"{old['id']} 仅归档，未完成对应学习处理")
        elif input_status == "duplicate":
            other = input_by_id.get(item.get("duplicate_of"), {})
            require(other and other.get("status") == "processed" and other.get("id") != item.get("id"), f"{old['id']} 重复项须指向已处理原件")
            require(item.get("reason") and item.get("event_id") == other.get("event_id"), f"{old['id']} 同页重拍须说明依据并归于同一学习事件")
        elif input_status in {"deferred", "excluded"}:
            require(item.get("reason"), f"{old['id']} 暂缓/排除必须说明具体原因")
            if mode == "review":
                block = item.get("review_block", {})
                require(isinstance(block, dict) and block.get("status") == "blocked"
                        and isinstance(block.get("next_action"), str) and block["next_action"].strip(),
                        f"{old['id']} 月度复盘只有确实无法可靠处理时才可暂缓，须写 review_block 和下一步")
                generic = ("引用入口", "只引用", "仅筛选", "只筛选", "仅归档", "只归档", "triage预索引")
                require(not any(token in str(item.get("reason", "")) for token in generic),
                        f"{old['id']} 月度复盘不能用引用入口/仅归档代替深度处理")
            limits.append(f"{old['id']}：{item.get('reason', '')}")
    try:
        existing_roots = []
        for raw in baseline["scope"]["source_roots"]:
            old_path = within(root, raw)
            if old_path.exists():
                existing_roots.append(raw)
            else:
                raw_rel = relative(root, old_path)
                is_registered_file = any(i.get("original_path") == raw_rel for i in inputs)
                if old_path.is_file() or is_registered_file:
                    covered = any(i.get("original_path") == raw_rel and within(root, i.get("path", "")) in observed_paths for i in inputs)
                else:
                    prefix = raw_rel.rstrip("/") + "/"
                    scoped = [i for i in inputs if i.get("original_path", "").startswith(prefix)]
                    covered = bool(scoped) and all(within(root, i.get("path", "")) in observed_paths for i in scoped)
                require(covered, f"输入范围消失且没有已核对移动去向：{raw}")
        current = set(enumerate_sources(root, existing_roots))
        require(not (current - locked_paths - observed_paths), "资料范围新增了文件，须明确追加批次或新建修订任务，不能仍声称全量完成")
    except ValueError as exc:
        errors.append(str(exc))
    active = []
    require(set(m.get("subject_decisions", {})) == set(subjects), "学科范围不能静默减少")
    for subject in subjects:
        decision = m.get("subject_decisions", {}).get(subject, {})
        if decision.get("status") == "active":
            active.append(subject)
            require(any(i.get("subject") == subject and i.get("status") == "processed" for i in inputs), f"{subject} 没有已处理资料依据")
        else:
            require(decision.get("status") == "no_material" and decision.get("reason"), f"{subject} 缺资料必须明确说明")
            require(not any(i.get("subject") == subject and i.get("status") == "processed" for i in inputs), f"{subject} 已有资料，不能声明无材料跳过")
            limits.append(f"{subject}：{decision.get('reason', '')}")
    require(active, "全部资料待核或无材料，不能宣布学习处理已完成")
    required = expected_artifacts(mode, active, baseline["scope"])
    actual_roles = {(a.get("role"), a.get("subject", "")) for a in artifacts if a.get("path")}
    for item in required:
        require((item["role"], item["subject"]) in actual_roles, f"缺必交付项：{item['subject']} {item['role']}")
    valid_artifacts: dict[str, Path] = {}
    destinations: set[Path] = set()
    for art in artifacts:
        if art.get("subject") and art["subject"] not in active and not art.get("path"):
            continue
        try:
            path = artifact_file(root, run_dir, art)
            require(path.stat().st_size > 0, f"空交付物：{art['id']}")
            expected_suffix = "." + art["role"].rsplit("_", 1)[-1]
            require(path.suffix.lower() == expected_suffix, f"交付类型与实际格式不符：{art['id']}")
            dest = within(root, art.get("destination", ""))
            allowed = dest.relative_to(root).parts[0] in {"打印版", "周复盘", "临时文件", *subjects}
            require(allowed and dest.suffix.lower() == path.suffix.lower(), f"非法交付位置：{art['id']}")
            require(dest not in locked_paths and dest not in observed_paths, f"禁止覆盖原始依据：{dest}")
            require(dest not in destinations, f"交付目标重复：{dest}")
            destinations.add(dest)
            text, _ = document_text(path)
            require(text.strip(), f"交付物没有可读取文字：{art['id']}")
            if art["role"] in STUDENT_ROLES:
                require(not ANSWER_MARKERS.search(text), f"学生版发现明显答案模块：{art['id']}")
            if path.suffix.lower() == ".docx" and art.get("subject") in {"数学", "物理", "化学"}:
                require(not re.search(r"\\(?:frac|sqrt|begin)\b|\b[A-Za-z]_[A-Za-z0-9]+|\b[A-Za-z]\^[0-9]", text), f"正式文档仍含未排版公式：{art['id']}")
            valid_artifacts[art["id"]] = path
        except (KeyError, ValueError, OSError, zipfile.BadZipFile, ET.ParseError) as exc:
            errors.append(f"交付物 {art.get('id')}：{exc}")
    finding_ids: set[str] = set()
    for finding in m.get("findings", []):
        fid = finding.get("id", "")
        require(fid and fid not in finding_ids, "诊断 id 为空或重复")
        finding_ids.add(fid)
        require(finding.get("state") in LEARNING_STATES and finding.get("subject") in active, f"{fid} 缺有效学科/掌握状态")
        evidence = finding.get("evidence", [])
        require(evidence and all(e.get("input_id") in input_by_id and e.get("locator") and e.get("observation") for e in evidence), f"{fid} 缺具体原始证据位置和观察")
        require(finding.get("next_check") and finding.get("topic"), f"{fid} 缺知识点或下次验证")
        attempts = finding.get("attempts", [])
        for attempt in attempts:
            source = input_by_id.get(attempt.get("input_id"), {})
            require(source and attempt.get("event_id") == source.get("event_id") and source.get("status") == "processed", f"{fid} 验证事件必须对应已处理原始资料")
            require(attempt.get("date") and attempt.get("locator"), f"{fid} 验证事件缺实际作答日期/位置")
            if attempt.get("date"):
                try:
                    attempt_date = date.fromisoformat(attempt["date"])
                    require(attempt_date <= date.today(), f"{fid} 验证日期不能晚于今天，不能用未来日期制造学习证据")
                except (TypeError, ValueError):
                    errors.append(f"{fid} 验证日期须为真实可确认日期，不能用未知字符串制造跨次证据")
            require(attempt.get("result") in {"correct", "wrong"}, f"{fid} 验证结果必须明确为 correct 或 wrong")
            require(isinstance(attempt.get("confirmed"), bool), f"{fid} 验证事件须明确 confirmed")
            require(isinstance(attempt.get("independent"), bool), f"{fid} 验证事件须明确 independent")
            require(isinstance(attempt.get("is_correction"), bool), f"{fid} 验证事件须明确 is_correction")
        wrong_events = {a.get("event_id") for a in attempts if a.get("result") == "wrong" and a.get("confirmed") is True}
        passed = [a for a in attempts if a.get("result") == "correct" and a.get("confirmed") is True
                  and a.get("independent") is True and a.get("is_correction") is False]
        if finding.get("state") == "薄弱":
            require(wrong_events, f"{fid} 缺已确认错误事件，应保留待观察而非直接标薄弱")
        if finding.get("state") == "反复薄弱":
            require(len(wrong_events) >= 2, f"{fid} 反复薄弱至少须两个独立、已确认错误事件；重拍不算")
        if finding.get("state") in {"已改善", "基本掌握"}:
            require(passed, f"{fid} 缺独立通过证据；完成订正不能直接升级掌握状态")
        if finding.get("state") == "已改善":
            require(finding.get("change_basis"), f"{fid} 已改善须说明相对哪条旧证据发生变化")
        if finding.get("state") == "基本掌握":
            require(len({a['event_id'] for a in passed}) >= 2 and len({a['date'] for a in passed}) >= 2, f"{fid} 基本掌握缺跨次验证证据")
        if finding.get("teaching_status") == "not_learned":
            require(finding.get("teaching_evidence"), f"{fid} 不能仅凭笔记缺记录认定没学过")
    question_ids: set[str] = set()
    minutes, core_subjects = 0, set()
    question_artifacts: set[str] = set()
    for q in m.get("practice", []):
        qid = q.get("id", "")
        require(qid and qid not in question_ids, "练习 id 为空或重复")
        question_ids.add(qid)
        require(q.get("subject") in active and q.get("topic"), f"{qid} 缺学科/训练目标")
        require(q.get("finding_ids") and all(f in finding_ids for f in q.get("finding_ids", [])), f"{qid} 未关联本次诊断或待验证知识点")
        require(q.get("learning_level") in {"learned", "intro_excerpt"}, f"{qid} 未确认已学前置内容，不能进入正式训练")
        require(q.get("prerequisite_evidence") and all(i in input_by_id for i in q.get("prerequisite_evidence", [])), f"{qid} 缺进度适配依据")
        for key in ("source", "answer_source"):
            source = q.get(key, {})
            require(source.get("citation") and source.get("locator") and source.get("sha256"), f"{qid} {key} 缺来源、题号/页码或指纹")
            verify_file(source.get("path", ""), source.get("sha256"))
        require(q.get("source_type") in {"original", "excerpt"} or (q.get("source_type") == "adapted" and q.get("user_authorization")), f"{qid} 非原题/节选需已有明确改编授权")
        require(q.get("source_category") in {"beijing_gaokao", "beijing_mock", "school", "teaching_material"},
                f"{qid} 缺题源类别；须区分北京高考 北京区级模拟 校内原题或教辅")
        if q.get("source_type") == "excerpt":
            require(q.get("excerpt_note"), f"{qid} 原题节选须说明保留范围与条件完整性")
        if mode == "review":
            require(q.get("source_completeness") in {"complete", "complete_excerpt"},
                    f"{qid} 月度复盘题缺 source_completeness；不能把题意概括当完整题面")
            components = q.get("source_components", [])
            require(isinstance(components, list) and components and all(isinstance(x, str) and x for x in components),
                    f"{qid} 月度复盘题缺 source_components")
            if q.get("source_type") == "original":
                require(q.get("source_completeness") == "complete", f"{qid} 原题必须保留完整题面、材料和小问")
            if q.get("source_type") == "excerpt":
                require(q.get("source_completeness") == "complete_excerpt" and q.get("excerpt_note"),
                        f"{qid} 节选题须说明保留范围和条件完整性")
        require(isinstance(q.get("figure_required"), bool), f"{qid} 未检查题图需求")
        if q.get("figure_required"):
            require(q.get("figure_paths"), f"{qid} 缺必要题图")
            for raw in q.get("figure_paths", []):
                figure_path = verify_file(raw)
                require(figure_path and figure_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".pdf"}, f"{qid} 必要题图须为实际图形文件")
        sid, aid = q.get("student_artifact_id"), q.get("answer_artifact_id")
        require(sid != aid and sid in valid_artifacts and aid in valid_artifacts, f"{qid} 缺学生/答案独立产物")
        require(artifact_by_id.get(sid, {}).get("role") in STUDENT_ROLES and artifact_by_id.get(aid, {}).get("role", "").startswith("answer_"), f"{qid} 学生与答案角色不匹配")
        if q.get("figure_required") and sid in valid_artifacts and valid_artifacts[sid].suffix == ".docx":
            require(document_text(valid_artifacts[sid])[1] > 0, f"{qid} DOCX 中未发现题图")
        question_artifacts.update({sid, aid} - {None})
        require(isinstance(q.get("required"), bool), f"{qid} 须明确必做或选做，不能漏计时间")
        require(isinstance(q.get("minutes"), (int, float)) and q.get("minutes", 0) > 0, f"{qid} 缺预计用时")
        if q.get("required") is True and isinstance(q.get("minutes"), (int, float)):
            minutes += q["minutes"]
            core_subjects.add(q["subject"])
    for activity in m.get("activities", []):
        require(activity.get("subject") in active and activity.get("description"), "卡片/回顾等活动须说明学科与内容")
        require(isinstance(activity.get("required"), bool), "非题目活动须明确必做或选做，不能漏计时间")
        require(isinstance(activity.get("minutes"), (int, float)) and activity.get("minutes", 0) > 0, "非题目活动缺预计用时")
        if activity.get("required") is True and isinstance(activity.get("minutes"), (int, float)):
            minutes += activity["minutes"]
            core_subjects.add(activity["subject"])
    findings_by_id = {f.get("id"): f for f in m.get("findings", []) if f.get("id")}
    questions_by_id = {q.get("id"): q for q in m.get("practice", []) if q.get("id")}
    if mode == "review":
        plan = m.get("review_plan", {})
        require(isinstance(plan, dict), "月度复盘须有 review_plan")
        plan = plan if isinstance(plan, dict) else {}
        require(plan.get("parent_deliverable") == "none", "月度复盘正式交付不应要求家长版")
        require(plan.get("time_policy") == "evidence_driven", "月度复盘必须按内容和证据决定用时，不能使用固定总时长策略")
        coverage = plan.get("coverage", [])
        require(isinstance(coverage, list) and coverage, "月度复盘缺知识点覆盖表")
        coverage_ids: set[str] = set()
        coverage_subjects: set[str] = set()
        for row in coverage:
            if not isinstance(row, dict):
                errors.append("月度复盘知识点覆盖表格式错误")
                continue
            cid = row.get("id")
            require(cid and cid not in coverage_ids, "月度复盘覆盖表 id 为空或重复")
            coverage_ids.add(cid)
            subject = row.get("subject")
            require(subject in active and row.get("topic"), f"{cid} 缺有效学科或知识点")
            coverage_subjects.add(subject)
            require(row.get("status") in COVERAGE_STATES, f"{cid} 缺有效月度状态")
            require(row.get("fact") and row.get("next_check"), f"{cid} 缺事实摘要或下次验证")
            evidence_ids = row.get("evidence_input_ids", [])
            require(isinstance(evidence_ids, list) and evidence_ids and all(input_by_id.get(i, {}).get("status") == "processed" for i in evidence_ids),
                    f"{cid} 缺已处理的原始证据位置")
            linked_findings = row.get("finding_ids", [])
            require(isinstance(linked_findings, list) and linked_findings and all(f in finding_ids for f in linked_findings),
                    f"{cid} 未关联有依据的 finding")
        require(coverage_subjects == set(active), "月度复盘覆盖表必须覆盖每个有材料学科")
        tasks = plan.get("validation_tasks", [])
        require(isinstance(tasks, list), "月度复盘 validation_tasks 格式错误")
        task_ids: set[str] = set()
        task_question_ids: set[str] = set()
        for task in tasks:
            if not isinstance(task, dict):
                errors.append("月度复盘验证任务格式错误")
                continue
            tid = task.get("id")
            require(tid and tid not in task_ids, "月度复盘验证任务 id 为空或重复")
            task_ids.add(tid)
            subject = task.get("subject")
            targets = task.get("finding_ids", [])
            require(subject in active and targets and all(findings_by_id.get(f, {}).get("subject") == subject for f in targets),
                    f"{tid} 验证任务须关联同科 finding")
            require(task.get("purpose"), f"{tid} 缺验证目的")
            qids = task.get("practice_ids", [])
            require(isinstance(qids, list), f"{tid} practice_ids 格式错误")
            for qid in qids:
                q = questions_by_id.get(qid, {})
                require(q and q.get("subject") == subject and set(q.get("finding_ids", [])).intersection(targets),
                        f"{tid} 关联的 {qid} 不是同科同目标验证题")
                require(qid not in task_question_ids, f"{qid} 被多个月度验证任务重复分配")
                task_question_ids.add(qid)
        required_question_ids = {q.get("id") for q in m.get("practice", []) if q.get("required") is True}
        require(required_question_ids.issubset(task_question_ids), "月度复盘必做题未归入 validation_tasks")
    if mode == "weekly":
        plan = m.get("weekly_plan", {})
        require(isinstance(plan, dict), "周复盘须有 weekly_plan")
        plan = plan if isinstance(plan, dict) else {}
        previous = plan.get("previous_review", {})
        require(isinstance(previous, dict), "周复盘须回看上期目标和实际回传")
        previous = previous if isinstance(previous, dict) else {}
        previous_status = previous.get("status")
        require(previous_status in {"reviewed", "no_feedback", "no_previous_plan"} and previous.get("summary"),
                "周复盘缺上期结果回看；无回传/无历史计划须如实说明")
        source = previous.get("source", {})
        if previous_status in {"reviewed", "no_feedback"}:
            require(isinstance(source, dict) and source.get("path") and source.get("sha256") and source.get("locator"),
                    "上期回看须定位原计划及指纹")
        if isinstance(source, dict) and source.get("path"):
            verify_file(source["path"], source.get("sha256"))
        evidence = previous.get("evidence", [])
        require(isinstance(evidence, list), "上期回传证据须为列表")
        evidence = evidence if isinstance(evidence, list) else []
        if previous_status == "reviewed":
            require(evidence, "声称已回看训练结果须有实际回传证据")
        for item in evidence:
            require(isinstance(item, dict) and input_by_id.get(item.get("input_id"), {}).get("status") == "processed"
                    and item.get("locator") and item.get("observation"), "上期结果须对应本批已核对的回传资料和具体作答位置")
        if previous_status == "no_feedback":
            limits.append("上期训练尚无可核对回传，学习效果待验证；不能据此判退步或继续加量")
        require(plan.get("budget_note"), "周计划缺完整用时口径，须计入阅读、卡片、核对和本次复测")
        findings_by_id = {f["id"]: f for f in m.get("findings", [])}
        activities_by_id = {a.get("id"): a for a in m.get("activities", [])}
        require(len(activities_by_id) == len(m.get("activities", [])) and all(activities_by_id), "周活动 id 为空或重复")
        for aid, activity in activities_by_id.items():
            targets = activity.get("finding_ids", [])
            require(targets and all(findings_by_id.get(f, {}).get("subject") == activity.get("subject") for f in targets),
                    f"{aid} 周活动须关联同科的具体目标")
        questions_by_id = {q["id"]: q for q in m.get("practice", [])}
        required_questions = {q["id"] for q in m.get("practice", []) if q.get("required") is True}
        required_activities = {a.get("id") for a in m.get("activities", []) if a.get("required") is True}
        focuses = plan.get("focuses", [])
        require(isinstance(focuses, list), "周重点须为列表")
        focuses = focuses if isinstance(focuses, list) else []
        if not focuses:
            require(not (required_questions or required_activities) and plan.get("no_required_reason"),
                    "周复盘缺可执行重点；确实无需必做时须说明依据")
        focus_ids, covered_questions, covered_activities = set(), set(), set()
        for focus in focuses:
            if not isinstance(focus, dict):
                errors.append("周重点格式错误")
                continue
            fid = focus.get("id")
            require(fid and fid not in focus_ids, "周重点 id 为空或重复")
            focus_ids.add(fid)
            subject, targets = focus.get("subject"), focus.get("finding_ids", [])
            require(subject in active and targets and all(findings_by_id.get(f, {}).get("subject") == subject for f in targets),
                    f"{fid} 周重点须关联同科的有依据目标")
            require(focus.get("success_criteria") and focus.get("stop_rule"), f"{fid} 缺独立通过标准或停止条件")
            recheck = focus.get("recheck", {})
            require(isinstance(recheck, dict) and recheck.get("trigger") and recheck.get("method"), f"{fid} 缺后续验证时机或方法")
            require(focus.get("practice_ids"), f"{fid} 周重点必须关联至少一道已核验北京高考原题或完整节选")
            focus_questions = [questions_by_id.get(qid, {}) for qid in focus.get("practice_ids", [])]
            require(any(q.get("source_category") == "beijing_gaokao" and q.get("required") is True
                        for q in focus_questions),
                    f"{fid} 周重点缺已核验北京高考原题；卡片或 practice_limits 不能替代")
            for key, by_id, covered in (("practice_ids", questions_by_id, covered_questions),
                                        ("activity_ids", activities_by_id, covered_activities)):
                for task_id in focus.get(key, []):
                    task = by_id.get(task_id, {})
                    require(task.get("required") is True and task.get("subject") == subject
                            and set(task.get("finding_ids", [])).intersection(targets), f"{fid} 关联的 {task_id} 不是同目标必做任务")
                    require(task_id not in covered, f"{task_id} 重复分配到多个周重点，须合并目标或拆分任务")
                    covered.add(task_id)
        require(required_questions == covered_questions and required_activities == covered_activities,
                "必做题目/活动未完整对应周重点，不能在周末建议中额外加任务")
        require(any(q.get("source_category") == "beijing_gaokao" for q in m.get("practice", [])),
                "周打印版至少须有一道已核验北京高考原题或完整节选；无明确弱项时按本周知识点或历史待验证弱项选题")
    if mode in {"weekly", "practice"}:
        require(minutes <= baseline["scope"]["time_budget_minutes"], "必做练习超过本次时间上限")
        require(len(core_subjects) <= baseline["scope"]["core_subject_limit"], "必做学科数超过当前计划上限")
    if mode in {"weekly", "practice", "exam"}:
        for subject in active:
            if not any(q.get("subject") == subject for q in m.get("practice", [])):
                records = [p for p in m.get("practice_limits", []) if p.get("subject") == subject and p.get("reason") and p.get("search_record")]
                require(records, f"{subject} 无正式题时须提供题源检索/暂缓记录，不能用空练习冒充完成")
                for row in records:
                    verify_file(row["search_record"])
                    limits.append(f"{subject} 练习限制：{row['reason']}")
    update_map = {u.get("path"): u for u in m.get("updates", [])}
    require(len(update_map) == len(m.get("updates", [])), "记忆更新目标重复")
    require(set(update_map) == {u["path"] for u in baseline["updates"]}, "记忆/索引更新项被删减或擅自扩展")
    for before in baseline["updates"]:
        raw, old_digest = before["path"], before["before_sha256"]
        path, update = within(root, raw), update_map.get(raw, {})
        current_digest = sha256(path) if path.is_file() else None
        # A target absent at start must remain absent until release. This keeps
        # an external creator from being mistaken for this task's new file.
        require(current_digest == old_digest, f"{raw} 已被其他任务更新；需合并新状态后重新登记，禁止覆盖")
        require(update.get("before_sha256") == old_digest, f"{raw} 不能改写更新前指纹")
        require(update.get("decision") in {"update", "unchanged"} and update.get("reason"), f"{raw} 未说明更新内容或不更新依据")
        if update.get("decision") == "update":
            try:
                staged = within(run_dir / "staged", within(root, update.get("staged_path", ""), exists=True), exists=True)
                require(staged.stat().st_size > 0 and sha256(staged) != old_digest, f"{raw} 所谓更新为空或没有变化")
                require(path not in destinations, f"交付与记忆更新目标重复：{raw}")
                destinations.add(path)
            except (ValueError, OSError) as exc:
                errors.append(str(exc))
    feedback_artifacts = validate_feedback(root, m, valid_artifacts, errors, limits)
    binding = review_binding(m)
    current_reviews = []
    for review in m.get("reviews", []):
        if review.get("status") != "pass" or review.get("manifest_digest") != binding:
            continue
        files = review.get("files", [])
        try:
            fresh = files and all(sha256(within(root, f["path"], exists=True)) == f["sha256"] for f in files)
        except (ValueError, OSError):
            fresh = False
        if fresh:
            current_reviews.append(review)
    for aid, path in valid_artifacts.items():
        require(any(r.get("kind") == "content" and aid in r.get("artifact_ids", []) for r in current_reviews), f"{aid} 缺对应当前文件的内容审核记录")
        if path.suffix in {".docx", ".pdf"}:
            require(any(r.get("kind") == "layout" and aid in r.get("artifact_ids", []) and r.get("pages", 0) == len(r.get("page_images", [])) > 0 for r in current_reviews), f"{aid} 缺逐页版式审核或审核已过期")
        if aid in question_artifacts:
            require(any(r.get("kind") == "source" and aid in r.get("artifact_ids", []) for r in current_reviews), f"{aid} 缺原题、题图、标准答案对照审核")
        if aid in feedback_artifacts:
            require(any(r.get("kind") == "source" and aid in r.get("artifact_ids", []) for r in current_reviews), f"{aid} 缺反馈作答与标准答案对照审核")
            require(any(r.get("kind") == "learning" and aid in r.get("artifact_ids", []) for r in current_reviews), f"{aid} 缺反馈正文、错因分寸、独立性及下一步核对")
        if artifact_by_id[aid]["role"] in STUDENT_ROLES:
            require(any(r.get("kind") == "learning" and aid in r.get("artifact_ids", []) for r in current_reviews), f"{aid} 缺进度、负担及泄题检查")
        if mode == "weekly" and artifact_by_id[aid]["role"] in {"parent_md", "parent_docx", "parent_pdf", "overview_md"}:
            require(any(r.get("kind") == "learning" and aid in r.get("artifact_ids", []) for r in current_reviews),
                    f"{aid} 缺周计划与正文的用时、目标、回传及减量核对")
    return {"run_id": m["run_id"], "pass": not errors, "errors": list(dict.fromkeys(errors)), "limits": list(dict.fromkeys(limits)),
            "input_count": len(baseline["inputs"]), "artifact_count": len(valid_artifacts), "required_minutes": minutes,
            "time_policy": m.get("review_plan", {}).get("time_policy") if mode == "review" else "scope_limited",
            "claim": "可交付但须列明限制" if not errors and limits else "可通过固定入口交付" if not errors else "未通过，不能标记完成",
            "boundary": "程序检查结构、对应关系和审核时效；不替代学科正误与原始证据审核。"}


def release(run_dir: Path, *, replace: bool = False, dry_run: bool = False) -> dict[str, Any]:
    root, baseline, m = load_run(run_dir)
    if m.get("status") != "draft":
        raise ValueError("该任务已交付；不能重复发布或重复更新记忆")
    report = validate(run_dir)
    write_json(run_dir / "validation.json", report)
    if not report["pass"]:
        return report
    moves = [(artifact_file(root, run_dir, a), within(root, a["destination"])) for a in m["artifacts"] if a.get("path")]
    moves += [(within(run_dir / "staged", within(root, u["staged_path"]), exists=True), within(root, u["path"])) for u in m["updates"] if u["decision"] == "update"]
    memory_targets = {within(root, u["path"]) for u in m["updates"]}
    for _, target in moves:
        if target.exists() and target not in memory_targets and not replace:
            raise ValueError(f"目标已存在：{target}；确认当前任务包含修订后用 --replace，程序会保留旧文件")
    report["destinations"] = [relative(root, target) for _, target in moves]
    if dry_run:
        return report
    written: list[tuple[Path, Path | None]] = []
    temporary_files: list[Path] = []
    try:
        for source, target in moves:
            # Resolve every destination before moving/copying; never remove trees.
            target = within(root, target)
            previous = None
            if target.exists():
                previous = within(run_dir, "previous/" + relative(root, target))
                previous.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, previous)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + "." + m["run_id"] + ".tmp")
            temporary_files.append(temporary)
            written.append((target, previous))
            shutil.copy2(source, temporary)
            if sha256(source) != sha256(temporary):
                raise ValueError(f"复制校验失败：{target}")
            os.replace(temporary, target)
        m["status"] = "delivered_with_limits" if report["limits"] else "delivered"
        m["delivery"] = {"time": datetime.now().isoformat(), "files": [{"path": relative(root, p), "sha256": sha256(p)} for _, p in moves], "limits": report["limits"]}
        write_json(run_dir / "delivery.json", m["delivery"])
        write_json(run_dir / "run.json", m)
    except Exception:
        for target, previous in reversed(written):
            if previous:
                shutil.copy2(previous, target)
            elif target.is_file():
                within(root, target).unlink()
        for temporary in temporary_files:
            if temporary.is_file():
                within(root, temporary).unlink()
        raise
    return report


def status(run_dir: Path) -> dict[str, Any]:
    root, baseline, m = load_run(run_dir)
    if m["status"] != "draft":
        changes = []
        receipt_path = run_dir / "delivery.json"
        delivery = m.get("delivery", {})
        if not receipt_path.is_file() or read_json(receipt_path) != delivery or not delivery.get("files"):
            changes.append("缺有效发布回执，不能手工标记已交付")
        for row in delivery.get("files", []):
            path = within(root, row["path"])
            if not path.is_file() or sha256(path) != row["sha256"]:
                changes.append(row["path"])
        return {"run_id": m["run_id"], "status": m["status"], "delivery": m.get("delivery"), "changed_since_delivery": changes}
    report = validate(run_dir)
    return {"run_id": m["run_id"], "status": m["status"], "scope": baseline["scope"], "pending": report["errors"], "limits": report["limits"]}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description="登记、续接和验收学习任务；只在核验通过后发布正式文件")
    sub = parser.add_subparsers(dest="command", required=True)
    begin = sub.add_parser("start")
    begin.add_argument("--root", type=Path, required=True)
    begin.add_argument("--scope", type=Path, required=True)
    for name in ("status", "validate", "release", "read-rules", "review"):
        p = sub.add_parser(name)
        p.add_argument("--run", type=Path, required=True)
        if name == "release":
            p.add_argument("--replace", action="store_true")
            p.add_argument("--dry-run", action="store_true")
        if name == "review":
            p.add_argument("--kind", choices=["content", "source", "learning", "layout"], required=True)
            p.add_argument("--record", required=True)
            p.add_argument("--artifacts", nargs="+", required=True)
            p.add_argument("--rendered-pdf")
            p.add_argument("--page-images", nargs="+")
    args = parser.parse_args()
    try:
        if args.command == "start":
            run_dir = start(args.root, read_json(args.scope))
            out = {"run": str(run_dir), "status": "draft", "next": "读取本次规则与原始资料，补全 run.json，在 staged 中生成草稿，再审核/validate/release。"}
        elif args.command == "read-rules":
            for row in read_rules(args.run):
                print(f"\n<!-- {row['path']} sha256={row['sha256']} -->\n")
                print(row["text"])
            return 0
        elif args.command == "review":
            record_review(args.run, args.kind, args.record, args.artifacts, rendered_pdf=args.rendered_pdf, page_images=args.page_images)
            out = {"recorded": args.kind, "note": "记录实际文件指纹；不代表程序独立确认了审核结论。"}
        elif args.command == "status":
            out = status(args.run)
        elif args.command == "validate":
            out = validate(args.run)
            write_json(args.run / "validation.json", out)
        else:
            out = release(args.run, replace=args.replace, dry_run=args.dry_run)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1 if out.get("pass") is False else 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
