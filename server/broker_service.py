"""FIFO multi-client speech broker for GPU-backed avatar sessions."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
from threading import Event, Lock, Thread
import time
import uuid

import soundfile as sf

from server.session_manager import session_manager
from streamout.broker import broadcast_registry
from utils.logger import logger


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_id(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not SAFE_ID.fullmatch(value):
        raise ValueError(
            f"{label} must contain 1-64 letters, numbers, '-' or '_', "
            "and must start with a letter or number"
        )
    return value


@dataclass
class ClientProfile:
    client_id: str
    avatar_id: str
    voice_id: str = ""
    stream_token_hash: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class SpeechJob:
    job_id: str
    client_id: str
    text: str
    status: str = "queued"
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None


@dataclass
class AssetJob:
    job_id: str
    client_id: str
    kind: str
    asset_id: str
    source_path: str
    ref_text: str = ""
    status: str = "queued"
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None


class BrokerService:
    """Own profiles, one global FIFO queue and per-client render sessions."""

    def __init__(
        self,
        root: Path | str = ".",
        avatar_model: str = "wav2lip",
        default_avatar_id: str = "",
        registration_key: str = "",
    ):
        self.root = Path(root).resolve()
        self.state_dir = self.root / "data" / "broker"
        self.upload_dir = self.state_dir / "uploads"
        self.voice_dir = self.root / "data" / "voices" / "broker"
        self.profile_file = self.state_dir / "clients.json"
        self.avatar_model = "wav2lip" if avatar_model in {
            "wav2lip", "way2lip", "lip2way"
        } else avatar_model
        self.default_avatar_id = str(default_avatar_id or "").strip()
        self.registration_key = str(registration_key or "").strip()
        self.profiles: dict[str, ClientProfile] = {}
        self.jobs: dict[str, SpeechJob] = {}
        self.asset_jobs: dict[str, AssetJob] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.asset_queue: asyncio.Queue[str] = asyncio.Queue()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._gpu_work_lock = asyncio.Lock()
        self._asset_submit_guard = Lock()
        self._managed_sessions: set[str] = set()
        self._worker_task: asyncio.Task | None = None
        self._asset_worker_task: asyncio.Task | None = None
        self._load_profiles()

    @staticmethod
    def session_id(client_id: str) -> str:
        return f"broker-{client_id}"

    def _load_profiles(self) -> None:
        if not self.profile_file.is_file():
            return
        try:
            payload = json.loads(self.profile_file.read_text(encoding="utf-8"))
            for item in payload.get("clients", []):
                profile = ClientProfile(**item)
                self.profiles[profile.client_id] = profile
        except Exception:
            logger.exception("Could not load broker client profiles")

    def _save_profiles(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.profile_file.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {"clients": [asdict(item) for item in self.profiles.values()]},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.profile_file)

    def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(
                self._worker(), name="broker-fifo-worker"
            )
            self._asset_worker_task = asyncio.create_task(
                self._asset_worker(), name="broker-asset-fifo-worker"
            )
            logger.info("Multi-client FIFO broker started")

    async def stop(self) -> None:
        task = self._worker_task
        self._worker_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        asset_task = self._asset_worker_task
        self._asset_worker_task = None
        if asset_task is not None:
            asset_task.cancel()
            try:
                await asset_task
            except asyncio.CancelledError:
                pass
        for session_id in tuple(self._managed_sessions):
            session_manager.remove_session(session_id)
            broadcast_registry.remove(session_id)
        self._managed_sessions.clear()

    def list_profiles(self) -> list[dict]:
        return [self.profile_view(item) for item in self.profiles.values()]

    @staticmethod
    def profile_view(profile: ClientProfile) -> dict:
        """Return client metadata without exposing the persisted token hash."""
        return {
            "client_id": profile.client_id,
            "avatar_id": profile.avatar_id,
            "voice_id": profile.voice_id,
            "has_stream_token": bool(profile.stream_token_hash),
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }

    def get_profile(self, client_id: str) -> ClientProfile:
        client_id = validate_id(client_id, "client_id")
        profile = self.profiles.get(client_id)
        if profile is None:
            raise KeyError(f"Client profile not found: {client_id}")
        return profile

    def upsert_profile(
        self,
        client_id: str,
        avatar_id: str,
        voice_id: str = "",
        rotate_stream_token: bool = False,
        _asset_job_id: str = "",
    ) -> tuple[ClientProfile, str]:
        client_id = validate_id(client_id, "client_id")
        avatar_id = validate_id(avatar_id, "avatar_id")
        voice_id = validate_id(voice_id, "voice_id") if voice_id else ""
        avatar_dir = self.root / "data" / "avatars" / avatar_id
        if not avatar_dir.is_dir():
            raise ValueError(f"Avatar does not exist on server: {avatar_id}")
        if voice_id and not self.voice_metadata_path(voice_id).is_file():
            raise ValueError(f"Voice does not exist on server: {voice_id}")
        self._assert_client_idle(client_id, ignore_asset_job_id=_asset_job_id)

        previous = self.profiles.get(client_id)
        now = time.time()
        stream_token = ""
        stream_token_hash = previous.stream_token_hash if previous else ""
        if rotate_stream_token or not stream_token_hash:
            stream_token = secrets.token_urlsafe(32)
            stream_token_hash = hashlib.sha256(stream_token.encode("utf-8")).hexdigest()
        profile = ClientProfile(
            client_id=client_id,
            avatar_id=avatar_id,
            voice_id=voice_id,
            stream_token_hash=stream_token_hash,
            created_at=previous.created_at if previous else now,
            updated_at=now,
        )
        self.profiles[client_id] = profile
        self._save_profiles()
        if previous and (
            previous.avatar_id != avatar_id or previous.voice_id != voice_id
        ):
            self.remove_session(client_id)
        return profile, stream_token

    def authorize_stream(self, client_id: str, token: str) -> ClientProfile:
        return self.authorize_client(client_id, token)

    def authorize_client(self, client_id: str, token: str) -> ClientProfile:
        profile = self.get_profile(client_id)
        supplied_hash = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()
        if not profile.stream_token_hash or not secrets.compare_digest(
            supplied_hash, profile.stream_token_hash
        ):
            raise PermissionError("Invalid stream token for this client")
        return profile

    def register_client(
        self, client_id: str, registration_key: str
    ) -> tuple[ClientProfile, str]:
        """Let a new client choose its own ID and receive a private token once."""
        client_id = validate_id(client_id, "client_id")
        supplied = str(registration_key or "").strip()
        if not self.registration_key or not secrets.compare_digest(
            supplied, self.registration_key
        ):
            raise PermissionError("Invalid client registration key")
        if client_id in self.profiles:
            raise FileExistsError(
                f"Client ID already exists: {client_id}. Choose another client_id."
            )
        if not self.default_avatar_id:
            raise RuntimeError("Server default avatar is not configured")
        return self.upsert_profile(
            client_id=client_id,
            avatar_id=self.default_avatar_id,
            voice_id="",
            rotate_stream_token=True,
        )

    @staticmethod
    def asset_job_view(job: AssetJob) -> dict:
        return {
            "job_id": job.job_id,
            "client_id": job.client_id,
            "kind": job.kind,
            "asset_id": job.asset_id,
            "status": job.status,
            "error": job.error,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
        }

    def submit_asset_upload(
        self,
        client_id: str,
        kind: str,
        filename: str,
        source_file,
        ref_text: str = "",
    ) -> AssetJob:
        with self._asset_submit_guard:
            profile = self.get_profile(client_id)
            self._assert_client_idle(profile.client_id)
            kind = str(kind or "").strip().lower()
            if kind not in {"avatar", "voice"}:
                raise ValueError("Asset kind must be avatar or voice")

            suffix = Path(str(filename or "")).suffix.lower()
            allowed = {".wav"} if kind == "voice" else {
                ".mp4", ".mov", ".mkv", ".webm"
            }
            if suffix not in allowed:
                expected = ", ".join(sorted(allowed))
                raise ValueError(f"Invalid {kind} file; expected: {expected}")
            reference_text = str(ref_text or "").strip()
            if len(reference_text) > 4000:
                raise ValueError("Voice reference transcript exceeds 4000 characters")

            job_id = str(uuid.uuid4())
            digest = hashlib.sha256(
                profile.client_id.encode("utf-8")
            ).hexdigest()[:10]
            readable = re.sub(r"[^A-Za-z0-9_-]", "_", profile.client_id)[:28]
            asset_id = f"client_{readable}_{digest}_{kind}_{job_id[:8]}"
            validate_id(asset_id, "asset_id")

            max_bytes = (
                25 * 1024 * 1024 if kind == "voice" else 500 * 1024 * 1024
            )
            self.upload_dir.mkdir(parents=True, exist_ok=True)
            destination = self.upload_dir / f"{job_id}{suffix}"
            job = AssetJob(
                job_id=job_id,
                client_id=profile.client_id,
                kind=kind,
                asset_id=asset_id,
                source_path=str(destination),
                ref_text=reference_text,
                status="uploading",
            )
            self.asset_jobs[job.job_id] = job
            total = 0
            try:
                with destination.open("wb") as output:
                    while True:
                        chunk = source_file.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError(
                                f"{kind} upload exceeds "
                                f"{max_bytes // (1024 * 1024)} MB"
                            )
                        output.write(chunk)
                if total == 0:
                    raise ValueError(f"{kind} upload is empty")
            except Exception:
                destination.unlink(missing_ok=True)
                self.asset_jobs.pop(job.job_id, None)
                raise
            job.status = "queued"
            self.asset_queue.put_nowait(job.job_id)
            return job

    def get_asset_job(self, client_id: str, job_id: str) -> AssetJob:
        client_id = validate_id(client_id, "client_id")
        job = self.asset_jobs.get(str(job_id))
        if job is None or job.client_id != client_id:
            raise KeyError(f"Asset job not found: {job_id}")
        return job

    def delete_profile(self, client_id: str) -> None:
        profile = self.get_profile(client_id)
        self._assert_client_idle(profile.client_id)
        self.remove_session(profile.client_id)
        self.profiles.pop(profile.client_id, None)
        self._save_profiles()

    def voice_audio_path(self, voice_id: str) -> Path:
        return self.voice_dir / f"{voice_id}.wav"

    def voice_metadata_path(self, voice_id: str) -> Path:
        return self.voice_dir / f"{voice_id}.json"

    def save_voice(self, voice_id: str, payload: bytes, ref_text: str) -> dict:
        voice_id = validate_id(voice_id, "voice_id")
        for profile in self.profiles.values():
            if profile.voice_id == voice_id:
                self._assert_client_idle(profile.client_id)
        transcript = str(ref_text or "").strip()
        if not payload:
            raise ValueError("Voice reference is empty")
        self.voice_dir.mkdir(parents=True, exist_ok=True)
        audio_path = self.voice_audio_path(voice_id)

        if not transcript:
            source = self.voice_dir / f".{voice_id}-{uuid.uuid4().hex}.wav"
            text_path = self.voice_dir / f"{voice_id}.txt"
            prepare_meta = self.voice_dir / f"{voice_id}.prepare.json"
            source.write_bytes(payload)
            try:
                subprocess.run(
                    [
                        sys.executable,
                        str(self.root / "tools" / "prepare_voice_clone.py"),
                        str(source),
                        "--audio-output", str(audio_path),
                        "--text-output", str(text_path),
                        "--metadata-output", str(prepare_meta),
                        "--asr-model", "vinai/PhoWhisper-medium",
                        "--force",
                    ],
                    cwd=self.root,
                    check=True,
                )
                payload = audio_path.read_bytes()
                transcript = text_path.read_text(encoding="utf-8").strip()
            finally:
                source.unlink(missing_ok=True)

        try:
            audio_info = sf.info(BytesIO(payload))
        except Exception as exc:
            raise ValueError(f"Invalid WAV reference: {exc}") from exc
        duration = audio_info.frames / audio_info.samplerate
        if duration < 3.0 or duration > 30.0:
            raise ValueError("Voice reference duration must be between 3 and 30 seconds")
        audio_tmp = audio_path.with_suffix(".wav.tmp")
        metadata_path = self.voice_metadata_path(voice_id)
        metadata_tmp = metadata_path.with_suffix(".json.tmp")
        write_audio = (
            not audio_path.is_file() or audio_path.read_bytes() != payload
        )
        if write_audio:
            audio_tmp.write_bytes(payload)
        metadata = {
            "voice_id": voice_id,
            "audio": str(audio_path),
            "ref_text": transcript,
            "duration_seconds": round(duration, 3),
            "sample_rate": audio_info.samplerate,
            "channels": audio_info.channels,
            "updated_at": time.time(),
        }
        metadata_tmp.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if audio_tmp.exists():
            audio_tmp.replace(audio_path)
        metadata_tmp.replace(metadata_path)
        for profile in tuple(self.profiles.values()):
            if profile.voice_id == voice_id:
                self.remove_session(profile.client_id)
        return metadata

    def get_voice(self, voice_id: str) -> dict:
        voice_id = validate_id(voice_id, "voice_id")
        path = self.voice_metadata_path(voice_id)
        if not path.is_file():
            raise KeyError(f"Voice not found: {voice_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_voices(self) -> list[dict]:
        if not self.voice_dir.is_dir():
            return []
        voices = []
        for path in sorted(self.voice_dir.glob("*.json")):
            if path.name.endswith(".prepare.json"):
                continue
            try:
                voices.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                logger.warning("Ignoring invalid voice metadata: %s", path)
        return voices

    def list_avatars(self) -> list[str]:
        directory = self.root / "data" / "avatars"
        if not directory.is_dir():
            return []
        return sorted(item.name for item in directory.iterdir() if item.is_dir())

    def submit(self, client_id: str, text: str) -> SpeechJob:
        profile = self.get_profile(client_id)
        if any(
            item.client_id == profile.client_id
            and item.status in {"uploading", "queued", "waiting_gpu", "running"}
            for item in self.asset_jobs.values()
        ):
            raise ValueError(
                f"Client {profile.client_id} is preparing an avatar/voice; "
                "wait for the asset job to finish"
            )
        speech = str(text or "").strip()
        if not speech:
            raise ValueError("text is required")
        if len(speech) > 4000:
            raise ValueError("text exceeds the 4000 character limit")
        job = SpeechJob(
            job_id=str(uuid.uuid4()), client_id=profile.client_id, text=speech
        )
        self.jobs[job.job_id] = job
        if len(self.jobs) > 5000:
            completed = sorted(
                (
                    item
                    for item in self.jobs.values()
                    if item.status in {"completed", "failed"}
                ),
                key=lambda item: item.completed_at or item.created_at,
            )
            for stale in completed[:1000]:
                self.jobs.pop(stale.job_id, None)
        self.queue.put_nowait(job.job_id)
        return job

    def _assert_client_idle(
        self, client_id: str, ignore_asset_job_id: str = ""
    ) -> None:
        session_id = self.session_id(client_id)
        if broadcast_registry.get(session_id).subscriber_count > 0:
            raise ValueError(
                f"Client {client_id} is connected; stop its OBS relay before "
                "changing the avatar or voice"
            )
        busy = any(
            job.client_id == client_id
            and job.status in {"queued", "waiting_client", "running"}
            for job in self.jobs.values()
        )
        if busy:
            raise ValueError(
                f"Client {client_id} has queued/running jobs; wait before "
                "changing its avatar or voice"
            )
        asset_busy = any(
            item.job_id != ignore_asset_job_id
            and item.client_id == client_id
            and item.status in {"uploading", "queued", "waiting_gpu", "running"}
            for item in self.asset_jobs.values()
        )
        if asset_busy:
            raise ValueError(
                f"Client {client_id} already has an avatar/voice job; "
                "wait for it to finish"
            )

    def get_job(self, job_id: str) -> SpeechJob:
        job = self.jobs.get(str(job_id))
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        return job

    def status(self) -> dict:
        queued = sum(
            job.status in {"queued", "waiting_client"}
            for job in self.jobs.values()
        )
        running = [asdict(job) for job in self.jobs.values() if job.status == "running"]
        return {
            "queued": queued,
            "running": running,
            "asset_queued": sum(
                item.status in {"uploading", "queued", "waiting_gpu"}
                for item in self.asset_jobs.values()
            ),
            "asset_running": [
                self.asset_job_view(item)
                for item in self.asset_jobs.values()
                if item.status == "running"
            ],
            "clients": len(self.profiles),
            "active_sessions": len(self._managed_sessions),
        }

    def _session_params(self, profile: ClientProfile) -> dict:
        params = {"avatar": profile.avatar_id}
        if profile.voice_id:
            voice = self.get_voice(profile.voice_id)
            params.update(
                {
                    "refaudio": str(self.voice_audio_path(profile.voice_id).resolve()),
                    "reftext": voice["ref_text"],
                }
            )
        return params

    async def ensure_session(self, client_id: str):
        profile = self.get_profile(client_id)
        session_id = self.session_id(profile.client_id)
        current = session_manager.get_session(session_id)
        if current is not None:
            return current
        lock = self._session_locks.setdefault(profile.client_id, asyncio.Lock())
        async with lock:
            current = session_manager.get_session(session_id)
            if current is not None:
                return current
            await session_manager.create_session(
                self._session_params(profile), sessionid=session_id
            )
            avatar = session_manager.get_session(session_id)
            quit_event = Event()
            thread = Thread(
                target=avatar.render,
                args=(quit_event,),
                daemon=True,
                name=f"broker-render-{profile.client_id}",
            )
            avatar.quit_event = quit_event
            avatar._broker_render_thread = thread
            thread.start()
            self._managed_sessions.add(session_id)
            logger.info(
                "Broker session ready: client=%s avatar=%s voice=%s",
                profile.client_id,
                profile.avatar_id,
                profile.voice_id or "default",
            )
            return avatar

    def remove_session(self, client_id: str) -> None:
        session_id = self.session_id(client_id)
        session_manager.remove_session(session_id)
        broadcast_registry.remove(session_id)
        self._managed_sessions.discard(session_id)

    async def _asset_worker(self) -> None:
        while True:
            job_id = await self.asset_queue.get()
            job = self.asset_jobs.get(job_id)
            if job is None:
                self.asset_queue.task_done()
                continue
            remove_source = True
            try:
                job.status = "waiting_gpu"
                async with self._gpu_work_lock:
                    job.status = "running"
                    job.started_at = time.time()
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self._prepare_asset, job)
                job.status = "completed"
                job.completed_at = time.time()
            except asyncio.CancelledError:
                # run_in_executor cannot stop an already-running subprocess.
                # Keep its input file only when work already entered the
                # executor; otherwise it is safe to clean up immediately.
                remove_source = job.status != "running"
                raise
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = time.time()
                logger.exception(
                    "Broker asset job failed: client=%s kind=%s job=%s",
                    job.client_id,
                    job.kind,
                    job.job_id,
                )
            finally:
                if remove_source:
                    Path(job.source_path).unlink(missing_ok=True)
                self.asset_queue.task_done()

    def _prepare_asset(self, job: AssetJob) -> None:
        self._assert_client_idle(
            job.client_id, ignore_asset_job_id=job.job_id
        )
        profile = self.get_profile(job.client_id)
        source = Path(job.source_path)
        if job.kind == "voice":
            self.save_voice(job.asset_id, source.read_bytes(), job.ref_text)
            self.upsert_profile(
                profile.client_id,
                profile.avatar_id,
                job.asset_id,
                _asset_job_id=job.job_id,
            )
            return

        command = [
            sys.executable,
            str(self.root / "tools" / "prepare_avatar.py"),
            str(source),
            "--avatar-id",
            job.asset_id,
            "--model",
            self.avatar_model,
        ]
        if self.avatar_model == "musetalk":
            command.extend(
                [
                    "--landmark-backend",
                    "fan",
                    "--bbox-shift",
                    "0",
                    "--musetalk-version",
                    "v15",
                ]
            )
        subprocess.run(command, cwd=self.root, check=True)
        avatar_dir = self.root / "data" / "avatars" / job.asset_id
        if not avatar_dir.is_dir():
            raise RuntimeError("Avatar preparation did not create its output")
        self.upsert_profile(
            profile.client_id,
            job.asset_id,
            profile.voice_id,
            _asset_job_id=job.job_id,
        )

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            job = self.jobs.get(job_id)
            if job is None:
                self.queue.task_done()
                continue
            try:
                job.status = "waiting_client"
                await self._wait_for_client(job.client_id)
                async with self._gpu_work_lock:
                    job.status = "running"
                    job.started_at = time.time()
                    avatar = await self.ensure_session(job.client_id)
                    avatar.put_msg_txt(
                        job.text,
                        {"source": "broker", "job_id": job.job_id},
                    )
                    await self._wait_for_speech(avatar, job)
                job.status = "completed"
                job.completed_at = time.time()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = time.time()
                logger.exception("Broker speech job failed: %s", job.job_id)
            finally:
                self.queue.task_done()

    async def _wait_for_client(self, client_id: str) -> None:
        session_id = self.session_id(client_id)
        broadcast = broadcast_registry.get(session_id)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if broadcast.subscriber_count > 0:
                return
            await asyncio.sleep(0.1)
        raise TimeoutError(
            f"OBS client {client_id} is not connected to its stream"
        )

    async def _wait_for_speech(self, avatar, job: SpeechJob) -> None:
        deadline = time.monotonic() + max(180.0, len(job.text) * 1.5)
        started = False
        quiet_since = None
        while time.monotonic() < deadline:
            speaking = bool(avatar.is_speaking())
            if speaking:
                started = True
                quiet_since = None
            elif started:
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since >= 0.6:
                    return
            await asyncio.sleep(0.05)
        if not started:
            raise TimeoutError("TTS/lip-sync did not start before timeout")
        raise TimeoutError("TTS/lip-sync did not finish before timeout")
