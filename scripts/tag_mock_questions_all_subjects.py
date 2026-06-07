from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz


ROOT = Path.cwd()
SUBJECTS = ["语文", "数学", "英语", "物理", "化学", "生物"]
YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
DISTRICTS = ["东城", "西城", "海淀", "朝阳"]
KINDS = ["一模", "二模"]

SCRIPT_DIR = Path(__file__).resolve().parent
TESSERACT = Path(shutil.which("tesseract") or "tesseract")
TESSDATA = SCRIPT_DIR / "tessdata"
EXTRACT_VERSION = 3

CSV_FIELDS = [
    "subject",
    "year",
    "district",
    "kind",
    "exam_type",
    "question_no",
    "source",
    "source_label",
    "source_page",
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
    "figure_required",
    "verify_status",
    "text_verify_status",
    "figure_verify_status",
    "answer_verify_status",
    "machine_tag_status",
    "child_ready",
    "priority",
    "extract_status",
    "ocr_status",
    "text_source",
    "needs_manual_review",
    "placeholder",
    "pdf",
    "pdf_path",
    "text_file",
    "snippet",
]

QUESTION_MAX = {
    "语文": 24,
    "数学": 21,
    "英语": 55,
    "物理": 20,
    "化学": 20,
    "生物": 21,
}

EXPECTED_MIN = {
    "语文": 18,
    "数学": 18,
    "英语": 30,
    "物理": 14,
    "化学": 16,
    "生物": 16,
}

EXPECTED_FULL = {
    "语文": 23,
    "数学": 21,
    "英语": 43,
    "物理": 20,
    "化学": 19,
    "生物": 21,
}


@dataclass(frozen=True)
class TagRule:
    pattern: str
    module: tuple[str, ...]
    knowledge: tuple[str, ...]
    models: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    mistakes: tuple[str, ...] = ()
    usage: tuple[str, ...] = ()
    priority: str | None = None


def configure_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()


def short_text(text: str, limit: int = 260) -> str:
    s = norm_space(text)
    return s[:limit] + ("..." if len(s) > limit else "")


def safe_name(path: Path) -> str:
    h = hashlib.sha1(str(path).encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{path.stem}-{h}"


def pdf_target(subject: str, year: int, district: str, kind: str) -> Path | None:
    folder = ROOT / subject / "北京一模二模真题" / str(year) / district / kind
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        return None
    return pdfs[0]


def question_candidates(subject: str, text: str) -> list[dict[str, Any]]:
    patterns: list[tuple[str, str]] = [
        (
            "line_arabic",
            r"(?m)^[ \t]*(?P<num>\d{1,2})(?P<mark>[\.．、,，]?)[ \t]*(?=\S)",
        ),
        (
            "paren_arabic",
            r"(?m)^[ \t]*[（(](?P<num>\d{1,2})[）)][ \t]*(?=\S)",
        ),
    ]
    if subject == "英语":
        patterns += [
            ("english_blank", r"_{2,}\s*(?P<num>\d{1,2})\s*_{2,}"),
            ("english_spaced_blank", r"\s{2,}(?P<num>3[5-9])\s{2,}"),
            ("english_grammar", r"(?<!\d)(?P<num>\d{1,2})\s*\([A-Za-z][A-Za-z \-]{0,28}\)"),
            ("english_choice", r"(?<!\d)(?P<num>\d{1,2})\.[ \t]*A\."),
            ("english_question", r"(?m)^[ \t]*(?P<num>4[0-3])\.[ \t]*(?=[A-Z])"),
            ("english_writing", r"(?m)^[ \t]*(?P<num>44)\.[ \t]*(?=假设|Write|作文|书面表达|Dear)"),
        ]
    seen: set[tuple[int, int]] = set()
    out: list[dict[str, Any]] = []
    max_no = QUESTION_MAX[subject]
    for kind, pattern in patterns:
        for m in re.finditer(pattern, text):
            try:
                qno = int(m.group("num"))
            except Exception:
                continue
            if not (1 <= qno <= max_no):
                continue
            key = (qno, m.start())
            if key in seen:
                continue
            seen.add(key)
            mark = ""
            try:
                mark = m.group("mark") or ""
            except Exception:
                pass
            out.append(
                {
                    "question_no": qno,
                    "start": m.start(),
                    "end": m.end(),
                    "kind": kind,
                    "mark": mark,
                    "score": candidate_score(subject, qno, kind, mark, text[m.start() : m.start() + 260]),
                }
            )
    out.sort(key=lambda x: (int(x["start"]), -int(x["score"])))
    return out


def candidate_score(subject: str, qno: int, kind: str, mark: str, context: str) -> int:
    ctx = norm_space(context)
    score = 0
    if kind in {"english_blank", "english_grammar", "english_choice"}:
        score += 8
    elif kind == "paren_arabic":
        score += 5
    elif mark:
        score += 5
    else:
        score += 2
    if re.search(r"关注北京高考在线|京考一点通|微信|bj[-_]?gaokao|bjgkzx|第\d+页|PAGE|答案|解析|参考答案", ctx, re.IGNORECASE):
        score -= 8
    if re.match(r"^\d{1,2}\s+[a-d]\s", ctx, re.IGNORECASE):
        score -= 8
    if re.match(r"^\d{1,2}[\.．、,，]?\s*[A-D人][\.、,，\s]", ctx):
        score -= 5
    cue_patterns = {
        "数学": r"已知|若|设|函数|集合|如图|求|证明|在.*中|下列|给出|有|点|直线|圆|椭圆|抛物线|数列|概率",
        "物理": r"下列|如图|已知|某|实验|研究|质量|电场|磁场|光|波|小球|电路|卫星|物体|为了|在.*中",
        "化学": r"下列|如图|已知|某|实验|研究|探究|物质|溶液|反应|元素|化合物|电池|流程|制备|用",
        "生物": r"下列|如图|研究|实验|细胞|基因|遗传|生态|植物|动物|蛋白质|病毒|某|为探究",
        "语文": r"下列|根据|结合|概括|分析|理解|赏析|翻译|默写|作文|阅读|材料|文中|加点|正确|不正确",
        "英语": r"According|What|Which|Why|How|Who|When|Where|The|A\.|阅读|根据|填空|write|essay|email",
    }
    if re.search(cue_patterns.get(subject, r"下列|如图|已知|根据|What|Which"), ctx, re.IGNORECASE):
        score += 4
    if qno >= 15 and re.search(r"本小题|[（(]?\d+\s*分|共\d+\s*分", ctx):
        score += 4
    if len(ctx) >= 30:
        score += 1
    return score


def looks_like_answer_page(text: str) -> bool:
    head = norm_space(text[:900])
    if not head:
        return False
    strong = [
        "参考答案",
        "答案及评分参考",
        "答案与评分参考",
        "试题答案",
        "试卷答案",
        "评分参考",
        "评分标准",
        "参考答案及评分标准",
        "参考答案及评分细则",
        "答案解析",
    ]
    if any(x in head for x in strong):
        return True
    return bool(re.search(r"(语文|数学|英语|物理|化学|生物).{0,20}(答案|评分参考)", head))


def page_offsets(pages: list[dict[str, Any]]) -> tuple[str, list[tuple[int, int]]]:
    chunks: list[str] = []
    offsets: list[tuple[int, int]] = []
    pos = 0
    for page in pages:
        marker = f"\n\n[[PAGE {page['page']}]]\n"
        chunk = marker + (page.get("text") or "")
        chunks.append(chunk)
        offsets.append((pos, int(page["page"])))
        pos += len(chunk)
    return "".join(chunks), offsets


def page_for_offset(offsets: list[tuple[int, int]], pos: int) -> int:
    current = 1
    for start, page_no in offsets:
        if start <= pos:
            current = page_no
        else:
            break
    return current


def select_question_sequence(subject: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_no: dict[int, list[dict[str, Any]]] = {
        i: [] for i in range(1, QUESTION_MAX[subject] + 1)
    }
    for cand in candidates:
        by_no[int(cand["question_no"])].append(cand)
    for items in by_no.values():
        items.sort(key=lambda x: (int(x["start"]), -int(x["score"])))

    selected: list[dict[str, Any]] = []
    prev_start = -1
    for qno in range(1, QUESTION_MAX[subject] + 1):
        options = [c for c in by_no.get(qno, []) if int(c["start"]) > prev_start + 3]
        if not options:
            continue
        # Prefer the earliest plausible candidate; for OCR text a later high-score
        # duplicate is often a repeated option or answer reference.
        good = [c for c in options if int(c["score"]) >= 0]
        pool = good or options
        chosen = sorted(pool, key=lambda c: (int(c["start"]), -int(c["score"])))[0]
        selected.append(chosen)
        prev_start = int(chosen["start"])
    return selected


def fill_missing_questions(
    subject: str,
    selected: list[dict[str, Any]],
    offsets: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    expected = EXPECTED_FULL[subject]
    if not selected:
        return [
            {
                "question_no": qno,
                "source_page": 1,
                "text": f"{qno}. 题干待人工抽取。机器未能从 PDF 文本/OCR 中稳定切出本题。",
                "placeholder": True,
            }
            for qno in range(1, expected + 1)
        ]
    existing = {int(item["question_no"]): item for item in selected}
    out: list[dict[str, Any]] = []
    last_page = 1
    for qno in range(1, expected + 1):
        if qno in existing:
            last_page = page_for_offset(offsets, int(existing[qno]["start"]))
            continue
        out.append(
            {
                "question_no": qno,
                "source_page": last_page,
                "text": f"{qno}. 题干待人工抽取。机器未能从 PDF 文本/OCR 中稳定切出本题。",
                "placeholder": True,
            }
        )
    return out


def cut_answer_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for i, page in enumerate(pages):
        text = page.get("text") or ""
        # Do not allow the first two pages to be cut merely because the instruction
        # says "answer on the answer sheet".
        if i >= 2 and looks_like_answer_page(text):
            break
        kept.append(page)
    return kept or pages


def split_questions(subject: str, pages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    usable_pages = cut_answer_pages(pages)
    combined, offsets = page_offsets(usable_pages)
    candidates = question_candidates(subject, combined)
    selected = select_question_sequence(subject, candidates)

    placeholders: list[dict[str, Any]] = []
    if len(selected) < EXPECTED_FULL[subject]:
        placeholders = fill_missing_questions(subject, selected, offsets)

    questions: list[dict[str, Any]] = []
    for i, item in enumerate(selected):
        qno = int(item["question_no"])
        start = int(item["start"])
        next_start = int(selected[i + 1]["start"]) if i + 1 < len(selected) else len(combined)
        text = combined[start:next_start].strip()
        if len(norm_space(text)) < 8:
            continue
        questions.append(
            {
                "question_no": qno,
                "source_page": page_for_offset(offsets, start),
                "text": text,
                "placeholder": False,
            }
        )
    questions.extend(placeholders)
    # Deduplicate real records and placeholders, preferring real extracted text.
    dedup: dict[int, dict[str, Any]] = {}
    for q in sorted(questions, key=lambda x: (int(x["question_no"]), bool(x.get("placeholder")))):
        qno = int(q["question_no"])
        if qno not in dedup or (dedup[qno].get("placeholder") and not q.get("placeholder")):
            dedup[qno] = q
    questions = [dedup[qno] for qno in sorted(dedup)]

    status = "题目级机器切分"
    real_count = len([q for q in questions if not q.get("placeholder")])
    if real_count < 3:
        status = "未能稳定题号切分，已生成占位题号"
    elif real_count < EXPECTED_MIN[subject]:
        status = "题目数偏少，已生成占位题号，需人工复核切分"
    elif placeholders:
        status = "部分题号占位，需人工补题干"
    return questions, status


def run_ocr_page(pdf_path: Path, page_index: int, subject: str, scale: float = 1.65) -> dict[str, Any]:
    lang = "chi_sim+eng"
    if subject == "英语":
        lang = "eng+chi_sim"
    with tempfile.TemporaryDirectory(prefix="ocr_page_") as td:
        doc = fitz.open(str(pdf_path))
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image_path = Path(td) / f"page-{page_index + 1}.png"
        out_base = Path(td) / f"page-{page_index + 1}"
        pix.save(str(image_path))
        cmd = [
            str(TESSERACT),
            str(image_path),
            str(out_base),
            "-l",
            lang,
            "--tessdata-dir",
            str(TESSDATA),
            "--psm",
            "6",
        ]
        cp = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        txt_path = Path(str(out_base) + ".txt")
        text = txt_path.read_text(encoding="utf-8", errors="replace") if txt_path.exists() else ""
        return {
            "page": page_index + 1,
            "text": text,
            "source": "ocr",
            "ocr_returncode": cp.returncode,
            "ocr_stderr": cp.stderr[-500:],
            "char_count": len(norm_space(text)),
        }


def tesseract_available() -> bool:
    return TESSERACT.exists() or shutil.which(str(TESSERACT)) is not None


def extract_pages(
    pdf_path: Path,
    subject: str,
    force: bool,
    ocr_mode: str,
    max_ocr_workers: int,
) -> tuple[list[dict[str, Any]], Path, dict[str, Any]]:
    raw_dir = ROOT / subject / "北京一模二模真题"
    cache_dir = raw_dir / "_extracted_text_unified_pages"
    text_dir = raw_dir / "_extracted_text_unified"
    cache_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{safe_name(pdf_path)}.json"
    text_path = text_dir / f"{pdf_path.stem}.txt"

    if cache_path.exists() and not force:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("version") == EXTRACT_VERSION:
            pages = cached["pages"]
            write_combined_text(text_path, pages)
            return pages, text_path, cached.get("report", {})

    doc = fitz.open(str(pdf_path))
    pages: list[dict[str, Any]] = []
    need_ocr: list[int] = []
    for idx in range(doc.page_count):
        text = doc[idx].get_text("text") or ""
        char_count = len(norm_space(text))
        page_record = {
            "page": idx + 1,
            "text": text,
            "source": "fitz",
            "char_count": char_count,
        }
        pages.append(page_record)
        if ocr_mode == "always" or (ocr_mode == "auto" and char_count < 80):
            need_ocr.append(idx)

    ocr_available = tesseract_available() and (TESSDATA / "chi_sim.traineddata").exists()
    ocr_done = 0
    ocr_failed = 0
    if need_ocr and ocr_mode != "never" and ocr_available:
        workers = max(1, max_ocr_workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(run_ocr_page, pdf_path, idx, subject): idx
                for idx in need_ocr
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    ocr_record = future.result()
                    if len(norm_space(ocr_record.get("text") or "")) >= max(20, pages[idx]["char_count"]):
                        pages[idx] = ocr_record
                    ocr_done += 1
                except Exception as exc:
                    pages[idx]["ocr_error"] = str(exc)
                    ocr_failed += 1
    elif need_ocr and ocr_mode != "never":
        for idx in need_ocr:
            pages[idx]["ocr_error"] = "tesseract 或 chi_sim.traineddata 不可用"
        ocr_failed = len(need_ocr)

    source_set = sorted({p.get("source", "") for p in pages})
    if source_set == ["fitz"]:
        text_source = "fitz"
    elif source_set == ["ocr"]:
        text_source = "ocr"
    else:
        text_source = "mixed"

    report = {
        "pdf": str(pdf_path),
        "pages": doc.page_count,
        "ocr_pages_requested": len(need_ocr),
        "ocr_pages_done": ocr_done,
        "ocr_pages_failed": ocr_failed,
        "text_source": text_source,
        "total_chars": sum(int(p.get("char_count") or len(norm_space(p.get("text") or ""))) for p in pages),
    }
    cache = {
        "version": EXTRACT_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "report": report,
        "pages": pages,
    }
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    write_combined_text(text_path, pages)
    return pages, text_path, report


def write_combined_text(text_path: Path, pages: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    for page in pages:
        lines.append(f"\n\n===== PAGE {page['page']} | {page.get('source', '')} =====\n")
        lines.append(page.get("text") or "")
    text_path.write_text("".join(lines), encoding="utf-8", errors="replace")


COMMON_FIGURE_PATTERN = re.compile(
    r"如图|图\d|图示|示意图|坐标系|图像|图象|曲线|表\d|下表|流程图|装置|实验装置|结构式|结构简式|遗传图|系谱|电路|几何体|棱锥|棱柱|圆锥曲线|折线|柱状图|散点图|diagram|figure|table",
    re.IGNORECASE,
)


RULES: dict[str, list[TagRule]] = {
    "数学": [
        TagRule(r"集合|子集|交集|并集|补集|充要条件|命题", ("集合与常用逻辑",), ("集合运算", "常用逻辑"), ("集合与逻辑基础",), ("条件翻译",), ("条件遗漏",)),
        TagRule(r"函数|定义域|值域|单调|奇偶|零点|对称|最值|指数|对数|幂函数", ("函数与导数",), ("函数性质", "函数图像"), ("函数图像与性质",), ("图像识别", "条件翻译"), ("图像理解偏差",)),
        TagRule(r"导数|切线|极值|单调区间|恒成立|零点个数|f['′]", ("函数与导数",), ("导数应用", "函数综合"), ("导数单调极值",), ("运算表达", "分类讨论"), ("分类不全", "运算失误"), ("高考拓展", "专题训练"), "P1"),
        TagRule(r"三角|sin|cos|tan|正弦|余弦|正切|角|周期|诱导公式", ("三角函数",), ("三角函数图像", "三角恒等变换"), ("三角恒等变换",), ("运算表达",), ("运算失误",)),
        TagRule(r"向量|数量积|夹角|共线|垂直|平面向量", ("平面向量",), ("平面向量运算",), ("向量几何运算",), ("条件翻译", "运算表达"), ("条件遗漏",)),
        TagRule(r"数列|等差|等比|通项|前n项|递推|a_n|Sn|S_n", ("数列",), ("数列通项", "数列求和"), ("数列递推与求和",), ("运算表达", "分类讨论"), ("运算失误",)),
        TagRule(r"立体|空间|直线.*平面|平面.*平面|棱锥|棱柱|正方体|四面体|二面角|体积", ("立体几何",), ("空间线面关系", "空间角与距离"), ("空间线面关系",), ("图像识别", "证明论证"), ("证明步骤跳跃",), ("高考拓展", "专题训练"), "P1"),
        TagRule(r"椭圆|双曲线|抛物线|圆锥曲线|焦点|准线|离心率|弦|切线|轨迹方程", ("解析几何",), ("圆锥曲线", "直线与圆锥曲线"), ("圆锥曲线综合",), ("运算表达", "分类讨论"), ("运算失误", "条件遗漏"), ("高考拓展", "专题训练"), "P1"),
        TagRule(r"概率|统计|随机|样本|频率|分布|期望|方差|独立|正态|回归", ("概率统计",), ("概率统计", "随机变量"), ("概率统计图表",), ("图像识别", "建模应用"), ("图表信息漏读", "条件遗漏"), ("专题训练",), "P1"),
        TagRule(r"复数|虚数|实部|虚部|共轭|i[ =]", ("复数",), ("复数运算",), ("复数基础",), ("运算表达",), ("运算失误",)),
        TagRule(r"不等式|基本不等式|均值|放缩|取等", ("不等式",), ("不等式", "基本不等式"), ("不等式应用",), ("运算表达", "分类讨论"), ("条件遗漏",)),
        TagRule(r"新定义|定义新运算|对于任意|存在|探究|证明", ("新定义与综合",), ("新定义阅读", "综合证明"), ("新定义阅读",), ("条件翻译", "证明论证"), ("模型识别不足", "证明步骤跳跃"), ("高考拓展",), "P1"),
    ],
    "物理": [
        TagRule(r"运动图像|v[-－]?t|x[-－]?t|a[-－]?t|位移|速度|加速度|匀变速|自由落体|竖直上抛", ("力学",), ("运动学公式", "运动图像"), ("运动图像与运动学",), ("图像解读", "运算表达"), ("图像轴意不清",), ("错因修复", "专题训练"), "P0"),
        TagRule(r"平抛|抛体|水平.*竖直|轨迹", ("力学",), ("平抛运动",), ("曲线运动分解",), ("建模论证",), ("模型识别不足",), ("错因修复",), "P0"),
        TagRule(r"圆周|向心|周期|频率|角速度|最高点|最低点|圆轨道", ("力学",), ("圆周运动", "圆周临界"), ("圆周临界",), ("建模论证", "条件翻译"), ("概念混淆", "未分阶段"), ("错因修复",), "P0"),
        TagRule(r"受力|摩擦|弹力|牛顿|加速度|连接体|滑轮|绳", ("力学",), ("受力分析", "牛顿第二定律", "连接体"), ("牛顿定律与连接体",), ("建模论证",), ("漏系统选择", "速度关系错误"), ("专题训练",), "P1"),
        TagRule(r"功|功率|动能|机械能|势能|守恒|弹簧|弹性势能", ("力学",), ("动能定理", "机械能守恒", "弹簧模型", "功能关系"), ("功能关系综合",), ("建模论证", "运算表达"), ("漏守恒条件", "未分阶段"), ("错因修复", "专题训练"), "P0"),
        TagRule(r"动量|冲量|碰撞|反冲|爆炸|平均力", ("力学",), ("动量守恒", "冲量", "碰撞模型"), ("动量与能量联用",), ("方向判断", "建模论证"), ("方向判断错误", "漏系统选择"), ("错因修复",), "P1"),
        TagRule(r"万有引力|卫星|轨道|开普勒|航天|天体", ("力学",), ("万有引力", "航天变轨"), ("天体运动",), ("建模论证",), ("模型识别不足",)),
        TagRule(r"简谐|振动|机械波|波长|波速|频率|干涉|衍射|偏振", ("力学", "光学"), ("简谐运动", "机械波", "光的干涉", "光的衍射"), ("振动波动图像",), ("图像解读",), ("图像轴意不清",)),
        TagRule(r"电场|电势|电势能|电容|带电粒子|库仑", ("电磁学",), ("静电场", "电容器"), ("电场综合",), ("方向判断", "运算表达"), ("方向判断错误",), ("高考拓展",), "P2"),
        TagRule(r"电路|电阻|电流|电压|电功率|欧姆|电源|内阻|多用电表", ("电磁学", "实验"), ("恒定电流", "电学实验"), ("电路分析",), ("图像解读", "实验探究"), ("实验步骤不完整",), ("专题训练",), "P2"),
        TagRule(r"磁场|洛伦兹|安培|霍尔|带电粒子.*圆", ("电磁学",), ("磁场",), ("磁场中的带电粒子",), ("方向判断", "建模论证"), ("方向判断错误",), ("高考拓展",), "P2"),
        TagRule(r"电磁感应|磁通|楞次|法拉第|感应电流|自感|互感|交流|变压器", ("电磁学",), ("电磁感应", "交流电", "自感互感"), ("电磁感应综合",), ("方向判断", "图像解读"), ("方向判断错误", "图像轴意不清"), ("高考拓展",), "P2"),
        TagRule(r"气体|压强|体积|温度|内能|热力学|分子|阿伏加德罗|理想气体", ("热学",), ("理想气体", "分子动理论", "热力学第一定律"), ("热学状态变化",), ("条件翻译",), ("概念混淆",)),
        TagRule(r"折射|全反射|光路|光电|能级|氢原子|半衰期|核反应|放射", ("光学", "近代物理"), ("几何光学", "光电效应", "原子能级", "原子核"), ("近代物理基础",), ("概念辨析",), ("概念混淆",)),
        TagRule(r"实验|打点|纸带|斜率|误差|有效数字|传感器|验证|测量", ("实验",), ("数据处理", "打点计时器", "验证机械能守恒"), ("实验数据处理",), ("实验探究", "图像解读"), ("实验步骤不完整", "图像轴意不清"), ("错因修复",), "P0"),
    ],
    "化学": [
        TagRule(r"化学用语|电子式|结构式|结构简式|VSEPR|杂化|晶胞|共价键|离子键|分子|元素周期", ("物质结构",), ("化学用语", "物质结构", "元素周期律"), ("物质结构辨析",), ("概念辨析",), ("概念混淆",)),
        TagRule(r"钠|镁|铝|铁|铜|氯|硫|氮|硅|碳酸|氧化物|单质|化合物", ("元素化合物",), ("元素化合物性质",), ("元素化合物推断",), ("信息提取",), ("条件遗漏",)),
        TagRule(r"离子方程式|离子反应|氧化还原|还原剂|氧化剂|化合价|电子转移", ("元素化合物",), ("离子反应", "氧化还原"), ("离子反应与氧化还原",), ("方程式书写",), ("方程式不配平", "条件漏写"), ("专题训练",), "P1"),
        TagRule(r"反应速率|化学平衡|平衡常数|转化率|勒夏特列|压强|浓度|温度.*平衡", ("化学反应原理", "化学平衡"), ("反应速率", "化学平衡", "平衡移动"), ("速率平衡综合",), ("图表分析", "计算表达"), ("图表信息漏读", "守恒关系不清"), ("高考拓展",), "P1"),
        TagRule(r"电池|原电池|电解|电极|阴极|阳极|电化学|电势|充电|放电", ("电化学",), ("原电池", "电解池", "电极反应"), ("电池与电解",), ("证据推理", "方程式书写"), ("方向判断错误", "方程式不配平"), ("专题训练",), "P1"),
        TagRule(r"电离|水解|pH|滴定|中和|沉淀|溶度积|Ksp|盐类|弱酸|弱碱", ("化学反应原理",), ("电离平衡", "盐类水解", "沉淀溶解平衡", "滴定计算"), ("溶液平衡与滴定",), ("计算表达", "图表分析"), ("守恒关系不清",), ("高考拓展",), "P1"),
        TagRule(r"有机|烃|醇|醛|酸|酯|苯|同分异构|加成|取代|消去|聚合|氨基酸|蛋白质|糖类|油脂", ("有机化学",), ("有机物结构与性质", "有机推断"), ("有机推断",), ("信息提取", "方程式书写"), ("条件遗漏",)),
        TagRule(r"实验|装置|试管|烧杯|滴定管|容量瓶|分液|萃取|蒸馏|过滤|检验|除杂|变量", ("实验探究",), ("实验方案评价", "物质检验", "分离提纯"), ("实验方案评价",), ("变量控制", "证据推理"), ("实验目的不明", "条件漏写"), ("专题训练",), "P1"),
        TagRule(r"流程|工艺|工业|浸取|焙烧|酸浸|调pH|滤渣|滤液|产品|循环", ("工业流程",), ("工业流程", "流程图分析"), ("流程图分析",), ("信息提取", "证据推理"), ("图表信息漏读", "守恒关系不清"), ("高考拓展",), "P1"),
    ],
    "生物": [
        TagRule(r"细胞|细胞器|细胞膜|线粒体|叶绿体|核糖体|染色体|有丝分裂|减数分裂", ("细胞结构与代谢",), ("细胞结构", "细胞分裂"), ("细胞结构与过程辨析",), ("概念辨析",), ("术语不准确",)),
        TagRule(r"光合|呼吸|酶|ATP|代谢|CO2|O2|叶绿素|暗反应|有氧呼吸|无氧呼吸", ("细胞结构与代谢",), ("光合作用", "呼吸作用", "酶与ATP"), ("光合作用呼吸作用",), ("图表读取", "证据推理"), ("图像趋势误读",), ("专题训练",), "P1"),
        TagRule(r"DNA|RNA|基因|遗传|杂交|显性|隐性|等位|伴性|分离定律|自由组合|突变|变异|染色体", ("遗传与变异",), ("遗传规律", "基因表达", "变异"), ("遗传图谱与概率",), ("证据推理", "计算表达"), ("遗传概率漏情况",), ("高考拓展", "专题训练"), "P1"),
        TagRule(r"神经|突触|兴奋|反射|激素|内分泌|血糖|体温|免疫|抗体|抗原|稳态", ("稳态与调节",), ("神经调节", "体液调节", "免疫调节", "稳态"), ("神经体液免疫调节",), ("概念辨析", "证据推理"), ("因果关系写反",)),
        TagRule(r"生态|种群|群落|生态系统|能量流动|物质循环|食物链|生物多样性|调查", ("生态系统",), ("种群群落", "生态系统功能"), ("种群群落生态",), ("图表读取", "文字表达"), ("术语不准确",)),
        TagRule(r"PCR|电泳|发酵|基因工程|细胞工程|胚胎工程|单克隆|限制酶|载体|质粒", ("生物技术与工程",), ("基因工程", "发酵工程", "细胞工程"), ("生物技术流程",), ("信息提取", "证据推理"), ("流程步骤遗漏",)),
        TagRule(r"实验|变量|对照|自变量|因变量|无关变量|探究|处理组|对照组|统计|曲线|表格", ("实验探究",), ("实验设计", "变量控制", "图表数据分析"), ("实验变量控制",), ("实验设计", "变量控制", "图表读取"), ("变量不清", "图像趋势误读"), ("专题训练",), "P1"),
    ],
    "语文": [
        TagRule(r"材料一|材料二|论述|观点|根据材料|概括|分析|文本|信息", ("现代文阅读",), ("信息筛选", "论述类文本阅读"), ("论述类文本",), ("信息筛选", "概括归纳"), ("文本依据不足",), ("高考拓展",), "P1"),
        TagRule(r"小说|散文|人物|情节|环境|叙述|描写|赏析|表达效果|文学类", ("现代文阅读",), ("文学类文本阅读", "表达效果分析"), ("文学类文本",), ("文本细读", "表达效果分析"), ("只复述不分析",), ("专题训练",), "P1"),
        TagRule(r"文言|实词|虚词|断句|翻译|古人|选自|下列对文中|加点词", ("文言文阅读",), ("文言实词虚词", "文言翻译", "文言断句"), ("文言实词虚词",), ("文本细读", "信息筛选"), ("答非所问",), ("高考拓展",), "P1"),
        TagRule(r"诗|词|鉴赏|意象|情感|抒发|诗人|首联|颔联|尾联", ("古诗词鉴赏",), ("诗歌意象情感", "诗歌表达技巧"), ("诗歌意象情感",), ("文本细读", "表达效果分析"), ("术语空泛",), ("专题训练",), "P1"),
        TagRule(r"名句|默写|补写|空缺|背诵", ("名句默写",), ("名篇名句默写",), ("名句默写",), ("准确记忆",), ("错字漏字",)),
        TagRule(r"语言文字|成语|病句|衔接|标点|语段|压缩|扩展|修辞|语序", ("语言文字运用",), ("语言表达与运用",), ("语言文字运用",), ("表达准确", "语篇衔接"), ("答非所问",)),
        TagRule(r"作文|写作|不少于|立意|题目|材料作文|议论文", ("作文",), ("作文审题立意", "作文结构"), ("作文立意结构",), ("审题立意", "论证结构"), ("审题偏差", "结构松散"), ("高考拓展",), "P1"),
        TagRule(r"红楼梦|乡土中国|整本书|名著|经典阅读", ("整本书阅读",), ("整本书阅读",), ("整本书阅读",), ("文本细读",), ("文本依据不足",)),
    ],
    "英语": [
        TagRule(r"听下面|听力|conversation|dialogue|listen|speaker|recording", ("听力",), ("听力信息获取",), ("听力细节定位",), ("定位检索", "上下文推断"), ("定位错误",)),
        TagRule(r"完形|cloze|blank|choose the best word|语法填空|用括号|proper form", ("完形填空", "语法填空"), ("完形语篇逻辑", "语法填空考点"), ("语法填空考点",), ("上下文推断", "语法搭配"), ("语法搭配错误", "词汇障碍"), ("专题训练",), "P1"),
        TagRule(r"According to|What can we learn|Which of the following|passage|paragraph|author|阅读", ("阅读理解",), ("细节定位", "推理判断", "主旨大意"), ("细节定位", "推理判断"), ("定位检索", "上下文推断"), ("定位错误", "过度推断"), ("高考拓展",), "P1"),
        TagRule(r"七选五|选项中有两项|从短文后的选项|best title|段落标题", ("七选五",), ("语篇衔接", "篇章结构"), ("篇章结构",), ("语篇衔接",), ("漏看限定条件",), ("专题训练",), "P1"),
        TagRule(r"假设你是|Dear|write an email|letter|notice|proposal|application|应用文", ("应用文写作",), ("写作情境任务", "应用文结构"), ("写作情境任务",), ("写作结构", "表达准确性"), ("写作不贴任务",), ("高考拓展",), "P1"),
        TagRule(r"续写|continue|续写一段|故事|情节", ("读后续写",), ("读后续写情节推进",), ("写作情境任务",), ("写作结构", "表达准确性"), ("写作不贴任务",), ("专题训练",), "P1"),
        TagRule(r"词义|meaning|refer to|sentence|grammar|vocabulary", ("词汇语块",), ("词义猜测", "长难句分析"), ("词义猜测",), ("长难句分析", "上下文推断"), ("词汇障碍",)),
    ],
}


def uniq(items: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def fallback_tags(subject: str, qno: int) -> dict[str, Any]:
    if subject == "数学":
        if qno <= 10:
            return {"module": ["综合基础"], "knowledge_tags": ["选择题基础考点"], "model_tags": ["基础小题"], "ability_tags": ["条件翻译"], "mistake_tags": ["条件遗漏"]}
        if qno <= 15:
            return {"module": ["综合基础"], "knowledge_tags": ["填空题基础考点"], "model_tags": ["基础小题"], "ability_tags": ["运算表达"], "mistake_tags": ["运算失误"]}
        return {"module": ["综合题"], "knowledge_tags": ["解答题综合"], "model_tags": ["综合解答"], "ability_tags": ["证明论证", "运算表达"], "mistake_tags": ["模型识别不足"]}
    if subject == "语文":
        if qno <= 5:
            return {"module": ["现代文阅读"], "knowledge_tags": ["论述类文本阅读"], "model_tags": ["论述类文本"], "ability_tags": ["信息筛选"], "mistake_tags": ["文本依据不足"]}
        if qno <= 9:
            return {"module": ["现代文阅读"], "knowledge_tags": ["文学类文本阅读"], "model_tags": ["文学类文本"], "ability_tags": ["文本细读"], "mistake_tags": ["只复述不分析"]}
        if qno <= 14:
            return {"module": ["文言文阅读"], "knowledge_tags": ["文言文阅读"], "model_tags": ["文言实词虚词"], "ability_tags": ["文本细读"], "mistake_tags": ["答非所问"]}
        if qno <= 16:
            return {"module": ["古诗词鉴赏"], "knowledge_tags": ["诗歌鉴赏"], "model_tags": ["诗歌意象情感"], "ability_tags": ["表达效果分析"], "mistake_tags": ["术语空泛"]}
        if qno == 17:
            return {"module": ["名句默写"], "knowledge_tags": ["名篇名句默写"], "model_tags": ["名句默写"], "ability_tags": ["准确记忆"], "mistake_tags": ["错字漏字"]}
        if qno <= 22:
            return {"module": ["语言文字运用"], "knowledge_tags": ["语言表达与运用"], "model_tags": ["语言文字运用"], "ability_tags": ["表达准确"], "mistake_tags": ["答非所问"]}
        return {"module": ["作文"], "knowledge_tags": ["作文审题立意"], "model_tags": ["作文立意结构"], "ability_tags": ["审题立意"], "mistake_tags": ["审题偏差"]}
    if subject == "英语":
        if qno <= 10:
            return {"module": ["语法填空"], "knowledge_tags": ["语法填空考点"], "model_tags": ["语法填空考点"], "ability_tags": ["语法搭配", "上下文推断"], "mistake_tags": ["语法搭配错误"]}
        if qno <= 25:
            return {"module": ["完形填空"], "knowledge_tags": ["完形语篇逻辑"], "model_tags": ["上下文推断"], "ability_tags": ["上下文推断"], "mistake_tags": ["词汇障碍"]}
        if qno <= 39:
            return {"module": ["阅读理解"], "knowledge_tags": ["阅读理解"], "model_tags": ["细节定位"], "ability_tags": ["定位检索"], "mistake_tags": ["定位错误"]}
        if qno <= 43:
            return {"module": ["阅读表达"], "knowledge_tags": ["阅读表达"], "model_tags": ["阅读表达任务"], "ability_tags": ["信息筛选", "表达准确性"], "mistake_tags": ["答非所问"]}
        return {"module": ["应用文写作"], "knowledge_tags": ["写作情境任务"], "model_tags": ["写作情境任务"], "ability_tags": ["写作结构"], "mistake_tags": ["写作不贴任务"]}
    if subject == "物理":
        if qno <= 14:
            return {"module": ["综合基础"], "knowledge_tags": ["选择题基础考点"], "model_tags": ["物理概念辨析"], "ability_tags": ["概念辨析"], "mistake_tags": ["概念混淆"]}
        return {"module": ["综合情境"], "knowledge_tags": ["综合计算与论证"], "model_tags": ["综合情境建模"], "ability_tags": ["建模论证"], "mistake_tags": ["模型识别不足"]}
    if subject == "化学":
        if qno <= 14:
            return {"module": ["综合基础"], "knowledge_tags": ["选择题基础考点"], "model_tags": ["化学概念辨析"], "ability_tags": ["概念辨析"], "mistake_tags": ["概念混淆"]}
        return {"module": ["综合题"], "knowledge_tags": ["非选择题综合"], "model_tags": ["化学综合推断"], "ability_tags": ["信息提取", "证据推理"], "mistake_tags": ["条件遗漏"]}
    if subject == "生物":
        if qno <= 15:
            return {"module": ["综合基础"], "knowledge_tags": ["选择题基础考点"], "model_tags": ["生物概念辨析"], "ability_tags": ["概念辨析"], "mistake_tags": ["术语不准确"]}
        return {"module": ["综合题"], "knowledge_tags": ["非选择题综合"], "model_tags": ["生物综合分析"], "ability_tags": ["证据推理", "文字表达"], "mistake_tags": ["因果关系写反"]}
    return {"module": ["待人工细分"], "knowledge_tags": ["待人工细分"], "model_tags": ["待人工细分"], "ability_tags": [], "mistake_tags": []}


def difficulty(subject: str, qno: int, text: str) -> str:
    if subject == "数学":
        if qno <= 8:
            return "基础"
        if qno <= 15:
            return "中档"
        if qno <= 18:
            return "综合"
        return "压轴"
    if subject in {"物理", "化学"}:
        if qno <= 8:
            return "基础"
        if qno <= 14:
            return "中档"
        if qno <= 18:
            return "综合"
        return "压轴"
    if subject == "生物":
        if qno <= 10:
            return "基础"
        if qno <= 15:
            return "中档"
        return "综合"
    if subject == "语文":
        if qno in {23, 24} or "作文" in text:
            return "综合"
        if qno <= 5 or qno == 17:
            return "基础"
        return "中档"
    if subject == "英语":
        if qno <= 15:
            return "基础"
        if qno <= 45:
            return "中档"
        return "综合"
    return "中档"


def figure_requirement(subject: str, text: str, page_sources: set[str]) -> str:
    s = norm_space(text)
    if subject in {"语文", "英语"} and len(s) > 900:
        return "文本材料必带"
    if COMMON_FIGURE_PATTERN.search(s):
        if re.search(r"表\d|下表|table|统计|数据表", s, re.IGNORECASE):
            return "表格图像"
        return "原图必带"
    if subject in {"化学", "生物"} and re.search(r"实验|流程|装置|结构|曲线|图", s):
        return "原图必带"
    if "ocr" in page_sources and subject in {"数学", "物理", "化学", "生物"}:
        return "需人工判断"
    return "无图"


def apply_rules(subject: str, qno: int, text: str) -> dict[str, Any]:
    fallback = fallback_tags(subject, qno)
    modules: list[str] = []
    knowledge: list[str] = []
    models: list[str] = []
    skills: list[str] = []
    mistakes: list[str] = []
    usages: list[str] = []
    priorities: list[str] = []
    for rule in RULES.get(subject, []):
        if re.search(rule.pattern, text, re.IGNORECASE):
            modules.extend(rule.module)
            knowledge.extend(rule.knowledge)
            models.extend(rule.models)
            skills.extend(rule.skills)
            mistakes.extend(rule.mistakes)
            usages.extend(rule.usage)
            if rule.priority:
                priorities.append(rule.priority)
    if not knowledge:
        modules = list(fallback["module"])
        knowledge = list(fallback["knowledge_tags"])
        models = list(fallback["model_tags"])
        skills = list(fallback["ability_tags"])
        mistakes = list(fallback["mistake_tags"])
    usage = uniq(usages or ["高考拓展", "专题训练"])
    priority = priorities[0] if priorities else ("P1" if subject in {"数学", "语文", "英语", "化学", "生物"} and difficulty(subject, qno, text) in {"综合", "压轴"} else "P2")
    return {
        "module": uniq(modules),
        "knowledge_tags": uniq(knowledge),
        "model_tags": uniq(models),
        "ability_tags": uniq(skills),
        "mistake_tags": uniq(mistakes),
        "usage": usage,
        "priority": priority,
    }


def old_key(record: dict[str, Any]) -> tuple[str, str, str, str, int] | None:
    try:
        return (
            str(record.get("subject") or ""),
            str(record.get("year")),
            str(record.get("district")),
            str(record.get("kind") or record.get("exam_type")),
            int(record.get("question_no")),
        )
    except Exception:
        return None


def load_existing(subject: str) -> dict[tuple[str, str, str, str, int], dict[str, Any]]:
    path = ROOT / subject / "题库" / "一模二模题目标签索引.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    out: dict[tuple[str, str, str, str, int], dict[str, Any]] = {}
    if isinstance(data, list):
        for rec in data:
            if not isinstance(rec, dict):
                continue
            key = old_key({**rec, "subject": rec.get("subject") or subject})
            if key:
                out[key] = rec
    return out


def merge_existing_tags(record: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    if not existing:
        return record
    for new_name, old_names in {
        "module": ["module"],
        "knowledge_tags": ["knowledge_tags", "knowledge_point"],
        "ability_tags": ["ability_tags", "skills"],
        "mistake_tags": ["mistake_tags"],
        "priority": ["priority"],
    }.items():
        for old_name in old_names:
            old_value = existing.get(old_name)
            if old_value:
                if isinstance(record.get(new_name), list):
                    if isinstance(old_value, list):
                        record[new_name] = uniq(list(old_value) + list(record.get(new_name) or []))
                    else:
                        record[new_name] = uniq([str(x) for x in re.split(r"[;；,，]", str(old_value)) if x.strip()] + list(record.get(new_name) or []))
                else:
                    record[new_name] = old_value
                break
    return record


def page_source_set(question: dict[str, Any], pages: list[dict[str, Any]]) -> set[str]:
    page = int(question.get("source_page") or 1)
    return {str(p.get("source")) for p in pages if int(p.get("page") or 0) == page}


def make_record(
    subject: str,
    year: int,
    district: str,
    kind: str,
    question: dict[str, Any],
    pdf_path: Path,
    text_path: Path,
    extraction_report: dict[str, Any],
    split_status: str,
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    qno = int(question["question_no"])
    text = question.get("text") or ""
    tags = apply_rules(subject, qno, text)
    source = f"{year}北京{district}高三{kind}{subject}第{qno}题"
    p_sources = set()
    text_source = extraction_report.get("text_source") or ""
    if text_source:
        p_sources.add(text_source)
    fig = figure_requirement(subject, text, p_sources)
    is_placeholder = bool(question.get("placeholder"))
    if is_placeholder:
        fallback = fallback_tags(subject, qno)
        tags = {
            "module": uniq(["题干待人工抽取"] + list(fallback["module"])),
            "knowledge_tags": uniq(list(fallback["knowledge_tags"]) + ["题干待人工抽取"]),
            "model_tags": uniq(list(fallback["model_tags"]) + ["题干待人工抽取"]),
            "ability_tags": uniq(list(fallback["ability_tags"]) + ["待人工判断"]),
            "mistake_tags": uniq(list(fallback["mistake_tags"]) + ["待人工判断"]),
            "usage": ["候选题占位", "人工校对"],
            "priority": "P0",
        }
        fig = "需人工判断"
    needs_manual = (
        is_placeholder
        or fig != "无图"
        or "偏少" in split_status
        or "占位" in split_status
        or extraction_report.get("ocr_pages_failed", 0) > 0
    )
    record: dict[str, Any] = {
        "subject": subject,
        "year": str(year),
        "district": district,
        "kind": kind,
        "exam_type": kind,
        "question_no": qno,
        "source": source,
        "source_label": source,
        "source_page": int(question.get("source_page") or 1),
        "module": tags["module"],
        "knowledge_tags": tags["knowledge_tags"],
        "knowledge_point": tags["knowledge_tags"],
        "model_tags": tags["model_tags"],
        "ability_tags": tags["ability_tags"],
        "skills": tags["ability_tags"],
        "mistake_tags": tags["mistake_tags"],
        "difficulty": difficulty(subject, qno, text),
        "stage": "高三复习",
        "usage": tags["usage"],
        "figure_required": fig,
        "verify_status": "机器初标",
        "text_verify_status": "待核对题干",
        "figure_verify_status": "待核对图示" if fig != "无图" else "无图",
        "answer_verify_status": "待核对答案",
        "machine_tag_status": "机器初标",
        "child_ready": "否",
        "priority": tags["priority"],
        "extract_status": ("题干占位待人工抽取" if is_placeholder else split_status),
        "ocr_status": (
            "含OCR"
            if extraction_report.get("ocr_pages_done", 0) > 0
            else ("未OCR" if extraction_report.get("ocr_pages_requested", 0) > 0 else "无需OCR")
        ),
        "text_source": extraction_report.get("text_source") or "",
        "needs_manual_review": "是" if needs_manual else "否",
        "pdf": str(pdf_path),
        "pdf_path": str(pdf_path),
        "text_file": str(text_path),
        "question_text_machine": norm_space(text),
        "snippet": short_text(text),
        "placeholder": is_placeholder,
        "manual_check": {
            "题干": "待核对",
            "图示": "待核对" if fig != "无图" else "无图",
            "答案": "待核对",
        },
    }
    return merge_existing_tags(record, existing)


def csv_value(value: Any) -> str:
    if isinstance(value, list):
        return ";".join(str(x) for x in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for rec in records:
            writer.writerow({field: csv_value(rec.get(field)) for field in CSV_FIELDS})


def write_json(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def build_knowledge_index(subject: str, records: list[dict[str, Any]]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    by_knowledge: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        for tag in rec.get("knowledge_tags") or ["待人工细分"]:
            by_knowledge.setdefault(tag, []).append(rec)
    lines = [
        f"# 北京{subject}一模二模知识点索引",
        "",
        f"更新时间：{now}",
        "",
        "说明：本索引为机器初标，用于筛选候选题；正式放入周反馈或学生打印版前，必须打开原 PDF 核对题干、图示和答案。",
        "",
        "## 汇总",
        "",
        "| 知识点 | 题数 | 代表来源 |",
        "|---|---:|---|",
    ]
    for tag, items in sorted(by_knowledge.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        reps = "；".join(x["source"] for x in items[:5])
        lines.append(f"| {tag} | {len(items)} | {reps} |")
    for tag, items in sorted(by_knowledge.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines += [
            "",
            f"## {tag}",
            "",
            "| 来源 | 页码 | 模块 | 题型模型 | 难度 | 图示要求 | 核验状态 | 题干片段 |",
            "|---|---:|---|---|---|---|---|---|",
        ]
        for rec in sorted(items, key=lambda r: (r["year"], r["district"], r["kind"], int(r["question_no"]))):
            module = ";".join(rec.get("module") or [])
            models = ";".join(rec.get("model_tags") or [])
            snippet = str(rec.get("snippet") or "").replace("|", "｜")
            lines.append(
                f"| {rec['source']} | {rec.get('source_page', '')} | {module} | {models} | {rec.get('difficulty', '')} | {rec.get('figure_required', '')} | {rec.get('verify_status', '')}/题干{rec.get('text_verify_status', '')}/答案{rec.get('answer_verify_status', '')} | {snippet} |"
            )
    return "\n".join(lines) + "\n"


def build_checklist(subject: str, paper_reports: list[dict[str, Any]], records: list[dict[str, Any]]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# {subject}一模二模 OCR 与人工校对清单",
        "",
        f"更新时间：{now}",
        "",
        "说明：所有题目前均为机器初标，不能直接给孩子。下表把文本抽取、OCR、题号切分和图示/材料核验风险分开列出。",
        "",
        "## 试卷抽取状态",
        "",
        "| 年份 | 区域 | 类型 | 页数 | 题数 | 文本来源 | OCR页 | 状态 | PDF |",
        "|---|---|---|---:|---:|---|---:|---|---|",
    ]
    for report in paper_reports:
        pdf = str(report.get("pdf", "")).replace("|", "｜")
        lines.append(
            f"| {report.get('year')} | {report.get('district')} | {report.get('kind')} | {report.get('pages', '')} | {report.get('question_count', 0)} | {report.get('text_source', '')} | {report.get('ocr_pages_done', 0)} | {report.get('split_status', '')} | `{pdf}` |"
        )
    risky = [
        rec for rec in records
        if rec.get("figure_required") != "无图"
        or rec.get("needs_manual_review") == "是"
        or rec.get("ocr_status") == "含OCR"
    ]
    lines += [
        "",
        "## 重点人工核验清单",
        "",
        "所有题正式使用前都要核对题干和答案；本表优先列出带图、带表、带长材料、OCR 或切分风险较高的题。",
        "",
        "| 来源 | 页码 | OCR状态 | 图示/材料要求 | 待核对项 | 题干片段 |",
        "|---|---:|---|---|---|---|",
    ]
    for rec in risky:
        pending = "题干;答案"
        if rec.get("figure_required") != "无图":
            pending += ";图示/材料"
        snippet = str(rec.get("snippet") or "").replace("|", "｜")
        lines.append(
            f"| {rec['source']} | {rec.get('source_page', '')} | {rec.get('ocr_status', '')} | {rec.get('figure_required', '')} | {pending} | {snippet} |"
        )
    return "\n".join(lines) + "\n"


def process_subject(
    subject: str,
    years: list[int],
    districts: list[str],
    kinds: list[str],
    force: bool,
    ocr_mode: str,
    max_ocr_workers: int,
    limit_pdfs: int | None,
) -> dict[str, Any]:
    print(f"\n== {subject} ==")
    qbank = ROOT / subject / "题库"
    qbank.mkdir(parents=True, exist_ok=True)
    existing = load_existing(subject)
    records: list[dict[str, Any]] = []
    paper_reports: list[dict[str, Any]] = []
    processed = 0
    for year in years:
        for district in districts:
            for kind in kinds:
                if limit_pdfs is not None and processed >= limit_pdfs:
                    break
                pdf = pdf_target(subject, year, district, kind)
                if pdf is None:
                    paper_reports.append(
                        {
                            "subject": subject,
                            "year": year,
                            "district": district,
                            "kind": kind,
                            "pdf": "",
                            "pages": 0,
                            "question_count": 0,
                            "split_status": "缺PDF",
                            "text_source": "",
                            "ocr_pages_done": 0,
                        }
                    )
                    continue
                pages, text_path, extract_report = extract_pages(pdf, subject, force, ocr_mode, max_ocr_workers)
                questions, split_status = split_questions(subject, pages)
                processed += 1
                paper_report = {
                    **extract_report,
                    "subject": subject,
                    "year": year,
                    "district": district,
                    "kind": kind,
                    "question_count": len(questions),
                    "split_status": split_status,
                    "text_file": str(text_path),
                }
                paper_reports.append(paper_report)
                print(
                    f"{subject} {year}{district}{kind}: {len(questions)}题, {extract_report.get('text_source')}, OCR {extract_report.get('ocr_pages_done', 0)}/{extract_report.get('ocr_pages_requested', 0)}, {split_status}"
                )
                for q in questions:
                    key = (subject, str(year), district, kind, int(q["question_no"]))
                    rec = make_record(
                        subject,
                        year,
                        district,
                        kind,
                        q,
                        pdf,
                        text_path,
                        extract_report,
                        split_status,
                        existing.get(key),
                    )
                    records.append(rec)
            if limit_pdfs is not None and processed >= limit_pdfs:
                break
        if limit_pdfs is not None and processed >= limit_pdfs:
            break

    records.sort(key=lambda r: (int(r["year"]), r["district"], r["kind"], int(r["question_no"])))
    write_json(qbank / "一模二模题目标签索引.json", records)
    write_csv(qbank / "一模二模题目标签索引.csv", records)
    (qbank / f"北京{subject}一模二模知识点索引.md").write_text(build_knowledge_index(subject, records), encoding="utf-8")
    (qbank / "一模二模OCR与人工校对清单.md").write_text(build_checklist(subject, paper_reports, records), encoding="utf-8")
    (qbank / "一模二模题目标签生成报告.json").write_text(
        json.dumps(
            {
                "subject": subject,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "paper_count": len(paper_reports),
                "question_count": len(records),
                "paper_reports": paper_reports,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "subject": subject,
        "paper_count": len([p for p in paper_reports if p.get("pdf")]),
        "question_count": len(records),
        "placeholder_count": len([r for r in records if r.get("placeholder")]),
        "ocr_papers": len([p for p in paper_reports if int(p.get("ocr_pages_done") or 0) > 0]),
        "low_split_papers": len([p for p in paper_reports if "偏少" in str(p.get("split_status")) or "未能" in str(p.get("split_status"))]),
        "figure_or_manual_questions": len([r for r in records if r.get("needs_manual_review") == "是"]),
        "child_ready_count": len([r for r in records if r.get("child_ready") == "是"]),
    }


def parse_years(text: str) -> list[int]:
    if text == "all":
        return YEARS
    out: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return sorted(set(out))


def main() -> None:
    global ROOT, TESSERACT
    configure_stdio()
    parser = argparse.ArgumentParser(description="生成六科北京一模二模题目级机器标签索引")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="学习资料库根目录，默认当前目录")
    parser.add_argument("--subjects", default="all", help="all 或逗号分隔科目")
    parser.add_argument("--years", default="all", help="all, 2025, 2023-2025, 2020,2021")
    parser.add_argument("--districts", default="all", help="all 或逗号分隔区域")
    parser.add_argument("--kinds", default="all", help="all 或逗号分隔一模/二模")
    parser.add_argument("--ocr", choices=["auto", "never", "always"], default="auto")
    parser.add_argument("--tesseract", type=Path, default=TESSERACT, help="tesseract 可执行文件路径，默认从 PATH 查找")
    parser.add_argument("--max-ocr-workers", type=int, default=max(1, min(4, (os.cpu_count() or 4) // 2)))
    parser.add_argument("--force", action="store_true", help="重新抽取文本/OCR，不使用缓存")
    parser.add_argument("--limit-pdfs", type=int, default=None)
    args = parser.parse_args()
    ROOT = args.root.resolve()
    TESSERACT = args.tesseract

    subjects = SUBJECTS if args.subjects == "all" else [x.strip() for x in args.subjects.split(",") if x.strip()]
    years = parse_years(args.years)
    districts = DISTRICTS if args.districts == "all" else [x.strip() for x in args.districts.split(",") if x.strip()]
    kinds = KINDS if args.kinds == "all" else [x.strip() for x in args.kinds.split(",") if x.strip()]

    summary: list[dict[str, Any]] = []
    for subject in subjects:
        summary.append(process_subject(subject, years, districts, kinds, args.force, args.ocr, args.max_ocr_workers, args.limit_pdfs))

    tmp = ROOT / "题库总控"
    tmp.mkdir(parents=True, exist_ok=True)
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "subjects": summary,
        "notes": [
            "所有标签均为机器初标，只可用于筛题。",
            "正式给孩子前必须人工核对题干、图示/材料和答案。",
        ],
    }
    (tmp / "全科一模二模题目标签生成报告.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 全科一模二模题目标签生成报告",
        "",
        f"更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "| 科目 | 试卷数 | 题目/题号数 | 占位题号 | 含OCR试卷 | 切分风险试卷 | 重点人工核验题 | 可直接给孩子 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(
            f"| {row['subject']} | {row['paper_count']} | {row['question_count']} | {row['placeholder_count']} | {row['ocr_papers']} | {row['low_split_papers']} | {row['figure_or_manual_questions']} | {row['child_ready_count']} |"
        )
    lines += [
        "",
        "说明：机器初标已生成 CSV/JSON/知识点索引/OCR人工校对清单；这些结果仍不是学生打印版，引用前必须打开原 PDF 核题干、图示/材料和答案。",
    ]
    (tmp / "全科一模二模题目标签生成报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n== SUMMARY ==")
    for row in summary:
        print(row)


if __name__ == "__main__":
    main()
