from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin

import fitz
import requests
from bs4 import BeautifulSoup


ROOT = Path.cwd()
WORK = ROOT / "tmp" / "全科一模二模链接采集"
DETAIL_CACHE = WORK / "detail_pages"

SUBJECTS = ["语文", "数学", "英语", "物理", "化学", "生物"]
DISTRICTS = ["海淀", "西城", "东城", "朝阳"]
EXAM_TYPES = ["一模", "二模"]
YEARS = list(range(2020, 2027))

AGGREGATE_URLS = [
    "https://www.gaokzx.com/gk/shitiku/153215.html",
    "https://www.gaokzx.com/gk/shitiku/154590.html",
    "https://www.gaokzx.com/gk/shitiku/136325.html",
    "https://www.gaokzx.com/gk/shitiku/138765.html",
    "https://www.gaokzx.com/c/202202/58924.html",
    "https://www.gaokzx.com/c/202204/60482.html",
    "https://www.gaokzx.com/c/202102/49641.html",
    "https://www.gaokzx.com/c/202104/50765.html",
    "https://www.gaokzx.com/c/202005/43346.html",
    "https://www.gaokzx.com/c/202005/43340.html",
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


@dataclass
class Candidate:
    year: int
    subject: str
    district: str
    exam_type: str
    source_page: str
    detail_page: str
    link_text: str
    title: str
    rank: int


@dataclass
class DownloadRecord:
    year: int
    subject: str
    district: str
    exam_type: str
    status: str
    size: int
    file: str
    source_page: str
    detail_page: str
    pdf_urls: list[str]
    head: str
    note: str


def safe_name(url: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", url).strip("_") + ".html"


def aggregate_pages() -> dict[str, Path]:
    return {url: WORK / safe_name(url) for url in AGGREGATE_URLS}


def fetch_text(url: str, cache_path: Path | None = None, refresh: bool = False) -> str:
    if cache_path and cache_path.exists() and not refresh:
        return cache_path.read_text(encoding="utf-8", errors="ignore")
    r = requests.get(url, timeout=(12, 45), headers={"User-Agent": UA})
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    text = r.text
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
    return text


def norm_district(text: str) -> str | None:
    text = text.replace("区", "")
    for district in DISTRICTS:
        if district in text:
            return district
    return None


def norm_subject(text: str) -> str | None:
    if any(x in text for x in ["查漏", "反馈", "拓展", "试卷分析", "备考策略", "排名"]):
        return None
    for subject in SUBJECTS:
        if subject in text:
            return subject
    return None


def infer_exam_type(source_url: str, title: str) -> str | None:
    blob = source_url + " " + title
    if "二模" in blob:
        return "二模"
    if "一模" in blob:
        return "一模"
    return None


def cell_payload(cell: Any) -> dict[str, Any]:
    links = []
    for a in cell.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        links.append(
            {
                "href": href,
                "text": " ".join(a.get_text(" ", strip=True).split()),
                "title": a.get("title", ""),
                "rel": " ".join(a.get("rel", [])) if isinstance(a.get("rel"), list) else (a.get("rel") or ""),
            }
        )
    return {
        "text": " ".join(cell.get_text(" ", strip=True).split()),
        "links": links,
        "rowspan": int(cell.get("rowspan", 1) or 1),
        "colspan": int(cell.get("colspan", 1) or 1),
    }


def expand_table(table: Any) -> list[list[dict[str, Any] | None]]:
    rows: list[list[dict[str, Any] | None]] = []
    spans: dict[int, tuple[int, dict[str, Any]]] = {}
    for tr in table.find_all("tr"):
        row: list[dict[str, Any] | None] = []
        col = 0
        cells = tr.find_all(["td", "th"])
        for raw in cells:
            while col in spans:
                remaining, payload = spans[col]
                row.append(payload)
                if remaining <= 1:
                    del spans[col]
                else:
                    spans[col] = (remaining - 1, payload)
                col += 1
            payload = cell_payload(raw)
            colspan = payload["colspan"]
            rowspan = payload["rowspan"]
            for offset in range(colspan):
                row.append(payload)
                if rowspan > 1:
                    spans[col + offset] = (rowspan - 1, payload)
            col += colspan
        while col in spans:
            remaining, payload = spans[col]
            row.append(payload)
            if remaining <= 1:
                del spans[col]
            else:
                spans[col] = (remaining - 1, payload)
            col += 1
        if row:
            rows.append(row)
    return rows


def find_header(rows: list[list[dict[str, Any] | None]]) -> tuple[int, dict[int, int]] | None:
    for idx, row in enumerate(rows):
        year_cols: dict[int, int] = {}
        has_subject = False
        has_area = False
        for col, cell in enumerate(row):
            text = cell["text"] if cell else ""
            if "科目" in text:
                has_subject = True
            if "区域" in text or "城区" in text:
                has_area = True
            for m in re.finditer(r"20\d{2}", text):
                year = int(m.group(0))
                if year in YEARS:
                    year_cols[col] = year
        if has_subject and has_area and year_cols:
            return idx, year_cols
    return None


def extract_candidates_from_table(source_url: str, html_text: str) -> list[Candidate]:
    soup = BeautifulSoup(html_text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    exam_type = infer_exam_type(source_url, title)
    if not exam_type:
        return []

    records: list[Candidate] = []
    for table in soup.find_all("table"):
        rows = expand_table(table)
        header = find_header(rows)
        if not header:
            continue
        header_idx, year_cols = header
        for row in rows[header_idx + 1 :]:
            texts = [cell["text"] if cell else "" for cell in row]
            district = next((norm_district(t) for t in texts if norm_district(t)), None)
            subject = next((norm_subject(t) for t in texts if norm_subject(t)), None)
            if not district or not subject:
                continue
            for col, year in year_cols.items():
                if year not in YEARS or col >= len(row):
                    continue
                cell = row[col]
                if not cell or not cell["links"]:
                    continue
                for rank, link in enumerate(cell["links"]):
                    href = urljoin(source_url, link["href"])
                    link_text = link["text"] or cell["text"]
                    link_title = link["title"]
                    blob = f"{link_text} {link_title} {href}"
                    if any(x in blob for x in ["查漏", "反馈", "拓展", "试卷分析", "排名"]):
                        continue
                    records.append(
                        Candidate(
                            year=year,
                            subject=subject,
                            district=district,
                            exam_type=exam_type,
                            source_page=source_url,
                            detail_page=href,
                            link_text=link_text,
                            title=link_title,
                            rank=rank,
                        )
                    )
    return records


def collect_candidates(refresh: bool = False) -> list[Candidate]:
    all_records: list[Candidate] = []
    for url, cache in aggregate_pages().items():
        try:
            text = fetch_text(url, cache, refresh=refresh)
        except Exception as exc:
            print(f"[aggregate failed] {url} {exc}")
            continue
        all_records.extend(extract_candidates_from_table(url, text))

    best: dict[tuple[int, str, str, str, str], Candidate] = {}
    for rec in all_records:
        key = (rec.year, rec.subject, rec.district, rec.exam_type, rec.detail_page)
        old = best.get(key)
        if old is None or rec.rank < old.rank:
            best[key] = rec
    deduped = sorted(best.values(), key=lambda r: (r.year, r.subject, r.district, r.exam_type, r.detail_page))

    out = WORK / "gaokzx_all_subject_target_pages.json"
    out.write_text(json.dumps([asdict(r) for r in deduped], ensure_ascii=False, indent=2), encoding="utf-8")
    return deduped


def extract_pdf_urls(text: str, base_url: str) -> list[str]:
    text = html.unescape(text)
    text = text.replace("\\u002F", "/").replace("\\/", "/")
    urls: list[str] = []

    for href in re.findall(r'https?://[^"\'<>\s]+?\.pdf(?:\?[^"\'<>\s]*)?', text, flags=re.I):
        urls.append(href)

    soup = BeautifulSoup(text, "html.parser")
    for a in soup.find_all("a"):
        href = a.get("href")
        if href and ".pdf" in href.lower():
            urls.append(urljoin(base_url, href))

    cleaned: list[str] = []
    seen = set()
    for url in urls:
        url = url.replace("\\", "")
        url = re.sub(r'["\')\]}，。；;]+$', "", url)
        url = unquote(url)
        if url not in seen:
            seen.add(url)
            cleaned.append(url)
    return cleaned


def detail_page_to_pdf_urls(url: str, refresh: bool = False) -> list[str]:
    cache_path = DETAIL_CACHE / safe_name(url)
    text = fetch_text(url, cache_path, refresh=refresh)
    return extract_pdf_urls(text, url)


def paged_detail_url(url: str, page_no: int) -> str:
    if page_no <= 1:
        return url
    return re.sub(r"\.html(?:$|\?)", f"_{page_no}.html", url, count=1)


def extract_content_image_urls(text: str, base_url: str) -> tuple[list[str], int]:
    soup = BeautifulSoup(text, "html.parser")
    title = soup.title.get_text(" ", strip=True).replace("_北京高考在线", "") if soup.title else ""
    content = soup.find(id="content") or soup
    urls: list[str] = []
    seen = set()
    for img in content.find_all("img"):
        src = img.get("src")
        if not src:
            continue
        alt = img.get("alt") or ""
        blob = f"{alt} {title} {src}"
        if not any(key in blob for key in ["试题", "答案", "高三", "一模", "二模"]):
            continue
        full = urljoin(base_url, src)
        if full not in seen:
            seen.add(full)
            urls.append(full)

    page_numbers = []
    for li in soup.select("ul.el-pager li.number"):
        text_no = li.get_text(" ", strip=True)
        if text_no.isdigit():
            page_numbers.append(int(text_no))
    for m in re.finditer(r'aria-label="第\s*(\d+)\s*页"', text):
        page_numbers.append(int(m.group(1)))
    max_page = max(page_numbers) if page_numbers else 1
    return urls, max_page


def detail_page_to_image_urls(url: str, refresh: bool = False) -> list[str]:
    first_cache = DETAIL_CACHE / safe_name(url)
    first_text = fetch_text(url, first_cache, refresh=refresh)
    first_images, max_page = extract_content_image_urls(first_text, url)

    all_urls: list[str] = []
    seen = set()
    for img_url in first_images:
        if img_url not in seen:
            seen.add(img_url)
            all_urls.append(img_url)

    for page_no in range(2, max_page + 1):
        page_url = paged_detail_url(url, page_no)
        cache_path = DETAIL_CACHE / safe_name(page_url)
        try:
            text = fetch_text(page_url, cache_path, refresh=refresh)
        except Exception:
            continue
        image_urls, _ = extract_content_image_urls(text, page_url)
        for img_url in image_urls:
            if img_url not in seen:
                seen.add(img_url)
                all_urls.append(img_url)
        time.sleep(0.02)
    return all_urls


def image_filetype(data: bytes, url: str) -> str:
    head = data[:12]
    if head.startswith(b"\x89PNG"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"RIFF") and b"WEBP" in head:
        return "webp"
    suffix = Path(url.split("?", 1)[0]).suffix.lower().lstrip(".")
    return {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(suffix, "jpeg")


def download_image_bytes(url: str) -> bytes:
    r = requests.get(url, timeout=(12, 90), headers={"User-Agent": UA})
    r.raise_for_status()
    data = r.content
    if len(data) < 100 or not data[:12]:
        raise ValueError("图片内容过短")
    return data


def images_to_pdf(image_urls: list[str], path: Path) -> tuple[bool, int, str]:
    if not image_urls:
        return False, 0, "未发现试题图片"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".download")
    doc = fitz.open()
    try:
        for image_url in image_urls:
            data = download_image_bytes(image_url)
            ftype = image_filetype(data, image_url)
            img_doc = fitz.open(stream=data, filetype=ftype)
            rect = img_doc[0].rect
            page = doc.new_page(width=rect.width, height=rect.height)
            page.insert_image(rect, stream=data)
            img_doc.close()
            time.sleep(0.02)
        doc.save(str(tmp), garbage=3, deflate=True)
    except Exception as exc:
        doc.close()
        if tmp.exists():
            tmp.unlink()
        return False, 0, f"图片合成PDF失败: {exc}"
    doc.close()
    head = tmp.open("rb").read(8)
    if not head.startswith(b"%PDF"):
        tmp.unlink()
        return False, 0, f"合成结果非PDF文件头: {head!r}"
    tmp.replace(path)
    return True, path.stat().st_size, head.decode("latin-1", errors="ignore")


def target_path(year: int, subject: str, district: str, exam_type: str) -> Path:
    filename = f"{year}北京{district}高三{exam_type}{subject}试题及答案.pdf"
    return ROOT / subject / "北京一模二模真题" / str(year) / district / exam_type / filename


def existing_pdf(path: Path) -> tuple[bool, str, int]:
    if not path.exists():
        return False, "", 0
    try:
        head = path.open("rb").read(8)
    except OSError:
        return False, "", 0
    return head.startswith(b"%PDF"), head.decode("latin-1", errors="ignore"), path.stat().st_size


def download_pdf(url: str, path: Path) -> tuple[bool, int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".download")
    try:
        r = requests.get(url, timeout=(12, 120), headers={"User-Agent": UA}, stream=True)
    except Exception as exc:
        return False, 0, f"请求失败: {exc}"
    if r.status_code != 200:
        return False, 0, f"HTTP {r.status_code}"

    first = b""
    size = 0
    try:
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                if not first:
                    first = chunk[:8]
                f.write(chunk)
                size += len(chunk)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink()
        return False, 0, f"写入失败: {exc}"

    if not first.startswith(b"%PDF"):
        if tmp.exists():
            tmp.unlink()
        head = first.decode("latin-1", errors="ignore")
        return False, size, f"非PDF文件头: {head!r}"

    tmp.replace(path)
    return True, size, first.decode("latin-1", errors="ignore")


def fallback_woaigaokao_urls(year: int, subject: str, district: str, exam_type: str) -> list[str]:
    filename = f"{year}北京{district}高三{exam_type}{subject}试题及答案.pdf"
    encoded = quote(filename)
    urls = []
    for month in ["12", "11", "10", "09", "08", "07", "06", "05", "04", "03", "02", "01"]:
        urls.append(f"https://www.woaigaokao.com/wp-content/uploads/{year}/{month}/{encoded}")
    return urls


def download_target(candidates: list[Candidate], year: int, subject: str, district: str, exam_type: str, refresh: bool = False) -> DownloadRecord:
    path = target_path(year, subject, district, exam_type)
    matches = [
        c
        for c in candidates
        if c.year == year and c.subject == subject and c.district == district and c.exam_type == exam_type
    ]
    ok, head, size = existing_pdf(path)
    if ok:
        source_page = matches[0].source_page if matches else ""
        detail_page = matches[0].detail_page if matches else ""
        return DownloadRecord(year, subject, district, exam_type, "已存在", size, str(path), source_page, detail_page, [], head, "")

    tried: list[str] = []
    notes: list[str] = []
    for cand in matches:
        try:
            pdf_urls = detail_page_to_pdf_urls(cand.detail_page, refresh=refresh)
        except Exception as exc:
            notes.append(f"详情页失败 {cand.detail_page}: {exc}")
            continue
        if not pdf_urls:
            notes.append(f"详情页未发现PDF {cand.detail_page}")
        for pdf_url in pdf_urls:
            if pdf_url in tried:
                continue
            tried.append(pdf_url)
            success, dl_size, dl_head = download_pdf(pdf_url, path)
            if success:
                return DownloadRecord(
                    year,
                    subject,
                    district,
                    exam_type,
                    "已下载",
                    dl_size,
                    str(path),
                    cand.source_page,
                    cand.detail_page,
                    tried,
                    dl_head,
                    "",
                )
            notes.append(f"{pdf_url}: {dl_head}")
            time.sleep(0.05)

        try:
            image_urls = detail_page_to_image_urls(cand.detail_page, refresh=refresh)
        except Exception as exc:
            notes.append(f"详情页图片提取失败 {cand.detail_page}: {exc}")
            image_urls = []
        if image_urls:
            success, img_size, img_head = images_to_pdf(image_urls, path)
            if success:
                return DownloadRecord(
                    year,
                    subject,
                    district,
                    exam_type,
                    "已下载",
                    img_size,
                    str(path),
                    cand.source_page,
                    cand.detail_page,
                    image_urls,
                    img_head,
                    "由北京高考在线分页试题图片合成为PDF",
                )
            notes.append(f"图片合成失败 {cand.detail_page}: {img_head}")

    for pdf_url in fallback_woaigaokao_urls(year, subject, district, exam_type):
        if pdf_url in tried:
            continue
        tried.append(pdf_url)
        success, dl_size, dl_head = download_pdf(pdf_url, path)
        if success:
            return DownloadRecord(year, subject, district, exam_type, "已下载", dl_size, str(path), "", "", tried, dl_head, "woaigaokao固定路径补得")
        time.sleep(0.03)

    return DownloadRecord(
        year,
        subject,
        district,
        exam_type,
        "待补",
        0,
        str(path),
        matches[0].source_page if matches else "",
        matches[0].detail_page if matches else "",
        tried[:8],
        "",
        "；".join(notes[:5]) if notes else "无候选详情页或固定路径未命中",
    )


def scan_status() -> dict[str, Any]:
    rows = []
    summary = []
    total_per_subject = len(YEARS) * len(DISTRICTS) * len(EXAM_TYPES)
    for subject in SUBJECTS:
        done = 0
        for year in YEARS:
            for district in DISTRICTS:
                for exam_type in EXAM_TYPES:
                    folder = ROOT / subject / "北京一模二模真题" / str(year) / district / exam_type
                    valid_files = []
                    invalid_files = []
                    if folder.exists():
                        for p in sorted(folder.glob("*.pdf")):
                            try:
                                head = p.open("rb").read(4)
                            except OSError:
                                head = b""
                            if head == b"%PDF":
                                valid_files.append(str(p))
                            else:
                                invalid_files.append(str(p))
                    status = "已完成" if valid_files else "待补"
                    if valid_files:
                        done += 1
                    rows.append(
                        {
                            "subject": subject,
                            "year": year,
                            "district": district,
                            "kind": exam_type,
                            "valid_count": len(valid_files),
                            "invalid_count": len(invalid_files),
                            "valid_files": valid_files,
                            "invalid_files": invalid_files,
                            "status": status,
                        }
                    )
        summary.append({"subject": subject, "done": done, "total": total_per_subject, "missing": total_per_subject - done})
    return {"summary": summary, "rows": rows}


def write_collection_checklist(subject: str, status: dict[str, Any], records: list[DownloadRecord]) -> None:
    candidates = collect_candidates(refresh=False)
    by_cand = {(c.year, c.subject, c.district, c.exam_type): c for c in candidates if c.subject == subject}
    by_key = {(r.year, r.subject, r.district, r.exam_type): r for r in records if r.subject == subject}
    rows = [r for r in status["rows"] if r["subject"] == subject]
    row_map = {(r["year"], r["district"], r["kind"]): r for r in rows}
    lines = [
        f"# 北京{subject}一模二模收集清单 {YEARS[0]}-{YEARS[-1]}",
        "",
        "## 收集目标",
        "",
        f"范围：{YEARS[0]}-{YEARS[-1]} 年，北京海淀、西城、东城、朝阳，高三一模、二模，科目：{subject}。",
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
        cells = []
        count = 0
        for district in DISTRICTS:
            for exam_type in EXAM_TYPES:
                rr = row_map[(year, district, exam_type)]
                ok = rr["status"] == "已完成"
                count += 1 if ok else 0
                cells.append("已完成" if ok else "待补")
        lines.append(f"| {year} | " + " | ".join(cells) + f" | {count}/8 |")

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
                rr = row_map[(year, district, exam_type)]
                if rr["status"] == "已完成":
                    continue
                rec = by_key.get((year, subject, district, exam_type))
                note = rec.note if rec else "尚未下载核验"
                lines.append(f"| {year} | {district} | {exam_type} | 待补 | {note.replace('|', '/')} |")

    lines += [
        "",
        "## 本轮来源记录",
        "",
        "| 年份 | 区域 | 类型 | 状态 | 大小 | 来源页 | PDF URL | 本地文件 |",
        "|---|---|---|---|---:|---|---|---|",
    ]
    for year in YEARS:
        for district in DISTRICTS:
            for exam_type in EXAM_TYPES:
                rec = by_key.get((year, subject, district, exam_type))
                cand = by_cand.get((year, subject, district, exam_type))
                rr = row_map[(year, district, exam_type)]
                file_path = rr["valid_files"][0] if rr["valid_files"] else (rec.file if rec else str(target_path(year, subject, district, exam_type)))
                size = Path(file_path).stat().st_size if rr["valid_files"] and Path(file_path).exists() else (rec.size if rec else 0)
                state = "已完成" if rr["valid_files"] else "待补"
                source = (rec.detail_page or rec.source_page) if rec else (cand.detail_page if cand else "")
                pdf_url = rec.pdf_urls[0] if rec and rec.pdf_urls else ""
                lines.append(
                    f"| {year} | {district} | {exam_type} | {state} | {size} | {source} | {pdf_url} | `{file_path}` |"
                )

    lines += [
        "",
        "## 入库纪律",
        "",
        "1. 只有文件头校验为 `%PDF` 的文件才标记为已完成。",
        "2. 不把 HTML、下载页、试卷分析页保存成 PDF。",
        "3. 正式给孩子使用前，必须打开原 PDF 核对题干、答案和必要图示。",
        "4. 题目级机器标签只用于候选筛选，不能直接作为学生打印版依据。",
    ]

    out = ROOT / subject / "题库" / f"北京{subject}一模二模收集清单-2020-2025.md"
    out.write_text("\n".join(lines), encoding="utf-8")


def write_trial_index(subject: str, status: dict[str, Any], records: list[DownloadRecord]) -> None:
    candidates = collect_candidates(refresh=False)
    by_cand = {(c.year, c.subject, c.district, c.exam_type): c for c in candidates if c.subject == subject}
    by_key = {(r.year, r.subject, r.district, r.exam_type): r for r in records if r.subject == subject}
    rows = [r for r in status["rows"] if r["subject"] == subject]
    lines = [
        f"# 北京{subject}一模二模试卷级索引",
        "",
        "本索引只记录已在本地校验为真实 PDF 的试卷。后续题目级标签、图示截取和人工核对在此基础上继续处理。",
        "",
        "| 年份 | 区域 | 类型 | 状态 | 文件大小 | 来源页 | 本地 PDF | 后续标签处理 |",
        "|---|---|---|---|---:|---|---|---|",
    ]
    for r in rows:
        rec = by_key.get((r["year"], subject, r["district"], r["kind"]))
        cand = by_cand.get((r["year"], subject, r["district"], r["kind"]))
        if r["valid_files"]:
            p = Path(r["valid_files"][0])
            size = p.stat().st_size if p.exists() else 0
            source = (rec.detail_page or rec.source_page) if rec else (cand.detail_page if cand else "")
            next_step = "待文本抽取/题号切分/机器初标/人工核题干图示"
            lines.append(
                f"| {r['year']} | {r['district']} | {r['kind']} | 已完成 | {size} | {source} | `{p}` | {next_step} |"
            )
        else:
            note = rec.note if rec else "待人工查找"
            lines.append(f"| {r['year']} | {r['district']} | {r['kind']} | 待补 | 0 |  |  | {note.replace('|', '/')} |")

    out = ROOT / subject / "题库" / f"北京{subject}一模二模试卷级索引.md"
    out.write_text("\n".join(lines), encoding="utf-8")


def write_tag_queue(status: dict[str, Any]) -> None:
    lines = [
        "# 全科一模二模题目标签处理队列",
        "",
        "用途：PDF 补齐后，按科目和年份进入文本抽取、题号切分、机器初标、人工核题干图示。机器初标只用于筛题，正式给孩子前必须核对原 PDF。",
        "",
        "| 优先级 | 科目 | 年份范围 | 前置条件 | 当前状态 | 下一步 |",
        "|---:|---|---|---|---|---|",
    ]
    priority = 1
    if 2026 in YEARS:
        for subject in ["数学", "化学", "生物", "英语", "语文", "物理"]:
            rows = [r for r in status["rows"] if r["subject"] == subject and r["year"] == 2026]
            done = sum(1 for r in rows if r["status"] == "已完成")
            state = f"{done}/8"
            next_step = "可进入 2026 题目级初标" if done == 8 else "先补齐 2026 PDF"
            lines.append(f"| {priority} | {subject} | 2026 | 8 份 PDF 全部真实校验 | {state} | {next_step} |")
            priority += 1

    for subject in ["数学", "化学", "生物", "英语", "语文", "物理"]:
        rows = [r for r in status["rows"] if r["subject"] == subject and r["year"] in [2023, 2024, 2025]]
        done = sum(1 for r in rows if r["status"] == "已完成")
        state = f"{done}/24"
        if done == 24:
            next_step = "可进入 2025-2023 题目级初标"
        else:
            next_step = "先补齐 2025-2023 PDF"
        lines.append(f"| {priority} | {subject} | 2025-2023 | 24 份 PDF 全部真实校验 | {state} | {next_step} |")
        priority += 1

    for subject in ["数学", "化学", "生物", "英语", "语文", "物理"]:
        rows = [r for r in status["rows"] if r["subject"] == subject and r["year"] in [2020, 2021, 2022]]
        done = sum(1 for r in rows if r["status"] == "已完成")
        state = f"{done}/24"
        next_step = "补 PDF 后再入题目级队列"
        lines.append(f"| {priority} | {subject} | 2022-2020 | 24 份 PDF 全部真实校验 | {state} | {next_step} |")
        priority += 1

    out = ROOT / "题库总控" / "全科一模二模题目标签处理队列.md"
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    global ROOT, WORK, DETAIL_CACHE
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="学习资料库根目录，默认当前目录")
    parser.add_argument("--subjects", default=",".join(SUBJECTS))
    parser.add_argument("--years", default=",".join(str(y) for y in YEARS))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--max-targets", type=int, default=0)
    args = parser.parse_args()
    ROOT = args.root.resolve()
    WORK = ROOT / "tmp" / "全科一模二模链接采集"
    DETAIL_CACHE = WORK / "detail_pages"

    subjects = [s for s in args.subjects.split(",") if s]
    years = [int(y) for y in args.years.split(",") if y]

    candidates = collect_candidates(refresh=args.refresh)
    if args.skip_download:
        print(f"candidates {len(candidates)}")
        return

    records: list[DownloadRecord] = []
    targets = [
        (year, subject, district, exam_type)
        for subject in subjects
        for year in years
        for district in DISTRICTS
        for exam_type in EXAM_TYPES
    ]
    if args.max_targets > 0:
        targets = targets[: args.max_targets]

    for idx, (year, subject, district, exam_type) in enumerate(targets, 1):
        rec = download_target(candidates, year, subject, district, exam_type, refresh=args.refresh)
        records.append(rec)
        print(f"[{idx}/{len(targets)}] {year} {subject} {district}{exam_type} {rec.status} {rec.size}")
        time.sleep(0.08)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_json = WORK / f"gaokzx_all_subject_downloads_{stamp}.json"
    out_json.write_text(json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2), encoding="utf-8")

    status = scan_status()
    status_path = ROOT / "题库总控" / "全科一模二模实际盘点.json"
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    for subject in subjects:
        write_collection_checklist(subject, status, records)
        write_trial_index(subject, status, records)
    write_tag_queue(status)

    md = [
        f"# gaokzx 全科一模二模下载记录 {stamp}",
        "",
        "| 年份 | 科目 | 区域 | 类型 | 状态 | 大小 | 详情页 | PDF URL | 文件 | 备注 |",
        "|---|---|---|---|---|---:|---|---|---|---|",
    ]
    for r in records:
        md.append(
            f"| {r.year} | {r.subject} | {r.district} | {r.exam_type} | {r.status} | {r.size} | "
            f"{r.detail_page} | {(r.pdf_urls[0] if r.pdf_urls else '')} | `{r.file}` | {r.note.replace('|', '/')} |"
        )
    out_json.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")

    print(out_json)
    print(status_path)
    print(json.dumps(status["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
