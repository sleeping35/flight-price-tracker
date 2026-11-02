"""指令入口。

  python -m tracker regions                       由 config/regions.yaml 產生 docs/data/regions.json
  python -m tracker holidays [--year 2027] [--url URL]   更新假日 JSON（在 GitHub Actions 執行）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from . import holidays as hol
from .config import DATA_DIR, ConfigError, load_regions, regions_json


def cmd_regions(_: argparse.Namespace) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = regions_json(load_regions())
    (DATA_DIR / "regions.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("已更新 docs/data/regions.json")
    return 0


def cmd_holidays(args: argparse.Namespace) -> int:
    this_year = datetime.now(ZoneInfo("Asia/Taipei")).year
    years = [args.year] if args.year else [this_year, this_year + 1]
    code = 0
    for y in years:
        try:
            data = hol.fetch_year(y, url=args.url if args.year else None)
        except Exception as exc:
            exists = (DATA_DIR / "holidays" / f"{y}.json").exists()
            # 明年尚未公告是正常的；今年抓不到且沒有舊檔才算錯誤
            level = "警告" if (y > this_year or exists) else "錯誤"
            print(f"{level}：{y} 年假日資料更新失敗：{type(exc).__name__}：{exc}")
            if level == "錯誤":
                code = 1
            continue
        path = hol.write_year(DATA_DIR, data)
        off = sum(1 for d in data["days"].values() if d["off"])
        print(f"已寫入 {path.name}：全年 {len(data['days'])} 天，放假 {off} 天")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tracker")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("regions", help="產生 regions.json")
    p.set_defaults(func=cmd_regions)
    p = sub.add_parser("holidays", help="更新假日 JSON")
    p.add_argument("--year", type=int, help="西元年，不填則更新今年與明年")
    p.add_argument("--url", help="直接指定 CSV 網址（需搭配 --year）")
    p.set_defaults(func=cmd_holidays)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"設定檔錯誤：{exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
