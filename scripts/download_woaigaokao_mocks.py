from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path

import requests


ROOT = Path.cwd()
SUBJECTS = ["数学", "语文", "英语", "化学", "生物"]
DISTRICTS = ["海淀", "西城", "东城", "朝阳"]
EXAM_TYPES = ["一模", "二模"]


@dataclass
class DownloadRecord:
    year: int
    district: str
    exam_type: str
    subject: str
    url: str
    file: str
    status: str
    size: int
    note: str


def candidate_urls(year: int, filename: str):
    encoded = urllib.parse.quote(filename)
    months = ["11", "10", "09", "08", "07", "06", "05", "04", "03", "02"]
    for month in months:
        yield f"https://www.woaigaokao.com/wp-content/uploads/{year}/{month}/{encoded}"


def try_download(year: int, district: str, exam_type: str, subject: str) -> DownloadRecord:
    filename = f"{year}北京{district}高三{exam_type}{subject}试题及答案.pdf"
    target = ROOT / subject / "北京一模二模真题" / str(year) / district / exam_type / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 1000:
        with target.open("rb") as f:
            if f.read(4) == b"%PDF":
                return DownloadRecord(year, district, exam_type, subject, "", str(target), "已存在", target.stat().st_size, "")

    for url in candidate_urls(year, filename):
        try:
            r = requests.get(url, timeout=(10, 60), headers={"User-Agent": "Mozilla/5.0"}, stream=True)
        except Exception as e:
            last = str(e)
            continue
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or "pdf" not in ctype.lower():
            last = f"HTTP {r.status_code} {ctype}"
            time.sleep(0.05)
            continue
        tmp = target.with_suffix(".download")
        size = 0
        first = b""
        try:
            with tmp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 128):
                    if not chunk:
                        continue
                    if not first:
                        first = chunk[:4]
                    f.write(chunk)
                    size += len(chunk)
        except Exception as e:
            if tmp.exists():
                tmp.unlink()
            last = str(e)
            continue
        if first != b"%PDF":
            if tmp.exists():
                tmp.unlink()
            last = "非PDF文件头"
            continue
        tmp.replace(target)
        return DownloadRecord(year, district, exam_type, subject, url, str(target), "已下载", size, "")
    return DownloadRecord(year, district, exam_type, subject, "", str(target), "待补", 0, last if "last" in locals() else "无候选")


def configure_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main():
    global ROOT
    configure_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="学习资料库根目录，默认当前目录")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--subjects", default=",".join(SUBJECTS))
    args = parser.parse_args()
    ROOT = args.root.resolve()

    subjects = [x for x in args.subjects.split(",") if x]
    records = []
    for subject in subjects:
        for district in DISTRICTS:
            for exam_type in EXAM_TYPES:
                rec = try_download(args.year, district, exam_type, subject)
                records.append(rec)
                print(rec.year, rec.subject, rec.district, rec.exam_type, rec.status, rec.size)
                time.sleep(0.08)

    out = ROOT / "临时文件" / "全科一模二模链接采集" / f"woaigaokao-download-{args.year}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2), encoding="utf-8")

    md = [f"# woaigaokao 下载记录 {args.year}", "", "| 科目 | 区域 | 类型 | 状态 | 大小 | 文件 | URL | 备注 |", "|---|---|---|---|---:|---|---|---|"]
    for r in records:
        md.append(f"| {r.subject} | {r.district} | {r.exam_type} | {r.status} | {r.size} | `{r.file}` | {r.url} | {r.note} |")
    out.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
