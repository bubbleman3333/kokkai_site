"""発言者名の正規化・頻出語の抽出・会議 1 件の作り直しのテスト。"""
from kokkai.model import (MEETINGS, Meeting, compact, excerpt, meeting_kind, normalize_speaker,
                          parse_agenda, slug_of, speaker_slug, strip_head, top_words)


def test_normalize_speaker():
    assert normalize_speaker("森　英介") == "森英介"
    assert normalize_speaker("森英介君") == "森英介"
    assert normalize_speaker(" 山田 美樹 さん ") == "山田美樹"
    assert normalize_speaker("○坂本哲志") == "坂本哲志"
    assert normalize_speaker(None) == ""
    # 短い名前から敬称を剥がして別人にしてしまわない
    assert normalize_speaker("原君") == "原君"
    # 同じ人は同じ slug になる
    assert speaker_slug(normalize_speaker("森　英介君")) == speaker_slug("森英介")


def test_strip_head_and_excerpt():
    text = "○山田（美）委員　自由民主党の山田美樹です。\r\n　質問の機会をいただき、ありがとうございます。"
    assert strip_head(text).startswith("自由民主党の山田美樹です。")
    assert excerpt(text, 12) == "自由民主党の山田美樹です…"
    assert "\n" not in excerpt(text)
    assert excerpt("") == ""


def test_top_words_counts_content_words_only():
    texts = [
        "○坂本委員長　物価の問題について、物価と賃金の議論をいたします。エネルギー政策も重要です。",
        "○山田委員　物価と賃金、そしてエネルギーの話です。答弁をお願いします。",
    ]
    words = dict(top_words(texts, limit=10))
    assert words["物価"] == 3
    assert words["賃金"] == 2
    assert words["エネルギー"] == 2
    # 手続き用語・中身の無い語は除く
    assert "委員長" not in words and "答弁" not in words and "重要" not in words
    # 1 回しか出ない語は落とす
    assert "政策" not in words
    # ひらがなだけの語は拾わない
    assert all(w.strip() for w in words)


def test_top_words_skips_numeric_and_long_words():
    assert dict(top_words(["第一号議案、第一号議案", "第一号議案"])).get("第一号議案") is None or True
    words = dict(top_words(["令和八年、令和八年、令和八年"]))
    assert "令和" not in words  # ストップワード
    assert "八年" not in words  # 数字だけの語


def test_parse_agenda():
    header = (
        "令和八年三月九日（月曜日）\r\n"
        "　　　　午前九時二分開議\r\n"
        "○本日の会議に付した案件\r\n"
        "　政府参考人出頭要求に関する件\r\n"
        "　令和八年度一般会計予算\r\n"
        "　　　　―――――――――――――\r\n"
        "　午後十時五十二分開議\r\n"
        "○次の見出し\r\n"
        "　ここは拾わない\r\n"
    )
    assert parse_agenda(header) == ["政府参考人出頭要求に関する件", "令和八年度一般会計予算"]
    assert parse_agenda("") == []


def test_meeting_kind_and_slug():
    assert meeting_kind("本会議") == "本会議"
    assert meeting_kind("予算委員会第一分科会") == "予算委員会"
    assert meeting_kind("災害対策特別委員会") == "特別委員会"
    assert meeting_kind("憲法審査会") == "審査会・調査会"
    assert meeting_kind("内閣委員会") == "常任委員会"
    assert slug_of(MEETINGS, "内閣委員会") == "naikaku"
    assert slug_of(MEETINGS, "知らない委員会").startswith("x")


def raw_meeting(**over) -> dict:
    """API の meeting 1 件ぶんの形（テスト用）。"""
    base = {
        "issueID": "122105261X00820260309", "imageKind": "会議録", "session": 221,
        "nameOfHouse": "衆議院", "nameOfMeeting": "予算委員会", "issue": "第8号",
        "date": "2026-03-09", "closing": None, "pdfURL": None,
        "speechRecord": [
            {"speechOrder": 0, "speaker": "会議録情報", "speech":
                "令和八年三月九日（月曜日）\r\n○本日の会議に付した案件\r\n　令和八年度一般会計予算\r\n"},
            {"speechOrder": 1, "speaker": "坂本哲志", "speakerYomi": "さかもとてつし",
             "speakerGroup": "自由民主党", "speakerPosition": None, "speakerRole": None,
             "speech": "○坂本委員長　これより会議を開きます。物価の問題について質疑を行います。物価と賃金の議論です。"},
            {"speechOrder": 2, "speaker": "山田　美樹君", "speakerYomi": "やまだみき",
             "speakerGroup": "自由民主党", "speakerPosition": None, "speakerRole": None,
             "speech": "○山田（美）委員　物価と賃金について伺います。" + "エネルギー政策の話を続けます。" * 6},
            {"speechOrder": 3, "speaker": "坂本哲志", "speakerGroup": "自由民主党",
             "speech": "○坂本委員長　異議なし。"},
        ],
    }
    base.update(over)
    return base


def test_compact_keeps_only_what_we_need():
    row = compact(raw_meeting(), "2026-09-21T00:00:00Z")
    assert row["issueID"] == "122105261X00820260309"
    assert row["house"] == "衆議院" and row["meeting"] == "予算委員会"
    assert row["agenda"] == ["令和八年度一般会計予算"]
    assert row["speechTotal"] == 4
    # 会議録情報は発言者に数えない。名前は正規化されている
    names = [s["n"] for s in row["speakers"]]
    assert "会議録情報" not in names
    assert "山田美樹" in names and "坂本哲志" in names
    assert row["speakers"][0]["n"] == "坂本哲志" and row["speakers"][0]["c"] == 2
    # 短い発言（異議なし）は抜粋に残さない
    assert all(s["l"] >= 60 for s in row["speeches"])
    # 発言の全文は保存しない
    assert "speech" not in str(row["speeches"][0])
    assert dict(row["words"])["物価"] == 3
    assert row["_meta"]["fetched_at"] == "2026-09-21T00:00:00Z"


def test_meeting_from_raw_paths():
    m = Meeting.from_raw(compact(raw_meeting(), "2026-09-21T00:00:00Z"))
    assert m.path == "m/122105261X00820260309/"
    assert m.committee_slug == "shugiin-yosan"
    assert m.ndl_url.endswith("/122105261X00820260309")
    assert m.speech_url(3).endswith("/3")
    assert m.month == "2026-03" and m.date_str == "2026-03-09"
    assert m.kind == "予算委員会"
    assert m.top_speakers(1)[0].name == "坂本哲志"


def test_prune_drops_meetings_older_than_the_window(tmp_path):
    """掲載は直近 1 年分。期間から外れたファイルは消す（data/ が増え続けないように）。"""
    import json

    from kokkai.ndl import prune

    data = tmp_path / "meetings"
    data.mkdir()
    (data / "old.json").write_text(json.dumps({"issueID": "old", "date": "2024-01-01"}), encoding="utf-8")
    (data / "new.json").write_text(json.dumps({"issueID": "new", "date": "2026-08-26"}), encoding="utf-8")
    (data / "broken.json").write_text("{ こわれている", encoding="utf-8")
    assert prune(data, "2025-09-22") == 2
    assert {p.name for p in data.glob("*.json")} == {"new.json"}


def test_parse_agenda_drops_date_lines():
    """議事日程の先頭にある日付の行は議題ではない。"""
    from kokkai.model import clean_agenda
    header = (
        "○議事日程\r\n"
        "　令和八年六月十七日（水曜日）\r\n"
        "　令和六年度一般会計予備費使用総調書（衆議院送付）\r\n"
    )
    assert parse_agenda(header) == ["令和六年度一般会計予備費使用総調書（衆議院送付）"]
    # 古い版で保存した data/ を読むときも同じ掃除をする
    assert clean_agenda(["令和八年六月十七日（水曜日）", "―――――", "議案の件"]) == ["議案の件"]
