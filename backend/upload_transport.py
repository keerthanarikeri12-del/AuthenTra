"""Bound upload reception before multipart parsing, including chunked requests."""
import tempfile
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from . import uploads
from .documents import MAX_BYTES
from .storage import canonical_role, ROLE_INSTITUTION_ADMIN, ROLE_SYSTEM_ADMIN


class UploadTransport:
    def __init__(self, app, authenticate):
        self.app = app
        self.authenticate = authenticate
        self.active = 0

    async def __call__(self, scope, receive, send):
        paths = {'/api/uploads', '/api/verify', '/api/certificates', '/api/certificates/bulk'}
        if scope['type'] != 'http' or scope['method'] != 'POST' or scope['path'] not in paths:
            return await self.app(scope, receive, send)
        request = Request(scope)
        try:
            user = await run_in_threadpool(self.authenticate, request)
            user_role = canonical_role(user.get('role'))
            if user_role == ROLE_SYSTEM_ADMIN:
                raise HTTPException(403, 'System administrators do not have certificate upload or registration permissions.')
            if scope['path'].startswith('/api/certificates') and user_role != ROLE_INSTITUTION_ADMIN:
                raise HTTPException(403, 'Only approved institutions may register certificates.')
            maximum = max(uploads.BULK_BYTES, uploads.USER_FILES * MAX_BYTES) if user_role == ROLE_INSTITUTION_ADMIN else uploads.USER_FILES * MAX_BYTES
            maximum += 1024 * 1024  # multipart headers and reference fields
            try:
                declared = int(request.headers.get('content-length', '0'))
            except ValueError:
                raise HTTPException(400, 'Invalid content length.')
            if declared < 0 or declared > maximum:
                raise HTTPException(413, 'Request exceeds the configured batch size limit.')
            if self.active >= 2:
                raise HTTPException(429, 'Two uploads are already being received. Please retry shortly.')
            self.active += 1
            try:
                # Disk-spooled, bounded input avoids trusting Content-Length or buffering unbounded RAM.
                with tempfile.TemporaryFile() as body:
                    total = 0
                    while True:
                        message = await receive()
                        if message['type'] == 'http.disconnect':
                            return
                        chunk = message.get('body', b'')
                        total += len(chunk)
                        if total > maximum:
                            raise HTTPException(413, 'Request exceeds the configured batch size limit.')
                        await run_in_threadpool(body.write, chunk)
                        if not message.get('more_body', False):
                            break
                    await run_in_threadpool(body.seek, 0)
                    remaining = total
                    async def replay():
                        nonlocal remaining
                        if remaining <= 0:
                            return {'type': 'http.request', 'body': b'', 'more_body': False}
                        chunk = await run_in_threadpool(body.read, min(65536, remaining))
                        remaining -= len(chunk)
                        return {'type': 'http.request', 'body': chunk, 'more_body': remaining > 0}
                    if total == 0:
                        raise HTTPException(422, 'Choose certificate files to upload.')
                    await self.app(scope, replay, send)
            finally:
                self.active -= 1
        except HTTPException as exc:
            try:
                while True:
                    msg = await receive()
                    if msg['type'] == 'http.disconnect' or not msg.get('more_body', False):
                        break
            except Exception:
                pass
            await JSONResponse({'detail': exc.detail}, status_code=exc.status_code, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})(scope, receive, send)
