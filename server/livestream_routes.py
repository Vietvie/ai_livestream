from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
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
        # A new OBS client authenticates this endpoint with the separate,
        # limited registration key and chooses its own client_id.
        if request.path == "/api/v1/register":
            return await handler(request)
        # Stream and self-service assets use a per-client token instead of the
        # administrator token. Their exact handlers enforce client ownership.
        client_scoped = request.path.startswith("/api/v1/clients/") and (
            request.path.endswith("/stream.ts") or "/assets/" in request.path
        )
        if client_scoped:
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

    def voice_tts(session_id):
        avatar = orchestrator.session_manager.get_session(str(session_id or "0"))
        if avatar is None:
            raise ValueError(f"Avatar session not found: {session_id or '0'}")
        tts = getattr(avatar, "tts", None)
        if tts is None or not hasattr(tts, "configure_voice_clone"):
            raise ValueError("Voice cloning requires the omnivoice TTS backend")
        return tts

    async def voice_clone_status(request):
        denied = await authorize(request)
        if denied:
            return denied
        try:
            tts = voice_tts(request.query.get("sessionid", "0"))
            return _json(tts.get_voice_clone_status())
        except Exception as exc:
            return _error(exc)

    async def voice_clone_upload(request):
        denied = await authorize(request)
        if denied:
            return denied
        destination = None
        temporary = None
        try:
            form = await request.post()
            consent = str(form.get("consent", "")).strip().lower()
            if consent not in {"1", "true", "yes", "confirmed"}:
                raise ValueError(
                    "Voice owner consent must be confirmed with consent=true"
                )
            ref_text = str(form.get("ref_text", "")).strip()
            if not ref_text:
                raise ValueError("ref_text must exactly match the reference speech")
            upload = form.get("file")
            if upload is None or not hasattr(upload, "file"):
                raise ValueError("A WAV file is required in multipart field 'file'")
            filename = str(getattr(upload, "filename", "") or "")
            if Path(filename).suffix.lower() != ".wav":
                raise ValueError("Voice reference must be a WAV file")

            max_bytes = 25 * 1024 * 1024
            payload = upload.file.read(max_bytes + 1)
            if not payload:
                raise ValueError("Uploaded voice reference is empty")
            if len(payload) > max_bytes:
                raise ValueError("Voice reference exceeds the 25 MB limit")

            session_id = str(form.get("sessionid", "0") or "0")
            session_key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
            voice_dir = Path("data/voices")
            voice_dir.mkdir(parents=True, exist_ok=True)
            destination = voice_dir / (
                f"session-{session_key}-{secrets.token_hex(4)}.wav"
            )
            temporary = destination.with_suffix(".wav.upload")
            temporary.write_bytes(payload)
            temporary.replace(destination)

            tts = voice_tts(session_id)
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(
                None,
                tts.configure_voice_clone,
                str(destination.resolve()),
                ref_text,
            )
            for stale in voice_dir.glob(f"session-{session_key}-*.wav"):
                if stale != destination:
                    stale.unlink(missing_ok=True)
            return _json({"enabled": True, "reference": info})
        except Exception as exc:
            if temporary is not None and temporary.exists():
                temporary.unlink(missing_ok=True)
            if destination is not None and destination.exists():
                destination.unlink(missing_ok=True)
            return _error(exc)

    async def voice_clone_clear(request):
        denied = await authorize(request)
        if denied:
            return denied
        try:
            session_id = request.query.get("sessionid", "0")
            tts = voice_tts(session_id)
            tts.clear_voice_clone()
            session_key = hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()[:16]
            voice_dir = Path("data/voices")
            if voice_dir.exists():
                for stale in voice_dir.glob(f"session-{session_key}-*.wav"):
                    stale.unlink(missing_ok=True)
            return _json({"enabled": False, "reference": None})
        except Exception as exc:
            return _error(exc)

    app.router.add_post("/api/livestream/comments", comments)
    app.router.add_post("/api/livestream/speak", speak)
    app.router.add_post("/api/livestream/scripts/trigger", trigger_script)
    app.router.add_post("/api/livestream/pause", pause)
    app.router.add_post("/api/livestream/resume", resume)
    app.router.add_get("/api/livestream/status", status)
    app.router.add_get("/api/livestream/products", products)
    app.router.add_get("/api/livestream/voice-clone", voice_clone_status)
    app.router.add_post("/api/livestream/voice-clone", voice_clone_upload)
    app.router.add_delete("/api/livestream/voice-clone", voice_clone_clear)
