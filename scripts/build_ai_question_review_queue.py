from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path.cwd()
SUBJECTS = ["语文", "数学", "英语", "物理", "化学", "生物"]

CSV_FIELDS = [
    "subject",
    "rank",
    "ai_score",
    "ai_usability_level",
    "candidate_scope",
    "matched_current_keywords",
    "ai_review_priority",
    "ai_next_action",
    "user_action",
    "risk_flags",
    "verification_steps",
    "year",
    "district",
    "kind",
    "question_no",
    "source",
    "source_page",
    "module",
    "knowledge_tags",
    "model_tags",
    "difficulty",
    "figure_required",
    "extract_status",
    "ocr_status",
    "placeholder",
    "needs_manual_review",
    "child_ready",
    "pdf_path",
    "snippet",
]

NOISE_RE = re.compile(
    r"关注北京高考在线|京考一点通|北京高考资讯|bj[-_]?gaokao|bjgkzx|"
    r"公众号|微信|扫码|二维码|试题下载|下载更多|答案解析|参考答案|评分参考|PAGE|第\s*\d+\s*页",
    re.IGNORECASE,
)

CURRENT_PRIORITY_KEYWORDS: dict[str, list[str]] = {
    "数学": [
        "立体几何",
        "空间线面关系",
        "线面垂直",
        "线面平行",
        "面面平行",
        "面面垂直",
        "空间角",
        "线面角",
        "异面直线",
        "截面",
        "几何体",
        "球",
        "证明论证",
    ],
    "物理": [
        "机械能守恒",
        "弹簧模型",
        "圆周临界",
        "圆周运动",
        "平抛运动",
        "运动图像",
        "打点计时器",
        "验证机械能守恒",
        "动量",
        "冲量",
        "动量守恒",
        "碰撞模型",
        "功能关系",
    ],
    "化学": [
        "原电池",
        "电化学",
        "电极反应",
        "电池",
        "电解",
        "化学反应原理",
        "反应速率",
        "化学平衡",
        "有机",
        "酯",
        "水解",
        "实验方案评价",
    ],
    "生物": [
        "遗传与变异",
        "遗传规律",
        "基因表达",
        "表观遗传",
        "DNA",
        "RNA",
        "染色体",
        "减数分裂",
        "单倍体",
        "生物技术",
        "实验设计",
    ],
    "英语": [
        "应用文写作",
        "写作情境任务",
        "应用文结构",
        "阅读理解",
        "细节定位",
        "推理判断",
        "词汇语块",
        "长难句",
        "语篇衔接",
    ],
    "语文": [
        "现代文阅读",
        "文学类文本",
        "小说",
        "人物",
        "情节",
        "文言文阅读",
        "古诗词鉴赏",
        "整本书阅读",
        "作文",
        "表达效果分析",
    ],
}

EVIDENCE_PATTERNS: dict[str, dict[str, str]] = {
    "数学": {
        "立体几何": r"立体|空间|平面|直线|棱|锥|柱|正方体|四面体|二面角|线面|面面|垂直|平行|截面|球",
        "空间线面关系": r"空间|平面|直线|线面|面面|垂直|平行|异面|二面角",
        "线面垂直": r"线面垂直|直线.*平面.*垂直|平面.*直线.*垂直|垂直于平面",
        "线面平行": r"线面平行|直线.*平面.*平行|平面.*直线.*平行|平行于平面",
        "面面平行": r"面面平行|平面.*平面.*平行|两个平面.*平行",
        "面面垂直": r"面面垂直|平面.*平面.*垂直|两个平面.*垂直",
        "空间角": r"空间角|二面角|线面角|异面直线.*角|所成角",
        "线面角": r"线面角|直线.*平面.*所成角|斜线|射影",
        "异面直线": r"异面直线|异面.*所成角",
        "截面": r"截面|截得|截去|截线",
        "几何体": r"几何体|棱锥|棱柱|圆锥|圆柱|正方体|长方体|四面体",
        "球": r"球|外接球|内切球|球心|半径",
        "证明论证": r"证明|求证|论证|说明",
    },
    "物理": {
        "机械能守恒": r"机械能|能量守恒|守恒|重力势能|弹性势能|势能|动能定理|功能关系",
        "弹簧模型": r"弹簧|弹性势能|劲度系数|压缩|伸长|形变量",
        "圆周临界": r"圆周|向心|圆轨道|最高点|最低点|临界|不脱离|脱轨",
        "圆周运动": r"圆周|向心|角速度|周期|频率|半径|圆轨道",
        "平抛运动": r"平抛|抛出|水平.*竖直|轨迹|落点",
        "运动图像": r"图像|图象|v[-－]?t|x[-－]?t|a[-－]?t|斜率|面积",
        "打点计时器": r"打点|纸带|计时器|计数点",
        "验证机械能守恒": r"验证.*机械能|机械能.*实验|重物下落|纸带",
        "动量": r"动量|冲量|碰撞|反冲|爆炸|平均作用力",
        "冲量": r"冲量|作用时间|平均作用力|动量变化",
        "动量守恒": r"动量守恒|碰撞|反冲|爆炸|系统动量",
        "碰撞模型": r"碰撞|弹性碰撞|非弹性|粘连",
        "功能关系": r"功能关系|做功|动能|势能|能量|机械能",
    },
    "化学": {
        "原电池": r"原电池|负极|正极|电极反应|盐桥|放电|电池",
        "电化学": r"电化学|原电池|电解|电极|阴极|阳极|电池|充电|放电",
        "电极反应": r"电极反应|负极|正极|阴极|阳极|得电子|失电子",
        "电池": r"电池|蓄电池|燃料电池|锂|铅|锌|放电|充电",
        "电解": r"电解|阴极|阳极|电解池|电解质",
        "化学反应原理": r"反应速率|平衡|电离|水解|沉淀|溶度积|pH|电化学",
        "反应速率": r"反应速率|速率|活化能|催化剂",
        "化学平衡": r"化学平衡|平衡常数|转化率|勒夏特列|平衡移动",
        "有机": r"有机|烃|醇|醛|羧酸|酯|苯|同分异构|加成|取代|消去",
        "酯": r"酯|乙酸乙酯|水解|酯化",
        "水解": r"水解|酸性水解|碱性水解|盐类水解",
        "实验方案评价": r"实验|装置|方案|操作|检验|验证|探究|变量|对照",
    },
    "生物": {
        "遗传与变异": r"遗传|变异|基因|染色体|等位|显性|隐性|杂交",
        "遗传规律": r"分离定律|自由组合|杂交|基因型|表现型|遗传",
        "基因表达": r"基因表达|转录|翻译|mRNA|tRNA|RNA|蛋白质",
        "表观遗传": r"表观遗传|DNA甲基化|甲基化",
        "DNA": r"DNA|脱氧核糖核酸|碱基",
        "RNA": r"RNA|mRNA|tRNA|rRNA|转录|翻译",
        "染色体": r"染色体|染色单体|同源染色体|减数分裂",
        "减数分裂": r"减数分裂|配子|同源染色体|联会|四分体",
        "单倍体": r"单倍体|花药离体|秋水仙素|加倍",
        "生物技术": r"PCR|电泳|基因工程|限制酶|载体|质粒|发酵|细胞工程",
        "实验设计": r"实验|变量|对照|处理组|自变量|因变量|探究",
    },
    "英语": {
        "应用文写作": r"write|email|letter|notice|proposal|Dear|假设你是|应用文|书面表达",
        "写作情境任务": r"write|email|letter|notice|proposal|Dear|假设你是|写作|书面表达",
        "应用文结构": r"Dear|Yours|letter|email|notice|proposal",
        "阅读理解": r"According to|What|Which|Why|How|passage|paragraph|author|阅读",
        "细节定位": r"According to|What|Which|Where|When|Who|detail|passage",
        "推理判断": r"infer|imply|suggest|probably|Why|How|author",
        "词汇语块": r"meaning|refer to|word|phrase|vocabulary|词义",
        "长难句": r"sentence|grammar|clause|which|that|where|when",
        "语篇衔接": r"paragraph|sentence|blank|七选五|coherence|选项",
    },
    "语文": {
        "现代文阅读": r"材料|文本|阅读|文章|作者|文中|概括|分析",
        "文学类文本": r"小说|散文|人物|情节|环境|叙述|描写|赏析",
        "小说": r"小说|人物|情节|环境|叙述",
        "人物": r"人物|形象|性格|心理|语言|动作",
        "情节": r"情节|铺垫|照应|转折|结尾|开头",
        "文言文阅读": r"文言|实词|虚词|翻译|断句|古人|下列对文中",
        "古诗词鉴赏": r"诗|词|意象|情感|首联|颔联|尾联|鉴赏",
        "整本书阅读": r"红楼梦|乡土中国|整本书|名著",
        "作文": r"作文|写作|不少于|立意|议论文|记叙文",
        "表达效果分析": r"表达效果|赏析|作用|好处|手法|修辞",
    },
}

YEAR_SCORE = {"2026": 16, "2025": 14, "2024": 12, "2023": 10, "2022": 7, "2021": 5, "2020": 4}
DISTRICT_SCORE = {"海淀": 10, "西城": 9, "东城": 8, "朝阳": 7}
DIFFICULTY_SCORE = {"基础": 6, "中档": 10, "综合": 9, "压轴": 5}
PRIORITY_SCORE = {"P0": 12, "P1": 8, "P2": 3}


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


def search_blob(record: dict[str, Any]) -> str:
    fields = [
        record.get("module"),
        record.get("knowledge_tags"),
        record.get("knowledge_point"),
        record.get("model_tags"),
        record.get("ability_tags"),
        record.get("mistake_tags"),
        record.get("snippet"),
        record.get("question_text_machine"),
    ]
    return " ".join(norm_text(x) for x in fields)


def text_blob(record: dict[str, Any]) -> str:
    return " ".join(
        norm_text(x)
        for x in [
            record.get("snippet"),
            record.get("question_text_machine"),
            record.get("source"),
        ]
    )


def keyword_has_text_evidence(subject: str, keyword: str, record: dict[str, Any]) -> bool:
    text = text_blob(record)
    pattern = EVIDENCE_PATTERNS.get(subject, {}).get(keyword)
    if pattern:
        return bool(re.search(pattern, text, re.IGNORECASE))
    return keyword.lower() in text.lower()


def matched_keywords(subject: str, record: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for keyword in CURRENT_PRIORITY_KEYWORDS.get(subject, []):
        if keyword and keyword_has_text_evidence(subject, keyword, record):
            out.append(keyword)
    return out


def risk_flags(record: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    snippet = norm_text(record.get("snippet"))
    fig = norm_text(record.get("figure_required"))
    extract = norm_text(record.get("extract_status"))
    if bool(record.get("placeholder")):
        flags.append("题干占位")
    if len(snippet.strip()) < 45:
        flags.append("题干片段过短")
    if NOISE_RE.search(snippet):
        flags.append("含水印/页脚噪声")
    if norm_text(record.get("ocr_status")) in {"含OCR", "未OCR"}:
        flags.append("OCR文本")
    if fig != "无图":
        flags.append(f"需核图示:{fig}")
    if "偏少" in extract or "未能稳定" in extract or "占位" in extract:
        flags.append(f"切分风险:{extract}")
    if record.get("child_ready") != "是":
        flags.append("未进入孩子可用")
    return flags


def verification_steps(record: dict[str, Any], risks: list[str]) -> list[str]:
    steps = [
        "打开原PDF定位题号和页码",
        "核对题干、选项、设问是否完整",
        "核对答案或评分参考",
    ]
    if any(x.startswith("需核图示") for x in risks):
        steps.insert(2, "截取或重绘题目所需图示/表格/材料")
    if any("水印" in x for x in risks):
        steps.append("清理水印、页脚和下载提示")
    if any("题干占位" in x or "切分风险" in x for x in risks):
        steps.insert(1, "从原PDF重新抽取完整题干")
    steps.append("确认知识点标签只保留核心1-3个")
    return steps


def ai_score(subject: str, record: dict[str, Any], matched: list[str], risks: list[str]) -> int:
    score = 0
    placeholder = bool(record.get("placeholder"))
    snippet = norm_text(record.get("snippet"))
    extract = norm_text(record.get("extract_status"))
    fig = norm_text(record.get("figure_required"))
    if not placeholder:
        score += 28
    else:
        score -= 60
    if extract == "题目级机器切分":
        score += 24
    elif "部分题号占位" in extract:
        score += 8
    elif "偏少" in extract:
        score -= 8
    elif "未能稳定" in extract:
        score -= 18
    if len(snippet) >= 120:
        score += 12
    elif len(snippet) >= 60:
        score += 7
    else:
        score -= 12
    if NOISE_RE.search(snippet):
        score -= 18
    score += YEAR_SCORE.get(norm_text(record.get("year")), 0)
    score += DISTRICT_SCORE.get(norm_text(record.get("district")), 0)
    score += DIFFICULTY_SCORE.get(norm_text(record.get("difficulty")), 0)
    score += PRIORITY_SCORE.get(norm_text(record.get("priority")), 0)
    score += min(len(matched), 4) * 16
    if fig == "无图":
        score += 5
    elif fig in {"原图必带", "表格图像"}:
        score -= 2
    elif fig == "文本材料必带":
        score -= 8
    else:
        score -= 10
    if norm_text(record.get("ocr_status")) == "无需OCR":
        score += 4
    elif norm_text(record.get("ocr_status")) == "含OCR":
        score -= 4
    # Fewer risks means this can be verified faster by the assistant.
    score -= max(0, len(risks) - 2) * 3
    return score


def usability_level(record: dict[str, Any], score: int, risks: list[str]) -> str:
    if bool(record.get("placeholder")):
        return "C-仅作定位线索"
    if "题干片段过短" in risks or any("切分风险" in x for x in risks):
        return "C-仅作定位线索"
    if "含水印/页脚噪声" in risks or "OCR文本" in risks or any(x.startswith("需核图示") for x in risks):
        return "B-可AI核验后使用"
    if score >= 70:
        return "A-优先AI核验"
    return "B-可AI核验后使用"


def ai_next_action(level: str) -> str:
    if level.startswith("A"):
        return "进入近期AI核验候选，出题时优先回PDF核题干和答案"
    if level.startswith("B"):
        return "保留为候选，使用前由AI补图、清洗OCR或核长材料"
    return "暂缓直接使用，只在缺少同类题时由AI回PDF重新抽题"


def load_records(subject: str) -> list[dict[str, Any]]:
    path = ROOT / subject / "题库" / "一模二模题目标签索引.json"
    return json.loads(path.read_text(encoding="utf-8"))


def decorate_record(subject: str, record: dict[str, Any]) -> dict[str, Any]:
    matched = matched_keywords(subject, record)
    risks = risk_flags(record)
    score = ai_score(subject, record, matched, risks)
    level = usability_level(record, score, risks)
    scope = "近期高一下/当前薄弱点优先" if matched else "长期全科储备"
    priority = "高" if level.startswith("A") and matched else ("中" if level.startswith(("A", "B")) else "低")
    return {
        "subject": subject,
        "ai_score": score,
        "ai_usability_level": level,
        "candidate_scope": scope,
        "matched_current_keywords": matched,
        "ai_review_priority": priority,
        "ai_next_action": ai_next_action(level),
        "user_action": "无需家长人工筛选；由AI筛候选并回原PDF核验",
        "risk_flags": risks,
        "verification_steps": verification_steps(record, risks),
        **record,
    }


def csv_value(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(str(x) for x in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for i, rec in enumerate(records, start=1):
            row = {field: csv_value(rec.get(field)) for field in CSV_FIELDS}
            row["rank"] = str(i)
            writer.writerow(row)


def write_json(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def top_table(records: list[dict[str, Any]], limit: int = 20) -> list[str]:
    lines = [
        "| 排名 | 分数 | 等级 | 来源 | 匹配当前知识点 | 风险 | AI动作 |",
        "|---:|---:|---|---|---|---|---|",
    ]
    for idx, rec in enumerate(records[:limit], start=1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(idx),
                    str(rec.get("ai_score", "")),
                    norm_text(rec.get("ai_usability_level")),
                    norm_text(rec.get("source")),
                    norm_text(rec.get("matched_current_keywords")) or "长期储备",
                    norm_text(rec.get("risk_flags")),
                    norm_text(rec.get("ai_next_action")),
                ]
            )
            + " |"
        )
    return lines


def write_subject_md(path: Path, subject: str, records: list[dict[str, Any]]) -> None:
    level_count = Counter(norm_text(r.get("ai_usability_level")) for r in records)
    matched_count = sum(1 for r in records if r.get("matched_current_keywords"))
    high_count = sum(1 for r in records if r.get("ai_review_priority") == "高")
    lines = [
        f"# {subject}一模二模AI筛题核验队列",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 结论",
        "",
        "- 本文件不是给孩子的题单，是 AI 筛题和核验队列。",
        "- 家长无需人工筛选题目；后续由 AI 先筛候选，再回原 PDF 核题干、图示/材料和答案。",
        "- `A-优先AI核验` 和 `B-可AI核验后使用` 仍不是 `child_ready=是`，正式输出前必须完成核验。",
        "",
        "## 统计",
        "",
        f"- 总记录：{len(records)}",
        f"- 匹配近期薄弱点/当前学习线索：{matched_count}",
        f"- 高优先AI核验：{high_count}",
        f"- A级：{level_count.get('A-优先AI核验', 0)}",
        f"- B级：{level_count.get('B-可AI核验后使用', 0)}",
        f"- C级：{level_count.get('C-仅作定位线索', 0)}",
        "",
        "## 近期优先候选",
        "",
    ]
    near = [r for r in records if r.get("matched_current_keywords")]
    lines.extend(top_table(near or records, 30))
    lines.append("")
    lines.append("## 使用规则")
    lines.append("")
    lines.append("1. 周报或学生版需要出题时，AI 从本队列按知识点筛 5-10 道候选。")
    lines.append("2. AI 只核最终要用的 3-5 道：题干、图示/材料、答案、核心知识点。")
    lines.append("3. 核验完成前，不得直接给孩子。")
    lines.append("4. C级题只作定位线索，不直接输出。")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_global_md(path: Path, by_subject: dict[str, list[dict[str, Any]]], all_records: list[dict[str, Any]]) -> None:
    lines = [
        "# 全科一模二模AI筛题核验队列",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 总结",
        "",
        "这一步的目标是把家长从人工筛题中拿出来。后续由 AI 负责：按知识点筛候选、回原 PDF 核题干、核图示/材料、核答案，再把少量可靠题放进周报或学生打印版。",
        "",
        "机器初标仍不能直接给孩子；本队列只是把题库变成可执行的 AI 工作台。",
        "",
        "## 全科统计",
        "",
        "| 科目 | 总记录 | A优先AI核验 | B可AI核验 | C仅定位 | 匹配近期薄弱点 | 高优先AI核验 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for subject in SUBJECTS:
        records = by_subject[subject]
        level_count = Counter(norm_text(r.get("ai_usability_level")) for r in records)
        matched_count = sum(1 for r in records if r.get("matched_current_keywords"))
        high_count = sum(1 for r in records if r.get("ai_review_priority") == "高")
        lines.append(
            f"| {subject} | {len(records)} | {level_count.get('A-优先AI核验', 0)} | "
            f"{level_count.get('B-可AI核验后使用', 0)} | {level_count.get('C-仅作定位线索', 0)} | "
            f"{matched_count} | {high_count} |"
        )
    lines.extend(
        [
            "",
            "## 近期全科优先队列",
            "",
        ]
    )
    near = [r for r in all_records if r.get("matched_current_keywords")]
    lines.extend(top_table(near[:80], 80))
    lines.extend(
        [
            "",
            "## 执行口径",
            "",
            "- 家长不需要人工筛选题号。",
            "- AI 负责从队列中选题，并回原 PDF 做最终核验。",
            "- 任何题进入孩子版前，都必须带原题题干；有图示/材料时必须带完整图示/材料。",
            "- `A/B/C` 是核验工作优先级，不是孩子可直接使用状态。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    global ROOT
    configure_stdio()
    parser = argparse.ArgumentParser(description="生成全科一模二模 AI 筛题核验队列")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="学习资料库根目录，默认当前目录")
    args = parser.parse_args()
    ROOT = args.root.resolve()
    all_records: list[dict[str, Any]] = []
    by_subject: dict[str, list[dict[str, Any]]] = {}
    for subject in SUBJECTS:
        records = [decorate_record(subject, r) for r in load_records(subject)]
        records.sort(
            key=lambda r: (
                0 if r.get("matched_current_keywords") else 1,
                {"A-优先AI核验": 0, "B-可AI核验后使用": 1, "C-仅作定位线索": 2}.get(
                    norm_text(r.get("ai_usability_level")), 9
                ),
                -int(r.get("ai_score") or 0),
                -int(r.get("year") or 0),
            )
        )
        by_subject[subject] = records
        all_records.extend(records)
        subject_dir = ROOT / subject / "题库"
        write_json(subject_dir / "一模二模AI筛题核验队列.json", records)
        write_csv(subject_dir / "一模二模AI筛题核验队列.csv", records)
        write_subject_md(subject_dir / "一模二模AI筛题核验队列.md", subject, records)

    all_records.sort(
        key=lambda r: (
            0 if r.get("matched_current_keywords") else 1,
            {"A-优先AI核验": 0, "B-可AI核验后使用": 1, "C-仅作定位线索": 2}.get(
                norm_text(r.get("ai_usability_level")), 9
            ),
            -int(r.get("ai_score") or 0),
            SUBJECTS.index(norm_text(r.get("subject"))) if norm_text(r.get("subject")) in SUBJECTS else 99,
        )
    )
    out_dir = ROOT / "题库总控"
    write_json(out_dir / "全科一模二模AI筛题核验队列.json", all_records)
    write_csv(out_dir / "全科一模二模AI筛题核验队列.csv", all_records)
    write_global_md(out_dir / "全科一模二模AI筛题核验队列.md", by_subject, all_records)
    print(f"created {out_dir / '全科一模二模AI筛题核验队列.md'}")


if __name__ == "__main__":
    main()
