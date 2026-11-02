"""Travelpayouts / Aviasales Data API。

使用 /aviasales/v3/prices_for_dates：回傳 Aviasales 使用者近期搜尋過的快取票價，
一次可拿到一個出發月份內的多筆日期組合，適合每天批次掃描。
文件：https://support.travelpayouts.com/hc/en-us/articles/203956163
速率限制：此端點每分鐘 600 次。
"""
from __future__ import annotations

import time

import requests

from ..models import FareQuery, FareResult
from ..secrets import get_secret, redact
from .base import FareSource, SourceError

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
TOKEN_ENV = "TRAVELPAYOUTS_TOKEN"


class TravelpayoutsSource(FareSource):
    name = "travelpayouts"
    cost_per_call = 1
    min_interval_sec = 0.2  # 每秒最多 5 次，遠低於每分鐘 600 次的限制

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self._last_call = 0.0

    def available(self) -> bool:
        return get_secret(TOKEN_ENV) is not None

    def plan(self, query: FareQuery) -> list[FareQuery]:
        return [query]

    def _get(self, params: dict) -> dict:
        wait = self.min_interval_sec - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        headers = {"X-Access-Token": get_secret(TOKEN_ENV) or "", "Accept-Encoding": "gzip"}
        for attempt in range(3):
            self._last_call = time.monotonic()
            try:
                resp = self.session.get(API_URL, params=params, headers=headers, timeout=30)
            except requests.RequestException as exc:
                # 不直接印出例外物件，避免帶出請求細節
                raise SourceError(f"連線失敗：{type(exc).__name__}") from None
            if resp.status_code == 429 and attempt < 2:
                time.sleep(61)  # 超過速率限制會被擋到這一分鐘結束
                continue
            if resp.status_code != 200:
                raise SourceError(f"HTTP {resp.status_code}：{redact(resp.text[:200])}")
            try:
                return resp.json()
            except ValueError:
                raise SourceError("回應不是 JSON") from None
        raise SourceError("連續被速率限制擋下")

    def search(self, query: FareQuery) -> list[FareResult]:
        params = {
            "origin": query.origin,
            "destination": query.destination,
            "departure_at": query.depart_month,
            "one_way": "true" if query.one_way else "false",
            "direct": "false",
            "currency": query.currency.lower(),
            "sorting": "price",
            "unique": "false",
            "limit": 1000,
            "page": 1,
        }
        payload = self._get(params)
        if not payload.get("success", False):
            raise SourceError(f"API 回報失敗：{redact(str(payload.get('error', ''))[:200])}")
        currency = str(payload.get("currency") or query.currency).upper()
        results: list[FareResult] = []
        for row in payload.get("data") or []:
            fare = self._parse(row, query, currency)
            if fare is not None:
                results.append(fare)
        return results

    @staticmethod
    def _parse(row: dict, query: FareQuery, currency: str) -> FareResult | None:
        try:
            dep = str(row["departure_at"])[:10]
            ret_raw = row.get("return_at")
            ret = str(ret_raw)[:10] if ret_raw and not query.one_way else None
            price = int(round(float(row["price"])))
        except (KeyError, TypeError, ValueError):
            return None
        if not dep.startswith(query.depart_month):
            return None
        if not query.one_way and not ret:
            return None
        stops = max(int(row.get("transfers") or 0), int(row.get("return_transfers") or 0))
        return FareResult(
            source=TravelpayoutsSource.name,
            # 用實際機場（例如城市碼 TPE 可能涵蓋 TSA），沒有時退回查詢值
            origin=str(row.get("origin_airport") or query.origin).upper(),
            destination=str(row.get("destination_airport") or query.destination).upper(),
            depart_date=dep,
            return_date=ret,
            price=price,
            currency=currency,
            airline=row.get("airline") or None,
            stops=stops,
        )
