# 国会ウォッチ

衆議院・参議院の本会議と委員会の会議録を、国立国会図書館「国会会議録検索システム」の公開 API から
毎日取り込み、静的サイトとして GitHub Pages に配信する。**運用費ゼロ**（API はキー不要、GitHub Actions と Pages は無料枠）。

- 公開先: https://bubbleman3333.github.io/kokkai_site/
- 掲載するのは直近 1 年分。会議録は会議の **3〜5 週間後**に公開されるので、きのうの委員会がすぐ載るわけではない。

## 仕組み

```
国会会議録 API ──fetch──▶ data/meetings/<issueID>.json ──build──▶ dist/ ──▶ GitHub Pages
```

- `kokkai/ndl.py` 取り込み。`meeting_list` で直近 1 年の会議を一覧し、まだ持っていない会議だけ `meeting` で詳細を取る。
  1 件ずつ取って必要な項目だけ残す（会議 1 件の JSON は最大 1 MB ほどあるため）。1 秒に 1 回程度に抑える。
- `kokkai/model.py` 生データ → 保存用の形（`compact`）と表示用の形（`Meeting`）。
  発言者名の正規化、発言冒頭の抜粋、よく出た語、議題の取り出し、slug。**Django にも requests にも依存させない。**
- `kokkai/build.py` Jinja2 で `dist/` を書き出す。日・委員会・議員・月ごとの集計はここ。
- `.github/workflows/daily.yml` 毎朝 6 時（JST）に fetch → データをコミット → build → Pages に配信。

### 保存するもの・保存しないもの

**発言の全文は保存しない。** 容量とメモリのため、1 件につき次だけを残す。

| 項目 | 中身 |
| --- | --- |
| `house` `meeting` `issue` `session` `date` `closing` | 院・会議名・号・回次・日付・閉会中審査か |
| `agenda` | 議題（会議録冒頭の「本日の会議に付した案件」） |
| `speakers` | 発言者ごとの 会派・役職・発言回数・文字数・よく使う語 10 件 |
| `speeches` | 発言の冒頭 160 字の抜粋（60 字未満の進行発言は除き、多いときは長い順に 120 件まで） |
| `words` | 会議全体でよく出た語 20 件 |

全文は `https://kokkai.ndl.go.jp/txt/<issueID>` へのリンクで読んでもらう。

## 生成されるページ

| パス | 内容 |
| --- | --- |
| `/` | トップ。直近の開催日の会議、今週の発言回数ランキング、最近よく出た語、委員会・月別の入口 |
| `/m/<issueID>/` | 会議 1 件（議題・発言者一覧・発言の抜粋・よく出た語・出典） |
| `/day/<YYYY-MM-DD>/` | その日に開かれた会議と、その日の発言者ランキング |
| `/day/` | 開催日の一覧 |
| `/speaker/<slug>/` | 議員ごと（発言した会議・月ごとの発言回数・よく使う語） |
| `/speaker/` | 発言回数の多い順の一覧 |
| `/committee/<slug>/` `/committee/` | 委員会ごとの開催日一覧、委員会の一覧 |
| `/monthly/<YYYY-MM>/` `/monthly/` | 月ごとのまとめ |
| `/search/` | 院・会議名・月・発言者・キーワードで絞り込む（`search.json` を JS で読む） |
| `/feed.xml` `/sitemap.xml` `/robots.txt` `/404.html` `/about/` `/privacy/` | RSS・サイトマップなど |

全ページに canonical・OGP・構造化データ（WebSite/SearchAction、Event、ProfilePage、CollectionPage、BreadcrumbList）を出す。

## コマンド（`.venv` を使う）

```powershell
.\.venv\Scripts\python -u -m kokkai fetch              # 取り込む（初回は 40 分ほど）
.\.venv\Scripts\python -m kokkai build --site-url http://127.0.0.1:8000   # ローカル確認用に生成
.\.venv\Scripts\python -m http.server 8000 -d dist     # ブラウザで http://127.0.0.1:8000/
.\.venv\Scripts\python -m kokkai stats                 # 取り込み済みの様子を見る
.\.venv\Scripts\python -m pytest -q
```

初回だけ `python -m venv .venv` と `.\.venv\Scripts\pip install -r requirements.txt`。

## 手を入れるとき

- **会議名の slug** は `kokkai/model.py` の `MEETINGS`。表に無い会議名は名前のハッシュ（`x…`）になるだけで壊れない。
  新しい委員会ができたら、ここに読みやすい slug を足す。
- **よく出た語** の精度を上げたいときは `model.py` の `STOP_WORDS` と `WORD_RE`。
  形態素解析ライブラリは入れない（Actions の無料枠で軽く動かすため）。`compact` を変えたら
  `data/meetings/` を作り直す必要があるので、`fetch` をやり直すか、保存済み JSON を作り直すこと。
- **色** は `static/style.css` の `:root`。えんじ（本会議場の絨毯）と紫。
- 出典表記（「国会会議録検索システム（国立国会図書館）」）は全ページに出す。会議録は公的記録だが、
  **発言の全文をそのまま並べるページにはしない**（抜粋＋リンクにとどめる）。

## 設定

`config/site.json`。`site_url` は Pages の URL。`days_back` は何日さかのぼるか。

## 出典

[国会会議録検索システム](https://kokkai.ndl.go.jp/)（国立国会図書館）の
[検索用 API](https://kokkai.ndl.go.jp/api.html)。キーは不要。
国立国会図書館・国会とは関係のない非公式サイト。
