"""基本單元測試：不呼叫任何外部 API。執行：python -m pytest"""
from __future__ import annotations

import json
from datetime import date

from tracker import storage
from tracker.config import load_settings, months_from
from tracker.holidays import find_csv_url, parse_csv
from tracker.models import FareQuery
from tracker.secrets import redact
from tracker.sources.serpapi import SerpApiSource
from tracker.sources.travelpayouts import TravelpayoutsSource

TODAY = date(2026, 11, 2)


def row(o="TPE", d="KIX", dep="2026-12-24", ret="2026-12-28", price=9000, stops=0, seen="2026-11-02"):
    return {"o": o, "d": d, "region": "japan-kansai", "dep": dep, "ret": ret, "days": 5,
            "price": price, "airline": "IT", "stops": stops, "src": "travelpayouts", "seen": seen}


def test_config_loads_and_expands():
    s = load_settings()
    assert "japan-kansai" in s.regions
    assert s.airport_region["CJU"] == "korea-jeju"
    assert months_from(date(2026, 11, 2), 3) == ["2026-11", "2026-12", "2027-01"]


def test_dedupe_keeps_cheapest_and_cheapest_direct():
    rows = [row(price=9000, stops=0), row(price=7000, stops=1), row(price=9500, stops=0)]
    out = storage.dedupe(rows)
    assert sorted(r["price"] for r in out) == [7000, 9000]


def test_merge_replaces_refreshed_and_keeps_others():
    old = [row(price=9000), row(d="HND", dep="2026-12-10", ret="2026-12-14", price=8000),
           row(dep="2026-10-01", ret="2026-10-05")]  # 過去日期
    new = [row(price=8500)]
    refreshed = {storage.query_key("TPE", "KIX", False, "2026-12")}
    out = storage.merge_latest(old, new, refreshed, TODAY)
    prices = sorted(r["price"] for r in out)
    assert prices == [8000, 8500]


def test_merge_drops_stale_rows():
    out = storage.merge_latest([row(seen="2026-10-01")], [], set(), TODAY)
    assert out == []


def test_history_appends_and_compacts(tmp_path):
    storage.update_history(tmp_path, [row(price=9000)], TODAY)
    storage.update_history(tmp_path, [row(price=8800, seen="2026-11-03")], date(2026, 11, 3))
    data = json.loads((tmp_path / "history" / "2026-11.json").read_text())
    assert data["TPE-KIX|rt"]["2026-12-24"] == [["2026-11-02", 9000], ["2026-11-03", 8800]]
    compacted = storage.compact_history(data, date(2026, 12, 25))
    assert compacted["TPE-KIX|rt"]["2026-12-24"] == {"min": 8800, "max": 9000, "last": 8800, "n": 2}


def test_history_cleanup(tmp_path):
    h = tmp_path / "history"
    h.mkdir()
    for name in ("2024-10", "2024-11", "2026-11"):
        (h / f"{name}.json").write_text("{}")
    assert storage.cleanup_history(h, TODAY) == ["2024-10.json"]


def test_holiday_csv_parse_handles_makeup_workday():
    lines = ["西元日期,星期,是否放假,備註"]
    d = date(2026, 1, 1)
    while d.year == 2026:
        off = "2" if d.weekday() >= 5 else "0"
        note = ""
        if d == date(2026, 1, 1):
            off, note = "2", "開國紀念日"
        if d == date(2026, 1, 3):  # 假設這個週六補班
            off, note = "0", "補行上班"
        lines.append(f"{d:%Y%m%d},{'一二三四五六日'[d.weekday()]},{off},{note}")
        d = date.fromordinal(d.toordinal() + 1)
    data = parse_csv("\n".join(lines), 2026)
    assert data["days"]["2026-01-01"] == {"off": True, "note": "開國紀念日"}
    assert data["days"]["2026-01-03"]["off"] is False
    assert len(data["days"]) == 365


def test_find_csv_url_skips_google_version():
    meta = {"result": {"distribution": [
        {"resourceDescription": "115年中華民國政府行政機關辦公日曆表(Google行事曆專用)", "resourceFormat": "CSV", "resourceDownloadUrl": "https://x/google.csv"},
        {"resourceDescription": "115年中華民國政府行政機關辦公日曆表", "resourceFormat": "CSV", "resourceDownloadUrl": "https://x/115.csv"},
        {"resourceDescription": "114年中華民國政府行政機關辦公日曆表", "resourceFormat": "CSV", "resourceDownloadUrl": "https://x/114.csv"},
    ]}}
    assert find_csv_url(meta, 2026) == "https://x/115.csv"


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.text = payload, status, json.dumps(payload)

    def json(self):
        return self._p


class FakeSession:
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return FakeResp(self.payload)


def test_travelpayouts_parse(monkeypatch):
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "secret-token-123")
    payload = {"success": True, "currency": "twd", "data": [
        {"origin": "TPE", "destination": "OSA", "origin_airport": "TPE", "destination_airport": "KIX",
         "price": 8900, "airline": "IT", "departure_at": "2026-12-24T07:00:00+08:00",
         "return_at": "2026-12-28T20:00:00+09:00", "transfers": 0, "return_transfers": 1},
    ]}
    session = FakeSession(payload)
    src = TravelpayoutsSource(session=session)
    src.min_interval_sec = 0
    fares = src.search(FareQuery("TPE", "KIX", "2026-12", False, (3, 7)))
    assert len(fares) == 1 and fares[0].price == 8900 and fares[0].stops == 1 and fares[0].days == 5
    _, params, headers = session.calls[0]
    assert "token" not in params and headers["X-Access-Token"] == "secret-token-123"


def test_serpapi_plan_picks_friday():
    src = SerpApiSource(today=TODAY)
    [q] = src.plan(FareQuery("TPE", "CJU", "2026-12", False, (3, 7)))
    assert date.fromisoformat(q.depart_date).weekday() == 4
    assert (date.fromisoformat(q.return_date) - date.fromisoformat(q.depart_date)).days + 1 == 5


def test_redact(monkeypatch):
    monkeypatch.setenv("SERPAPI_KEY", "abcdef123456")
    assert "abcdef123456" not in redact("GET https://serpapi.com/search?api_key=abcdef123456&q=1")
    assert redact("token=zzz&x=1") == "token=***&x=1"
