from __future__ import annotations

import json
import secrets
from aiohttp import web


def _json(data=None, status=200):
    body = {"code": 0 if status < 400 else -1, "msg": "ok" if status < 400 else "error"}
    if data is not None:
        body["data"] = data
    return web.Response(status=status, content_type="application/json", text=json.dumps(body, ensure_ascii=False))


def _error(message, status=400):
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps({"code": -1, "msg": str(message)}, ensure_ascii=False),
    )


def setup_livestream_routes(app, orchestrator):
    def auth_error(request):
        settings = orchestrator.settings
        token = settings.api_token
        if not token and settings.api.allow_unauthenticated:
            return None
        if not token:
            return _error(
                f"Server API token is not configured ({settings.api.token_env})", status=503
            )
        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {token}"
        if not secrets.compare_digest(supplied, expected):
            return _error("Unauthorized", status=401)
        return None

    @web.middleware
    async def protect_upstream_control_api(request, handler):
        if request.method == "OPTIONS":
            return await handler(request)
        protected = tuple(orchestrator.settings.api.protected_paths)
        if protected and request.path.startswith(protected):
            denied = auth_error(request)
            if denied:
                return denied
        return await handler(request)

    app.middlewares.append(protect_upstream_control_api)

    async def authorize(request):
        return auth_error(request)

    async def body(request):
        try:
            payload = await request.json()
        except Exception as exc:
            raise ValueError("Request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    async def comments(request):
        denied = await authorize(request)
        if denied:
            return denied
        try:
            payload = await body(request)
            accepted = orchestrator.submit_comment(
                text=str(payload.get("text", "")),
                session_id=payload.get("sessionid"),
                external_id=str(payload.get("comment_id", "")),
                interrupt=payload.get("interrupt"),
                metadata={"user": payload.get("user", "")},
            )
            return _json({"accepted": accepted, "duplicate": not accepted})
        except Exception as exc:
            return _error(exc)

    async def speak(request):
        denied = await authorize(request)
        if denied:
            return denied
        try:
            payload = await body(request)
            orchestrator.submit_speech(
                text=str(payload.get("text", "")),
                session_id=payload.get("sessionid"),
                interrupt=bool(payload.get("interrupt", False)),
            )
            return _json({"accepted": True})
        except Exception as exc:
            return _error(exc)

    async def trigger_script(request):
        denied = await authorize(request)
        if denied:
            return denied
        try:
            payload = await body(request)
            orchestrator.trigger_script(str(payload.get("script_id", "")), payload.get("sessionid"))
            return _json({"accepted": True})
        except KeyError as exc:
            return _error(exc, status=404)
        except Exception as exc:
            return _error(exc)

    async def pause(request):
        denied = await authorize(request)
        if denied:
            return denied
        orchestrator.pause()
        return _json(orchestrator.status())

    async def resume(request):
        denied = await authorize(request)
        if denied:
            return denied
        orchestrator.resume()
        return _json(orchestrator.status())

    async def status(request):
        denied = await authorize(request)
        if denied:
            return denied
        return _json(orchestrator.status())

    async def products(request):
        denied = await authorize(request)
        if denied:
            return denied
        return _json({"products": orchestrator.agent.catalog.public_products()})

    app.router.add_post("/api/livestream/comments", comments)
    app.router.add_post("/api/livestream/speak", speak)
    app.router.add_post("/api/livestream/scripts/trigger", trigger_script)
    app.router.add_post("/api/livestream/pause", pause)
    app.router.add_post("/api/livestream/resume", resume)
    app.router.add_get("/api/livestream/status", status)
    app.router.add_get("/api/livestream/products", products)
