"""指令入口。

  python -m tracker fetch [--region KEY ...] [--dry-run]   抓價並更新 docs/data
  python -m tracker holidays [--year 2027] [--url URL]     更新假日 JSON
  python -m tracker regions                                只重新產生 docs/data/regions.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from . import holidays as hol
from . import storage
from .budget import Budget
from .config import DATA_DIR, ConfigError, Settings, load_settings, months_from, regions_json
from .models import FareQuery
from .secrets import log, redact
from .sources import SOURCES, FareSource, SourceError

TAIPEI = ZoneInfo("Asia/Taipei")


def taipei_today() -> date:
    return datetime.now(TAIPEI).date()


def write_regions(settings: Settings) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "regions.json").write_text(
        json.dumps(regions_json(settings), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def build_queries(settings: Settings, today: date, only_regions: set[str]) -> dict[str, list[tuple]]:
    """依來源分組，回傳 (watch, FareQuery) 清單。"""
    by_source: dict[str, list[tuple]] = {}
    for w in settings.watches:
        if only_regions and w.region.key not in only_regions:
            continue
        for origin in w.origins:
            for dest in w.region.airports:
                if origin == dest:
                    continue
                for ttype in w.trip_types:
                    for month in months_from(today, w.months_ahead):
                        q = FareQuery(origin, dest, month, ttype == "one_way", w.trip_days, w.currency)
                        by_source.setdefault(w.source, []).append((w, q))
    return by_source


def cmd_fetch(args: argparse.Namespace) -> int:
    settings = load_settings()
    today = taipei_today()
    only = set(args.region or [])
    unknown = only - set(settings.regions)
    if unknown:
        log(f"錯誤：找不到地區 {sorted(unknown)}，可用的地區：{sorted(settings.regions)}")
        return 2

    budget = Budget(
        DATA_DIR / "usage.json",
        today,
        limits={"serpapi": settings.serpapi_monthly_limit},
        per_run={"serpapi": settings.serpapi_max_calls_per_run},
    )
    by_source = build_queries(settings, today, only)
    new_rows: list[dict] = []
    refreshed: set[tuple] = set()
    stats = {"ok": 0, "failed": 0, "skipped": 0}
    seen = today.isoformat()

    for source_name, items in by_source.items():
        cls = SOURCES.get(source_name)
        if cls is None:
            log(f"錯誤：watchlist.yaml 指定了不存在的來源「{source_name}」，可用：{sorted(SOURCES)}")
            stats["failed"] += len(items)
            continue
        source: FareSource = cls()
        if not source.available():
            log(f"警告：{source_name} 的金鑰沒有設定（GitHub Secrets），略過 {len(items)} 個查詢")
            stats["skipped"] += len(items)
            continue

        planned = [(w, pq) for w, q in items for pq in source.plan(q)]
        if source_name == "serpapi" and planned:
            # 每次只能用少量額度，依日期輪替起點，讓所有航線輪流被查到
            start = today.toordinal() % len(planned)
            planned = planned[start:] + planned[:start]

        budget_hit = False
        for w, q in planned:
            if not budget.can_call(source_name, source.cost_per_call):
                if not budget_hit:
                    log(f"{source_name}：已達用量上限（本月已用 {budget.used(source_name)} 次），其餘查詢略過")
                    budget_hit = True
                stats["skipped"] += 1
                continue
            label = f"{source_name} {q.origin}→{q.destination} {q.depart_date or q.depart_month} {'單程' if q.one_way else '來回'}"
            try:
                fares = source.search(q)
            except SourceError as exc:
                budget.record(source_name, source.cost_per_call)
                log(f"失敗：{label}：{exc}")
                stats["failed"] += 1
                continue
            except Exception as exc:  # 未預期錯誤也不能把金鑰印出來
                budget.record(source_name, source.cost_per_call)
                log(f"失敗：{label}：{type(exc).__name__}：{redact(exc)[:200]}")
                stats["failed"] += 1
                continue
            budget.record(source_name, source.cost_per_call)
            stats["ok"] += 1
            if q.depart_date:
                refreshed.add(storage.exact_key(q.origin, q.destination, q.depart_date, q.return_date))
            else:
                refreshed.add(storage.query_key(q.origin, q.destination, q.one_way, q.depart_month))
            kept = 0
            for f in fares:
                if f.depart_date < seen:
                    continue
                if not q.one_way:
                    days = f.days
                    if days is None or not (w.trip_days[0] <= days <= w.trip_days[1]):
                        continue
                region = settings.airport_region.get(f.destination, w.region.key)
                new_rows.append(storage.fare_to_row(f, region, seen))
                kept += 1
            log(f"完成：{label}：API 回傳 {len(fares)} 筆，符合條件 {kept} 筆")

    log(f"查詢結果：成功 {stats['ok']}、失敗 {stats['failed']}、略過 {stats['skipped']}")

    if args.dry_run:
        cov = storage.coverage(storage.dedupe(new_rows))
        log("覆蓋率測試（不寫檔）：航線 / 來回筆數 / 單程筆數")
        for route, c in cov.items():
            log(f"  {route:9s} 來回 {c['rt']:5d}  單程 {c['ow']:5d}")
        return 0 if stats["ok"] or not stats["failed"] else 1

    old_rows = storage.read_latest(DATA_DIR)
    rows = storage.merge_latest(old_rows, new_rows, refreshed, today)
    currency = settings.watches[0].currency if settings.watches else "TWD"
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    storage.write_latest(DATA_DIR, rows, generated, currency, storage.coverage(rows))
    storage.update_history(DATA_DIR, rows, today)
    write_regions(settings)
    budget.save()
    log(f"已寫入 latest.json：共 {len(rows)} 筆")
    # 全部失敗時讓 workflow 顯示紅燈，方便發現金鑰失效等問題
    return 1 if stats["failed"] and not stats["ok"] else 0


def cmd_holidays(args: argparse.Namespace) -> int:
    this_year = taipei_today().year
    years = [args.year] if args.year else [this_year, this_year + 1]
    code = 0
    for y in years:
        try:
            data = hol.fetch_year(y, url=args.url if args.year else None)
        except Exception as exc:
            exists = (DATA_DIR / "holidays" / f"{y}.json").exists()
            level = "警告" if (y > this_year or exists) else "錯誤"
            log(f"{level}：{y} 年假日資料更新失敗：{type(exc).__name__}：{exc}")
            if level == "錯誤":
                code = 1
            continue
        path = hol.write_year(DATA_DIR, data)
        off = sum(1 for d in data["days"].values() if d["off"])
        log(f"已寫入 {path.relative_to(DATA_DIR.parent.parent)}：全年 {len(data['days'])} 天，放假 {off} 天")
    return code


def cmd_regions(_: argparse.Namespace) -> int:
    write_regions(load_settings())
    log("已更新 docs/data/regions.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tracker")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch", help="抓價並更新 docs/data")
    p.add_argument("--region", action="append", help="只抓指定地區 key，可重複")
    p.add_argument("--dry-run", action="store_true", help="只印出覆蓋率，不寫檔")
    p.set_defaults(func=cmd_fetch)
    p = sub.add_parser("holidays", help="更新假日 JSON")
    p.add_argument("--year", type=int, help="西元年，不填則更新今年與明年")
    p.add_argument("--url", help="直接指定 CSV 網址（需搭配 --year）")
    p.set_defaults(func=cmd_holidays)
    p = sub.add_parser("regions", help="只重新產生 regions.json")
    p.set_defaults(func=cmd_regions)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        log(f"設定檔錯誤：{exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
