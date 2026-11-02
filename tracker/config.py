"""讀取地區對照表（config/regions.yaml），轉成網頁使用的 docs/data/regions.json。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "docs" / "data"

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
IATA_RE = re.compile(r"^[A-Z]{3}$")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Region:
    key: str
    name: str
    airports: tuple[str, ...]


@dataclass(frozen=True)
class Country:
    key: str
    name: str
    en: str
    regions: tuple[Region, ...]


def load_regions(path: Path | None = None) -> list[Country]:
    path = path or CONFIG_DIR / "regions.yaml"
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ConfigError("regions.yaml 的最外層必須是對照表（key: value）")
    seen: set[str] = set()
    countries: list[Country] = []
    for ckey, cval in raw.items():
        if not KEY_RE.match(str(ckey)):
            raise ConfigError(f"國家 key「{ckey}」只能用小寫英文、數字與連字號")
        if not isinstance(cval, dict) or not cval.get("regions"):
            raise ConfigError(f"國家「{ckey}」缺少 regions")
        regions = []
        for rkey, rval in cval["regions"].items():
            if not KEY_RE.match(str(rkey)):
                raise ConfigError(f"地區 key「{rkey}」只能用小寫英文、數字與連字號")
            if rkey in seen:
                raise ConfigError(f"地區 key「{rkey}」重複")
            seen.add(rkey)
            airports = tuple(str(a).upper() for a in (rval or {}).get("airports") or [])
            if not airports or not all(IATA_RE.match(a) for a in airports):
                raise ConfigError(f"地區「{rkey}」的 airports 必須是三碼機場代碼")
            regions.append(Region(rkey, str(rval.get("name") or rkey), airports))
        countries.append(Country(ckey, str(cval.get("name") or ckey), str(cval.get("en") or ""), tuple(regions)))
    return countries


def regions_json(countries: list[Country]) -> dict:
    return {
        "countries": [
            {
                "key": c.key,
                "name": c.name,
                "en": c.en,
                "regions": [{"key": r.key, "name": r.name, "airports": list(r.airports)} for r in c.regions],
            }
            for c in countries
        ]
    }
