"""單元測試：不呼叫任何外部網站。執行：python -m pytest"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from tracker.config import ConfigError, load_regions, regions_json
from tracker.holidays import HolidayError, decode, find_csv_url, parse_csv


def test_regions_load():
    countries = load_regions()
    data = regions_json(countries)
    keys = {r["key"]: r for c in data["countries"] for r in c["regions"]}
    assert keys["japan-kansai"]["airports"] == ["KIX", "UKB"]
    assert keys["korea-jeju"]["airports"] == ["CJU"]


def test_regions_rejects_bad_airport(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("japan:\n  name: 日本\n  regions:\n    japan-x: {name: X, airports: [KIXX]}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_regions(p)


def _calendar(year: int, overrides: dict) -> str:
    lines = ["西元日期,星期,是否放假,備註"]
    d = date(year, 1, 1)
    while d.year == year:
        off, note = ("2" if d.weekday() >= 5 else "0"), ""
        if d in overrides:
            off, note = overrides[d]
        lines.append(f"{d:%Y%m%d},{'一二三四五六日'[d.weekday()]},{off},{note}")
        d += timedelta(days=1)
    return "\n".join(lines)


def test_holiday_csv_parse_handles_makeup_workday():
    text = _calendar(2026, {date(2026, 1, 1): ("2", "開國紀念日"), date(2026, 1, 3): ("0", "補行上班")})
    data = parse_csv(text, 2026)
    assert data["days"]["2026-01-01"] == {"off": True, "note": "開國紀念日"}
    assert data["days"]["2026-01-03"]["off"] is False  # 週六補班
    assert data["days"]["2026-01-04"]["off"] is True
    assert len(data["days"]) == 365


def test_holiday_csv_big5_and_incomplete():
    text = _calendar(2026, {})
    assert decode(text.encode("cp950")).startswith("西元日期")
    with pytest.raises(HolidayError):
        parse_csv("\n".join(text.splitlines()[:100]), 2026)


def test_find_csv_url_skips_google_version():
    meta = {"result": {"distribution": [
        {"resourceDescription": "115年中華民國政府行政機關辦公日曆表(Google行事曆專用)", "resourceFormat": "CSV", "resourceDownloadUrl": "https://x/google.csv"},
        {"resourceDescription": "115年中華民國政府行政機關辦公日曆表", "resourceFormat": "CSV", "resourceDownloadUrl": "https://x/115.csv"},
        {"resourceDescription": "114年中華民國政府行政機關辦公日曆表", "resourceFormat": "CSV", "resourceDownloadUrl": "https://x/114.csv"},
    ]}}
    assert find_csv_url(meta, 2026) == "https://x/115.csv"
    assert find_csv_url(meta, 2027) is None
