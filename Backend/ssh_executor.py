import paramiko
import logging
import os
from .config import settings

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def connect_ssh() -> paramiko.SSHClient | None:
    """
    SSH接続を初期化し、接続済みのParamikoクライアントオブジェクトを返します。
    
    仕様書に基づき、秘密鍵 (SSH_KEY_PATH) または パスワード (SSH_PASSWORD) の
    いずれかが .env に設定されていれば接続を試みます。

    Returns:
        paramiko.SSHClient | None: 
            接続成功時はSSHクライアントオブジェクト。
            失敗時は None。
    """
    client = paramiko.SSHClient()
    
    # 初回接続時にホストキーを自動的に追加するポリシー (セキュリティ的には警告が出る可能性があるが、開発用としては一般的)
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        key_path = settings.SSH_KEY_PATH
        password = settings.SSH_PASSWORD

        # 1. 秘密鍵による接続を試行
        if key_path and os.path.exists(key_path):
            logger.info(f"SSH接続試行 (公開鍵認証) -> {settings.SSH_USER}@{settings.SSH_HOST} (キー: {key_path})")
            client.connect(
                settings.SSH_HOST,
                username=settings.SSH_USER,
                key_filename=key_path
            )
        # 2. パスワードによる接続を試行
        elif password:
            logger.info(f"SSH接続試行 (パスワード認証) -> {settings.SSH_USER}@{settings.SSH_HOST}")
            client.connect(
                settings.SSH_HOST,
                username=settings.SSH_USER,
                password=password
            )
        # 3. どちらの設定もない場合
        else:
            logger.error("SSH接続失敗: .env に SSH_KEY_PATH (ファイルが存在しない) も SSH_PASSWORD も設定されていません。")
            return None
        
        logger.info("SSH接続成功。")
        return client
        
    except Exception as e:
        logger.error(f"SSH接続中に例外が発生しました: {e}")
        return None

def run_remote_command(client: paramiko.SSHClient, command: str) -> tuple[str, str, int]:
    """
    接続済みのSSHクライアントを使用して、リモートでbashコマンドを実行します。

    Args:
        client (paramiko.SSHClient): 接続済みのSSHクライアント。
        command (str): リモートで実行するbashコマンド文字列。

    Returns:
        tuple[str, str, int]: 
            (stdout: 標準出力, stderr: 標準エラー, exit_code: 終了コード) のタプル。
    """
    if not client:
        return "", "SSHクライアントが接続されていません", 1

    try:
        logger.info(f"リモートコマンド実行: {command}")
        
        # client.exec_command() はコマンドを実行し、即座に (stdin, stdout, stderr) のチャネルを返す
        stdin, stdout, stderr = client.exec_command(command)
        
        # コマンドの実行完了を待機し、終了コードを取得する
        # stdout.channel.recv_exit_status() は実行が完了するまでブロック (待機) する
        exit_code = stdout.channel.recv_exit_status()
        
        # 出力チャネルから結果を読み取り、デコードする
        stdout_output = stdout.read().decode('utf-8').strip()
        stderr_output = stderr.read().decode('utf-8').strip()
        
        logger.info(f"コマンド実行完了 (終了コード: {exit_code})")
        
        if stdout_output:
            logger.debug(f"STDOUT:\n{stdout_output}")
        if stderr_output:
            logger.warning(f"STDERR:\n{stderr_output}")

        return stdout_output, stderr_output, exit_code
        
    except Exception as e:
        logger.error(f"リモートコマンド実行中に例外が発生しました ('{command}'): {e}")
        return "", str(e), 1
        