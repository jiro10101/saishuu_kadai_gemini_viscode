import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    アプリケーションの設定を管理するクラス。
    .env ファイルから環境変数を読み込みます。
    
    Attributes:
        SSH_HOST (str): 接続先のSSHサーバーホスト名 (仕様書指定)。
        SSH_USER (str): SSH接続に使用するユーザー名。
        SSH_KEY_PATH (str | None): SSH接続用の秘密鍵のパス。Noneの場合はパスワード認証を試みます。
        SSH_PASSWORD (str | None): SSH接続用のパスワード。Noneの場合は公開鍵認証を試みます。
        REMOTE_SAVE_DIR (str): リモートサーバ上で結果を保存するベースディレクトリ (仕様書指定)。
    """
    
    # model_config: Pydantic V2 の設定方法
    # .env ファイルをUTF-8で読み込む設定
    model_config = SettingsConfigDict(
        env_file='.env', 
        env_file_encoding='utf-8', 
        extra='ignore' # .envファイルに余分な定義があっても無視する
    )

    # --- SSH接続設定 ---
    SSH_HOST: str  #= "localhost"
    SSH_USER: str  # .env での定義が必須
    
    # os.path.expanduser は "~" (ホームディレクトリ) を解決するために使用
    SSH_KEY_PATH: str | None = os.path.expanduser("~/.ssh/id_rsa") 
    SSH_PASSWORD: str | None = None

    # --- 保存先設定 (仕様書要件) ---
    REMOTE_SAVE_DIR: str = "~/fio_results"
    
    # --- API認証設定 (シンプル認証) ---
    API_KEY: str | None = None

# 設定クラスのインスタンスを作成
# この 'settings' オブジェクトを他のモジュールがインポートして使用する
settings = Settings()
