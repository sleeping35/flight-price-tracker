"""假日資料：下載「中華民國政府行政機關辦公日曆表」並轉成 JSON。

資料來源：政府資料開放平台 https://data.gov.tw/dataset/14718
（行政院人事行政總處每年公告隔年的辦公日曆）

輸出 docs/data/holidays/<西元年>.json，列出全年每一天：
  {"year": 2026, "days": {"2026-01-01": {"off": true, "note": "開國紀念日"}, ...}}
off 以 CSV 的「是否放假」欄位為準（2 = 放假，0 = 上班），
所以週六補班日會是 off: false，不會被誤判成週末。
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from pathlib import Path

import requests

from .secrets import log

DATASET_API = "https://data.gov.tw/api/v2/rest/dataset/14718"


class HolidayError(Exception):
    pass


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def find_csv_url(meta: dict, year: int) -> str | None:
    """從資料集 metadata 找出指定年度的 CSV 下載網址（排除 Google 行事曆專用版）。"""
    roc = year - 1911
    candidates = []
    for d in _walk(meta):
        url = d.get("resourceDownloadUrl") or d.get("downloadURL") or d.get("accessURL")
        desc = str(d.get("resourceDescription") or d.get("title") or d.get("description") or "")
        fmt = str(d.get("resourceFormat") or d.get("format") or "").upper()
        if not url or "CSV" not in (fmt + url.upper()):
            continue
        if f"{roc}年" not in desc and str(year) not in desc:
            continue
        if "google" in desc.lower():
            continue
        candidates.append(url)
    return candidates[0] if candidates else None


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp950", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise HolidayError("無法辨識 CSV 編碼")


def _parse_date(s: str) -> date | None:
    digits = re.findall(r"\d+", s)
    try:
        if len(digits) == 1 and len(digits[0]) == 8:
            v = digits[0]
            return date(int(v[:4]), int(v[4:6]), int(v[6:]))
        if len(digits) >= 3:
            return date(int(digits[0]), int(digits[1]), int(digits[2]))
    except ValueError:
        return None
    return None


def parse_csv(text: str, year: int) -> dict:
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise HolidayError("CSV 是空的")
    header = [h.strip() for h in rows[0]]

    def col(*names: str) -> int:
        for i, h in enumerate(header):
            if any(n in h for n in names):
                return i
        raise HolidayError(f"CSV 找不到欄位 {names}，實際欄位：{header}")

    i_date = col("西元日期", "日期", "Date")
    i_off = col("是否放假", "放假")
    try:
        i_note = col("備註", "說明")
    except HolidayError:
        i_note = None

    days: dict[str, dict] = {}
    for r in rows[1:]:
        d = _parse_date(r[i_date]) if i_date < len(r) else None
        if d is None or d.year != year:
            continue
        flag = r[i_off].strip() if i_off < len(r) else ""
        note = r[i_note].strip() if i_note is not None and i_note < len(r) else ""
        days[d.isoformat()] = {"off": flag == "2", "note": note}
    if len(days) < 365:
        raise HolidayError(f"{year} 年只解析到 {len(days)} 天，資料可能不完整")
    return {
        "year": year,
        "source": "政府資料開放平台：中華民國政府行政機關辦公日曆表 https://data.gov.tw/dataset/14718",
        "days": dict(sorted(days.items())),
    }


def fetch_year(year: int, url: str | None = None, session: requests.Session | None = None) -> dict:
    s = session or requests.Session()
    if not url:
        resp = s.get(DATASET_API, timeout=60)
        resp.raise_for_status()
        url = find_csv_url(resp.json(), year)
        if not url:
            raise HolidayError(f"資料集裡還沒有 {year} 年（民國 {year - 1911} 年）的 CSV，可能尚未公告")
    log(f"下載 {year} 年辦公日曆：{url}")
    resp = s.get(url, timeout=60)
    resp.raise_for_status()
    return parse_csv(decode(resp.content), year)


def write_year(data_dir: Path, data: dict) -> Path:
    out_dir = data_dir / "holidays"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{data['year']}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    years = sorted(int(p.stem) for p in out_dir.glob("[0-9][0-9][0-9][0-9].json"))
    (out_dir / "index.json").write_text(json.dumps({"years": years}) + "\n", encoding="utf-8")
    return path
