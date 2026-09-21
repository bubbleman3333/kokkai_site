"""国会会議録検索システム（国立国会図書館）の API から会議録を取り込む。

API はキー不要。https://kokkai.ndl.go.jp/api.html
- meeting_list … 会議の一覧（発言は話者名だけ）。1 回 100 件まで。
- meeting      … 会議 1 件の全発言。1 回 10 件までだが、重いので 1 件ずつ取る。

「短時間に大量に叩かないでほしい」と案内されているので、1 秒に 1 回程度に抑える。
会議録は会議の 3〜5 週間後に載るので、毎日「直近 1 年の一覧」を取り直して、
まだ持っていない会議だけ詳細を取る。
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from .model import JST, compact

API = "https://kokkai.ndl.go.jp/api"
DATA_DIR = Path("data/meetings")
DAYS_BACK = 365


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "kokkai-watch/1.0 (static site generator; https://github.com/bubbleman3333/kokkai_site)"
    return s


def _get(session: requests.Session, path: str, params: dict, tries: int = 6) -> dict:
    """GET して JSON を返す。混んでいる・切れたときは間を空けて何度かやり直す。"""
    last: Exception | None = None
    wait = 3.0
    for _ in range(tries):
        try:
            r = session.get(f"{API}/{path}", params={**params, "recordPacking": "json"}, timeout=180)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(float(r.headers.get("Retry-After") or wait))
                wait = min(wait * 2, 60)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 - ネットワーク系は何でも再試行
            last = e
            time.sleep(wait)
            wait = min(wait * 2, 60)
    raise RuntimeError(f"国会会議録 API に失敗: {path} {params}: {last}")


def list_meetings(session: requests.Session, frm: str, until: str, sleep: float = 1.0, log=print) -> list[dict]:
    """期間内の会議を一覧する。戻り値は API の meetingRecord（発言本文は入っていない）。"""
    out: list[dict] = []
    pos = 1
    while True:
        data = _get(session, "meeting_list", {"from": frm, "until": until, "maximumRecords": 100, "startRecord": pos})
        rows = data.get("meetingRecord") or []
        out.extend(rows)
        nxt = data.get("nextRecordPosition")
        if not nxt or not rows:
            break
        pos = nxt
        time.sleep(sleep)
    log(f"一覧: {len(out)} 件（{frm} 〜 {until}）")
    return out


def fetch_meeting(session: requests.Session, issue_id: str) -> dict | None:
    data = _get(session, "meeting", {"issueID": issue_id, "maximumRecords": 1})
    rows = data.get("meetingRecord") or []
    return rows[0] if rows else None


def prune(data_dir: Path, frm: str) -> int:
    """掲載は直近 1 年分なので、期間から外れた会議のファイルを消す。

    これをしないと data/ が永遠に増え続け、サイトにも 1 年より前の会議が残ってしまう。
    """
    dropped = 0
    for path in data_dir.glob("*.json"):
        try:
            day = json.loads(path.read_text(encoding="utf-8")).get("date") or ""
        except Exception:  # noqa: BLE001 - 読めないファイルは消して取り直す
            day = ""
        if not day or day < frm:
            path.unlink()
            dropped += 1
    return dropped


def sync(data_dir: Path = DATA_DIR, days: int = DAYS_BACK, sleep: float = 1.0,
         limit: int | None = None, today: date | None = None, log=print) -> tuple[int, int]:
    """直近 days 日の会議を取り込む。戻り値は (新規件数, 取り直した件数)。

    メモリが小さい環境でも動くよう、1 件取っては必要な項目だけにして書き出し、生データは捨てる。
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    today = today or datetime.now(JST).date()
    frm = (today - timedelta(days=days)).isoformat()
    until = (today - timedelta(days=1)).isoformat()

    dropped = prune(data_dir, frm)
    if dropped:
        log(f"1 年より前になった会議を {dropped} 件外した")

    session = _session()
    rows = list_meetings(session, frm, until, sleep=sleep, log=log)

    todo: list[tuple[str, bool]] = []  # (issueID, 既に持っているか)
    for row in rows:
        issue_id = row.get("issueID")
        if not issue_id:
            continue
        path = data_dir / f"{issue_id}.json"
        if not path.exists():
            todo.append((issue_id, False))
            continue
        # 発言数が変わっていたら会議録が差し替わったとみなして取り直す
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 壊れていたら取り直す
            todo.append((issue_id, True))
            continue
        if old.get("speechTotal") != len(row.get("speechRecord") or []):
            todo.append((issue_id, True))
    if limit is not None:
        todo = todo[:limit]
    log(f"詳細を取る: {len(todo)} 件")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new = updated = 0
    for i, (issue_id, existed) in enumerate(todo, 1):
        raw = fetch_meeting(session, issue_id)
        if raw is None:
            log(f"  取れなかった: {issue_id}")
            continue
        row = compact(raw, now)
        del raw
        (data_dir / f"{issue_id}.json").write_text(json.dumps(row, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if existed:
            updated += 1
        else:
            new += 1
        if i % 20 == 0 or i == len(todo):
            log(f"  {i}/{len(todo)}  {row['date']} {row['house']}{row['meeting']}{row['issue']}")
        time.sleep(sleep)
    log(f"新規 {new} 件、取り直し {updated} 件")
    return new, updated
