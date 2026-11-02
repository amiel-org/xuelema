from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

LOCKS = ("learning_state_changed", "child_ready", "formal_bank_release", "student_release")
WEEK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_至_\d{4}-\d{2}-\d{2}$")


def read_json(path: Path) -> Any:
    if path.suffix.lower() != ".json":
        raise ValueError(f"结构化输入必须是JSON：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inside(root: Path, raw: str | Path) -> Path:
    path = Path(raw)
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"路径必须位于资料库内：{raw}")
    return resolved


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def locks_false() -> dict[str, bool]:
    return {key: False for key in LOCKS}


def check_locks(value: Any, location: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in LOCKS and item is not False:
                raise ValueError(f"{location} 的 {key} 必须为false")
            check_locks(item, location)
    elif isinstance(value, list):
        for item in value:
            check_locks(item, location)


def event_id(item: dict[str, Any]) -> str:
    return str(item.get("response_event_id") or item.get("event_id") or f"UNSPECIFIED::{item['evidence_id']}")


def load_release(release_dir: Path) -> tuple[dict[str, dict], list[dict], dict[str, dict]]:
    docs = {name: read_json(release_dir / f"{name}.json")
            for name in ("targets", "record-target-map", "known-risks")}
    for name, doc in docs.items():
        check_locks(doc, name)
    targets = {item["target_id"]: item for item in docs["targets"]["targets"]}
    if len(targets) != len(docs["targets"]["targets"]):
        raise ValueError("正式目标ID存在重复")
    risks = {item["risk_id"]: item for item in docs["known-risks"].get("items", []) if item.get("record_id")}
    return targets, docs["record-target-map"]["records"], risks


def read_signed_source(root: Path, source: dict) -> tuple[dict, dict]:
    evidence_path = inside(root, source["evidence_path"])
    review_path = inside(root, source["review_path"])
    for kind, path in (("evidence", evidence_path), ("review", review_path)):
        expected = source.get(f"{kind}_sha256")
        if expected and sha256(path) != expected:
            raise ValueError(f"{kind} 指纹与已签基线不符：{path}")
    if source["signature"] not in review_path.read_text(encoding="utf-8"):
        raise ValueError(f"终审记录未找到指定签署：{source['signature']}")
    doc = read_json(evidence_path)
    check_locks(doc, str(evidence_path))
    report = {"subject": doc["subject"], "evidence_path": relative(root, evidence_path),
              "review_path": relative(root, review_path), "signature": source["signature"],
              "evidence_sha256": sha256(evidence_path)}
    return doc, report


def collect_links(root: Path, manifest: dict, targets: dict) -> tuple[list[dict], list[dict], int, int]:
    links, sources = [], []
    evidence_ids, pairs = set(), set()
    event_subjects = defaultdict(set)
    for source in manifest["sources"]:
        doc, source_report = read_signed_source(root, source)
        sources.append(source_report)
        for item in doc["evidence"]:
            eid = item["evidence_id"]
            if eid in evidence_ids:
                raise ValueError(f"证据ID重复：{eid}")
            evidence_ids.add(eid)
            event_subjects[event_id(item)].add(doc["subject"])
            if not item.get("source_file") or not item.get("source_location"):
                raise ValueError(f"证据缺少来源位置：{eid}")
            if item.get("learning_judgement") != "candidate_observation":
                raise ValueError(f"工具不接受学情升级判断：{eid}")
            for mapping in item.get("candidate_targets", []):
                target_id = mapping["target_id"]
                target = targets.get(target_id)
                if not target:
                    raise ValueError(f"未知正式目标ID：{target_id}")
                if target["subject"] != doc["subject"]:
                    raise ValueError(f"证据与目标学科不一致：{eid} / {target_id}")
                pair = (eid, target_id, mapping["mapping_role"])
                if pair in pairs:
                    raise ValueError(f"证据—目标—角色重复：{pair}")
                pairs.add(pair)
                links.append({
                    "evidence_id": eid, "event_id": event_id(item), "subject": doc["subject"],
                    "evidence_type": item["evidence_type"], "independence": item.get("independence", "unknown"),
                    "source_file": item["source_file"], "source_location": item["source_location"],
                    "observed_fact": item["observed_fact"], "prior_interpretation": item.get("prior_interpretation", ""),
                    "target_id": target_id, "target_name": target["canonical_name"],
                    "mapping_role": mapping["mapping_role"], "mapping_reason": mapping["mapping_reason"],
                    "learning_judgement": "candidate_observation", "mapping_status": "REVIEWED_PILOT_CANDIDATE"})
    cross_subject = sorted(key for key, value in event_subjects.items() if len(value) > 1)
    if cross_subject:
        raise ValueError(f"同一学习事件跨学科重复：{cross_subject}")
    return links, sources, len(evidence_ids), len(event_subjects)

def question_groups(links: list[dict], targets: dict, records: list[dict], risks: dict) -> list[dict]:
    risks_by_record = defaultdict(list)
    for risk in risks.values():
        risks_by_record[risk["record_id"]].append(risk)
    lookup_ids = sorted({link["target_id"] for link in links
                         if link["mapping_role"] in {"primary_focus", "supporting_skill"}})
    groups = []
    for target_id in lookup_ids:
        matches = []
        for record in records:
            occurrences = [item for item in record.get("target_occurrences", [])
                           if item["target_id"] == target_id]
            if not occurrences:
                continue
            matches.append({
                "record_id": record["record_id"], "subject": record["subject"], "year": record["year"],
                "source_pdf": record["source_pdf"], "question_pages": record.get("question_pages", []),
                "source_occurrences": occurrences, "known_risks": risks_by_record.get(record["record_id"], []),
                "selection_status": "CANDIDATE_ONLY_REQUIRES_QUESTION_REVIEW", "student_use_allowed": False})
        target = targets[target_id]
        groups.append({"target_id": target_id, "subject": target["subject"],
                       "target_name": target["canonical_name"],
                       "lookup_basis": "仅由primary_focus/supporting_skill证据映射反查既有record-target-map；未打开图片或PDF",
                       "record_count": len(matches), "records": matches})
    return groups


def build(root: Path, release_dir: Path, manifest_path: Path, out_dir: Path) -> dict:
    targets, records, risks = load_release(release_dir)
    links, sources, evidence_count, event_count = collect_links(root, read_json(manifest_path), targets)
    groups = question_groups(links, targets, records, risks)
    common = {"schema_version": "target-linker-output-1.0", "status": "CANDIDATE_ONLY",
              "source_release": relative(root, release_dir), **locks_false()}
    evidence_doc = {**common, "sources": sources, "evidence_count": evidence_count,
                    "event_count": event_count, "mapping_count": len(links), "links": links}
    question_doc = {**common, "target_count": len(groups), "targets": groups,
                    "selection_policy": "这里只提供记录级候选。实际选题另核完整题干、图材、答案、已学前置知识与风险。"}
    report = {**common,
              "inputs": [relative(root, manifest_path), relative(root, release_dir / "targets.json"),
                         relative(root, release_dir / "record-target-map.json"), relative(root, release_dir / "known-risks.json")],
              "image_or_pdf_read": False, "content_semantic_mapping_performed": False,
              "mastery_judgement_performed": False, "question_source_opened": False,
              "evidence_count": evidence_count, "event_count": event_count, "mapping_count": len(links),
              "distinct_target_count": len({link["target_id"] for link in links}),
              "question_lookup_target_count": len(groups),
              "question_record_count": sum(group["record_count"] for group in groups),
              "subjects": sorted({link["subject"] for link in links}), "exceptions": []}
    dump(out_dir / "evidence-target-links.json", evidence_doc)
    dump(out_dir / "target-question-candidates.json", question_doc)
    dump(out_dir / "build-report.json", report)
    lines = ["# 证据—目标—真题记录联动候选", "",
             "本文件由结构化记录生成，没有重读图片/PDF，没有重新判学情，也没有放行学生练习。", "",
             f"- 证据：{evidence_count} 条；学习事件：{event_count} 个（事件ID去重）。",
             f"- 证据—目标映射：{len(links)} 条；去重目标：{report['distinct_target_count']} 个。",
             f"- 仅对主目标/支持技能反查真题：{len(groups)} 个目标，共 {report['question_record_count']} 条记录级候选。", "",
             "## 使用边界", "", "- `context_only` 只保留背景关系，不据此批量推题。",
             "- 真题记录只是候选；实际给孩子使用前必须另核完整题干、图材、卷内答案、前置知识与风险。",
             "- 原始证据位置始终保留；异常或高影响判断按规则回原图，不在本工具内重做。", "", "## 目标反查摘要", ""]
    for group in groups:
        lines.append(f"- `{group['target_id']}` {group['target_name']}：{group['record_count']} 条记录候选。")
    (out_dir / "联动说明.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def inventory(root: Path, review_roots: list[Path], out_dir: Path) -> dict:
    entries = []
    for review_root in review_roots:
        for folder in sorted((path for path in review_root.iterdir() if path.is_dir()), key=lambda p: p.name):
            if folder.name == "历史版本" or "历史版本" in folder.parts:
                continue
            if not WEEK_RE.match(folder.name) and "复盘" not in folder.name:
                continue
            aggregate = not WEEK_RE.match(folder.name)
            files = sorted(path for path in folder.iterdir() if path.is_file())
            coverage = [path for path in files if "覆盖" in path.name and path.suffix.lower() == ".md"]
            summaries = [path for path in files if path.name in
                         {"本周总览.md", "家长周报.md", "家长版周报.md", "本周资料整理.md"}]
            evidence_maps = list(folder.rglob("evidence-map.json"))
            if evidence_maps:
                readiness = "STRUCTURED_EVIDENCE_PRESENT_REVIEW_STILL_REQUIRED"
            elif aggregate:
                readiness = "AGGREGATE_REVIEW_NOT_INDEPENDENT_INPUT"
            elif coverage or summaries:
                readiness = "LEGACY_REPORT_NEEDS_FIELD_ADAPTATION"
            else:
                readiness = "SOURCE_REPORT_OR_COVERAGE_GAP"
            entries.append({
                "term": review_root.name, "period": folder.name, "entry_path": relative(root, folder),
                "entry_kind": "aggregate_review" if aggregate else "natural_week",
                "legacy_coverage_reports": [relative(root, path) for path in coverage],
                "legacy_summary_reports": [relative(root, path) for path in summaries],
                "structured_evidence_maps": [relative(root, path) for path in evidence_maps],
                "evidence_readiness": readiness, "mapping_status": "PENDING_HISTORICAL_MAPPING",
                "learning_reprocessing_required": False, "image_or_pdf_rescan_required_by_default": False,
                "next_action": "复用旧覆盖表/分科汇总补来源字段并做目标语义复核；仅异常回原图。月复盘只作汇总证据，不与自然周重复累计。"})
    doc = {"schema_version": "historical-target-link-inventory-1.0", "status": "INVENTORY_ONLY_NOT_MAPPING_COMPLETED",
           **locks_false(), "review_roots": [relative(root, path) for path in review_roots],
           "natural_week_count": sum(item["entry_kind"] == "natural_week" for item in entries),
           "aggregate_review_count": sum(item["entry_kind"] == "aggregate_review" for item in entries),
           "entries": entries,
           "policy": "已复盘不等于已映射。先补关系，不重做旧周复盘；只有分拣、缺核心资料或证据不足者另列，不能伪造对应。"}
    dump(out_dir / "historical-coverage-inventory.json", doc)
    return doc


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="复用结构化学习证据和五年目标索引，生成联动候选；不识别图片、不判学情、不放行题目。")
    parser.add_argument("command", choices=("build", "inventory"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--release-dir")
    parser.add_argument("--manifest")
    parser.add_argument("--review-root", action="append", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    out_dir = inside(root, args.out)
    if args.command == "build":
        if not args.release_dir or not args.manifest:
            raise ValueError("build需要--release-dir和--manifest")
        result = build(root, inside(root, args.release_dir), inside(root, args.manifest), out_dir)
    else:
        if not args.review_root:
            raise ValueError("inventory至少需要一个--review-root")
        result = inventory(root, [inside(root, path) for path in args.review_root], out_dir)
    print(json.dumps({"ok": True, "command": args.command, "out": relative(root, out_dir),
                      "summary": {key: value for key, value in result.items() if key.endswith("_count")}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
