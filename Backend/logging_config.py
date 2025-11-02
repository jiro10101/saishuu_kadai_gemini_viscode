import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path

def setup_logging():
    """
    アプリケーション用のログ設定を初期化
    """
    # ログディレクトリの作成
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # ログフォーマット
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # ルートロガーの設定
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # 既存のハンドラーをクリア
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # コンソールハンドラー
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(log_format, date_format)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # アプリケーションログファイルハンドラー（ローテーション）
    app_file_handler = logging.handlers.RotatingFileHandler(
        filename=log_dir / "app.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    app_file_handler.setLevel(logging.INFO)
    app_file_formatter = logging.Formatter(log_format, date_format)
    app_file_handler.setFormatter(app_file_formatter)
    root_logger.addHandler(app_file_handler)
    
    # アクセスログ専用ハンドラー
    access_logger = logging.getLogger("access")
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False  # ルートロガーに伝播しない
    
    access_file_handler = logging.handlers.RotatingFileHandler(
        filename=log_dir / "access.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=10,
        encoding='utf-8'
    )
    access_file_handler.setLevel(logging.INFO)
    
    # アクセスログ用の詳細フォーマット
    access_format = "%(asctime)s - %(message)s"
    access_formatter = logging.Formatter(access_format, date_format)
    access_file_handler.setFormatter(access_formatter)
    access_logger.addHandler(access_file_handler)
    
    # エラーログ専用ハンドラー
    error_logger = logging.getLogger("error")
    error_logger.setLevel(logging.ERROR)
    error_logger.propagate = False
    
    error_file_handler = logging.handlers.RotatingFileHandler(
        filename=log_dir / "error.log",
        maxBytes=5*1024*1024,  # 5MB
        backupCount=5,
        encoding='utf-8'
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s",
        date_format
    )
    error_file_handler.setFormatter(error_file_formatter)
    error_logger.addHandler(error_file_handler)
    
    logging.info("Logging configuration initialized")
    logging.info(f"Log files will be saved to: {log_dir.absolute()}")

def get_access_logger():
    """アクセスログ専用ロガーを取得"""
    return logging.getLogger("access")

def get_error_logger():
    """エラーログ専用ロガーを取得"""
    return logging.getLogger("error")