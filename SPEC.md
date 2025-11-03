# Linuxアシスタント実装仕様 (Python + LangChain + FastAPI + Streamlit)

この文書は、リポジトリ `saishuu_kadai_gemini_viscode` に実装された Linux アシスタントの仕様を、現状のソースコード構成に基づいて整理したものです。Ubuntu 24.04 に関する知識を活用し、fio を用いたディスクI/Oベンチマークを安全に実行することを主目的としています。

## 1. システム概要

* **対象OS**: Ubuntu 24.04
* **目的**: ユーザーの自然言語リクエストを解釈し、リモート Linux サーバー上で安全にコマンド (特に fio) を実行する。
* **主要技術**:
  * フロントエンド: Streamlit + LangChain + OpenAI GPT-4o
  * バックエンド: FastAPI + Paramiko
  * SSH 実行先: `.env` で指定するリモートホスト (例: `itotest.tailfb67d0.ts.net`)
  * 結果保存先: リモートユーザーの `~/fio_results/<timestamp>/`

フロントエンド (Streamlit) 側でコマンド生成とユーザー確認を行い、承認されたコマンドのみを FastAPI バックエンド経由で SSH 実行します。バックエンドは実行結果をリモートサーバー上に保存し、レスポンスとして返却します。

## 2. ディレクトリ構成

```
saishuu_kadai_gemini_viscode/
├── Frontend/               # Streamlit アプリ & LangChain
│   ├── app_streamlit.py
│   ├── llm_handler.py
│   ├── config.py
│   └── requirements.txt
└── Backend/                # FastAPI バックエンド
    ├── main.py
    ├── ssh_executor.py
    ├── result_saver.py
    ├── access_middleware.py
    ├── logging_config.py
    ├── simple_auth.py
    ├── config.py
    └── requirements.txt
```

* それぞれのディレクトリに `.env` を配置し、必要な環境変数 (OpenAI API キー、バックエンド URL、SSH 接続情報、API キーなど) を設定します。

## 3. フロントエンド仕様 (Streamlit)

### 3.1 主な機能

1. **チャット UI (`app_streamlit.py`)**
   * `st.session_state` に会話履歴と確認待ちコマンドを保持。
   * 生成されたコマンドは必ずユーザーに確認させ、承認後にバックエンドへ送信。
   * 実行結果 (stdout/stderr、リモート保存先) をチャットに追記。

2. **LLM ハンドラ (`llm_handler.py`)**
   * `LLMHandler` が LangChain のチェーンを保持。
   * **コマンド生成チェーン**: GPT-4o を温度 0.0 で呼び出し、プロンプト上で fio 制約 (対象デバイス・10 秒以内・危険コマンド禁止) を厳格に指定。
   * **QA チェーン**: Ubuntu 24.04 の一般的な質問に回答。
   * 生成後のコマンドは Python 側で再バリデーション。
     * ブラックリスト (`rm`, `apt`, `dd` など) を検知するとブロック。
     * fio の `--filename=/dev/nvme0n1` 固定、`--runtime<=10` 秒を必須確認。
     * `--time_based` の場合は `--runtime` の併記を必須化。
   * 会話履歴は直近 10 件までを LangChain に渡す。

3. **バックエンド呼び出し**
   * `config.py` の `FASTAPI_BACKEND_URL` と `FASTAPI_API_KEY` を使用。
   * `execute_command()` が `/execute` に POST。タイムアウトは 120 秒。
   * レスポンスの `saved_path` をユーザーに提示。保存失敗時は警告。

### 3.2 UI・表示

* Streamlit ページタイトル: "Linux Assistant"
* エクスパンダで使用例を案内。
* 確認画面ではターゲットホスト (`SSH_TARGET_HOST`) を明示。
* 実行結果はコードブロックで表示。

### 3.3 設定 (`Frontend/config.py`)

* `OPENAI_API_KEY`, `FASTAPI_BACKEND_URL`, `FASTAPI_API_KEY` (任意) を `.env` から読込。
* fio の制約値を定数として保持:
  * `TARGET_DEVICE = "/dev/nvme0n1"`
  * `MAX_RUNTIME_SEC = 10`
* `SSH_TARGET_HOST` は確認 UI で表示するホスト名。

## 4. バックエンド仕様 (FastAPI)

### 4.1 API エンドポイント (`Backend/main.py`)

| Method | Path         | 認証 | 説明 |
|--------|--------------|------|------|
| POST   | `/execute`   | 任意 (API キー) | SSH でコマンド実行し、結果を保存して返却。|
| GET    | `/auth-test` | 要  | API キーの検証用。|
| GET    | `/health`    | 不要 | 動作確認用ヘルスチェック。|
| GET    | `/logs`      | 要  | アクセスログを末尾から取得。|
| GET    | `/logs/stats`| 要  | ログファイルサイズなどの統計情報。

* `CommandRequest`: `command` (必須)、`query` (任意)。
* `CommandResponse`: `stdout`, `stderr`, `exit_code`, `saved_path`。
* エラー時は `HTTPException` を返却。SSH 接続失敗などを詳細にログ出力。

### 4.2 認証 (`Backend/simple_auth.py`)

* `.env` の `API_KEY` が設定されている場合、`X-API-Key` ヘッダーをチェック。
* 未設定の場合は認証をバイパス (警告ログ出力)。

### 4.3 SSH 実行 (`Backend/ssh_executor.py`)

* Paramiko で SSH 接続 (`connect_ssh`)。
  * `.env` の `SSH_HOST`, `SSH_USER`, `SSH_KEY_PATH`, `SSH_PASSWORD` を使用。
  * パスワード認証 → 公開鍵認証の順に試行。
* `run_remote_command` で実行し、stdout/stderr/exit code を返却。

### 4.4 結果保存 (`Backend/result_saver.py`)

* `~/fio_results/YYYY-MM-DD_HH-MM-SS/` に保存。
  * `input.json`: `query`, `command`
  * `output.txt`: stdout/stderr
* `REMOTE_SAVE_DIR` を `echo` で展開し、`mkdir -p` でディレクトリ生成。
* ファイルはヒアドキュメント (`cat <<'EOF' > file`) でリモートに書き込み。

### 4.5 ロギングとミドルウェア

* `logging_config.py` で `logs/` ディレクトリ以下に `app.log`, `access.log`, `error.log` を出力。
* `access_middleware.py` が全リクエスト/レスポンスの詳細ログを記録。
* 起動時に設定値や認証状態をログ出力。

### 4.6 設定 (`Backend/config.py`)

* `.env` から以下を読込:
  * `SSH_HOST`, `SSH_USER`, `SSH_KEY_PATH`, `SSH_PASSWORD`
  * `REMOTE_SAVE_DIR` (デフォルト: `~/fio_results`)
  * `API_KEY`
* 追加の環境変数が存在しても無視 (`extra='ignore'`)。

## 5. コマンド生成とセキュリティ

1. **二重防御**
   * プロンプトで禁止コマンドや fio 制約を明示。
   * Python 側のバリデーションでブラックリスト検出・fio パラメータチェックを実施。

2. **ユーザー確認**
   * Streamlit UI で必ず実行確認を取り、許可された単一コマンドのみ実行。
   * キャンセル時は履歴に理由を記録。

3. **バックエンド側考慮**
   * 現状はフロントエンドを信頼して実行 (コメントに二重チェックの拡張余地あり)。
   * API キーによる保護をサポート。

4. **fio 制約**
   * 対象デバイス: `/dev/nvme0n1`
   * 実行時間: 最大 10 秒 (`--runtime` 必須)
   * `--time_based` 使用時も必ず `--runtime` をセット。
   * 曖昧または制約違反の指示は `Error: ...` を返す。

## 6. 結果保存とログ

* 実行ごとに一意のタイムスタンプディレクトリを作成。
* Streamlit 側は `saved_path` をチャットに表示し、保存失敗を警告。
* バックエンドはアクセスログ/API ログ/エラーログをローテーション出力。
* `/logs` エンドポイントで最新ログを確認可能。

## 7. セットアップ手順 (抜粋)

### 7.1 フロントエンド

```bash
cd Frontend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # (存在する場合)
# .env に OPENAI_API_KEY, FASTAPI_BACKEND_URL, FASTAPI_API_KEY を設定
streamlit run app_streamlit.py
```

### 7.2 バックエンド

```bash
cd Backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # (存在する場合)
# .env に SSH_HOST, SSH_USER, SSH_KEY_PATH または SSH_PASSWORD, REMOTE_SAVE_DIR, API_KEY を設定
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 8. 拡張ポイント

* バックエンド側にもコマンドバリデーションを追加して二重防御を強化。
* `.env` ひな型 (`.env.example`) の整備。
* Streamlit UI で結果履歴のダウンロードやフィルタリング機能を追加可能。
* 他の監視コマンド (iostat, top など) はプロンプトに追記することで拡張。

---

この仕様書は 2025-11-03 時点のソースコードを基にしており、コード変更に合わせて適宜更新してください。
