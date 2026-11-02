"""資料來源註冊表。新增來源時，實作 FareSource 並加進 SOURCES。"""
from __future__ import annotations

from .base import FareSource, SourceError
from .serpapi import SerpApiSource
from .travelpayouts import TravelpayoutsSource

SOURCES: dict[str, type[FareSource]] = {
    TravelpayoutsSource.name: TravelpayoutsSource,
    SerpApiSource.name: SerpApiSource,
}

__all__ = ["FareSource", "SourceError", "SOURCES"]
