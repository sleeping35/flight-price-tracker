"""SerpApi Google Flights API（輔助來源）。

一次呼叫只能查一組「去程日＋回程日」，而免費方案每月只有 250 次，
所以每個月份只抽樣一組日期：從該月尚未出發的週五中，依執行日期輪流挑一個，
來回票的天數取設定範圍的中間值。整體呼叫次數再由 budget 模組控管。
文件：https://serpapi.com/google-flights-api
"""
from __future__ import annotations

from datetime import date, timedelta

import requests

from ..models import FareQuery, FareResult
from ..secrets import get_secret, redact
from .base import FareSource, SourceError

API_URL = "https://serpapi.com/search"
KEY_ENV = "SERPAPI_KEY"


def _fridays(month: str, after: date) -> list[date]:
    y, m = (int(x) for x in month.split("-"))
    d = date(y, m, 1)
    out = []
    while d.month == m:
        if d.weekday() == 4 and d > after:
            out.append(d)
        d += timedelta(days=1)
    return out


class SerpApiSource(FareSource):
    name = "serpapi"
    cost_per_call = 1

    def __init__(self, session: requests.Session | None = None, today: date | None = None) -> None:
        self.session = session or requests.Session()
        self.today = today or date.today()

    def available(self) -> bool:
        return get_secret(KEY_ENV) is not None

    def plan(self, query: FareQuery) -> list[FareQuery]:
        fridays = _fridays(query.depart_month, self.today)
        if not fridays:
            return []
        dep = fridays[self.today.toordinal() % len(fridays)]
        ret = None
        if not query.one_way:
            length = (query.trip_days[0] + query.trip_days[1]) // 2
            ret = (dep + timedelta(days=length - 1)).isoformat()
        return [
            FareQuery(
                origin=query.origin,
                destination=query.destination,
                depart_month=query.depart_month,
                one_way=query.one_way,
                trip_days=query.trip_days,
                currency=query.currency,
                depart_date=dep.isoformat(),
                return_date=ret,
            )
        ]

    def search(self, query: FareQuery) -> list[FareResult]:
        if not query.depart_date:
            raise SourceError("SerpApi 查詢需要指定日期")
        params = {
            "engine": "google_flights",
            "departure_id": query.origin,
            "arrival_id": query.destination,
            "outbound_date": query.depart_date,
            "type": "2" if query.one_way else "1",
            "currency": query.currency.upper(),
            "hl": "zh-TW",
            "gl": "tw",
            "api_key": get_secret(KEY_ENV) or "",
        }
        if not query.one_way:
            params["return_date"] = query.return_date
        try:
            resp = self.session.get(API_URL, params=params, timeout=60)
        except requests.RequestException as exc:
            # 例外訊息可能含完整網址（內有 api_key），只回報類型
            raise SourceError(f"連線失敗：{type(exc).__name__}") from None
        if resp.status_code != 200:
            raise SourceError(f"HTTP {resp.status_code}：{redact(resp.text[:200])}")
        try:
            payload = resp.json()
        except ValueError:
            raise SourceError("回應不是 JSON") from None
        if payload.get("error"):
            # 「沒有結果」也會用 error 欄位回報，視為空結果
            if "no results" in str(payload["error"]).lower():
                return []
            raise SourceError(f"API 回報失敗：{redact(str(payload['error'])[:200])}")

        results: list[FareResult] = []
        for group in ("best_flights", "other_flights"):
            for offer in payload.get(group) or []:
                fare = self._parse(offer, query)
                if fare is not None:
                    results.append(fare)
        return results

    @staticmethod
    def _parse(offer: dict, query: FareQuery) -> FareResult | None:
        try:
            price = int(offer["price"])
            legs = offer.get("flights") or []
        except (KeyError, TypeError, ValueError):
            return None
        if not legs:
            return None
        first, last = legs[0], legs[-1]
        flight_no = str(first.get("flight_number") or "")
        airline = flight_no.split()[0] if flight_no else None
        return FareResult(
            source=SerpApiSource.name,
            origin=str((first.get("departure_airport") or {}).get("id") or query.origin).upper(),
            destination=str((last.get("arrival_airport") or {}).get("id") or query.destination).upper(),
            depart_date=query.depart_date or "",
            return_date=None if query.one_way else query.return_date,
            price=price,
            currency=query.currency.upper(),
            airline=airline,
            # 來回票只看得到去程的轉機數（回程要再花一次額度查），先以去程為準
            stops=len(legs) - 1,
        )
