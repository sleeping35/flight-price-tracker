"""金鑰讀取與 log 遮蔽。

所有會被印出的文字都要先經過 redact()，確保金鑰不會出現在 Actions log。
GitHub 本身也會遮蔽 Secrets，這是第二道保險。
"""
from __future__ import annotations

import os
import re

SECRET_ENV_NAMES = ("TRAVELPAYOUTS_TOKEN", "SERPAPI_KEY")

# 網址參數裡常見的金鑰欄位名稱
_KEY_PARAM_RE = re.compile(r"((?:api_key|token|access_token)=)[^&\s]+", re.IGNORECASE)


def get_secret(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def redact(text: object) -> str:
    s = str(text)
    for name in SECRET_ENV_NAMES:
        value = get_secret(name)
        if value:
            s = s.replace(value, "***")
    return _KEY_PARAM_RE.sub(r"\1***", s)


def log(*parts: object) -> None:
    print(redact(" ".join(str(p) for p in parts)), flush=True)
