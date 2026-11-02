"""輸出 latest.json 與價格歷史，並處理保留期限。

- docs/data/latest.json：目前每個日期組合的最低價，網頁主要讀這份。
- docs/data/history/YYYY-MM.json：按「抓價月份」分檔，每天記錄每個航線、
  每個去程日的最低價。去程日過了就彙整成一筆摘要；超過 24 個月的檔案刪除。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .models import FareResult

SCHEMA_VERSION = 1
HISTORY_KEEP_MONTHS = 24


def _dump(path: Path, data: dict, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":"))
    path.write_text(text + "\n", encoding="utf-8")


def fare_to_row(f: FareResult, region: str | None, seen: str) -> dict:
    return {
        "o": f.origin,
        "d": f.destination,
        "region": region,
        "dep": f.depart_date,
        "ret": f.return_date,
        "days": f.days,
        "price": f.price,
        "airline": f.airline,
        "stops": f.stops,
        "src": f.source,
        "seen": seen,
    }


def dedupe(rows: list[dict]) -> list[dict]:
    """同一組「航線＋去程＋回程」只留最低價；若最低價不是直飛，再另外留最便宜的直飛。"""
    best: dict[tuple, dict] = {}
    best_direct: dict[tuple, dict] = {}
    for r in rows:
        k = (r["o"], r["d"], r["dep"], r["ret"])
        if k not in best or r["price"] < best[k]["price"]:
            best[k] = r
        if r["stops"] == 0 and (k not in best_direct or r["price"] < best_direct[k]["price"]):
            best_direct[k] = r
    out = list(best.values())
    for k, r in best_direct.items():
        if best[k]["stops"] != 0:
            out.append(r)
    out.sort(key=lambda r: (r["o"], r["d"], r["dep"], r["ret"] or "", r["price"]))
    return out


def query_key(origin: str, dest: str, one_way: bool, month: str) -> tuple:
    return (origin, dest, "ow" if one_way else "rt", month)


def row_query_key(r: dict) -> tuple:
    return (r["o"], r["d"], "ow" if r["ret"] is None else "rt", r["dep"][:7])


def exact_key(origin: str, dest: str, dep: str, ret: str | None) -> tuple:
    return ("exact", origin, dest, dep, ret)


MAX_STALE_DAYS = 14


def merge_latest(old_rows: list[dict], new_rows: list[dict], refreshed: set[tuple], today: date) -> list[dict]:
    """新資料取代成功重抓的查詢；沒重抓或失敗的查詢保留舊資料。

    refreshed 可以是整個月份的查詢（Travelpayouts），也可以是單一日期組合（SerpApi）。
    過去日期、以及超過 14 天沒有更新的舊資料一律移除。
    """
    today_s = today.isoformat()
    stale_before = date.fromordinal(today.toordinal() - MAX_STALE_DAYS).isoformat()
    kept = [
        r for r in old_rows
        if row_query_key(r) not in refreshed
        and exact_key(r["o"], r["d"], r["dep"], r["ret"]) not in refreshed
        and r.get("seen", "") >= stale_before
    ]
    merged = [r for r in kept + new_rows if r["dep"] >= today_s]
    return dedupe(merged)


def coverage(rows: list[dict]) -> dict:
    """每個航線目前有幾筆資料，用來判斷 Travelpayouts 的覆蓋率。"""
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        c = out.setdefault(f'{r["o"]}-{r["d"]}', {"rt": 0, "ow": 0})
        c["ow" if r["ret"] is None else "rt"] += 1
    return dict(sorted(out.items()))


def write_latest(data_dir: Path, rows: list[dict], generated_at: str, currency: str, coverage: dict) -> None:
    _dump(
        data_dir / "latest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "currency": currency,
            "coverage": coverage,
            "fares": rows,
        },
    )


def read_latest(data_dir: Path) -> list[dict]:
    path = data_dir / "latest.json"
    if not path.exists():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).get("fares") or [])


def update_history(data_dir: Path, rows: list[dict], today: date) -> None:
    """把今天抓到的價格（每個航線、每個去程日的最低價）寫進本月的歷史檔。"""
    hist_dir = data_dir / "history"
    path = hist_dir / f"{today:%Y-%m}.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    seen = today.isoformat()
    daily_min: dict[tuple[str, str], int] = {}
    for r in rows:
        if r["seen"] != seen:
            continue  # 舊資料保留在 latest 裡，但不算今天的觀測值
        key = (f'{r["o"]}-{r["d"]}|{"ow" if r["ret"] is None else "rt"}', r["dep"])
        if key not in daily_min or r["price"] < daily_min[key]:
            daily_min[key] = r["price"]
    for (route, dep), price in daily_min.items():
        series = data.setdefault(route, {}).setdefault(dep, [])
        if isinstance(series, dict):
            continue  # 已彙整的過去日期
        if series and series[-1][0] == seen:
            series[-1][1] = min(series[-1][1], price)
        else:
            series.append([seen, price])
    _dump(path, compact_history(data, today))
    cleanup_history(hist_dir, today)


def compact_history(data: dict, today: date) -> dict:
    """去程日已過的每日紀錄，彙整成 {min, max, last, n}。"""
    today_s = today.isoformat()
    for route in data.values():
        for dep, series in list(route.items()):
            if dep < today_s and isinstance(series, list) and series:
                prices = [p for _, p in series]
                route[dep] = {"min": min(prices), "max": max(prices), "last": prices[-1], "n": len(prices)}
    return data


def cleanup_history(hist_dir: Path, today: date) -> list[str]:
    """刪除超過保留期限的歷史檔，回傳被刪除的檔名。"""
    y, m = today.year, today.month - HISTORY_KEEP_MONTHS
    while m <= 0:
        y, m = y - 1, m + 12
    cutoff = f"{y:04d}-{m:02d}"
    removed = []
    for p in sorted(hist_dir.glob("????-??.json")):
        if p.stem < cutoff:
            p.unlink()
            removed.append(p.name)
    return removed
