from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz


ROOT = Path.cwd()


def configure_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def norm_text(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(str(x) for x in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def load_queue(subject: str) -> list[dict[str, Any]]:
    path = ROOT / subject / "题库" / "一模二模AI筛题核验队列.json"
    if not path.exists():
        raise FileNotFoundError(f"missing queue: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def candidate_blob(record: dict[str, Any]) -> str:
    fields = [
        "source",
        "module",
        "knowledge_tags",
        "knowledge_point",
        "model_tags",
        "ability_tags",
        "mistake_tags",
        "matched_current_keywords",
        "snippet",
        "question_text_machine",
    ]
    return " ".join(norm_text(record.get(field)) for field in fields)


def keyword_match(record: dict[str, Any], keywords: list[str]) -> bool:
    if not keywords:
        return True
    matched = [norm_text(x).lower() for x in record.get("matched_current_keywords") or []]
    return all(any(keyword.lower() == item or keyword.lower() in item for item in matched) for keyword in keywords)


def select_candidates(records: list[dict[str, Any]], keywords: list[str], limit: int) -> list[dict[str, Any]]:
    pool = [
        r
        for r in records
        if keyword_match(r, keywords)
        and norm_text(r.get("ai_usability_level")) in {"A-优先AI核验", "B-可AI核验后使用"}
    ]
    if len(pool) < limit and keywords:
        # Fallback to records whose text-evidence keywords contain at least one requested keyword.
        seen = {record_key(r) for r in pool}
        for r in records:
            if record_key(r) in seen:
                continue
            matched = [norm_text(x).lower() for x in r.get("matched_current_keywords") or []]
            if any(any(k.lower() == item or k.lower() in item for item in matched) for k in keywords) and norm_text(
                r.get("ai_usability_level")
            ) in {
                "A-优先AI核验",
                "B-可AI核验后使用",
            }:
                pool.append(r)
                seen.add(record_key(r))
            if len(pool) >= limit:
                break
    return pool[:limit]


def record_key(record: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        norm_text(record.get("subject")),
        norm_text(record.get("year")),
        norm_text(record.get("district")),
        norm_text(record.get("kind")),
        norm_text(record.get("question_no")),
        norm_text(record.get("source")),
    )


def safe_slug(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", text)
    text = re.sub(r"\s+", "-", text).strip("-")
    return text[:80] or "review-pack"


def render_pdf_page(pdf_path: Path, page_no: int, out_path: Path, zoom: float = 2.2) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf_path) as doc:
        index = max(0, min(page_no - 1, len(doc) - 1))
        page = doc.load_page(index)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pix.save(out_path)


def write_pack(subject: str, keywords: list[str], candidates: list[dict[str, Any]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    image_dir = out_dir / "pages"
    lines: list[str] = [
        f"# {subject}一模二模AI核验包",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"关键词：{'、'.join(keywords) if keywords else '未指定'}",
        "",
        "## 使用说明",
        "",
        "- 本文件是 AI 核题工作包，不是给孩子的题单。",
        "- 每道题必须对照页面图核对题干、图示/材料、答案和核心知识点。",
        "- 核验完成前，不得放入学生打印版。",
        "",
        "## 候选题",
        "",
    ]
    for idx, record in enumerate(candidates, start=1):
        pdf_path = Path(norm_text(record.get("pdf_path") or record.get("pdf")))
        page_no = int(record.get("source_page") or 1)
        image_name = f"{idx:02d}-{safe_slug(norm_text(record.get('source')))}-p{page_no}.png"
        image_path = image_dir / image_name
        image_status = "未生成"
        try:
            render_pdf_page(pdf_path, page_no, image_path)
            image_status = str(image_path)
        except Exception as exc:
            image_status = f"生成失败：{exc}"
        lines.extend(
            [
                f"### {idx}. {norm_text(record.get('source'))}",
                "",
                f"- 队列等级：{norm_text(record.get('ai_usability_level'))}",
                f"- AI分数：{norm_text(record.get('ai_score'))}",
                f"- PDF页码：{page_no}",
                f"- PDF路径：`{pdf_path}`",
                f"- 页图：`{image_status}`",
                f"- 机器知识点：{norm_text(record.get('knowledge_tags'))}",
                f"- 匹配关键词：{norm_text(record.get('matched_current_keywords')) or '长期储备'}",
                f"- 风险标记：{norm_text(record.get('risk_flags')) or '无明显机器风险'}",
                f"- 机器片段：{norm_text(record.get('snippet'))}",
                "",
                "核验清单：",
                "",
                "- [ ] 原 PDF 题号与来源一致",
                "- [ ] 题干和选项/设问完整",
                "- [ ] 图示、表格、实验装置、材料已保留或可重绘",
                "- [ ] 答案或评分参考已核对",
                "- [ ] 核心知识点压缩为 1-3 个",
                "- [ ] 可以进入学生版，或明确暂缓原因",
                "",
            ]
        )
    out_path = out_dir / "AI核验包.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def main() -> None:
    global ROOT
    configure_stdio()
    parser = argparse.ArgumentParser(description="Build an AI review pack from a subject mock-question queue.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="学习资料库根目录，默认当前目录")
    parser.add_argument("--subject", required=True, help="科目，如 物理")
    parser.add_argument("--keywords", default="", help="逗号分隔关键词，如 机械能守恒,弹簧模型")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--out", default="", help="输出目录；默认写入 对应学科/题库/AI核验包")
    args = parser.parse_args()
    ROOT = args.root.resolve()

    keywords = [x.strip() for x in re.split(r"[,，;；]", args.keywords) if x.strip()]
    records = load_queue(args.subject)
    candidates = select_candidates(records, keywords, args.limit)
    if not candidates:
        raise SystemExit("未找到匹配候选题")
    if args.out:
        out_dir = Path(args.out)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        key = safe_slug("-".join(keywords) if keywords else "all")
        out_dir = ROOT / args.subject / "题库" / "AI核验包" / f"{stamp}-{args.subject}-{key}"
    out_path = write_pack(args.subject, keywords, candidates, out_dir)
    print(out_path)


if __name__ == "__main__":
    main()
