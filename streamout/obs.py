"""OBS-ready MPEG-TS output with interleaved H.264 video and AAC audio."""

from __future__ import annotations

from collections import deque
from fractions import Fraction
import shutil
import subprocess
import time
from typing import TYPE_CHECKING, Optional

import av
import numpy as np

from registry import register
from streamout.base_output import BaseOutput
from utils.logger import logger

if TYPE_CHECKING:
    from avatars.base_avatar import BaseAvatar


@register("streamout", "obs")
class OBSOutput(BaseOutput):
    """Send one muxed low-latency stream that OBS can open as a Media Source.

    The default destination is a local UDP port.  Unlike the virtual-camera
    transport this keeps audio and video in the same stream, so OBS needs no
    virtual audio cable and cannot accidentally capture its own virtual camera.
    """

    def __init__(self, opt=None, parent: Optional["BaseAvatar"] = None, **kwargs):
        super().__init__(opt, parent)
        configured_url = str(
            getattr(opt, "obs_url", "")
            or getattr(opt, "push_url", "")
            or ""
        ).strip()
        self.push_url = configured_url or "udp://127.0.0.1:23000?pkt_size=1316"
        self._mux_url = self.push_url
        self.fps = max(1, int(getattr(opt, "fps", 25)))
        self.sample_rate = int(getattr(parent, "sample_rate", 16000))
        self.output_sample_rate = 48000
        self.video_encoder = str(
            getattr(opt, "obs_video_encoder", "libx264") or "libx264"
        )
        self.video_bitrate = max(
            250_000, int(getattr(opt, "obs_video_bitrate", 4_000_000))
        )

        self._container = None
        self._video_stream = None
        self._audio_stream = None
        self._audio_resampler = None
        self._video_index = 0
        self._audio_input_samples = 0
        self._started_at = 0.0
        # Keep at most roughly five seconds of 20 ms audio chunks while the
        # destination is connecting. This prevents an offline remote OBS from
        # growing memory forever.
        self._pending_audio = deque(maxlen=250)
        self._retry_at = 0.0
        self._srt_relay_port = int(getattr(opt, "obs_srt_relay_port", 23001))
        self._srt_relay_process = None
        self._uses_srt_relay = False

    def start(self) -> None:
        self._video_index = 0
        self._audio_input_samples = 0
        self._started_at = time.perf_counter()
        self._pending_audio.clear()
        self._retry_at = 0.0
        logger.info("[OBS] Waiting for first video frame; destination=%s", self.push_url)

    def _open_output(self, height: int, width: int) -> None:
        output_format = "flv" if self.push_url.lower().startswith("rtmp") else "mpegts"
        try:
            av.Codec(self.video_encoder, "w")
        except Exception:
            if self.video_encoder == "libx264":
                raise RuntimeError(
                    "PyAV does not expose the libx264 encoder required by the "
                    "OBS transport. Reinstall the PyAV wheel in .venv."
                )
            logger.warning(
                "[OBS] Encoder %s is unavailable in PyAV; falling back to libx264",
                self.video_encoder,
            )
            self.video_encoder = "libx264"
            av.Codec(self.video_encoder, "w")

        if self._uses_srt_relay:
            self._ensure_srt_relay()
        try:
            self._container = av.open(
                self._mux_url,
                mode="w",
                format=output_format,
                options={"flush_packets": "1"},
            )
        except Exception as exc:
            # Windows PyAV wheels commonly omit libSRT even when the standalone
            # ffmpeg.exe includes it.  Keep encoding in PyAV, send MPEG-TS to a
            # loopback UDP socket, and let FFmpeg copy packets to SRT.
            if (
                self.push_url.lower().startswith("srt://")
                and "protocol not found" in str(exc).lower()
            ):
                logger.warning(
                    "[OBS] PyAV has no SRT protocol; using ffmpeg SRT relay"
                )
                self._enable_srt_relay()
                self._container = av.open(
                    self._mux_url,
                    mode="w",
                    format="mpegts",
                    options={"flush_packets": "1"},
                )
            else:
                raise

        self._video_stream = self._container.add_stream(
            self.video_encoder, rate=self.fps
        )
        self._video_stream.width = width
        self._video_stream.height = height
        self._video_stream.pix_fmt = "yuv420p"
        self._video_stream.bit_rate = self.video_bitrate
        self._video_stream.gop_size = self.fps * 2
        self._video_stream.codec_context.max_b_frames = 0
        if self.video_encoder == "libx264":
            self._video_stream.options = {
                "preset": "veryfast",
                "tune": "zerolatency",
                "profile": "main",
            }
        elif self.video_encoder == "h264_nvenc":
            self._video_stream.options = {
                "preset": "p4",
                "tune": "ll",
                "rc": "cbr",
            }

        self._audio_stream = self._container.add_stream(
            "aac", rate=self.output_sample_rate
        )
        self._audio_stream.layout = "mono"
        self._audio_stream.bit_rate = 128_000
        self._audio_resampler = av.AudioResampler(
            format="fltp", layout="mono", rate=self.output_sample_rate
        )
        self._video_index = 0
        self._audio_input_samples = 0
        self._started_at = time.perf_counter()
        self._retry_at = 0.0

        logger.info(
            "[OBS] Output started: %sx%s@%s, %s, %s bps, audio AAC mono -> %s",
            width,
            height,
            self.fps,
            self.video_encoder,
            self.video_bitrate,
            self.push_url,
        )

        pending = list(self._pending_audio)
        self._pending_audio.clear()
        for audio, eventpoint in pending:
            self._encode_audio(audio, eventpoint)

    def _enable_srt_relay(self) -> None:
        self._uses_srt_relay = True
        self._mux_url = (
            f"udp://127.0.0.1:{self._srt_relay_port}?pkt_size=1316"
        )
        self._ensure_srt_relay()

    def _ensure_srt_relay(self) -> None:
        process = self._srt_relay_process
        if process is not None and process.poll() is None:
            return

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError(
                "PyAV has no SRT support and ffmpeg was not found in PATH"
            )

        input_url = (
            f"udp://127.0.0.1:{self._srt_relay_port}"
            "?fifo_size=1000000&overrun_nonfatal=1"
        )
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-i",
            input_url,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c",
            "copy",
            "-mpegts_flags",
            "+resend_headers",
            "-f",
            "mpegts",
            self.push_url,
        ]
        self._srt_relay_process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
        logger.info(
            "[OBS] FFmpeg SRT relay started on local UDP port %d",
            self._srt_relay_port,
        )

    def _stop_srt_relay(self) -> None:
        process = self._srt_relay_process
        self._srt_relay_process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def _reset_output(self, reason: Exception | str | None = None) -> None:
        if reason is not None:
            logger.warning("[OBS] Output disconnected; retrying in 2 seconds: %s", reason)

        container = self._container
        self._container = None
        self._video_stream = None
        self._audio_stream = None
        self._audio_resampler = None
        self._video_index = 0
        self._audio_input_samples = 0
        self._retry_at = time.perf_counter() + 2.0
        if container is not None:
            try:
                container.close()
            except Exception:
                pass

    def _handle_output_error(self, exc: Exception) -> None:
        should_enable_relay = (
            self.push_url.lower().startswith("srt://")
            and not self._uses_srt_relay
            and "protocol not found" in str(exc).lower()
        )
        self._reset_output(exc)
        if should_enable_relay:
            logger.warning(
                "[OBS] PyAV has no SRT protocol; using ffmpeg SRT relay"
            )
            self._enable_srt_relay()
            # Reopen immediately on the next frame instead of waiting for the
            # normal disconnect backoff.
            self._retry_at = 0.0

    def _mux_packets(self, packets) -> None:
        for packet in packets:
            self._container.mux(packet)

    def push_video_frame(self, frame) -> None:
        if not isinstance(frame, np.ndarray):
            return
        if self._uses_srt_relay:
            try:
                self._ensure_srt_relay()
            except Exception as exc:
                self._reset_output(exc)
                return
        if self._container is None and time.perf_counter() < self._retry_at:
            time.sleep(1 / self.fps)
            return
        if self._container is None:
            height, width = frame.shape[:2]
            try:
                self._open_output(height, width)
            except Exception as exc:
                self._reset_output(exc)
                return

        try:
            video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
            video_frame.pts = self._video_index
            video_frame.time_base = Fraction(1, self.fps)
            self._mux_packets(self._video_stream.encode(video_frame))
        except Exception as exc:
            self._handle_output_error(exc)
            return

        target = self._started_at + self._video_index / self.fps
        delay = target - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        self._video_index += 1

    def _encode_audio(self, frame, eventpoint=None) -> None:
        samples = np.asarray(frame, dtype=np.int16).reshape(1, -1)
        audio_frame = av.AudioFrame.from_ndarray(
            samples, format="s16", layout="mono"
        )
        audio_frame.sample_rate = self.sample_rate
        audio_frame.pts = self._audio_input_samples
        audio_frame.time_base = Fraction(1, self.sample_rate)
        self._audio_input_samples += samples.shape[1]

        resampled_frames = self._audio_resampler.resample(audio_frame)
        if not isinstance(resampled_frames, list):
            resampled_frames = [resampled_frames]
        for resampled in resampled_frames:
            if resampled is not None:
                # PyAV's audio encoder buffers partial AAC frames internally.
                self._mux_packets(self._audio_stream.encode(resampled))

        if self.parent:
            self.parent.notify(eventpoint)

    def push_audio_frame(self, frame, eventpoint=None) -> None:
        if not isinstance(frame, np.ndarray):
            return
        if self._container is None:
            self._pending_audio.append((frame.copy(), eventpoint))
            return
        try:
            self._encode_audio(frame, eventpoint)
        except Exception as exc:
            self._handle_output_error(exc)

    def stop(self) -> None:
        if self._container is None:
            self._stop_srt_relay()
            return
        try:
            for resampled in self._audio_resampler.resample(None):
                self._mux_packets(self._audio_stream.encode(resampled))
            self._mux_packets(self._video_stream.encode(None))
            self._mux_packets(self._audio_stream.encode(None))
        except Exception as exc:
            logger.warning("[OBS] Error while flushing output: %s", exc)
        finally:
            self._reset_output()
            self._stop_srt_relay()
            logger.info("[OBS] Output stopped")
