import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    フロントエンド (Streamlit) アプリケーションの設定を管理するクラス。
    .env ファイルから環境変数を読み込みます。
    
    Attributes:
        OPENAI_API_KEY (str): LLM (GPT) を使用するためのAPIキー。
        FASTAPI_BACKEND_URL (str): 接続先のバックエンドAPIのURL。
    """
    model_config = SettingsConfigDict(
        env_file='.env', 
        env_file_encoding='utf-8', 
        extra='ignore'
    )

    # --- LLM設定 ---
    OPENAI_API_KEY: str # .env での定義が必須

    # --- バックエンドAPI設定 ---
    FASTAPI_BACKEND_URL: str  # = "https://itotest.tailfb67d0.ts.net" # デフォルト
    # FastAPIにリクエストする際に使用するAPIキー (任意)。.env に設定すると
    # フロントエンドからのリクエスト時に自動で `X-API-Key` ヘッダーが付与されます。
    FASTAPI_API_KEY: str | None = None

# 設定クラスのインスタンスを作成
settings = Settings()


def get_backend_headers() -> dict:
    """
    バックエンド (FastAPI) に送信する共通ヘッダーを返します。
    `FASTAPI_API_KEY` が設定されている場合は `X-API-Key` ヘッダーを含めます。
    """
    if settings.FASTAPI_API_KEY:
        return {"X-API-Key": settings.FASTAPI_API_KEY}
    return {}


# --- 仕様書に基づく固定値 (プロンプト制御用) ---
# これらの値は llm_handler.py のプロンプトテンプレートで使用されます。

# (仕様書要件) fio の対象デバイスを厳密に指定
TARGET_DEVICE = "/dev/nvme0n1"

# (仕様書要件) fio の最大実行時間 (秒) を厳密に指定
MAX_RUNTIME_SEC = 10

# UI表示用のターゲットホスト名
SSH_TARGET_HOST = "loaclhost"
