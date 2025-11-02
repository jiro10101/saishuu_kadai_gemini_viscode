# Linux Assistant Frontend

Ubuntu 24.04用のLinuxコマンド生成・実行アシスタントのフロントエンドアプリケーション。

## 機能

- **LLMによるコマンド生成**: 自然言語でのコマンド指示をbashコマンドに変換
- **安全なfio実行**: ディスクI/Oパフォーマンステストの安全な実行
- **会話履歴対応**: 過去の会話を考慮したコンテキスト対応
- **実行前確認**: 危険なコマンドの実行前確認機能
- **SSH経由実行**: リモートサーバーでのコマンド実行

## 技術スタック

- **UI**: Streamlit
- **LLM**: OpenAI GPT-4o + LangChain
- **HTTP Client**: Requests
- **設定管理**: Pydantic Settings
- **バックエンド連携**: FastAPI

## セットアップ

### 1. 仮想環境の作成
```bash
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows
# source venv/bin/activate    # Linux/Mac
```

### 2. 依存関係のインストール
```bash
pip install -r requirements.txt
```

### 3. 環境変数の設定
`.env` ファイルを作成し、以下を設定：
```
OPENAI_API_KEY=your_openai_api_key_here
FASTAPI_BACKEND_URL=http://127.0.0.1:8000
```

### 4. アプリケーションの起動
```bash
streamlit run app_streamlit.py
```

## ファイル構成

- `app_streamlit.py` - Streamlit UIメイン
- `llm_handler.py` - LLM処理とプロンプト管理
- `config.py` - 設定管理
- `requirements.txt` - Python依存関係
- `.env` - 環境変数（要作成）

## 安全性

- コマンド実行前の確認UI
- ブラックリストベースのコマンド検証
- fio実行時間の制限（最大10秒）
- 対象デバイスの固定化

## ログ機能

- 各関数レベルでの詳細ログ出力
- LLM呼び出しと応答の追跡
- エラーハンドリングとデバッグ情報

## 会話履歴

- 過去10件の会話履歴を考慮
- 文脈を理解したコマンド生成
- 継続的な対話サポート