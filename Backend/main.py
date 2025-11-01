from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
import logging
from . import ssh_executor
from . import result_saver
from .config import settings

# ロガー設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPIアプリケーションインスタンスの作成
app = FastAPI(
    title="Linux Assistant Backend",
    description="SSH経由でLinuxコマンドを実行し、結果を保存するAPI (仕様書要件)"
)

# --- Pydanticモデル定義 (APIの入出力の型定義) ---

class CommandRequest(BaseModel):
    """
    /execute エンドポイントが受け取るリクエストボディの型定義。
    Streamlit (フロントエンド) はこの形式でJSONを送る必要がある。
    """
    command: str          # 実行するbashコマンド
    query: str | None = None # 元の自然言語クエリ (保存用)

class CommandResponse(BaseModel):
    """
    /execute エンドポイントが返すレスポンスボディの型定義。
    """
    stdout: str           # コマンドの標準出力
    stderr: str           # コマンドの標準エラー
    exit_code: int        # コマンドの終了コード
    saved_path: str | None = None # リモートサーバ上の保存先パス

# --- FastAPIイベントハンドラ ---

@app.on_event("startup")
def startup_event():
    """ FastAPIサーバ起動時に一度だけ実行される処理 """
    logger.info("FastAPIバックエンドサーバが起動します...")
    # 設定値（認証情報除く）をログに出力し、設定ミスがないか確認しやすくする
    logger.info(f"SSH接続先ホスト: {settings.SSH_HOST}")
    logger.info(f"SSH接続ユーザー: {settings.SSH_USER}")
    logger.info(f"SSHキーパス: {settings.SSH_KEY_PATH}")
    logger.info(f"リモート保存先: {settings.REMOTE_SAVE_DIR}")
    
    if not settings.SSH_KEY_PATH and not settings.SSH_PASSWORD:
        logger.error("重大な設定エラー: SSH_KEY_PATH も SSH_PASSWORD も設定されていません。")
        logger.error("backend/.env ファイルを確認してください。")

# --- APIエンドポイント定義 ---

@app.post("/execute", response_model=CommandResponse)
def execute_command_endpoint(request: CommandRequest):
    """
    (仕様書要件) Streamlitフロントエンドからコマンド実行リクエストを受け付けるエンドポイント。
    
    処理フロー:
    1. SSH接続を確立する。
    2. 受け取ったコマンドをリモートで実行する。
    3. 実行結果 (stdout, stderr) をリモートサーバに保存する。
    4. 実行結果をStreamlitに返す。
    """
    command = request.command
    query = request.query
    
    logger.info(f"コマンド実行リクエスト受信 (Query: '{query}'): {command}")

    # (仕様書要件) セキュリティ: 
    # 本来はフロントエンド(Streamlit/LLM)側でコマンドの検証を行う前提。
    # バックエンド側でも二重にチェック (例: ブラックリスト検証) を追加することが望ましいが、
    # ここでは仕様書に基づき、フロントエンドからの指示を信頼して実行する。
    # if is_command_unsafe(command):
    #     logger.warning(f"ブロックされたコマンド: {command}")
    #     raise HTTPException(status_code=403, detail="実行が禁止されたコマンドです。")

    client = None
    try:
        # 1. SSH接続
        client = ssh_executor.connect_ssh()
        if client is None:
            # 接続失敗時は 500 Internal Server Error を返す
            logger.error("SSH接続に失敗しました。認証情報 (ユーザー名、鍵、パスワード) とネットワーク設定を確認してください。")
            raise HTTPException(status_code=500, detail="SSH接続に失敗しました。バックエンドサーバのログを確認してください。")

        # 2. コマンド実行
        stdout, stderr, exit_code = ssh_executor.run_remote_command(client, command)
        
        # 3. 結果保存
        saved_path = result_saver.save_input_output(
            ssh_client=client,
            query=query if query else "N/A", # クエリが空の場合のフォールバック
            command=command,
            stdout=stdout,
            stderr=stderr
        )
        
        if saved_path is None:
            logger.warning("コマンドは実行されましたが、リモートサーバへの結果保存に失敗しました。")

        # 4. Streamlitへのレスポンス
        return CommandResponse(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            saved_path=saved_path # 保存パス (または失敗時はNone) を含める
        )

    except HTTPException as http_exc:
        # 既にHTTPExceptionとして処理済みの場合はそのまま投げる
        raise http_exc
    except Exception as e:
        # その他の予期せぬエラー
        logger.error(f"コマンド実行のワークフロー全体でエラーが発生: {e}")
        raise HTTPException(status_code=500, detail=f"内部サーバーエラー: {e}")
    finally:
        # 処理が成功しても失敗しても、必ずSSH接続を切断する
        if client:
            client.close()
            logger.info("SSH接続を切断しました。")

# Uvicornで実行する場合:
# uvicorn backend.main:app --host 0.0.0.0 --port 8000
