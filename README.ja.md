<div align="center">

<img src="docs/img/logo.png" alt="Mens キャンパスアシスタント" width="104" height="104" />

# Mens キャンパスアシスタント

**ローカル優先のキャンパス質問応答ワークベンチ**  
Electron デスクトップシェル + Vue 3 インターフェース + FastAPI バックエンド。1 台の端末でオフラインでも動作します

<a href="https://github.com/HuanMoovo/campus-agent/actions/workflows/build-desktop.yml"><img src="https://github.com/HuanMoovo/campus-agent/actions/workflows/build-desktop.yml/badge.svg" alt="デスクトップビルドの状態" /></a>
<img src="https://img.shields.io/badge/%E3%83%90%E3%83%BC%E3%82%B8%E3%83%A7%E3%83%B3-1.2.1-0e7c74" alt="バージョン 1.2.1" />
<img src="https://img.shields.io/badge/%E3%83%A9%E3%82%A4%E3%82%BB%E3%83%B3%E3%82%B9-Apache--2.0-0e7c74" alt="Apache-2.0" />
<img src="https://img.shields.io/badge/%E5%AF%BE%E5%BF%9C-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20PWA-0e7c74" alt="対応プラットフォーム" />

[中文](README.md) · [English](README.en.md) · **日本語**

[Windows 版をダウンロード](https://github.com/HuanMoovo/campus-agent/releases/latest) ·
[プロジェクト紹介ページ](https://huanmoovo.github.io/campus-agent/) ·
[対応プラットフォーム](PLATFORMS.md) ·
[検証記録](VERIFICATION.md) ·
[ライセンス](LICENSE)

</div>

---

## これは何か

Mens は「学内規定・手続きの質問応答」「ローカルのナレッジベース検索」「学内データサービス」を
1 つのデスクトップアプリにまとめ、文書・データ・鍵を既定で端末内に留めるツールです。
個人の端末で試す・評価する・作り込む用途に向いており、学内の本番システムとして配備する場合は
シングルサインオン、監査、データのコンプライアンス対応を追加する必要があります
（[既知の制限](#既知の制限)を参照）。

### 名前の由来

**Mens はラテン語で、英語ではありません。** ラテン語の *mēns*（属格 *mentis*）は
**心・理性・思考**を意味し、英語の *mental*（心の）や *dementia*（認知症。直訳すると「心から離れた状態」）
の語源でもあります。英語の *men*（*man* の複数形）とはまったく関係がなく、性別を指す意味もありません。
「考えることを助ける道具」という意味を込めた名前で、この学内アシスタントの役割に重ねています。

- **ローカル優先** — ナレッジベース、会話、設定、鍵は端末内（SQLite + ユーザーデータフォルダ）に保存され、外部データベースは不要です。ネットワークがなくても質問応答ができます。
- **事実のまま表示** — 未設定の学内エンドポイントは明確に「デモデータ」と表示し、モデルが使えないときは回答を捏造せずナレッジベースの原文引用に切り替えます。
- **任意のウェブ検索** — 既定は無効。管理者が設定画面で有効化し（キー不要の Bing、または Tavily / 博查）、メッセージごとに切り替えられます。回答は参照元リンクと検索時刻を引用します。
- **クロスプラットフォーム** — Windows はインストーラーですぐ使えます。macOS（Intel / Apple silicon）と Linux（AppImage / deb）は CI がビルドし、スマホ・タブレットはインストール可能なウェブ版（PWA）を使います。
- **オープンソース** — Apache License 2.0（[`LICENSE`](LICENSE) と [`NOTICE`](NOTICE)）。サードパーティ一覧は [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。

## 機能一覧

### チャット

| 機能 | 説明 |
| --- | --- |
| ストリーミング回答 | 文字単位で出力し、生成中も画面が随時更新されます |
| 生成の停止 | いつでも中断でき、生成済みの内容は「停止」の印とともに保存されます。履歴が完全な回答を装うことはありません |
| 複数ターンの会話 | 文脈を保持し、再読み込みや再起動後も会話を復元できます |
| 参照スニペット | 回答には使用したナレッジベースの断片が付き、根拠を確認できます |
| 会話の分離 | デスクトップ版は端末ごと、ウェブ版はブラウザごとに分離。1 件ずつの削除や一括削除ができます |
| 正直な表示 | デモデータ、検索の降格、ウェブの参照元などの状態を画面に明示します |
| 会話の書き出し | 任意の会話を Markdown（閲覧用）または JSON（ツール連携用）で書き出せます。参照リンク、ツール呼び出し、デモデータの表示も含まれ、デスクトップ版は保存ダイアログ、ウェブ版は直接ダウンロードします |
| 推論の強度 | 入力バーの右端で「高速 / じっくり」の 2 段階を選べます。高速は即答、じっくりは思考チェーンを有効化（Ollama think、Qwen enable_thinking、DeepSeek は推論モデルに切替）し、より詳細ですが低速です。選択はリクエストごとに反映され、端末内に保存されます |
| 思考プロセス | じっくり（深度）モードでは思考チェーンがリアルタイムに流れ、思考中は自動展開・回答開始で自動折りたたみ。いつでも手動で開閉でき、会話と一緒に保存され、履歴復元後も確認できます |
| リッチな回答 | 回答は Markdown で描画：見出し・リスト・表・コードブロック（シンタックスハイライト）・引用・リンク。HTML はサニタイズされ、デスクトップ版のリンクはシステムブラウザで開きます |
| 回答アクション | 各回答の下に操作バー：コピー、再生成（その回答を置き換え、履歴に重複を残しません）、じっくりで再回答（保存済みの強度は変えない単発の深度回答）、役に立った / 役に立たなかった（会話と一緒に保存、もう一度クリックで取消） |

### ナレッジベースと検索

| 機能 | 説明 |
| --- | --- |
| 文書形式 | PDF・Markdown・TXT・Word（.docx）、1 ファイル 5 MB まで |
| 文書管理 | アップロード・差し替え・削除。文書データベースが正となります |
| キーワード検索 | 既定の方式で追加依存はなく、インストーラーだけで動作します |
| ベクトル検索（任意） | RAG を有効にすると BGE-M3 + Chroma による意味検索に切り替わります。ベクトルが使えない場合はキーワード検索に降格し、その旨を表示します |
| 索引の整合性 | 索引はバージョンハッシュを記録するため、削除・更新した文書が古い断片として返ることはありません |
| デモ資料 | 初回起動の SQLite には明確に表示された 3 件のデモ文書が入ります。PostgreSQL にはデモを入れません |
| ウェブ取り込み | 公開ページ（HTTPS）の本文を取得して端末内の文書として保存し、オフラインで検索できます。取得はウェブ検索と同じ送信ルール（HTTPS のみ、検証済みのグローバルアドレスに固定、リダイレクト禁止、サイズ上限）に従い、プライベートアドレスは拒否します |
| 一括アップロード | 複数ファイルをまとめて選択でき、結果はファイルごとに表示されます |

### ウェブ検索（任意・既定は無効）

| 機能 | 説明 |
| --- | --- |
| 切り替えの粒度 | 管理者による全体スイッチと、メッセージごとのスイッチ。無効時は一切検索しません |
| プロバイダ | `auto`（既定）、Bing（キー不要、中国大陸から直接接続可）、Tavily、博查（Bocha、API キーが必要） |
| 結果の扱い | 上位 1〜3 ページの本文を取得（1 ページ 2000 文字まで、1 応答 400 KB まで）し、ナレッジベースの資料と通し番号を付けてプロンプトに渡します |
| 引用 | 回答にリンク付きの参照元と検索時刻を表示します |
| 送信の制約 | HTTPS のみ、検証済みのグローバルアドレスに固定（DNS リバインディング対策として SNI を保持）、リダイレクト禁止、サイズとタイムアウトの上限あり |

### 学内サービスと修理申請

| 機能 | 説明 |
| --- | --- |
| 学内エンドポイント | 設定可能な 9 種類の HTTPS JSON エンドポイント：成績、時間割、単位数、空き教室、修理申請、学内公告、図書館、食堂、シャトルバス |
| エンドポイント設定 | 結果パス（JSON の値パス）と Bearer トークンに対応。アドレスは HTTPS 必須 |
| 修理申請 | ユーザーが明示的に送信。エンドポイント設定後は学校へ POST し、未設定時は端末内にのみ保存して「デモ」と表示します |
| 端末内の記録 | 送信した申請は新しい順に並び、結果を確認できます |
| デモデータ | 未設定のエンドポイントは明確に表示されたデモデータを返し、学校システムに接続済みであるかのようには見せません |

### モデルの利用

| 方式 | 説明 |
| --- | --- |
| クラウド API | Qwen3 / DeepSeek。各社の API キーと HTTPS アドレスを設定します。鍵は端末内に保存し、画面には再表示しません |
| 自動ルーティング | 分析・比較系の質問は設定済みの DeepSeek を優先し、それ以外は Qwen3 を優先します。手動指定も可能です |
| ローカルモデル | 内蔵カタログ（Qwen3 0.6B / 1.7B、DeepSeek R1 1.5B）。ダウンロード元は Ollama 公式 / Hugging Face / HF Mirror |
| ダウンロードの信頼性 | レジューム、固定バージョン、SHA-256 検証、インポート再試行に対応し、進捗表示とキャンセルができます |
| 降格動作 | キーがない、またはモデルが使えない場合は、ルールによる計画 + ナレッジベース原文の引用に切り替え、その旨を明示します |

### データ・バックアップ・更新

| 機能 | 説明 |
| --- | --- |
| バックアップの書き出し | ナレッジベース、会話、モデル、学内エンドポイントの設定を zip にまとめて書き出します。SQLite は `VACUUM INTO` で一貫性のあるスナップショットを作り、各ファイルの SHA-256 一覧を同梱します |
| バックアップの読み込み | 検証して復元するため、機種変更や再インストール後も完全に戻せます（zip には鍵ファイルが含まれるため厳重に保管してください） |
| 更新確認 | 管理者が HTTPS マニフェストを設定すると、設定画面から新バージョンを確認してダウンロードページを開けます。空欄なら更新確認は一切通信しません |
| バージョンの整合性 | デスクトップ・フロントエンド・バックエンドのバージョンが一致しない限り、ビルドスクリプトはパッケージを作りません |

### デスクトップ体験

| 機能 | 説明 |
| --- | --- |
| すぐ使える | インストーラーに Python ランタイムを内蔵。Python / Node / データベースの別途インストールは不要です |
| ウィンドウ記憶 | ウィンドウのサイズと位置を記憶します（画面外の座標は破棄） |
| ログとデータフォルダ | 設定画面からバックエンドのログ閲覧とデータフォルダの表示ができます |
| 外観 | ライト / ダーク / システム連動とテーマカラーの変更。サイドバーとモバイル向けレイアウトを個別に調整しています |
| 画面の言語 | 中文 / English / 日本語。既定はシステム連動で、選択は記憶されます（現在はアプリのシェル、チャット画面、外観設定が対象） |
| 起動時の検証 | 凍結したバックエンドはランダムポートとワンタイムトークンで起動し、シェルが起動エンベロープを検証してから画面を読み込みます |

### プラグインと運用

| 機能 | 説明 |
| --- | --- |
| 内蔵プラグイン | OpenAlex の学術検索、Crossref の文献照会、百度百科へのリンク（必要時にインストール。インストールは設定の登録のみです） |
| プラグインマニフェスト | HTTPS JSON マニフェストに対応。ホストは `PLUGIN_ALLOWED_HOSTS` に登録します |
| 呼び出し | 管理者が明示的に実行します。プラグインは JSON しか返せず、通常の質問応答が外部プラグインへ自動送信することはありません |
| 送信の制約 | ウェブ検索と同じ HTTPS / IP 固定 / リダイレクト禁止 / 上限のポリシーを適用します |

### MCP サーバー（外部ツール）

Mens は MCP（Model Context Protocol）クライアントとしても動作し、標準入出力でローカルの
MCP サーバーを起動して、必要なときにそのツールをモデルへ渡します。

- 「MCP」ページでサーバーを登録（コマンド・引数・環境変数）。「テスト」は**実際に子プロセスを
  起動**し、ハンドシェイクとツール一覧の取得を行います。有効かつテスト済みのサーバーのみ公開。
- ツール名は `mcp__サーバー__ツール`。1 回の質問で最大 1 つ呼び出し、結果はそのまま表示します。
- 環境変数（トークンなど）はインターフェース上、キー名とマスクのみを返します。
- 実装は stdio トランスポートのみ（SSE / streamable HTTP は対象外）。

### コマンドライン（CLI）

CLI はデスクトップ版と同じバックエンドとデータディレクトリを共有します：

```bash
python -m app.cli ask "図書館の開館時間"               # 1 回だけ質問（--json 可）
python -m app.cli chat                                 # 対話モード：/quit、/new
python -m app.cli mcp add campus --command npx --args -y <server-package>
python -m app.cli mcp list | test campus | tools --json
python -m app.cli serve --port 8000                    # バックエンドのみ起動
```

### ウェブサイトとしてのデプロイ（任意）

デスクトップ版に加えて、ログイン付きのウェブサイトとしても公開できます：

- リポジトリには `Dockerfile.web`（フロントエンドビルド + FastAPI の単一コンテナ）と
  `render.yaml` が含まれます。Render に GitHub でログインし **New → Blueprint** で本リポジトリを
  選ぶだけです。詳しくは [DEPLOY.md](DEPLOY.md)。
- `AUTH_REQUIRED=true` では、ヘルスチェックと認証系以外のすべての API にログインが必要です。
  パスワードは PBKDF2-HMAC-SHA256 のハッシュで保存し、セッションは HttpOnly Cookie
  （サーバー側はトークンのハッシュのみ保存）です。
- 初回起動時に `AUTH_ADMIN_USERNAME` / `AUTH_ADMIN_PASSWORD` から管理者を作成します
  （パスワード未設定ならランダム生成し、ログに一度だけ出力）。
- デスクトップ版には影響しません（`AUTH_REQUIRED` の既定はオフ）。

## 対応プラットフォーム

| プラットフォーム | 状態 | 成果物とデータフォルダ |
| --- | --- | --- |
| Windows 10/11 x64 | **ビルド済み・実機検証済み** | `Mens-Setup-1.2.1-x64.exe`（NSIS、ユーザー単位で `%LOCALAPPDATA%\Programs\Mens` にインストール）、データは `%APPDATA%\CampusAgent` |
| macOS 12+（Intel） | CI ビルド・実機未検証 | `Mens-1.2.1-x64.dmg` / `.zip`。署名・公証なしのため初回は右クリックから「開く」 |
| macOS 12+（Apple silicon） | CI ビルド・実機未検証 | `Mens-1.2.1-arm64.dmg` / `.zip`。データは `~/Library/Application Support/CampusAgent` |
| Linux x64 | CI ビルド・実機未検証 | `Mens-1.2.1-x86_64.AppImage`（インストール不要）と `Mens-1.2.1-amd64.deb`。データは `~/.config/CampusAgent` |
| Android / iOS | ネイティブアプリなし | インストール可能なウェブ版（PWA）を使います。ブラウザで配備済みサイトを開き、ホーム画面に追加してください。推論はサーバー側で実行します |

> 「実機検証済み」はその OS で実際にインストール・起動し画面確認まで行ったことを指し、
> 「CI ビルド」は GitHub Actions が成果物を生成したが実機では未実行であることを指します。
> マトリクス・ビルドコマンド・理由は [PLATFORMS.md](PLATFORMS.md)、結果と範囲は
> [VERIFICATION.md](VERIFICATION.md) を参照してください。

### Release 成果物（v1.2.1）

| 成果物 | サイズ | 説明 |
| --- | --- | --- |
| `Mens-Setup-1.2.1-x64.exe`（+ `.blockmap`） | 126,409,577 B | Windows インストーラー。実機のインストール検証で使ったのはこのファイルです |
| `Mens-1.2.1-x64.dmg` / `Mens-1.2.1-x64.zip` | 約 158 MB | macOS Intel |
| `Mens-1.2.1-arm64.dmg` / `Mens-1.2.1-arm64.zip` | 約 151 MB | macOS Apple silicon |
| `Mens-1.2.1-x86_64.AppImage` / `Mens-1.2.1-amd64.deb` | 191 MB / 153 MB | Linux |

インストーラーには `LICENSE`、`NOTICE`、`THIRD-PARTY-NOTICES.md` も含まれます（インストール後は
`resources/` にあります）。

## クイックスタート

### 1. Windows デスクトップ版のインストール

[最新リリース](https://github.com/HuanMoovo/campus-agent/releases/latest) から
`Mens-Setup-1.2.1-x64.exe` をダウンロードして実行します（ユーザー単位インストール、管理者権限は
不要）。スタートメニューまたはデスクトップから起動し、設定画面でモデルの API キーを入力するか
ローカルの Ollama モデルを選べば、すぐに質問できます。

### 2. ソースからのデスクトップビルド

3 プラットフォーム共通のスクリプトで、成果物は `release/` に出力されます：

```bash
# 現在のプラットフォーム（アーキテクチャは自動判定）
python scripts/build_desktop.py

# 対象を指定
python scripts/build_desktop.py --os mac   --arch arm64
python scripts/build_desktop.py --os linux --arch x64

# よく使うオプション
#   --skip-install   インストール済みの依存を使う（高速な再ビルド）
#   --directory      未パッケージのアプリケーションフォルダのみ生成
#   --full-rag       ベクトル検索の依存も同梱（ダウンロードが大きくなります）
```

スクリプトはバックエンド / フロントエンド / デスクトップのテストを実行し、バックエンドを凍結して
から electron-builder でパッケージします。途中で失敗するとインストーラーは生成されません。

### 3. ソースからの実行（ウェブ開発）

Windows では `install.cmd` をダブルクリックすると、依存のインストール、LangGraph の確認、
バックエンドテスト、フロントエンドのビルドまで実行されます。その後 `start-backend.cmd` と
`start-frontend.cmd` を実行し、<http://localhost:5173> を開きます。

手動の場合：

```powershell
# バックエンド（ターミナル 1）
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env          # ADMIN_TOKEN を自分で生成した強力な乱数に変更
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# フロントエンド（ターミナル 2）
cd frontend
npm install
npm run dev
```

画面は <http://localhost:5173>、API ドキュメントは <http://localhost:8000/docs>。
`backend/.env` の `ADMIN_TOKEN` を設定画面に入力すると、文書とプラグインを管理できます
（トークンはブラウザのセッション内にのみ保持されます）。

### 4. Docker での配備（サーバー・PWA）

```bash
cp .env.example .env      # POSTGRES_PASSWORD と ADMIN_TOKEN を設定
docker compose up -d --build
docker compose logs -f backend
```

<http://localhost:8080> を開きます（スタックは `127.0.0.1:8080` にのみバインドされます）。
スマホのブラウザでこのアドレスを開きホーム画面に追加すると、インストール可能なウェブ版（PWA）
として使えます。

スタックは PostgreSQL + バックエンド + Nginx で構成されます：

| サービス | イメージ | 補足 |
| --- | --- | --- |
| `database` | `postgres:16-alpine` | ヘルスチェック後にバックエンドが起動します。データは `postgres_data` ボリューム |
| `backend` | `python:3.11-slim` | 非 root ユーザーで実行。データは `backend_data`、モデルキャッシュは `model_cache`。`/api/health` でヘルスチェック |
| `frontend` | `nginx:alpine` | ビルド済み Vue アプリを配信し、`/api/` をバックエンドへプロキシします。アップロード上限は 6 MB |

補足：

- ルート `.env` の変数はそのまま渡されるため、ウェブ検索、更新マニフェスト、プラグインの許可ホストもローカル版と同じように設定できます（設定リファレンスを参照）。
- `ENABLE_RAG=true` にするとベクトル検索の依存をイメージに含めます（`INSTALL_VECTOR` ビルド引数）。再ビルドが必要です。
- データは名前付きボリュームに保存されるため、`docker compose down` では残り、`docker compose down -v` で削除されます。更新前にデータベースをバックアップしてください。
- この構成は 1 台の端末または信頼できるネットワーク向けです。インターネットへ公開する場合は、HTTPS と前段の認証、レート制限が別途必要です。
- **本機で実測済み**（Docker Desktop 29.1.3）：2 つのイメージがビルドされ、database / backend / frontend の 3 サービスが起動して前 2 つがヘルスチェックを通過。`http://localhost:8080/` は 200、`/api/health` は `{"status":"ok",…}` を返し、バックエンドがコンテナ内で **PostgreSQL 16.15** への接続を確認。実ブラウザで「Mens 工作台」が開き、失敗リクエストもページエラーもありません。

### 5. Docker を使わないスマホ・タブレット（PWA）

到達可能な場所にバックエンドを配備し（上記のサーバー配備を参照）、スマホのブラウザでサイトを
開いてホーム画面に追加すると、全画面・専用アイコンのアプリ風に使えます。

## 設定リファレンス

### backend/.env

| 変数 | 既定値 | 説明 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///backend/data/campus.db` | PostgreSQL も可：`postgresql+psycopg://user:pass@host:5432/campus_agent`（予約文字は URL エンコード） |
| `ADMIN_TOKEN` | 空 | 管理トークン。設定画面で文書とプラグインの管理に使います。配備前に必ず変更してください |
| `QWEN_API_KEY` / `DEEPSEEK_API_KEY` | 空 | クラウドモデルのキー（設定画面から保存も可能） |
| `QWEN_BASE_URL` / `DEEPSEEK_BASE_URL` | 公式 HTTPS アドレス | HTTPS 必須 |
| `QWEN_MODEL` / `DEEPSEEK_MODEL` | `qwen3-235b-a22b` / `deepseek-chat` | アカウントで実際に使えるモデルに変更します |
| `ENABLE_RAG` | `false` | BGE-M3 + Chroma のベクトル検索を有効化（先に `requirements-ai.txt` をインストール） |
| `BGE_MODEL_NAME` | `BAAI/bge-m3` | ダウンロード済みのローカルモデルを指定しても構いません |
| `PLUGIN_ALLOWED_HOSTS` | 空 | プラグインがアクセスできるホストの許可リスト（カンマ区切り） |
| `CORS_ORIGINS` | `http://localhost:5173` | ウェブ版の許可オリジン |
| `WEB_SEARCH_ENABLED` | `false` | ウェブ検索の全体スイッチ |
| `WEB_SEARCH_PROVIDER` | `auto` | `auto` / `bing`（キー不要）/ `tavily` / `bocha` |
| `WEB_SEARCH_API_KEY` | 空 | Tavily または博查のキー |
| `WEB_SEARCH_MAX_RESULTS` | `5` | 1 回の検索で返す件数 |
| `WEB_SEARCH_FETCH_PAGES` | `2` | 本文を取得するページ数（最大 3） |
| `UPDATE_MANIFEST_URL` | 空 | 任意の HTTPS 更新マニフェスト（例：`{"version":"1.2.1","url":"https://…","notes":"…"}`）。空なら更新確認を一切行いません |

デスクトップ版ではシェルが `CAMPUS_DESKTOP_MODE`、`CAMPUS_DESKTOP_TOKEN`、`CAMPUS_DESKTOP_NONCE`、
`CAMPUS_DATA_DIR`、`CAMPUS_FRONTEND_DIR`、`CAMPUS_CONFIG_FILE` を注入します（入力不要。絶対パスのみ
受け付けます）。

### モデルとベクトル検索

- 設定画面でキーを保存し「保存済み設定をテスト」で接続を確認します。Windows では新しいキーを DPAPI で暗号化し、画面には再表示しません。
- ローカルモデル：Ollama をインストールして起動し、設定画面でモデルとダウンロード元を選びます。GGUF は固定バージョンで取得し SHA-256 を検証してから Ollama に取り込みます。モデルファイルはインストーラーに同梱されません。
- ベクトル検索の有効化：

  ```powershell
  cd backend
  .venv\Scripts\python -m pip install -r requirements-ai.txt
  # .env で ENABLE_RAG=true に設定し、バックエンドを再起動して知識ページの「索引を再構築」を押す
  ```

  初回の `BAAI/bge-m3` 読み込みにはダウンロードが必要です。ベクトルの初期化や検索に失敗した場合は、文書を保持したままキーワード検索に降格します。

### 学内データエンドポイント

9 種類のエンドポイントのフィールド、値パス、例は [CAMPUS-DATA.md](CAMPUS-DATA.md) にあります。要点：

- HTTPS の JSON のみ。Bearer トークンと結果パスに対応します。
- 未設定のエンドポイントは明確に表示されたデモデータを返します。本プロジェクトは実際の学校エンドポイント、統合認証、モデルの鍵を**同梱していません**。
- 本番配備には学校が認可したインターフェースと受け入れ検証が必要です。複数人での利用には、シングルサインオン、ユーザーごとの学籍番号の紐付け、操作の監査、レート制限も必要です（[CAMPUS-DATA.md](CAMPUS-DATA.md) と [ARCHITECTURE.md](ARCHITECTURE.md) を参照）。

## アーキテクチャとセキュリティ境界

### 技術スタック

- **フロントエンド**：Vue 3 + TypeScript + Vite + Element Plus + Pinia。ビルド時に依存ごとにチャンクを分割します（メインバンドルは約 71 KB）。
- **バックエンド**：FastAPI + SQLAlchemy + LangGraph。既定は SQLite の単一ファイルで、PostgreSQL も選択できます。
- **デスクトップ**：Electron シェル + PyInstaller で凍結した CPython（ランタイムをインストーラーに同梱）。
- **インストール可能なウェブ版**：マニフェスト、オフラインシェル（service worker）、iOS のセーフエリア対応。

### セキュリティ設計

- **ローカル優先**：デスクトップ版のバックエンドは `127.0.0.1` のランダムポートのみを待ち受け、起動ごとにワンタイムトークンを発行します。シェルは追加のリクエストヘッダーを注入し、Electron の設定を厳格化します（`nodeIntegration:false`、`contextIsolation:true`、`sandbox:true`、`webSecurity:true`、`webviewTag` 無効）。外部ページからこれらの API には到達できません。
- **送信の規律**（プラグイン / ウェブ検索 / 更新確認で共通）：HTTPS の 443 のみ。解決済みで検証済みのグローバルアドレスに接続を固定（DNS リバインディング対策として SNI を保持）。リダイレクト禁止。応答サイズとタイムアウトの上限。システムのプロキシ環境変数は無視（`trust_env=False`）。プライベートアドレスに解決した場合は即座に拒否します。
- **鍵の保存**：Windows は DPAPI。macOS / Linux には同等の仕組みがないため、`0600` 権限の平文ファイル（同一ユーザーのみ読取可）に保存します。この点は [PLATFORMS.md](PLATFORMS.md) に明記しています。
- **バックアップ**：書き出した zip には鍵ファイルが含まれるため厳重に保管してください。読み込み時は SHA-256 一覧を検証します。
- **捏造しない**：デモデータ、検索の降格、ウェブの参照元などの状態は必ず画面に表示します。

### リポジトリ構成

```text
campus-agent/
├─ backend/         FastAPI バックエンド（app/、tests/、requirements*.txt）
├─ frontend/        Vue 3 フロントエンド（src/、tests/、dist/）
├─ desktop/         Electron シェル（main.cjs、preload.cjs、lib/、assets/ アイコン）
├─ scripts/         ビルドとパッケージング（build_desktop.py、install.py、create_icon.py など）
├─ docs/            プロジェクト紹介ページ（GitHub Pages、中 / 英 / 日）
├─ assets/          ブランド素材
├─ examples/        プラグインマニフェストの例
├─ compose.yaml     Docker 配備用（PostgreSQL + バックエンド + Nginx）
├─ PLATFORMS.md     プラットフォームマトリクスとビルド方法
├─ DESKTOP.md       デスクトップ版の説明
├─ ARCHITECTURE.md  アーキテクチャと主要インターフェース
├─ CAMPUS-DATA.md   学内エンドポイントの形式
├─ VERIFICATION.md  検証記録（サイズ、SHA-256、範囲）
└─ LICENSE / NOTICE / THIRD-PARTY-NOTICES.md
```

## テストと検証

```powershell
# バックエンド（260 件、サブテスト 65 件）
cd backend
.venv\Scripts\python -m pytest -q

# フロントエンド（ユニットテスト 13 件）と本番ビルド
cd ..\frontend
npm test
npm run build

# デスクトップシェル（テスト 8 件）
cd ..\desktop
npm test

# 上記をまとめて実行（Windows）
.\verify.ps1
```

ネットワークがない環境では、システムの Python で 2 組のロジックテスト（フレームワーク / ネットワーク /
データベースに依存しません）を実行できます：

```powershell
cd backend
python -m unittest discover -s tests -p test_core_unit.py -v
python -m unittest discover -s tests -p test_agent_unit.py -v
```

これらは中核の検証と判断ロジックを対象としますが、実際の FastAPI、LangGraph、Chroma、モデルサービス、
ブラウザ連携の代替にはなりません。バグが絶対にないことを保証するテストはありません。完了した検証範囲、
インストーラーのサイズと SHA-256 は [VERIFICATION.md](VERIFICATION.md) にあります。

## 画面

| チャット（ウェブ参照元つき） | 設定（ウェブ検索） |
| --- | --- |
| <img src="docs/img/chat-web-search.png" alt="チャット画面：ウェブ検索結果と参照リンク" /> | <img src="docs/img/settings-web-search.png" alt="設定画面：ウェブ検索" /> |

| 学内サービス（修理申請と端末内の記録） |
| --- |
| <img src="docs/img/campus-services.png" alt="学内サービス画面：修理申請と端末内の記録" /> |

## 既知の制限

- **macOS / Linux の成果物は実機未検証** — CI が生成したもので、実機へのインストールと実行は未実施です。
- **署名・公証なし** — 発行者の証明書がないため、Windows / macOS の初回起動でシステムの警告が出ることがあります。本格配布の前に署名を設定すべきです。
- **学内連携とシングルサインオン** — 実際の学校エンドポイント、統合認証、モデルの鍵は同梱していません。本番配備には学校が認可したインターフェースと受け入れ検証が必要です。
- **クラウドモデルとウェブ検索** — それぞれ API キーが必要です（ウェブ検索の Bing 経路はキー不要）。検索バックエンドの可用性はネットワーク環境に左右されます。
- **Android / iOS のネイティブアプリ** — 対象外です。理由は [PLATFORMS.md](PLATFORMS.md) に記載しています（Python バックエンドはモバイルストアに同梱できません）。
- **ワンクリック更新** — 更新確認はバージョン差の通知とダウンロードページの表示のみで、自動ダウンロードやサイレントインストールは行いません。
- **複数人での配備** — 現在のデモ会話はランダムなセッション ID をアクセス資格情報にしています。ローカル開発のみに適しており、本番にはユーザー所属の検証、操作監査、レート制限、HTTPS、データベース移行、バックアップ方針が必要です。

## ライセンス

**Apache License 2.0**（[`LICENSE`](LICENSE)）で公開しています。著作権と帰属の表示は
[`NOTICE`](NOTICE) にあります。

- **できること**：自由な使用・改変・再配布。商用利用、学内配備、改変版のクローズドソース配布も含みます。
- **求められること**：著作権表示・ライセンス表示・NOTICE を保持し、改変したファイルを明示すること。本ライセンスはプロジェクト名や商標の使用権を許諾しません。
- **無保証**：本ソフトウェアは現状のまま提供され、明示・黙示を問わずいかなる保証も伴いません。
- **サードパーティ**：インストーラーには Electron、Chromium、CPython、PyInstaller、FastAPI、Vue、Element Plus などが含まれ、それぞれ元のライセンスで配布されます。一覧は [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) にあります。

## ドキュメント

| ドキュメント | 内容 |
| --- | --- |
| [プロジェクト紹介ページ](https://huanmoovo.github.io/campus-agent/) | 中・英・日の図解つき紹介、プラットフォームマトリクス、既知の制限 |
| [PLATFORMS.md](PLATFORMS.md) | プラットフォームマトリクス、ビルドコマンド、macOS / Linux の鍵保存の違い、モバイルの理由 |
| [DESKTOP.md](DESKTOP.md) | デスクトップ版の実行方法、データフォルダ、IPC とセキュリティ設定 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | アーキテクチャ、モジュールの役割、主要インターフェース |
| [CAMPUS-DATA.md](CAMPUS-DATA.md) | 9 種類の学内エンドポイントのフィールドと連携形式 |
| [VERIFICATION.md](VERIFICATION.md) | 各バッチの検証方法、インストーラーのサイズと SHA-256、未検証の範囲 |
| [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) | サードパーティコンポーネントとライセンス |
