"""資料來源的統一介面。"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import FareQuery, FareResult


class SourceError(Exception):
    """資料來源呼叫失敗。訊息必須已經不含金鑰。"""


class FareSource(ABC):
    name: str = ""
    # 每次呼叫要扣多少額度（用於 budget 統計與上限控制）
    cost_per_call: int = 1

    @abstractmethod
    def available(self) -> bool:
        """金鑰是否已設定。"""

    @abstractmethod
    def plan(self, query: FareQuery) -> list[FareQuery]:
        """把一個月份查詢拆成實際要呼叫 API 的次數單位。

        Travelpayouts 一次就能拿整個月，回傳 [query]；
        SerpApi 一次只能查一組日期，由實作自行決定要抽樣哪些日期。
        """

    @abstractmethod
    def search(self, query: FareQuery) -> list[FareResult]:
        """呼叫一次 API。失敗時丟出 SourceError。"""
