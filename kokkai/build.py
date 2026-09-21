"""data/meetings/ から dist/ に静的サイトを書き出す。"""
from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .model import (HOUSES, JST, KIND_ORDER, MEETINGS, Meeting, Speaker, fmt_day, fmt_month,
                    meeting_kind, slug_of, speaker_slug)

ROOT = Path(__file__).resolve().parent.parent
PER_PAGE = 60
FEED_ITEMS = 40


def load_meetings(data_dir: Path) -> list[Meeting]:
    out: list[Meeting] = []
    for path in sorted(data_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 壊れたファイルは無視して残りを生成する
            continue
        if raw.get("issueID") and raw.get("date"):
            out.append(Meeting.from_raw(raw))
    out.sort(key=lambda m: (m.day, m.house, m.name, m.issue), reverse=True)
    return out


def load_config(root: Path = ROOT) -> dict:
    return json.loads((root / "config" / "site.json").read_text(encoding="utf-8"))


@dataclass
class SpeakerStat:
    """1 人の議員（または大臣・参考人）の 1 年分のまとめ。"""
    name: str
    yomi: str = ""
    groups: Counter = field(default_factory=Counter)
    positions: Counter = field(default_factory=Counter)
    roles: Counter = field(default_factory=Counter)
    count: int = 0
    chars: int = 0
    words: Counter = field(default_factory=Counter)
    by_month: Counter = field(default_factory=Counter)
    rows: list[tuple[Meeting, int, int]] = field(default_factory=list)  # (会議, 発言回数, 文字数)

    def add(self, meeting: Meeting, sp: Speaker) -> None:
        if sp.yomi and not self.yomi:
            self.yomi = sp.yomi
        if sp.group:
            self.groups[sp.group] += sp.count
        if sp.position:
            self.positions[sp.position] += sp.count
        if sp.role:
            self.roles[sp.role] += sp.count
        self.count += sp.count
        self.chars += sp.chars
        self.by_month[meeting.month] += sp.count
        for w, c in sp.words:
            self.words[w] += c
        self.rows.append((meeting, sp.count, sp.chars))

    @property
    def slug(self) -> str:
        return speaker_slug(self.name)

    @property
    def path(self) -> str:
        return f"speaker/{self.slug}/"

    @property
    def group(self) -> str:
        return self.groups.most_common(1)[0][0] if self.groups else ""

    @property
    def position(self) -> str:
        return self.positions.most_common(1)[0][0] if self.positions else ""

    @property
    def role(self) -> str:
        return self.roles.most_common(1)[0][0] if self.roles else ""

    @property
    def label(self) -> str:
        return self.position or self.role or self.group or ""

    @property
    def meetings(self) -> int:
        return len(self.rows)


@dataclass
class Committee:
    """院 + 会議名。衆院の内閣委員会と参院の内閣委員会は別ものとして扱う。"""
    house: str
    name: str
    rows: list[Meeting] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return f"{slug_of(HOUSES, self.house)}-{slug_of(MEETINGS, self.name)}"

    @property
    def path(self) -> str:
        return f"committee/{self.slug}/"

    @property
    def title(self) -> str:
        return f"{self.house} {self.name}"

    @property
    def kind(self) -> str:
        return meeting_kind(self.name)


def rank_speakers(meetings: list[Meeting], limit: int = 20) -> list[tuple[str, str, int, int]]:
    """(名前, 会派か役職, 発言回数, 文字数) を発言回数の多い順に返す。"""
    counts: Counter = Counter()
    chars: Counter = Counter()
    label: dict[str, str] = {}
    for m in meetings:
        for sp in m.speakers:
            counts[sp.name] += sp.count
            chars[sp.name] += sp.chars
            if sp.name not in label and sp.label:
                label[sp.name] = sp.label
    rows = [(n, label.get(n, ""), c, chars[n]) for n, c in counts.items()]
    rows.sort(key=lambda t: (-t[2], -t[3], t[0]))
    return rows[:limit]


def moji(n: int | float) -> str:
    """文字数の表示。1 万字を超えたら「12.3 万」、それ以下は「3,400」。"""
    n = int(n or 0)
    return f"{n / 10000:.1f}万" if n >= 10000 else f"{n:,}"


def merge_words(meetings: list[Meeting], limit: int = 30) -> list[tuple[str, int]]:
    counts: Counter = Counter()
    for m in meetings:
        for w, c in m.words:
            counts[w] += c
    return counts.most_common(limit)


class Builder:
    def __init__(self, out_dir: Path, site_url: str, now: datetime | None = None,
                 data_dir: Path | None = None, root: Path = ROOT):
        self.out = out_dir
        self.site_url = site_url.rstrip("/")
        self.now = now or datetime.now(JST)
        self.data_dir = data_dir or root / "data" / "meetings"
        self.root = root
        self.site = load_config(root)
        self.env = Environment(loader=FileSystemLoader(root / "templates"),
                               autoescape=select_autoescape(["html", "xml"]))
        self.env.filters["day"] = fmt_day
        self.env.filters["month"] = fmt_month
        self.env.filters["man"] = lambda n: f"{n:,}"
        self.env.filters["moji"] = moji
        self.env.globals.update(url=self.url, site=self.site, now=self.now, speaker_slug=speaker_slug)
        self.sitemap: list[tuple[str, date | None]] = []

    # ---- 部品 ----
    def url(self, path: str = "") -> str:
        return f"{self.site_url}/{path.lstrip('/')}"

    def write(self, path: str, text: str) -> None:
        target = self.out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def render(self, template: str, path: str, *, noindex: bool = False, lastmod: date | None = None, **ctx) -> None:
        canonical = self.url(path.replace("index.html", ""))
        html = self.env.get_template(template).render(canonical=canonical, noindex=noindex, **ctx)
        self.write(path, html)
        if not noindex:
            self.sitemap.append((canonical, lastmod))

    def paginate(self, template: str, base: str, items: list, *, title: str, description: str, **ctx) -> None:
        pages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
        for i in range(pages):
            chunk = items[i * PER_PAGE:(i + 1) * PER_PAGE]
            path = f"{base}index.html" if i == 0 else f"{base}page/{i + 1}/index.html"
            self.render(template, path, title=title if i == 0 else f"{title}（{i + 1}ページ目）",
                        description=description, items=chunk, page=i + 1, pages=pages, base=base,
                        count=len(items), **ctx)

    # ---- 本体 ----
    def build(self) -> int:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        shutil.copytree(self.root / "static", self.out / "static")

        meetings = load_meetings(self.data_dir)
        by_day: dict[str, list[Meeting]] = defaultdict(list)
        by_month: dict[str, list[Meeting]] = defaultdict(list)
        by_committee: dict[str, Committee] = {}
        by_session: dict[int, list[Meeting]] = defaultdict(list)
        speakers: dict[str, SpeakerStat] = {}

        for m in meetings:
            by_day[m.date_str].append(m)
            by_month[m.month].append(m)
            com = by_committee.setdefault(m.committee_slug, Committee(m.house, m.name))
            com.rows.append(m)
            if m.session:
                by_session[m.session].append(m)
            for sp in m.speakers:
                stat = speakers.setdefault(sp.name, SpeakerStat(sp.name))
                stat.add(m, sp)

        days = sorted(by_day.keys(), reverse=True)
        months = sorted(by_month.keys(), reverse=True)
        latest_day = date.fromisoformat(days[0]) if days else None
        # 会議録は会議の 3〜5 週間後に載るので、「開会中か」は最後の会議からの日数では測れない。
        # 直近 60 日に会議があれば会期中とみなす。
        in_session = bool(latest_day and (self.now.date() - latest_day).days <= 60)

        week_start = (latest_day - timedelta(days=6)) if latest_day else None
        week_meetings = [m for m in meetings if week_start and m.day >= week_start] if latest_day else []
        week_ranking = rank_speakers(week_meetings, 20)
        recent_meetings = [m for m in meetings if latest_day and m.day >= latest_day - timedelta(days=30)]
        hot_words = merge_words(recent_meetings, 40)

        committees = sorted(by_committee.values(),
                            key=lambda c: (list(HOUSES).index(c.house) if c.house in HOUSES else 9,
                                           KIND_ORDER.index(c.kind), -len(c.rows), c.name))
        committee_index = [(c, len(c.rows)) for c in committees]
        month_index = [(mk, len(by_month[mk])) for mk in months]
        day_index = [(d, len(by_day[d])) for d in days]
        speaker_list = sorted(speakers.values(), key=lambda s: (-s.count, -s.chars, s.name))

        stats = dict(meetings=len(meetings), days=len(days), speakers=len(speakers),
                     speeches=sum(m.speech_total for m in meetings),
                     chars=sum(m.chars for m in meetings),
                     committees=len(committees),
                     latest=latest_day, in_session=in_session,
                     sessions=sorted(by_session.keys(), reverse=True))
        self.env.globals.update(stats=stats, committee_index=committee_index[:24], month_index=month_index[:12],
                                sidebar_days=day_index[:8], sidebar_ranking=week_ranking[:8],
                                latest_day=latest_day, in_session=in_session)

        # ---- 会議ごと ----
        for m in meetings:
            same_day = [x for x in by_day[m.date_str] if x is not m]
            siblings = by_committee[m.committee_slug].rows
            idx = siblings.index(m)
            self.render("meeting.html", f"{m.path}index.html", m=m, same_day=same_day,
                        prev=siblings[idx + 1] if idx + 1 < len(siblings) else None,
                        next=siblings[idx - 1] if idx > 0 else None,
                        committee=by_committee[m.committee_slug], lastmod=m.day)

        # ---- 日ごと ----
        for i, d in enumerate(days):
            rows = sorted(by_day[d], key=lambda x: (list(HOUSES).index(x.house) if x.house in HOUSES else 9,
                                                    KIND_ORDER.index(x.kind), x.name))
            self.render("day.html", f"day/{d}/index.html", d=date.fromisoformat(d), rows=rows,
                        rank_rows=rank_speakers(rows, 30), words=merge_words(rows, 30),
                        prev=days[i + 1] if i + 1 < len(days) else None,
                        next=days[i - 1] if i > 0 else None, lastmod=date.fromisoformat(d))
        self.paginate("days.html", "day/", day_index, title="国会が開かれた日の一覧",
                      description="直近 1 年で本会議・委員会が開かれた日を新しい順に並べています。日付をたどると、その日の会議と発言者ランキングが見られます。")

        # ---- 委員会ごと ----
        for c in committees:
            self.render("committee.html", f"{c.path}index.html", c=c, rows=c.rows,
                        rank_rows=rank_speakers(c.rows, 30), words=merge_words(c.rows, 30),
                        lastmod=c.rows[0].day)
        self.render("committees.html", "committee/index.html", title="委員会・本会議の一覧",
                    description="衆議院・参議院の本会議と各委員会の一覧です。開催回数の多い順に並べています。",
                    rows=committee_index)

        # ---- 議員ごと ----
        for s in speaker_list:
            months_of = sorted(s.by_month.items())
            peak = max((c for _, c in months_of), default=1)
            self.render("speaker.html", f"{s.path}index.html", s=s, months=months_of, peak=peak,
                        rows=sorted(s.rows, key=lambda t: t[0].day, reverse=True)[:200],
                        lastmod=max((t[0].day for t in s.rows), default=None))
        self.paginate("speakers.html", "speaker/", speaker_list, title="発言した議員・大臣の一覧",
                      description="直近 1 年の国会で発言した議員・大臣・参考人を、発言回数の多い順に並べています。")

        # ---- 月ごと ----
        for mk in months:
            rows = by_month[mk]
            mdays = sorted({x.date_str for x in rows}, reverse=True)
            self.render("monthly.html", f"monthly/{mk}/index.html", mk=mk, rows=rows, mdays=mdays,
                        by_day=by_day, rank_rows=rank_speakers(rows, 30), words=merge_words(rows, 30),
                        committees=sorted(Counter((x.house, x.name) for x in rows).items(), key=lambda t: -t[1]),
                        lastmod=max(x.day for x in rows))
        self.render("months.html", "monthly/index.html", title="月ごとの国会まとめ",
                    description="月ごとに、開かれた会議の数・よく発言した議員・よく出た語をまとめています。",
                    rows=month_index)

        # ---- そのほかのページ ----
        self.render("index.html", "index.html",
                    today_meetings=by_day[days[0]] if days else [],
                    recent_days=[(d, by_day[d]) for d in days[:6]],
                    week_ranking=week_ranking, hot_words=hot_words,
                    all_committees=committee_index, months=month_index)
        self.render("search.html", "search/index.html", title="国会の会議を検索する",
                    description="会議名・発言者・キーワードで、直近 1 年の国会の会議を絞り込めます。")
        self.render("about.html", "about/index.html", title="このサイトについて",
                    description="国会ウォッチは、国会会議録検索システム（国立国会図書館）の公開 API を使って、国会の会議録を毎日自動でまとめている個人サイトです。")
        self.render("privacy.html", "privacy/index.html", title="プライバシーポリシー",
                    description="国会ウォッチのプライバシーポリシーです。")
        self.write("404.html", self.env.get_template("404.html").render(canonical=self.url("404.html"), noindex=True))

        # ---- 機械向け ----
        self.write("search.json", self.search_json(meetings))
        self.write_sitemap()
        self.write_feed(meetings[:FEED_ITEMS])
        self.write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {self.url('sitemap.xml')}\n")
        self.write(".nojekyll", "")
        return len(meetings)

    # ---- 機械向けの中身 ----
    def search_json(self, meetings: list[Meeting]) -> str:
        rows = []
        for m in meetings:
            rows.append({
                "i": m.issue_id, "h": m.house, "m": m.name, "n": m.issue, "d": m.date_str,
                "s": m.session, "p": [sp.name for sp in m.speakers[:30]],
                "w": [w for w, _ in m.words[:12]], "a": m.agenda[:4], "c": m.speech_total,
            })
        return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))

    def write_sitemap(self) -> None:
        rows = []
        for loc, lastmod in self.sitemap:
            lm = f"<lastmod>{lastmod.isoformat()}</lastmod>" if lastmod else ""
            rows.append(f"<url><loc>{escape(loc)}</loc>{lm}</url>")
        self.write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                   + "\n".join(rows) + "\n</urlset>\n")

    def write_feed(self, meetings: list[Meeting]) -> None:
        entries = []
        for m in meetings:
            pub = datetime(m.day.year, m.day.month, m.day.day, 9, tzinfo=JST).strftime("%a, %d %b %Y %H:%M:%S %z")
            link = escape(self.url(m.path))
            top = "、".join(f"{sp.name}（{sp.count}回）" for sp in m.top_speakers(5))
            desc = f"{fmt_day(m.day)}の{m.house}{m.name}{m.issue}。発言 {m.speech_total} 件。よく発言したのは {top}。"
            if m.agenda:
                desc += f" 議題: {'／'.join(m.agenda[:3])}"
            entries.append(f"<item><title>{escape(fmt_day(m.day))} {escape(m.title)}</title>"
                           f"<link>{link}</link><guid>{link}</guid><pubDate>{pub}</pubDate>"
                           f"<description>{escape(desc)}</description></item>")
        self.write("feed.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
                   f"<title>{escape(self.site['name'])}</title><link>{escape(self.url())}</link>"
                   f"<description>{escape(self.site['description'])}</description>"
                   "<language>ja</language>\n" + "\n".join(entries) + "\n</channel></rss>\n")
