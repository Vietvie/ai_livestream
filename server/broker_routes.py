"""HTTP API for the multi-client FIFO speech broker."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import queue

from aiohttp import web

from server.broker_service import BrokerService
from streamout.broker import broadcast_registry


def _json(data=None, status: int = 200):
    payload = {
        "code": 0 if status < 400 else -1,
        "msg": "ok" if status < 400 else "error",
    }
    if data is not None:
        payload["data"] = data
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps(payload, ensure_ascii=False),
    )


def _error(exc: Exception, status: int = 400):
    if isinstance(exc, KeyError):
        status = 404
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps({"code": -1, "msg": str(exc)}, ensure_ascii=False),
    )


async def _body(request) -> dict:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")
    return payload


def setup_broker_routes(app: web.Application, service: BrokerService) -> None:
    async def list_assets(request):
        return _json(
            {
                "avatars": service.list_avatars(),
                "voices": service.list_voices(),
            }
        )

    async def list_clients(request):
        return _json({"clients": service.list_profiles()})

    async def get_client(request):
        try:
            return _json(asdict(service.get_profile(request.match_info["client_id"])))
        except Exception as exc:
            return _error(exc)

    async def put_client(request):
        try:
            payload = await _body(request)
            profile = service.upsert_profile(
                request.match_info["client_id"],
                str(payload.get("avatar_id", "")),
                str(payload.get("voice_id", "")),
            )
            return _json(asdict(profile))
        except Exception as exc:
            return _error(exc)

    async def delete_client(request):
        try:
            service.delete_profile(request.match_info["client_id"])
            return _json({"deleted": True})
        except Exception as exc:
            return _error(exc)

    async def upload_voice(request):
        try:
            form = await request.post()
            consent = str(form.get("consent", "")).strip().lower()
            if consent not in {"1", "true", "yes", "confirmed"}:
                raise ValueError("Voice owner consent must be confirmed")
            upload = form.get("file")
            if upload is None or not hasattr(upload, "file"):
                raise ValueError("Multipart WAV field 'file' is required")
            filename = str(getattr(upload, "filename", "") or "")
            if not filename.lower().endswith(".wav"):
                raise ValueError("Voice reference must be a WAV file")
            max_bytes = 25 * 1024 * 1024
            payload = upload.file.read(max_bytes + 1)
            if len(payload) > max_bytes:
                raise ValueError("Voice reference exceeds 25 MB")
            loop = asyncio.get_running_loop()
            metadata = await loop.run_in_executor(
                None,
                service.save_voice,
                request.match_info["voice_id"],
                payload,
                str(form.get("ref_text", "")),
            )
            return _json(metadata)
        except Exception as exc:
            return _error(exc)

    async def submit_job(request):
        try:
            payload = await _body(request)
            job = service.submit(
                str(payload.get("client_id", "")),
                str(payload.get("text", "")),
            )
            return _json(
                {**asdict(job), "queue_position": service.queue.qsize()},
                status=202,
            )
        except Exception as exc:
            return _error(exc)

    async def get_job(request):
        try:
            return _json(asdict(service.get_job(request.match_info["job_id"])))
        except Exception as exc:
            return _error(exc)

    async def queue_status(request):
        return _json(service.status())

    async def client_stream(request):
        client_id = request.match_info["client_id"]
        subscriber = None
        broadcast = None
        try:
            service.get_profile(client_id)
            session_id = service.session_id(client_id)
            broadcast = broadcast_registry.get(session_id)
            subscriber = broadcast.subscribe()
        except Exception as exc:
            if broadcast is not None and subscriber is not None:
                broadcast.unsubscribe(subscriber)
            return _error(exc)

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "video/mp2t",
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)
        try:
            # Headers are sent before loading GPU models so a first-time client
            # does not hit its HTTP connect timeout. It is already subscribed
            # when rendering begins, so it receives the initial PAT/PMT/SPS/PPS.
            await service.ensure_session(client_id)
            while True:
                try:
                    chunk = subscriber.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.005)
                    continue
                await response.write(chunk)
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            broadcast.unsubscribe(subscriber)
        return response

    app.router.add_get("/api/v1/assets", list_assets)
    app.router.add_get("/api/v1/clients", list_clients)
    app.router.add_get("/api/v1/clients/{client_id}", get_client)
    app.router.add_put("/api/v1/clients/{client_id}", put_client)
    app.router.add_delete("/api/v1/clients/{client_id}", delete_client)
    app.router.add_get("/api/v1/clients/{client_id}/stream.ts", client_stream)
    app.router.add_post("/api/v1/voices/{voice_id}", upload_voice)
    app.router.add_post("/api/v1/jobs", submit_job)
    app.router.add_get("/api/v1/jobs/{job_id}", get_job)
    app.router.add_get("/api/v1/queue", queue_status)
