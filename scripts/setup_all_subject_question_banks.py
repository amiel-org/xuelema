import argparse
import sys
from pathlib import Path
import csv
import json


ROOT = Path.cwd()
SUBJECTS = {
    "数学": {
        "modules": ["集合与常用逻辑", "函数与导数", "三角函数", "平面向量", "数列", "立体几何", "解析几何", "概率统计", "复数", "不等式", "新定义与综合"],
        "models": ["函数图像与性质", "导数单调极值", "三角恒等变换", "数列递推与求和", "空间线面关系", "圆锥曲线综合", "概率统计图表", "新定义阅读"],
        "skills": ["条件翻译", "图像识别", "运算表达", "分类讨论", "证明论证", "建模应用"],
        "mistakes": ["模型识别不足", "条件遗漏", "图像理解偏差", "运算失误", "证明步骤跳跃", "分类不全"],
    },
    "语文": {
        "modules": ["现代文阅读", "文言文阅读", "古诗词鉴赏", "名句默写", "语言文字运用", "作文", "整本书阅读"],
        "models": ["论述类文本", "文学类文本", "实用类文本", "文言实词虚词", "诗歌意象情感", "作文立意结构"],
        "skills": ["信息筛选", "概括归纳", "文本细读", "表达效果分析", "审题立意", "论证结构"],
        "mistakes": ["答非所问", "只复述不分析", "术语空泛", "文本依据不足", "结构松散", "审题偏差"],
    },
    "英语": {
        "modules": ["听力", "完形填空", "阅读理解", "七选五", "语法填空", "应用文写作", "读后续写", "词汇语块"],
        "models": ["主旨大意", "细节定位", "推理判断", "词义猜测", "篇章结构", "语法填空考点", "写作情境任务"],
        "skills": ["定位检索", "上下文推断", "长难句分析", "语篇衔接", "表达准确性", "写作结构"],
        "mistakes": ["定位错误", "过度推断", "词汇障碍", "语法搭配错误", "漏看限定条件", "写作不贴任务"],
    },
    "物理": {
        "modules": ["运动学", "相互作用", "牛顿运动定律", "曲线运动", "机械能", "动量", "电场", "电路", "磁场", "电磁感应", "实验"],
        "models": ["受力分析", "运动过程分段", "机械能守恒", "动量守恒", "圆周运动", "图像分析", "实验误差", "电路动态", "带电粒子运动"],
        "skills": ["对象选择", "方向规定", "过程划分", "图像读取", "方程联立", "单位检验", "实验评价"],
        "mistakes": ["系统对象不清", "方向正负混乱", "守恒条件误判", "图像斜率面积误读", "实验误差方向不明", "公式套用"],
    },
    "化学": {
        "modules": ["物质结构", "元素化合物", "化学反应原理", "电化学", "化学平衡", "有机化学", "实验探究", "工业流程"],
        "models": ["离子反应", "氧化还原", "电池与电解", "平衡移动", "滴定计算", "有机推断", "实验方案评价", "流程图分析"],
        "skills": ["信息提取", "方程式书写", "图表分析", "变量控制", "证据推理", "计算表达"],
        "mistakes": ["方程式不配平", "条件漏写", "守恒关系不清", "实验目的不明", "图表信息漏读", "概念混淆"],
    },
    "生物": {
        "modules": ["细胞结构与代谢", "遗传与变异", "稳态与调节", "生态系统", "生物技术与工程", "实验探究"],
        "models": ["光合作用呼吸作用", "遗传图谱与概率", "神经体液免疫调节", "种群群落生态", "实验变量控制", "图表数据分析"],
        "skills": ["图表读取", "实验设计", "变量控制", "证据推理", "概念辨析", "文字表达"],
        "mistakes": ["变量不清", "图像趋势误读", "遗传概率漏情况", "术语不准确", "因果关系写反", "实验结论过度"],
    },
}
YEARS = list(range(2020, 2026))
DISTRICTS = ["海淀", "西城", "东城", "朝阳"]
EXAM_TYPES = ["一模", "二模"]


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def configure_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def collection_table(subject: str) -> str:
    lines = [
        f"# 北京{subject}一模二模收集清单 2020-2025",
        "",
        "## 收集目标",
        "",
        f"按物理试点同款范围补齐：海淀、西城、东城、朝阳；2020-2025；高三一模、二模；科目：{subject}。",
        "",
        "## 文件归档位置",
        "",
        f"`{subject}\\北京一模二模真题\\年份\\区域\\考试类型\\`",
        "",
        "## 收集状态总表",
        "",
        "| 年份 | 海淀一模 | 海淀二模 | 西城一模 | 西城二模 | 东城一模 | 东城二模 | 朝阳一模 | 朝阳二模 | 完成 |",
        "|---|---|---|---|---|---|---|---|---|---:|",
    ]
    for year in YEARS:
        lines.append(f"| {year} | 待补 | 待补 | 待补 | 待补 | 待补 | 待补 | 待补 | 待补 | 0/8 |")
    lines += [
        "",
        "## 待补缺口",
        "",
        "| 年份 | 区域 | 类型 | 状态 | 备注 |",
        "|---|---|---|---|---|",
    ]
    for year in YEARS:
        for district in DISTRICTS:
            for exam_type in EXAM_TYPES:
                lines.append(f"| {year} | {district} | {exam_type} | 待补 | 尚未下载核验 |")
    lines += [
        "",
        "## 入库流程",
        "",
        "1. 下载或放入真实 PDF，先做文件头校验，避免网页伪装 PDF。",
        "2. 提取文本；图表、实验装置、几何图、结构图等不可只靠 OCR，要保留或重画图示。",
        "3. 生成试卷级索引，再生成题目级标签索引。",
        "4. 周汇总引用前必须打开原 PDF 核对题干、图像和答案。",
    ]
    return "\n".join(lines)


def tag_system(subject: str, cfg: dict) -> str:
    rows = "\n".join(f"| {x} | 待细化 |" for x in cfg["modules"])
    model_rows = "\n".join(f"| {x} | 北京卷/区统考常见题型 |" for x in cfg["models"])
    skill_rows = "\n".join(f"| {x} | 题目主要考查能力 |" for x in cfg["skills"])
    mistake_rows = "\n".join(f"| {x} | 孩子常见失误或周总结可追踪错因 |" for x in cfg["mistakes"])
    return f"""# {subject}知识点标签体系

## 用途

本文件规定{subject}题库统一标签。后续高考真题、一模、二模、校内试卷、作业错题都按同一套标签入库，方便周总结按知识点、题型模型、错因和难度检索。

## 标签字段

| 字段 | 说明 |
|---|---|
| 一级模块 | 学科大模块 |
| 二级知识点 | 可复习的具体知识点 |
| 题型模型 | 北京卷或区统考常见命题模型 |
| 能力标签 | 题目主要考查的能力 |
| 错因标签 | 孩子容易出错的原因 |
| 难度 | 基础 / 中档 / 综合 / 压轴 |
| 适用阶段 | 高一 / 高二 / 高三 / 跨阶段 |
| 周总结用途 | 笔记巩固 / 错因修复 / 高考拓展 / 专题训练 |
| 图示要求 | 无图 / 原图必带 / 需重画 / 表格图像 |
| 校对状态 | 机器初标 / 已核对题干 / 已核对图示 / 已核对答案 |

## 一级模块

| 标签 | 说明 |
|---|---|
{rows}

## 题型模型

| 标签 | 说明 |
|---|---|
{model_rows}

## 能力标签

| 标签 | 说明 |
|---|---|
{skill_rows}

## 错因标签

| 标签 | 说明 |
|---|---|
{mistake_rows}

## 输出要求

- 周汇总不缩减原有内容，只在原内容后增补北京卷拓展和针对题。
- 引用真题或一模二模题，不能只写题号，必须补原题题干；有图、表、实验装置、文本材料或结构示意的必须带完整图示。
- 机器初标只用于筛题，正式给孩子前必须核对原卷。
"""


def weekly_rules(subject: str) -> str:
    return f"""# {subject}周总结调用题库规则

## 目标

每次{subject}周总结都从三项资料出发：

1. 笔记：本周新学了什么。
2. 试卷：本周在哪些题型上丢分。
3. 作业：日常练习中哪些错误反复出现。

然后从本地题库中补充北京卷必考点和 3-5 道针对性练习。

## 周总结新增栏目

```text
## 北京卷必考点拓展

| 本周材料来源 | 对应知识点 | 北京卷常见考法 | 孩子当前风险 | 推荐题 |
|---|---|---|---|---|

## 本周针对性练习

1. 笔记巩固题：
2. 错因修复题：
3. 北京高考真题：
4. 北京一模/二模题：
5. 综合提升题（可选）：

## 本周出现过但本版不重点展开

| 知识点 | 来源 | 本版处理 | 后续动作 |
|---|---|---|---|
```

## 统一规则

1. 不缩减原周汇总内容，只增补题库拓展。
2. 真题和一模二模题必须带原题题干；有图示、表格、材料、实验装置、几何图、结构图时必须带完整对应图示。
3. 一模二模机器标签只用于筛候选题，正式打印前必须打开原 PDF 核对。
4. 每周默认 3-5 题，优先解决本周最集中的 2-4 个问题。

## 索引入口

| 文件 | 用法 |
|---|---|
| `一模二模题目标签索引.csv` | 用 Excel 按知识点、区域、年份、优先级筛题 |
| `一模二模题目标签索引.json` | 用脚本按标签检索 |
| `北京{subject}一模二模知识点索引.md` | 人工快速浏览某知识点有哪些题 |
| `北京{subject}一模二模试卷级索引.md` | 查看哪份卷子可文本索引，哪份需 OCR |
"""


def readme(subject: str) -> str:
    return f"""# {subject}题库

## 目标

按物理试点同款结构建设{subject}题库，用于周汇总、月复盘、错题复盘和针对性练习。

## 当前入口

| 文件 | 用途 | 状态 |
|---|---|---|
| `北京{subject}一模二模收集清单-2020-2025.md` | 东西海朝 2020-2025 一模二模下载与缺口 | 已建骨架 |
| `{subject}知识点标签体系.md` | 统一知识点、题型、能力、错因标签 | 已建初版 |
| `周总结调用规则.md` | 周汇总如何调用题库 | 已建初版 |
| `北京{subject}一模二模试卷级索引.md` | 试卷级索引 | 待下载后生成 |
| `北京{subject}一模二模知识点索引.md` | 知识点索引 | 待题目标注后生成 |
| `一模二模题目标签索引.csv` | 题目级表格索引 | 待生成 |
| `一模二模题目标签索引.json` | 题目级结构化索引 | 待生成 |

## 本地资料目录

- 高考北京卷：`{subject}\\高考北京卷真题`
- 一模二模：`{subject}\\北京一模二模真题`

## 输出纪律

- 后续各科周汇总只增补，不缩减原有内容。
- 题目不能只列题号，必须带原题和必要图示。
- 有图表、材料、实验、结构示意、几何图、流程图的题，正式给孩子前必须保留原图或重画清晰图。
"""


def create_subject(subject: str, cfg: dict):
    qbank = ROOT / subject / "题库"
    raw = ROOT / subject / "北京一模二模真题"
    gaokao = ROOT / subject / "高考北京卷真题"
    qbank.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    gaokao.mkdir(parents=True, exist_ok=True)
    for year in YEARS:
        for district in DISTRICTS:
            for exam_type in EXAM_TYPES:
                (raw / str(year) / district / exam_type).mkdir(parents=True, exist_ok=True)
    (raw / "_extracted_text").mkdir(exist_ok=True)
    (raw / "_extracted_text_fitz").mkdir(exist_ok=True)
    (qbank / "真题图示" / "高考北京卷").mkdir(parents=True, exist_ok=True)
    (qbank / "真题图示" / "一模二模").mkdir(parents=True, exist_ok=True)

    write(qbank / "README.md", readme(subject))
    write(qbank / f"北京{subject}一模二模收集清单-2020-2025.md", collection_table(subject))
    write(qbank / f"{subject}知识点标签体系.md", tag_system(subject, cfg))
    write(qbank / "周总结调用规则.md", weekly_rules(subject))
    write(qbank / f"北京{subject}一模二模试卷级索引.md", f"# 北京{subject}一模二模试卷级索引\n\n待下载 PDF 后生成。\n")
    write(qbank / f"北京{subject}一模二模知识点索引.md", f"# 北京{subject}一模二模知识点索引\n\n待题目级标签生成后更新。\n")
    write(qbank / "一模二模OCR与人工校对清单.md", f"# {subject}一模二模 OCR 与人工校对清单\n\n待文本抽取后生成。\n")
    with (qbank / "一模二模题目标签索引.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "year", "district", "exam_type", "question_no", "module", "knowledge_point", "model", "skills", "mistake_tags", "difficulty", "stage", "usage", "figure_required", "verify_status", "pdf_path"])
    write(qbank / "一模二模题目标签索引.json", json.dumps([], ensure_ascii=False, indent=2))
    write(qbank / "一模二模AI筛题核验队列.md", f"# {subject}一模二模 AI 筛题核验队列\n\n待题目标签生成后更新。\n")
    write(qbank / "一模二模AI筛题核验队列.json", json.dumps([], ensure_ascii=False, indent=2))
    with (qbank / "一模二模AI筛题核验队列.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "rank", "ai_score", "ai_usability_level", "source", "knowledge_tags", "risk_flags"])


def main():
    global ROOT
    configure_stdio()
    parser = argparse.ArgumentParser(description="初始化 xuelema 六科题库骨架")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="学习资料库根目录，默认当前目录")
    args = parser.parse_args()
    ROOT = args.root.resolve()
    (ROOT / "题库总控").mkdir(parents=True, exist_ok=True)
    for subject, cfg in SUBJECTS.items():
        create_subject(subject, cfg)
    print("root", ROOT)
    print("created", ", ".join(SUBJECTS))


if __name__ == "__main__":
    main()
