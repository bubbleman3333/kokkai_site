"""会議録の生データを、保存用・表示用の扱いやすい形に直す。

ここには Django も requests も持ち込まない（取り込みと生成の両方から使う純粋な処理だけ）。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

HOUSES: dict[str, str] = {
    "衆議院": "shugiin",
    "参議院": "sangiin",
    "両院": "ryoin",
    "両院協議会": "ryoin-kyogikai",
}

# 会議名 → URL に使う slug。表になければ名前のハッシュに落ちるだけで壊れはしない。
MEETINGS: dict[str, str] = {
    "本会議": "honkaigi",
    "議院運営委員会": "giin-unei",
    "議院運営委員会庶務小委員会": "giin-unei-shomu",
    "議院運営委員会図書館運営小委員会": "giin-unei-toshokan",
    "議院運営委員会院内の警察及び秩序に関する小委員会": "giin-unei-keisatsu",
    "内閣委員会": "naikaku",
    "厚生労働委員会": "kosei-rodo",
    "法務委員会": "homu",
    "予算委員会": "yosan",
    "予算委員会公聴会": "yosan-kochokai",
    "予算委員会第一分科会": "yosan-bunkakai-1",
    "予算委員会第二分科会": "yosan-bunkakai-2",
    "予算委員会第三分科会": "yosan-bunkakai-3",
    "予算委員会第四分科会": "yosan-bunkakai-4",
    "予算委員会第五分科会": "yosan-bunkakai-5",
    "予算委員会第六分科会": "yosan-bunkakai-6",
    "予算委員会第七分科会": "yosan-bunkakai-7",
    "予算委員会第八分科会": "yosan-bunkakai-8",
    "農林水産委員会": "norin-suisan",
    "国土交通委員会": "kokudo-kotsu",
    "経済産業委員会": "keizai-sangyo",
    "総務委員会": "somu",
    "環境委員会": "kankyo",
    "憲法審査会": "kenpo-shinsakai",
    "外交防衛委員会": "gaiko-boei",
    "外務委員会": "gaimu",
    "安全保障委員会": "anzen-hosho",
    "財政金融委員会": "zaisei-kinyu",
    "財務金融委員会": "zaimu-kinyu",
    "文教科学委員会": "bunkyo-kagaku",
    "文部科学委員会": "monbu-kagaku",
    "決算委員会": "kessan",
    "決算行政監視委員会": "kessan-gyosei-kanshi",
    "行政監視委員会": "gyosei-kanshi",
    "国家基本政策委員会": "kokka-kihon",
    "国家基本政策委員会合同審査会": "kokka-kihon-godo",
    "懲罰委員会": "chobatsu",
    "情報監視審査会": "joho-kanshi",
    "政治改革に関する特別委員会": "seiji-kaikaku",
    "消費者問題に関する特別委員会": "shohisha",
    "北朝鮮による拉致問題等に関する特別委員会": "rachi",
    "災害対策特別委員会": "saigai",
    "災害対策及び東日本大震災復興特別委員会": "saigai-fukko",
    "東日本大震災復興及び原子力問題調査特別委員会": "shinsai-genshiryoku",
    "沖縄及び北方問題に関する特別委員会": "okinawa-hoppo",
    "沖縄・北方問題及び地方に関する特別委員会": "okinawa-hoppo-chiho",
    "こども・子育て・若者活躍に関する特別委員会": "kodomo-kosodate",
    "地域活性化・こども政策・デジタル社会形成に関する特別委員会": "chiiki-kodomo-digital",
    "デジタル社会の形成及び人工知能の活用等に関する特別委員会": "digital-ai",
    "政府開発援助及び国際協力・人道支援等に関する特別委員会": "oda",
    "皇室典範等の一部を改正する法律案特別委員会": "koshitsu-tenpan",
    "資源エネルギー・持続可能社会に関する調査会": "shigen-energy",
    "国際問題に関する調査会": "kokusai-mondai",
    "国民生活・経済に関する調査会": "kokumin-seikatsu",
}

# 会議の種類。トップや一覧の並べ替えに使う
KIND_ORDER = ["本会議", "予算委員会", "常任委員会", "特別委員会", "審査会・調査会", "その他"]


def meeting_kind(name: str) -> str:
    if name == "本会議":
        return "本会議"
    if name.startswith("予算委員会"):
        return "予算委員会"
    if "特別委員会" in name:
        return "特別委員会"
    if "審査会" in name or "調査会" in name:
        return "審査会・調査会"
    if name.endswith("委員会") or "委員会" in name:
        return "常任委員会"
    return "その他"


def slug_of(table: dict[str, str], name: str) -> str:
    if name in table:
        return table[name]
    return "x" + hashlib.md5(name.encode("utf-8")).hexdigest()[:10]


def speaker_slug(name: str) -> str:
    """議員名は漢字なので、URL には名前のハッシュを使う。"""
    return "p" + hashlib.md5(name.encode("utf-8")).hexdigest()[:10]


# ---- 発言者名の正規化 ----------------------------------------------------

_SPACE_RE = re.compile(r"[\s　]+")


def normalize_speaker(name: str | None) -> str:
    """'森　英介君' → '森英介'。空白（全角・半角）を落とし、敬称を外す。

    API の speaker は概ね整っているが、まれに全角空白入りや「君」付きが混ざる。
    ここを 1 か所に集めておかないと、同じ議員が別人として数えられる。
    """
    s = _SPACE_RE.sub("", name or "")
    s = s.strip("○●・")
    for suffix in ("君", "さん", "氏"):
        if len(s) > 2 and s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s


# 発言本文の頭に付く「○山田（美）委員　」のような話者表示を落とす
_HEAD_RE = re.compile(r"^[○◯][^　]{0,40}　")


def strip_head(text: str) -> str:
    return _HEAD_RE.sub("", (text or "").lstrip())


def flatten(text: str) -> str:
    """改行・全角空白をならして 1 行にする。"""
    return _SPACE_RE.sub(" ", (text or "").replace("\r", "\n")).strip()


def excerpt(text: str, length: int = 160) -> str:
    body = flatten(strip_head(text))
    if len(body) <= length:
        return body
    return body[:length].rstrip() + "…"


# ---- よく出た語 ----------------------------------------------------------

# 形態素解析は入れない。漢字 2 文字以上・カタカナ 3 文字以上・英字 3 文字以上を語とみなし、
# 手続き用語と中身の無い語を落とす簡易処理。
WORD_RE = re.compile(r"[一-龥々〆]{2,}|[ァ-ヴ][ァ-ヴー]{2,}|[A-Za-z][A-Za-z0-9]{2,}")
NUMERIC_CHARS = set("一二三四五六七八九十百千万億兆零〇第号年月日時分秒件番目次回")

STOP_WORDS: frozenset[str] = frozenset("""
委員長 委員 大臣 国務大臣 総理大臣 内閣総理大臣 副大臣 政務官 政府参考人 参考人 公述人 証人
議長 副議長 理事 理事会 議員 議院 委員会 本会議 分科会 審査会 調査会 小委員会 連合審査会
衆議院 参議院 両院 国会 通常国会 臨時国会 国会議員
質疑 質問 御質問 答弁 御答弁 発言 御発言 指摘 御指摘 説明 御説明 意見 御意見 御審議 審議
採決 起立 動議 異議 賛成 反対 可決 否決 休憩 再開 散会 開議 閉会 速記 発言者 着席 拍手
本日 昨日 今日 今回 今後 現在 以上 以下 以外 場合 部分 程度 一定 一部 全体 中心 中身 内容
必要 重要 我々 皆様 皆さん 先生 先ほど 思い 考え 意味 関係 結果 理由 状況 具体的 基本的
令和 平成 昭和 政府 大変 十分 本当 自分 自身 一つ 二つ 三つ 何度 若干 多く 非常 最後 最初
""".split())


def top_words(texts, limit: int = 20) -> list[tuple[str, int]]:
    """発言本文の並びから、よく出た語を上位 limit 件返す。"""
    counts: dict[str, int] = {}
    for text in texts:
        for w in WORD_RE.findall(strip_head(text)):
            if w in STOP_WORDS or len(w) > 12:
                continue
            if all(c in NUMERIC_CHARS for c in w):
                continue
            counts[w] = counts.get(w, 0) + 1
    rows = [(w, c) for w, c in counts.items() if c >= 2]
    rows.sort(key=lambda t: (-t[1], t[0]))
    return rows[:limit]


# ---- 議題（会議録冒頭の「本日の会議に付した案件」） ----------------------

_AGENDA_HEAD = re.compile(r"^[○◯]?\s*(本日の会議に付した案件|議事日程|本日の本会議に付した案件)")
_SEPARATOR_CHARS = set("―-—‐=＝◇◆△▽・ 　")
_CLOCK_RE = re.compile(r"^午[前後].{0,20}(開議|散会|休憩|開会|閉会)")
# 議事日程の先頭にある「令和八年六月十七日（水曜日）」のような日付だけの行
_DATELINE_RE = re.compile(r"^(令和|平成|昭和)[〇一二三四五六七八九十0-9]{1,4}年.{1,8}月.{1,8}日([（(].{1,4}[）)])?$")


def parse_agenda(header_text: str, limit: int = 12) -> list[str]:
    """会議録冒頭（speechOrder 0）から議題の行を取り出す。

    「○本日の会議に付した案件」の次の行から、次の「○見出し」または罫線までを議題とみなす。
    「午後一時開議」のような時刻の行、日付だけの行、罫線は落とす。
    """
    out: list[str] = []
    started = False
    for raw_line in (header_text or "").replace("\r", "").split("\n"):
        line = raw_line.strip().strip("　")
        if not started:
            if _AGENDA_HEAD.match(line):
                started = True
            continue
        if not line:
            continue
        if line.startswith("○") or line.startswith("◯"):
            break
        if set(line) <= _SEPARATOR_CHARS:
            continue
        if _CLOCK_RE.match(line) or _DATELINE_RE.match(line):
            continue
        item = re.sub(r"^[（(]?[第]?[〇一二三四五六七八九十0-9１-９]+[）)、.]?　?", "", line).strip()
        item = item.strip("　 ")
        if len(item) < 2:
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return clean_agenda(out)


def clean_agenda(items) -> list[str]:
    """議題から、日付・時刻・罫線だけの行を落とす。

    parse_agenda の仕上げに使うほか、古い版で保存した data/ を読むときの掃除も兼ねる
    （保存済みの JSON には会議録の冒頭が残っていないので、ここで直すしかない）。
    """
    out = []
    for a in items or []:
        a = (a or "").strip()
        if not a or len(a) < 2 or set(a) <= _SEPARATOR_CHARS:
            continue
        if _CLOCK_RE.match(a) or _DATELINE_RE.match(a):
            continue
        out.append(a)
    return out


# ---- 保存用の 1 件 -------------------------------------------------------

MAX_SPEECHES = 120       # 1 会議あたりに残す発言の数（これを超えたら長いものを優先）
MIN_SPEECH_CHARS = 60    # これより短い発言（「異議なし」など）は抜粋を残さない


def compact(raw: dict, fetched_at: str) -> dict:
    """API の meeting 1 件から、保存する項目だけを抜き出す。

    発言の全文は保存しない（容量とメモリのため）。冒頭の抜粋・長さ・よく出た語だけ残す。
    """
    speeches_raw = raw.get("speechRecord") or []
    header = ""
    speakers: dict[str, dict] = {}
    speaker_texts: dict[str, list[str]] = {}
    body_texts: list[str] = []
    kept: list[dict] = []
    total_chars = 0

    for sp in speeches_raw:
        name = normalize_speaker(sp.get("speaker"))
        text = sp.get("speech") or ""
        if sp.get("speechOrder") == 0 or name in ("会議録情報", "会議録情報等"):
            header = text
            continue
        body = strip_head(text)
        total_chars += len(body)
        body_texts.append(text)
        if name:
            row = speakers.setdefault(name, {
                "n": name, "y": sp.get("speakerYomi") or "", "g": sp.get("speakerGroup") or "",
                "p": sp.get("speakerPosition") or "", "r": sp.get("speakerRole") or "", "c": 0, "l": 0,
            })
            row["c"] += 1
            row["l"] += len(body)
            if not row["g"] and sp.get("speakerGroup"):
                row["g"] = sp["speakerGroup"]
            if not row["p"] and sp.get("speakerPosition"):
                row["p"] = sp["speakerPosition"]
            speaker_texts.setdefault(name, []).append(text)
        if len(body) >= MIN_SPEECH_CHARS:
            kept.append({"o": sp.get("speechOrder"), "n": name, "p": sp.get("speakerPosition") or "",
                         "e": excerpt(text), "l": len(body)})

    if len(kept) > MAX_SPEECHES:
        longest = sorted(kept, key=lambda s: -s["l"])[:MAX_SPEECHES]
        order = {id(s) for s in longest}
        kept = [s for s in kept if id(s) in order]

    for name, row in speakers.items():
        row["w"] = top_words(speaker_texts.get(name, []), limit=10)

    return {
        "issueID": raw.get("issueID"),
        "house": raw.get("nameOfHouse") or "",
        "meeting": raw.get("nameOfMeeting") or "",
        "issue": raw.get("issue") or "",
        "session": raw.get("session"),
        "date": raw.get("date") or "",
        "closing": bool(raw.get("closing")),
        "pdfURL": raw.get("pdfURL") or None,
        "agenda": parse_agenda(header),
        "speechTotal": len(speeches_raw),
        "speechKept": len(kept),
        "chars": total_chars,
        "speakers": sorted(speakers.values(), key=lambda r: (-r["c"], -r["l"], r["n"])),
        "speeches": kept,
        "words": top_words(body_texts, limit=20),
        "_meta": {"fetched_at": fetched_at},
    }


# ---- 表示用 --------------------------------------------------------------

@dataclass
class Speaker:
    name: str
    yomi: str
    group: str
    position: str
    role: str
    count: int
    chars: int
    words: list[tuple[str, int]] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return speaker_slug(self.name)

    @property
    def label(self) -> str:
        """役職があれば役職、無ければ会派を返す（一覧の 2 行目に出す用）。"""
        return self.position or self.group or ""


@dataclass
class Speech:
    order: int
    speaker: str
    position: str
    excerpt: str
    chars: int


@dataclass
class Meeting:
    issue_id: str
    house: str
    name: str
    issue: str
    session: int | None
    day: date
    closing: bool
    pdf_url: str | None
    agenda: list[str]
    speech_total: int
    chars: int
    speakers: list[Speaker]
    speeches: list[Speech]
    words: list[tuple[str, int]]

    @classmethod
    def from_raw(cls, raw: dict) -> "Meeting":
        return cls(
            issue_id=raw["issueID"],
            house=raw.get("house") or "",
            name=raw.get("meeting") or "",
            issue=raw.get("issue") or "",
            session=raw.get("session"),
            day=date.fromisoformat(raw["date"]),
            closing=bool(raw.get("closing")),
            pdf_url=raw.get("pdfURL"),
            agenda=clean_agenda(raw.get("agenda")),
            speech_total=int(raw.get("speechTotal") or 0),
            chars=int(raw.get("chars") or 0),
            speakers=[Speaker(name=s["n"], yomi=s.get("y", ""), group=s.get("g", ""), position=s.get("p", ""),
                              role=s.get("r", ""), count=s.get("c", 0), chars=s.get("l", 0),
                              words=[tuple(w) for w in s.get("w", [])]) for s in raw.get("speakers") or []],
            speeches=[Speech(order=s.get("o") or 0, speaker=s.get("n", ""), position=s.get("p", ""),
                             excerpt=s.get("e", ""), chars=s.get("l", 0)) for s in raw.get("speeches") or []],
            words=[tuple(w) for w in raw.get("words") or []],
        )

    # 表示の部品
    @property
    def path(self) -> str:
        return f"m/{self.issue_id}/"

    @property
    def kind(self) -> str:
        return meeting_kind(self.name)

    @property
    def house_slug(self) -> str:
        return slug_of(HOUSES, self.house)

    @property
    def committee_slug(self) -> str:
        return f"{self.house_slug}-{slug_of(MEETINGS, self.name)}"

    @property
    def title(self) -> str:
        return f"{self.house} {self.name} {self.issue}".strip()

    @property
    def ndl_url(self) -> str:
        return f"https://kokkai.ndl.go.jp/txt/{self.issue_id}"

    def speech_url(self, order: int) -> str:
        return f"{self.ndl_url}/{order}"

    @property
    def month(self) -> str:
        return self.day.strftime("%Y-%m")

    @property
    def date_str(self) -> str:
        return self.day.isoformat()

    def top_speakers(self, n: int = 10) -> list[Speaker]:
        return self.speakers[:n]


def fmt_day(d: date | datetime | None) -> str:
    if not d:
        return "不明"
    wd = "月火水木金土日"[d.weekday()]
    return f"{d.year}年{d.month}月{d.day}日（{wd}）"


def fmt_month(key: str) -> str:
    y, m = key.split("-")
    return f"{y}年{int(m)}月"
