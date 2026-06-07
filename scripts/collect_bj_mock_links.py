from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


ROOT = Path.cwd()
OUT = ROOT / "临时文件" / "全科一模二模链接采集"
SUBJECTS = ["数学", "语文", "英语", "化学", "生物", "物理"]
DISTRICTS = ["海淀", "西城", "东城", "朝阳"]
EXAM_TYPES = ["一模", "二模"]
YEARS = ["2020", "2021", "2022", "2023", "2024", "2025"]

SOURCE_PAGES = [
    "https://www.gaokzx.com/gk/shitiku/136325.html",
    "https://www.gaokzx.com/gk/shitiku/138765.html",
    "https://www.gaokzx.com/c/202202/58924.html",
    "https://www.gaokzx.com/c/202204/60482.html",
    "https://www.gaokzx.com/c/202102/49641.html",
    "https://www.gaokzx.com/c/202104/50765.html",
    "https://www.gaokzx.com/c/202005/43346.html",
    "https://www.gaokzx.com/c/202005/43340.html",
]


@dataclass
class LinkRecord:
    source_page: str
    text: str
    url: str
    year: str | None
    district: str | None
    exam_type: str | None
    subject: str | None
    is_pdf_hint: bool


def infer(text: str, url: str):
    blob = f"{text} {url}"
    year = next((x for x in YEARS if x in blob), None)
    district = next((x for x in DISTRICTS if x in blob), None)
    exam_type = next((x for x in EXAM_TYPES if x in blob), None)
    subject = next((x for x in SUBJECTS if x in blob), None)
    is_pdf = ".pdf" in url.lower() or "pdf" in text.lower()
    return year, district, exam_type, subject, is_pdf


def fetch(url: str) -> str:
    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def configure_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def collect():
    OUT.mkdir(parents=True, exist_ok=True)
    records: list[LinkRecord] = []
    for page in SOURCE_PAGES:
        html = fetch(page)
        (OUT / (re.sub(r"[^0-9A-Za-z]+", "_", page) + ".html")).write_text(html, encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a"):
            href = a.get("href")
            if not href:
                continue
            text = " ".join(a.get_text(" ", strip=True).split())
            full = urljoin(page, href)
            blob = f"{text} {full}"
            if not any(x in blob for x in DISTRICTS):
                continue
            if not any(x in blob for x in SUBJECTS):
                continue
            if not any(x in blob for x in EXAM_TYPES):
                continue
            year, district, exam_type, subject, is_pdf = infer(text, full)
            records.append(LinkRecord(page, text, full, year, district, exam_type, subject, is_pdf))
    return records


def main():
    global ROOT, OUT
    configure_stdio()
    parser = argparse.ArgumentParser(description="采集北京一模二模候选链接")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="学习资料库根目录，默认当前目录")
    args = parser.parse_args()
    ROOT = args.root.resolve()
    OUT = ROOT / "临时文件" / "全科一模二模链接采集"
    records = collect()
    json_path = OUT / "mock_link_candidates.json"
    json_path.write_text(json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# 全科一模二模链接候选", "", f"- 候选链接数：{len(records)}", ""]
    md += ["| 年份 | 区域 | 类型 | 科目 | PDF提示 | 链接文字 | URL | 来源页 |", "|---|---|---|---|---|---|---|---|"]
    for r in records:
        md.append(f"| {r.year or ''} | {r.district or ''} | {r.exam_type or ''} | {r.subject or ''} | {'是' if r.is_pdf_hint else '否'} | {r.text} | {r.url} | {r.source_page} |")
    md_path = OUT / "mock_link_candidates.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(json_path)
    print(md_path)
    print("records", len(records))


if __name__ == "__main__":
    main()
