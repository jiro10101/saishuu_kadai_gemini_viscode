import time
import json
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse
from logging_config import get_access_logger, get_error_logger
import traceback

access_logger = get_access_logger()
error_logger = get_error_logger()

class AccessLogMiddleware(BaseHTTPMiddleware):
    """
    すべてのHTTPリクエストとレスポンスを詳細にログ記録するミドルウェア
    """
    
    async def dispatch(self, request: Request, call_next):
        # リクエスト開始時刻
        start_time = time.time()
        
        # クライアント情報を取得
        client_ip = self.get_client_ip(request)
        user_agent = request.headers.get("user-agent", "Unknown")
        
        # リクエスト詳細情報
        request_info = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time)),
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "client_ip": client_ip,
            "user_agent": user_agent,
            "headers": dict(request.headers) if self.should_log_headers() else "HIDDEN",
        }
        
        # リクエストボディの取得（小さいサイズのみ）
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await self.get_request_body(request)
                if body and len(body) < 1000:  # 1KB未満のみログ
                    request_info["body_preview"] = body[:500]  # 最初の500文字のみ
            except Exception as e:
                request_info["body_error"] = str(e)
        
        # レスポンス処理
        response = None
        error_occurred = False
        
        try:
            response = await call_next(request)
        except Exception as e:
            error_occurred = True
            error_logger.error(f"Request processing failed: {e}\n{traceback.format_exc()}")
            # エラーレスポンスを作成
            response = Response(
                content=json.dumps({"error": "Internal server error"}),
                status_code=500,
                media_type="application/json"
            )
        
        # 処理時間を計算
        process_time = time.time() - start_time
        
        # レスポンス情報
        response_info = {
            "status_code": response.status_code,
            "response_headers": dict(response.headers) if self.should_log_headers() else "HIDDEN",
            "process_time_ms": round(process_time * 1000, 2),
            "error_occurred": error_occurred
        }
        
        # アクセスログを記録
        log_entry = {
            "request": request_info,
            "response": response_info
        }
        
        # ログレベルを決定
        if response.status_code >= 500:
            log_level = "ERROR"
        elif response.status_code >= 400:
            log_level = "WARNING"
        else:
            log_level = "INFO"
        
        # ログメッセージの作成
        log_message = (
            f"[{log_level}] {request.method} {request.url.path} "
            f"- {response.status_code} - {client_ip} - {process_time:.3f}s"
        )
        
        # 詳細情報をJSONとして記録
        access_logger.info(f"{log_message} | {json.dumps(log_entry, ensure_ascii=False)}")
        
        return response
    
    def get_client_ip(self, request: Request) -> str:
        """クライアントIPアドレスを取得"""
        # プロキシ経由の場合の対応
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"
    
    async def get_request_body(self, request: Request) -> str:
        """リクエストボディを取得"""
        try:
            body = await request.body()
            if body:
                return body.decode('utf-8')
        except Exception:
            pass
        return ""
    
    def should_log_headers(self) -> bool:
        """ヘッダー情報をログに含めるかどうか"""
        # セキュリティ上の理由で、本番環境では False にすることを推奨
        return True
    
    def should_exclude_path(self, path: str) -> bool:
        """特定のパスをログから除外するかどうか"""
        exclude_paths = ["/health", "/metrics", "/favicon.ico"]
        return path in exclude_paths