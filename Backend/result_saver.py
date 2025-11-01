import json
import logging
from datetime import datetime
from .config import settings
from .ssh_executor import run_remote_command
import paramiko

logger = logging.getLogger(__name__)

def get_timestamp_folder() -> str:
    """
    仕様書要件 (YYYY-MM-DD_HH-MM-SS) に基づくタイムスタンプ付きの
    ディレクトリ名を生成します。

    Returns:
        str: 現在時刻のタイムスタンプ文字列。
    """
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def save_input_output(ssh_client: paramiko.SSHClient, query: str, command: str, stdout: str, stderr: str) -> str | None:
    """
    実行条件と結果を、リモートのLinuxサーバに保存します (仕様書要件)。
    
    保存先: {REMOTE_SAVE_DIR}/{タイムスタンプ}/
    保存ファイル:
      - input.json (実行コマンドと元のクエリ)
      - output.txt (標準出力と標準エラー)

    Args:
        ssh_client: 接続済みのParamiko SSHClient。
        query: ユーザーの元の入力 (Streamlitから受け取る)。
        command: 実行されたコマンド。
        stdout: コマンドの標準出力。
        stderr: コマンドの標準エラー。
        
    Returns:
        str | None: 保存に成功したリモートディレクトリのフルパス。失敗した場合は None。
    """
    try:
        timestamp_folder = get_timestamp_folder()
        
        # 1. ベースディレクトリのパスを展開
        # configのREMOTE_SAVE_DIRが "~/fio_results" のような相対パスの場合、
        # `echo` を使ってリモートシェルに展開させ、絶対パス (例: /home/user/fio_results) を取得します。
        base_dir_cmd = f"echo {settings.REMOTE_SAVE_DIR}"
        stdout_base, stderr_base, exit_code_base = run_remote_command(ssh_client, base_dir_cmd)
        
        if exit_code_base != 0:
            logger.error(f"リモート保存先ディレクトリのパス解決に失敗: {stderr_base}")
            return None
            
        base_save_dir = stdout_base.strip()
        # 最終的な保存先ディレクトリパス
        remote_dir = f"{base_save_dir}/{timestamp_folder}"
        
        # 2. タイムスタンプ付きディレクトリの作成
        # `mkdir -p` は親ディレクトリが存在しなくても再帰的に作成するオプション
        mkdir_cmd = f"mkdir -p {remote_dir}"
        _, stderr_mkdir, exit_mkdir = run_remote_command(ssh_client, mkdir_cmd)
        if exit_mkdir != 0:
            logger.error(f"リモートディレクトリの作成に失敗 '{remote_dir}': {stderr_mkdir}")
            return None

        # 3. input.json (実行条件) の保存
        input_data = {
            "query": query,
            "command": command
        }
        # JSON文字列に変換
        input_json_str = json.dumps(input_data, indent=2, ensure_ascii=False)
        
        # 'cat' とヒアドキュメント (<<) を使って、リモートサーバ上に直接ファイルを作成します。
        # これにより、ローカルに一時ファイルを作成する必要がなくなります。
        # 'FIO_ASSISTANT_EOF' は終端マーカーです。
        # シングルクォート ('FIO_ASSISTANT_EOF') にすることで、中の $ 変数が展開されるのを防ぎます。
        save_input_cmd = f"""
cat << 'FIO_ASSISTANT_EOF' > {remote_dir}/input.json
{input_json_str}
FIO_ASSISTANT_EOF
"""
        _, stderr_input, exit_input = run_remote_command(ssh_client, save_input_cmd)
        if exit_input != 0:
            # 警告をログに残すが、処理は続行 (output.txtの保存を試みる)
            logger.warning(f"input.json のリモート保存に失敗: {stderr_input}")

        # 4. output.txt (実行結果) の保存
        output_data = f"--- STDOUT ---\n{stdout}\n\n--- STDERR ---\n{stderr}"
        
        save_output_cmd = f"""
cat << 'FIO_ASSISTANT_EOF' > {remote_dir}/output.txt
{output_data}
FIO_ASSISTANT_EOF
"""
        _, stderr_output, exit_output = run_remote_command(ssh_client, save_output_cmd)
        if exit_output != 0:
            logger.error(f"output.txt のリモート保存に失敗: {stderr_output}")
            return None # outputの保存失敗は致命的とみなす
            
        logger.info(f"結果をリモートに保存成功: {settings.SSH_HOST}:{remote_dir}")
        return remote_dir

    except Exception as e:
        logger.error(f"結果保存プロセス中に例外が発生: {e}")
        return None
    