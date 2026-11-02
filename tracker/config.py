"""讀取設定檔，並把追蹤清單展開成實際的查詢。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "docs" / "data"

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
IATA_RE = re.compile(r"^[A-Z]{3}$")
TRIP_TYPES = ("round_trip", "one_way")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Region:
    key: str
    name: str
    country_key: str
    country_name: str
    airports: tuple[str, ...]


@dataclass
class Watch:
    region: Region
    origins: list[str]
    months_ahead: int
    trip_days: tuple[int, int]
    trip_types: list[str]
    currency: str
    source: str


@dataclass
class Settings:
    regions: dict[str, Region]
    countries: dict[str, dict]
    watches: list[Watch]
    serpapi_monthly_limit: int = 230
    serpapi_max_calls_per_run: int = 7
    airport_region: dict[str, str] = field(default_factory=dict)


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} 的最外層必須是對照表（key: value）")
    return data


def load_regions(path: Path | None = None) -> tuple[dict[str, Region], dict[str, dict]]:
    path = path or CONFIG_DIR / "regions.yaml"
    raw = _load_yaml(path)
    regions: dict[str, Region] = {}
    countries: dict[str, dict] = {}
    for ckey, cval in raw.items():
        if not KEY_RE.match(str(ckey)):
            raise ConfigError(f"regions.yaml：國家 key「{ckey}」只能用小寫英文、數字與連字號")
        if not isinstance(cval, dict) or "regions" not in cval:
            raise ConfigError(f"regions.yaml：國家「{ckey}」缺少 regions")
        cname = str(cval.get("name") or ckey)
        countries[ckey] = {"name": cname, "regions": []}
        for rkey, rval in (cval.get("regions") or {}).items():
            if not KEY_RE.match(str(rkey)):
                raise ConfigError(f"regions.yaml：地區 key「{rkey}」只能用小寫英文、數字與連字號")
            if rkey in regions:
                raise ConfigError(f"regions.yaml：地區 key「{rkey}」重複")
            airports = tuple(str(a).upper() for a in (rval or {}).get("airports") or [])
            if not airports or not all(IATA_RE.match(a) for a in airports):
                raise ConfigError(f"regions.yaml：地區「{rkey}」的 airports 必須是三碼機場代碼")
            regions[rkey] = Region(rkey, str(rval.get("name") or rkey), ckey, cname, airports)
            countries[ckey]["regions"].append(rkey)
    return regions, countries


def load_settings(regions_path: Path | None = None, watchlist_path: Path | None = None) -> Settings:
    regions, countries = load_regions(regions_path)
    raw = _load_yaml(watchlist_path or CONFIG_DIR / "watchlist.yaml")
    defaults = raw.get("defaults") or {}
    watches: list[Watch] = []
    for i, item in enumerate(raw.get("watches") or [], start=1):
        merged = {**defaults, **(item or {})}
        rkey = merged.get("region")
        if rkey not in regions:
            raise ConfigError(f"watchlist.yaml 第 {i} 項：regions.yaml 裡沒有地區「{rkey}」")
        origins = [str(o).upper() for o in merged.get("origins") or ["TPE"]]
        if not all(IATA_RE.match(o) for o in origins):
            raise ConfigError(f"watchlist.yaml 第 {i} 項：origins 必須是三碼機場代碼")
        td = merged.get("trip_days") or [3, 7]
        if len(td) != 2 or int(td[0]) < 1 or int(td[0]) > int(td[1]):
            raise ConfigError(f"watchlist.yaml 第 {i} 項：trip_days 要寫成 [最少, 最多]")
        types = list(merged.get("trip_types") or ["round_trip"])
        if any(t not in TRIP_TYPES for t in types):
            raise ConfigError(f"watchlist.yaml 第 {i} 項：trip_types 只能是 round_trip、one_way")
        months = int(merged.get("months_ahead") or 6)
        if not 1 <= months <= 12:
            raise ConfigError(f"watchlist.yaml 第 {i} 項：months_ahead 要介於 1～12")
        watches.append(
            Watch(
                region=regions[rkey],
                origins=origins,
                months_ahead=months,
                trip_days=(int(td[0]), int(td[1])),
                trip_types=types,
                currency=str(merged.get("currency") or "TWD").upper(),
                source=str(merged.get("source") or "travelpayouts"),
            )
        )
    serp = raw.get("serpapi") or {}
    airport_region = {a: r.key for r in regions.values() for a in r.airports}
    return Settings(
        regions=regions,
        countries=countries,
        watches=watches,
        serpapi_monthly_limit=int(serp.get("monthly_limit", 230)),
        serpapi_max_calls_per_run=int(serp.get("max_calls_per_run", 7)),
        airport_region=airport_region,
    )


def months_from(today: date, count: int) -> list[str]:
    """從本月起算 count 個月，回傳 ["2026-11", "2026-12", ...]。"""
    out = []
    y, m = today.year, today.month
    for _ in range(count):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def regions_json(settings: Settings) -> dict:
    """給網頁用的地區清單（docs/data/regions.json）。"""
    tracked = {w.region.key for w in settings.watches}
    origins = sorted({o for w in settings.watches for o in w.origins})
    return {
        "countries": [
            {
                "key": ckey,
                "name": c["name"],
                "regions": [
                    {
                        "key": rkey,
                        "name": settings.regions[rkey].name,
                        "airports": list(settings.regions[rkey].airports),
                        "tracked": rkey in tracked,
                    }
                    for rkey in c["regions"]
                ],
            }
            for ckey, c in settings.countries.items()
        ],
        "tracked_origins": origins,
    }
