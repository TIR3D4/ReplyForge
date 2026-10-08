"""Bound request bytes before JSON/multipart parsing, including chunked requests."""
from starlette.responses import JSONResponse


class RequestBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        limit = 16 * 1024 * 1024 if path == "/admin/insight/import" else 262144
        chunks = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > limit:
                return await JSONResponse({"detail": "Request too large"}, status_code=413)(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        consumed = False

        async def bounded_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([(b"x-content-type-options", b"nosniff"),
                                (b"referrer-policy", b"no-referrer"),
                                (b"x-frame-options", b"DENY")])
                if path.startswith("/admin") and not any(k.lower() == b"cache-control" for k, _ in headers):
                    headers.append((b"cache-control", b"private, no-store"))
                message["headers"] = headers
            await send(message)
        await self.app(scope, bounded_receive, secure_send)
