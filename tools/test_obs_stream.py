"""Generate a short test card + tone through the OBS MPEG-TS transport."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamout.obs import OBSOutput


class TestParent:
    sample_rate = 16000

    @staticmethod
    def notify(_eventpoint):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Test the complete OBS A/V stream")
    parser.add_argument("--url", default="udp://127.0.0.1:23000?pkt_size=1316")
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=25)
    args = parser.parse_args()

    opt = SimpleNamespace(
        fps=args.fps,
        obs_url=args.url,
        push_url="",
        obs_video_encoder="libx264",
        obs_video_bitrate=4_000_000,
    )
    output = OBSOutput(opt=opt, parent=TestParent())
    output.start()

    sample_rate = TestParent.sample_rate
    samples_per_video_frame = sample_rate // args.fps
    audio_chunk = samples_per_video_frame // 2
    phase = 0
    try:
        for index in range(args.seconds * args.fps):
            frame = np.zeros((args.height, args.width, 3), dtype=np.uint8)
            frame[:, :, 1] = np.linspace(32, 180, args.width, dtype=np.uint8)
            cv2.putText(
                frame,
                "AI LIVESTREAM - OBS TEST",
                (50, 100),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.4,
                (255, 255, 255),
                3,
                cv2.LINE_AA,
            )
            cv2.putText(
                frame,
                f"Frame {index + 1} / {args.seconds * args.fps}",
                (50, 165),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            output.push_video_frame(frame)

            for _ in range(2):
                positions = np.arange(audio_chunk, dtype=np.float32) + phase
                tone = 0.15 * np.sin(2 * math.pi * 440.0 * positions / sample_rate)
                pcm = (tone * 32767).astype(np.int16)
                output.push_audio_frame(pcm)
                phase += audio_chunk
    finally:
        output.stop()

    print("OBS test stream completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
