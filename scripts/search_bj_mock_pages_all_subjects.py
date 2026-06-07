from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup


ROOT = Path.cwd()
OUT = ROOT / "临时文件" / "全科一模二模链接采集"
SUBJECTS = ["数学", "语文", "英语", "化学", "生物"]
DISTRICTS = ["海淀", "西城", "东城", "朝阳"]
EXAM_TYPES = ["一模", "二模"]
YEARS = [2020, 2021, 2022, 2023, 2024, 2025]


@dataclass
class SearchRecord:
    year: int
    district: str
    exam_type: str
    subject: str
    query: str
    title: str
    url: str
    score: int


def fetch(url: str) -> str:
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def configure_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def score_result(title: str, url: str, year: int, district: str, exam_type: str, subject: str) -> int:
    blob = f"{title} {url}"
    score = 0
    for token, weight in [(str(year), 4), (district, 4), (exam_type, 4), (subject, 5), ("高三", 2), ("试题", 2), ("答案", 1)]:
        if token in blob:
            score += weight
    if "高三" in blob and "高一" not in blob and "高二" not in blob:
        score += 1
    if "中考" in blob or "初三" in blob:
        score -= 10
    return score


def parse_search(html: str, base: str, year: int, district: str, exam_type: str, subject: str, query: str):
    soup = BeautifulSoup(html, "html.parser")
    records = []
    seen = set()
    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        url = urljoin(base, href)
        if "gaokzx.com" not in url:
            continue
        text = " ".join(a.get_text(" ", strip=True).split())
        if not text or len(text) < 8:
            continue
        blob = f"{text} {url}"
        if subject not in blob or district not in blob or exam_type not in blob:
            continue
        if str(year) not in blob and f"{year}年" not in blob:
            continue
        key = (text, url)
        if key in seen:
            continue
        seen.add(key)
        score = score_result(text, url, year, district, exam_type, subject)
        if score >= 12:
            records.append(SearchRecord(year, district, exam_type, subject, query, text, url, score))
    records.sort(key=lambda r: r.score, reverse=True)
    return records


def main():
    global ROOT, OUT
    configure_stdio()
    parser = argparse.ArgumentParser(description="站内搜索北京一模二模候选页面")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="学习资料库根目录，默认当前目录")
    args = parser.parse_args()
    ROOT = args.root.resolve()
    OUT = ROOT / "临时文件" / "全科一模二模链接采集"
    OUT.mkdir(parents=True, exist_ok=True)
    all_records = []
    for year in YEARS:
        for district in DISTRICTS:
            for exam_type in EXAM_TYPES:
                for subject in SUBJECTS:
                    query = f"{year}北京{district}高三{exam_type}{subject}试题及答案"
                    url = "https://www.gaokzx.com/search?keyword=" + quote(query)
                    try:
                        html = fetch(url)
                    except Exception as e:
                        print("fetch failed", query, e)
                        continue
                    records = parse_search(html, url, year, district, exam_type, subject, query)
                    all_records.extend(records[:3])
                    print(query, "=>", len(records), records[0].url if records else "")
                    time.sleep(0.12)

    json_path = OUT / "site_search_page_candidates.json"
    json_path.write_text(json.dumps([asdict(r) for r in all_records], ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# 站内搜索页面候选", "", f"- 候选记录：{len(all_records)}", ""]
    md += ["| 年份 | 区域 | 类型 | 科目 | 分数 | 标题 | URL |", "|---|---|---|---|---:|---|---|"]
    for r in all_records:
        md.append(f"| {r.year} | {r.district} | {r.exam_type} | {r.subject} | {r.score} | {r.title} | {r.url} |")
    md_path = OUT / "site_search_page_candidates.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(json_path)
    print(md_path)
    print("records", len(all_records))


if __name__ == "__main__":
    main()
