"""資料來源共用的資料類別。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True)
class FareQuery:
    """一次查詢：一個航線、一個出發月份、一種票種。"""

    origin: str                 # 出發機場，例如 TPE
    destination: str            # 目的機場，例如 KIX
    depart_month: str           # "2026-12"
    one_way: bool               # True = 單程
    trip_days: tuple[int, int]  # 來回票的天數範圍（含頭尾）；單程不使用
    currency: str = "TWD"
    # 只有逐日查詢的來源（SerpApi）會用到：指定的去程／回程日期
    depart_date: str | None = None
    return_date: str | None = None


@dataclass
class FareResult:
    """所有資料來源統一輸出的票價格式。"""

    source: str                 # "travelpayouts" / "serpapi"
    origin: str
    destination: str
    depart_date: str            # "2026-12-24"
    return_date: str | None     # 單程為 None
    price: int                  # 整數，單位為 currency
    currency: str
    airline: str | None         # IATA 航空公司代碼
    stops: int                  # 0 = 直飛；來回票取去回程中較多的一段

    @property
    def days(self) -> int | None:
        """旅遊天數（含出發與回程當天），單程為 None。"""
        if not self.return_date:
            return None
        d0 = date.fromisoformat(self.depart_date)
        d1 = date.fromisoformat(self.return_date)
        return (d1 - d0).days + 1

    def to_dict(self) -> dict:
        return asdict(self)
