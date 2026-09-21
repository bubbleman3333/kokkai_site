"""使い方:
  python -m kokkai fetch [--days 365] [--limit N]        会議録を取り込む
  python -m kokkai build [--out dist] [--site-url URL]   サイトを生成
  python -m kokkai all                                    fetch → build
  python -m kokkai stats                                  取り込み済みの様子を見る
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from .build import ROOT, Builder, load_config, load_meetings
from .ndl import sync


def main(argv: list[str] | None = None) -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="kokkai", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--days", type=int, default=365, help="何日前までさかのぼるか")
    f.add_argument("--limit", type=int, default=None, help="詳細を取る件数の上限（試し用）")
    f.add_argument("--sleep", type=float, default=1.0)
    b = sub.add_parser("build")
    b.add_argument("--out", default="dist")
    b.add_argument("--site-url", default=None)
    a = sub.add_parser("all")
    a.add_argument("--days", type=int, default=365)
    a.add_argument("--out", default="dist")
    a.add_argument("--site-url", default=None)
    sub.add_parser("stats")
    args = p.parse_args(argv)

    site = load_config(ROOT)
    if args.cmd in ("fetch", "all"):
        sync(ROOT / "data" / "meetings", days=args.days, limit=getattr(args, "limit", None),
             sleep=getattr(args, "sleep", 1.0))
    if args.cmd in ("build", "all"):
        n = Builder(Path(args.out), args.site_url or site["site_url"]).build()
        print(f"{n} 件の会議から {args.out}/ を生成した")
    if args.cmd == "stats":
        meetings = load_meetings(ROOT / "data" / "meetings")
        if not meetings:
            print("まだ 1 件も取り込んでいない")
            return
        days = {m.date_str for m in meetings}
        speakers = Counter()
        for m in meetings:
            for s in m.speakers:
                speakers[s.name] += s.count
        print(f"会議 {len(meetings)} 件 / 開催日 {len(days)} 日 / 発言者 {len(speakers)} 人")
        print(f"期間: {min(days)} 〜 {max(days)}")
        for name, c in speakers.most_common(10):
            print(f"  {c:5d}  {name}")


if __name__ == "__main__":
    main()
