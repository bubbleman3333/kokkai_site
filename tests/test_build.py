"""ビルドが一式のファイルを出すことのテスト。"""
import json
from datetime import datetime
from pathlib import Path

from kokkai.build import Builder, load_meetings, merge_words, rank_speakers
from kokkai.model import JST, compact, speaker_slug
from test_model import raw_meeting


def make_data(tmp_path: Path) -> Path:
    data = tmp_path / "meetings"
    data.mkdir()
    rows = [
        raw_meeting(),
        raw_meeting(issueID="122105261X00920260310", issue="第9号", date="2026-03-10"),
        raw_meeting(issueID="122205261X00120260415", nameOfHouse="参議院", nameOfMeeting="内閣委員会",
                    issue="第1号", date="2026-04-15"),
    ]
    for r in rows:
        (data / f"{r['issueID']}.json").write_text(
            json.dumps(compact(r, "2026-09-21T00:00:00Z"), ensure_ascii=False), encoding="utf-8")
    return data


def build(tmp_path: Path):
    data = make_data(tmp_path)
    out = tmp_path / "dist"
    now = datetime(2026, 5, 1, tzinfo=JST)
    n = Builder(out, "https://example.com/site", now=now, data_dir=data).build()
    return out, n


def test_build_generates_every_kind_of_page(tmp_path):
    out, n = build(tmp_path)
    assert n == 3
    slug = speaker_slug("山田美樹")
    for path in ("index.html", "m/122105261X00820260309/index.html", "day/2026-03-09/index.html",
                 "day/index.html", "committee/shugiin-yosan/index.html", "committee/sangiin-naikaku/index.html",
                 "committee/index.html", f"speaker/{slug}/index.html", "speaker/index.html",
                 "monthly/2026-03/index.html", "monthly/index.html", "search/index.html",
                 "about/index.html", "privacy/index.html", "404.html",
                 "search.json", "sitemap.xml", "feed.xml", "robots.txt", ".nojekyll",
                 "static/style.css", "static/favicon.svg"):
        assert (out / path).exists(), path


def test_meeting_page_contents(tmp_path):
    out, _ = build(tmp_path)
    page = (out / "m/122105261X00820260309/index.html").read_text(encoding="utf-8")
    assert "2026年3月9日（月）" in page
    assert "予算委員会" in page and "第8号" in page
    assert "令和八年度一般会計予算" in page            # 議題
    assert "山田美樹" in page and "坂本哲志" in page    # 発言者一覧
    assert "物価" in page                              # よく出た語
    assert "https://kokkai.ndl.go.jp/txt/122105261X00820260309" in page  # 出典リンク
    assert "国会会議録検索システム（国立国会図書館）" in page
    assert '"@type":"Event"' in page and '"@type":"BreadcrumbList"' in page
    assert 'href="https://example.com/site/static/style.css"' in page
    assert '<link rel="canonical" href="https://example.com/site/m/122105261X00820260309/">' in page


def test_day_and_speaker_and_search_json(tmp_path):
    out, _ = build(tmp_path)
    day = (out / "day/2026-03-09/index.html").read_text(encoding="utf-8")
    assert "2026年3月9日（月）の国会" in day and "予算委員会" in day

    sp = (out / f"speaker/{speaker_slug('山田美樹')}/index.html").read_text(encoding="utf-8")
    assert "山田美樹の国会発言" in sp and "2026-03" in sp and "エネルギー" in sp

    rows = json.loads((out / "search.json").read_text(encoding="utf-8"))
    assert {r["i"] for r in rows} == {"122105261X00820260309", "122105261X00920260310", "122205261X00120260415"}
    assert "山田美樹" in rows[0]["p"]

    sitemap = (out / "sitemap.xml").read_text(encoding="utf-8")
    assert "https://example.com/site/m/122105261X00820260309/" in sitemap
    assert "https://example.com/site/committee/sangiin-naikaku/" in sitemap
    feed = (out / "feed.xml").read_text(encoding="utf-8")
    assert "<item>" in feed and "内閣委員会" in feed


def test_index_says_when_the_latest_meeting_was(tmp_path):
    out, _ = build(tmp_path)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "2026年4月15日（水）" in index
    assert "会期中です" in index  # now=2026-05-01 なので直近 60 日以内


def test_rank_speakers_and_merge_words(tmp_path):
    data = make_data(tmp_path)
    meetings = load_meetings(data)
    assert [m.date_str for m in meetings] == ["2026-04-15", "2026-03-10", "2026-03-09"]
    rows = rank_speakers(meetings, 5)
    assert rows[0][0] == "坂本哲志" and rows[0][2] == 6  # 3 会議 × 2 回
    assert dict(merge_words(meetings))["物価"] == 9  # 1 会議 3 回 × 3 会議
