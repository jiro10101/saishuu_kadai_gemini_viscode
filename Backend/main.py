from fastapi import FastAPI, HTTPException, Body, Depends
from pydantic import BaseModel
import logging
import os
import ssh_executor
import result_saver
from config import settings
from simple_auth import verify_api_key
from logging_config import setup_logging
from access_middleware import AccessLogMiddleware

# ログ設定を初期化
setup_logging()
logger = logging.getLogger(__name__)

# FastAPIアプリケーションインスタンスの作成
app = FastAPI(
    title="Linux Assistant Backend",
    description="SSH経由でLinuxコマンドを実行し、結果を保存するAPI (仕様書要件)"
)

# アクセスログミドルウェアを追加
app.add_middleware(AccessLogMiddleware)

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
    logger.info("=== FastAPIバックエンドサーバ起動処理開始 ===")
    logger.info("FastAPIバックエンドサーバが起動します...")
    
    # 設定値（認証情報除く）をログに出力し、設定ミスがないか確認しやすくする
    logger.info("=== 設定値確認 ===")
    logger.info(f"SSH接続先ホスト: {settings.SSH_HOST}")
    logger.info(f"SSH接続ユーザー: {settings.SSH_USER}")
    logger.info(f"SSHキーパス: {settings.SSH_KEY_PATH}")
    logger.info(f"リモート保存先: {settings.REMOTE_SAVE_DIR}")
    
    # セキュリティ確認
    logger.info("=== 認証設定確認 ===")
    if settings.SSH_KEY_PATH:
        if os.path.exists(settings.SSH_KEY_PATH):
            logger.info(f"SSHキーファイル存在確認: OK ({settings.SSH_KEY_PATH})")
        else:
            logger.warning(f"SSHキーファイルが見つかりません: {settings.SSH_KEY_PATH}")
    
    if settings.SSH_PASSWORD:
        logger.info("SSHパスワード設定: あり")
    else:
        logger.info("SSHパスワード設定: なし")
    
    if not settings.SSH_KEY_PATH and not settings.SSH_PASSWORD:
        logger.error("重大な設定エラー: SSH_KEY_PATH も SSH_PASSWORD も設定されていません。")
        logger.error("backend/.env ファイルを確認してください。")
    else:
        logger.info("認証設定: OK")
    
    # API認証設定確認
    logger.info("=== API認証設定確認 ===")
    if settings.API_KEY:
        logger.info("API認証: 有効 (X-API-Key ヘッダーが必要)")
    else:
        logger.warning("API認証: 無効 (セキュリティリスク)")
    
    logger.info("=== FastAPIバックエンドサーバ起動処理完了 ===")

# --- APIエンドポイント定義 ---

@app.post("/execute", response_model=CommandResponse)
def execute_command_endpoint(
    request: CommandRequest,
    api_key: str = Depends(verify_api_key)
):
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
    
    logger.info(f"=== execute_command_endpoint 開始 ===")
    logger.info(f"受信したリクエスト - Query: '{query}', Command: '{command}'")

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
        logger.info("ステップ1: SSH接続を開始")
        client = ssh_executor.connect_ssh()
        if client is None:
            # 接続失敗時は 500 Internal Server Error を返す
            logger.error("SSH接続に失敗しました。認証情報 (ユーザー名、鍵、パスワード) とネットワーク設定を確認してください。")
            raise HTTPException(status_code=500, detail="SSH接続に失敗しました。バックエンドサーバのログを確認してください。")
        logger.info("ステップ1: SSH接続成功")

        # 2. コマンド実行
        logger.info("ステップ2: リモートコマンド実行を開始")
        stdout, stderr, exit_code = ssh_executor.run_remote_command(client, command)
        logger.info(f"ステップ2: コマンド実行完了 - 終了コード: {exit_code}")
        logger.debug(f"stdout長: {len(stdout)}文字, stderr長: {len(stderr)}文字")
        
        # 3. 結果保存
        logger.info("ステップ3: 結果保存を開始")
        saved_path = result_saver.save_input_output(
            ssh_client=client,
            query=query if query else "N/A", # クエリが空の場合のフォールバック
            command=command,
            stdout=stdout,
            stderr=stderr
        )
        
        if saved_path is None:
            logger.warning("コマンドは実行されましたが、リモートサーバへの結果保存に失敗しました。")
        else:
            logger.info(f"ステップ3: 結果保存成功 - パス: {saved_path}")

        # 4. Streamlitへのレスポンス
        logger.info("ステップ4: レスポンス作成")
        response = CommandResponse(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            saved_path=saved_path # 保存パス (または失敗時はNone) を含める
        )
        logger.info(f"=== execute_command_endpoint 正常終了 ===")
        return response

    except HTTPException as http_exc:
        # 既にHTTPExceptionとして処理済みの場合はそのまま投げる
        logger.error(f"HTTPException発生: {http_exc.status_code} - {http_exc.detail}")
        raise http_exc
    except Exception as e:
        # その他の予期せぬエラー
        logger.error(f"予期せぬエラーが発生: {type(e).__name__}: {e}")
        logger.error(f"=== execute_command_endpoint 異常終了 ===")
        raise HTTPException(status_code=500, detail=f"内部サーバーエラー: {e}")
    finally:
        # 処理が成功しても失敗しても、必ずSSH接続を切断する
        if client:
            logger.info("SSH接続のクリーンアップを実行")
            client.close()
            logger.info("SSH接続を切断しました。")

# --- 認証テスト用エンドポイント ---

@app.get("/auth-test")
def auth_test(api_key: str = Depends(verify_api_key)):
    """API認証のテスト用エンドポイント"""
    return {"message": "認証成功！", "status": "authenticated", "api_key_provided": api_key != "no-auth"}

@app.get("/health")
def health_check():
    """認証不要のヘルスチェックエンドポイント"""
    return {"status": "ok", "message": "サーバーは正常に動作しています"}

@app.get("/logs")
def get_recent_logs(api_key: str = Depends(verify_api_key), lines: int = 50):
    """最近のアクセスログを取得（認証必要）"""
    import os
    from pathlib import Path
    
    log_file = Path("logs/access.log")
    if not log_file.exists():
        return {"error": "ログファイルが見つかりません"}
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            
        return {
            "total_lines": len(all_lines),
            "returned_lines": len(recent_lines),
            "logs": [line.strip() for line in recent_lines]
        }
    except Exception as e:
        return {"error": f"ログファイル読み取りエラー: {str(e)}"}

@app.get("/logs/stats")
def get_log_stats(api_key: str = Depends(verify_api_key)):
    """ログファイルの統計情報を取得"""
    from pathlib import Path
    import os
    
    log_dir = Path("logs")
    if not log_dir.exists():
        return {"error": "ログディレクトリが見つかりません"}
    
    stats = {}
    for log_file in log_dir.glob("*.log"):
        file_stat = os.stat(log_file)
        stats[log_file.name] = {
            "size_bytes": file_stat.st_size,
            "size_mb": round(file_stat.st_size / (1024*1024), 2),
            "modified": file_stat.st_mtime
        }
    
    return {"log_files": stats}

# Uvicornで実行する場合:
# uvicorn main:app --host 0.0.0.0 --port 8000
