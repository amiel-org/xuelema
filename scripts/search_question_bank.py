from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


SUBJECTS = ["语文", "数学", "英语", "物理", "化学", "生物"]

SEARCH_FIELDS = [
    "module",
    "knowledge_tags",
    "knowledge_point",
    "model_tags",
    "ability_tags",
    "skills",
    "mistake_tags",
    "difficulty",
    "stage",
    "usage",
    "source_label",
    "snippet",
]

CSV_FIELDS = [
    "subject",
    "year",
    "district",
    "kind",
    "question_no",
    "module",
    "knowledge_point",
    "knowledge_tags",
    "model_tags",
    "mistake_tags",
    "difficulty",
    "stage",
    "figure_required",
    "verify_status",
    "child_ready",
    "needs_manual_review",
    "source_label",
    "pdf_path",
    "snippet",
    "score",
]


def configure_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def default_root() -> Path:
    return Path.cwd()


def split_values(text: str | None) -> list[str]:
    if not text:
        return []
    return [x.strip() for x in text.replace("；", ",").replace("，", ",").split(",") if x.strip()]


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "；".join(str(x) for x in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def contains_any(blob: str, terms: list[str]) -> bool:
    if not terms:
        return True
    low = blob.lower()
    return any(term.lower() in low for term in terms)


def parse_int_values(text: str | None) -> set[int] | None:
    if not text or text == "all":
        return None
    out: set[int] = set()
    for part in split_values(text):
        if "-" in part:
            left, right = part.split("-", 1)
            out.update(range(int(left), int(right) + 1))
        else:
            out.add(int(part))
    return out


def selected_subjects(text: str) -> list[str]:
    if text == "all":
        return SUBJECTS
    subjects = split_values(text)
    invalid = [x for x in subjects if x not in SUBJECTS]
    if invalid:
        raise ValueError(f"未知科目：{','.join(invalid)}")
    return subjects


def record_blob(record: dict[str, Any]) -> str:
    return "\n".join(as_text(record.get(field)) for field in SEARCH_FIELDS)


def score_record(record: dict[str, Any], terms: list[str]) -> int:
    if not terms:
        return 0
    score = 0
    weighted_fields = {
        "knowledge_point": 8,
        "knowledge_tags": 6,
        "module": 5,
        "model_tags": 4,
        "mistake_tags": 4,
        "snippet": 1,
    }
    for term in terms:
        term_low = term.lower()
        for field, weight in weighted_fields.items():
            if term_low in as_text(record.get(field)).lower():
                score += weight
    return score


def load_records(root: Path, subjects: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for subject in subjects:
        path = root / subject / "题库" / "一模二模题目标签索引.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        for rec in data:
            if isinstance(rec, dict):
                rec.setdefault("subject", subject)
                records.append(rec)
    return records


def filter_records(records: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    years = parse_int_values(args.years)
    districts = split_values(args.districts if args.districts != "all" else None)
    kinds = split_values(args.kinds if args.kinds != "all" else None)
    terms = (
        split_values(args.keyword)
        + split_values(args.knowledge)
        + split_values(args.module)
        + split_values(args.model)
        + split_values(args.mistake)
    )
    difficulty = split_values(args.difficulty)
    stage = split_values(args.stage)

    out: list[dict[str, Any]] = []
    for rec in records:
        if years is not None:
            try:
                if int(rec.get("year")) not in years:
                    continue
            except Exception:
                continue
        if districts and as_text(rec.get("district")) not in districts:
            continue
        if kinds and as_text(rec.get("kind") or rec.get("exam_type")) not in kinds:
            continue
        if difficulty and as_text(rec.get("difficulty")) not in difficulty:
            continue
        if stage and not contains_any(as_text(rec.get("stage")), stage):
            continue
        if args.child_ready and as_text(rec.get("child_ready")) != args.child_ready:
            continue
        if args.needs_manual_review and as_text(rec.get("needs_manual_review")) != args.needs_manual_review:
            continue

        blob = record_blob(rec)
        if args.keyword and not contains_any(blob, split_values(args.keyword)):
            continue
        if args.knowledge and not contains_any(as_text(rec.get("knowledge_point")) + as_text(rec.get("knowledge_tags")), split_values(args.knowledge)):
            continue
        if args.module and not contains_any(as_text(rec.get("module")), split_values(args.module)):
            continue
        if args.model and not contains_any(as_text(rec.get("model_tags")), split_values(args.model)):
            continue
        if args.mistake and not contains_any(as_text(rec.get("mistake_tags")), split_values(args.mistake)):
            continue

        row = dict(rec)
        row["score"] = score_record(rec, terms)
        out.append(row)

    out.sort(
        key=lambda rec: (
            -int(rec.get("score") or 0),
            as_text(rec.get("subject")),
            int(rec.get("year") or 0),
            as_text(rec.get("district")),
            as_text(rec.get("kind") or rec.get("exam_type")),
            int(rec.get("question_no") or 0),
        )
    )
    return out[: args.limit]


def trim(text: str, limit: int = 120) -> str:
    value = " ".join(text.split())
    return value[:limit] + ("..." if len(value) > limit else "")


def write_markdown(records: list[dict[str, Any]]) -> None:
    print(f"共找到 {len(records)} 条候选。")
    print("")
    print("| # | 来源 | 题号 | 知识点 | 题型/模型 | 难度 | 核验 | child_ready | 摘要 |")
    print("|---:|---|---:|---|---|---|---|---|---|")
    for i, rec in enumerate(records, start=1):
        source = rec.get("source_label") or f"{rec.get('year')} {rec.get('district')} {rec.get('kind') or rec.get('exam_type')} {rec.get('subject')}"
        print(
            "| {i} | {source} | {q} | {kp} | {model} | {diff} | {verify} | {ready} | {snippet} |".format(
                i=i,
                source=as_text(source),
                q=as_text(rec.get("question_no")),
                kp=trim(as_text(rec.get("knowledge_point") or rec.get("knowledge_tags")), 48),
                model=trim(as_text(rec.get("model_tags") or rec.get("module")), 48),
                diff=as_text(rec.get("difficulty")),
                verify=as_text(rec.get("verify_status") or rec.get("text_verify_status")),
                ready=as_text(rec.get("child_ready")),
                snippet=trim(as_text(rec.get("snippet")), 80),
            )
        )
    if records:
        print("")
        print("提醒：检索结果通常仍是机器初标；进入学生版前必须回原 PDF 核题干、图示/材料和答案。")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow({field: as_text(rec.get(field)) for field in CSV_FIELDS})


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="检索本地一模二模题目标签索引")
    parser.add_argument("--root", type=Path, default=default_root(), help="学习资料库根目录")
    parser.add_argument("--subjects", default="all", help="all 或逗号分隔科目")
    parser.add_argument("--keyword", help="全文关键词，逗号分隔")
    parser.add_argument("--knowledge", help="知识点关键词，逗号分隔")
    parser.add_argument("--module", help="一级模块，逗号分隔")
    parser.add_argument("--model", help="题型模型，逗号分隔")
    parser.add_argument("--mistake", help="错因标签，逗号分隔")
    parser.add_argument("--difficulty", help="难度，逗号分隔")
    parser.add_argument("--stage", help="适用阶段，逗号分隔")
    parser.add_argument("--years", default="all", help="all、2026、2020-2026 或逗号分隔")
    parser.add_argument("--districts", default="all", help="all 或逗号分隔区域")
    parser.add_argument("--kinds", default="all", help="all、一模、二模")
    parser.add_argument("--child-ready", choices=["是", "否"])
    parser.add_argument("--needs-manual-review", choices=["是", "否"])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--format", choices=["md", "json", "csv"], default="md")
    parser.add_argument("--out", type=Path, help="输出文件；format=md 时不使用")
    args = parser.parse_args()

    root = args.root.resolve()
    subjects = selected_subjects(args.subjects)
    records = load_records(root, subjects)
    results = filter_records(records, args)

    if args.format == "json":
        text = json.dumps(results, ensure_ascii=False, indent=2)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        else:
            print(text)
        return 0
    if args.format == "csv":
        if not args.out:
            raise SystemExit("--format csv 必须指定 --out")
        write_csv(args.out, results)
        print(f"已输出：{args.out}")
        return 0

    write_markdown(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
