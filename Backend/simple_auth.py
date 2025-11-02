from fastapi import HTTPException, status, Header
from typing import Optional
import logging
from config import settings

logger = logging.getLogger(__name__)

def verify_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    """
    シンプルなAPIキー認証
    X-API-Key ヘッダーをチェックして環境変数のAPI_KEYと比較
    """
    # 設定されたAPIキーがない場合は認証をスキップ
    if not settings.API_KEY:
        logger.warning("API_KEY not configured - authentication disabled")
        return "no-auth"
    
    # APIキーが提供されていない場合
    if not x_api_key:
        logger.warning("API key missing from request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Provide via 'X-API-Key' header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    # APIキーが間違っている場合
    if x_api_key != settings.API_KEY:
        logger.warning(f"Invalid API key attempted: {x_api_key[:10]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    logger.info("API key authenticated successfully")
    return x_api_key