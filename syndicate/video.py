"""Low-level MP4 encoding independent from the application UI."""
from __future__ import annotations

import math
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def encode_mp4_frames(
    frames: Iterable[Image.Image],
    frame_size: tuple[int, int],
    fps: float,
) -> bytes:
    """Encode RGB Pillow frames to a self-contained MP4 byte stream."""

    width, height = frame_size
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError("MP4 frame dimensions must be positive and even")
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("MP4 frame rate must be positive")

    handle, temporary_name = tempfile.mkstemp(
        prefix="syndicate-roll-",
        suffix=".mp4",
    )
    os.close(handle)
    temporary_path = Path(temporary_name)
    writer: cv2.VideoWriter | None = None
    try:
        temporary_path.unlink(missing_ok=True)
        candidates: list[tuple[int, str]] = []
        if os.name == "nt":
            candidates.extend(
                (
                    (cv2.CAP_MSMF, "avc1"),
                    (cv2.CAP_MSMF, "H264"),
                )
            )
        candidates.append((cv2.CAP_FFMPEG, "mp4v"))

        for backend, codec in candidates:
            candidate = cv2.VideoWriter(
                str(temporary_path),
                backend,
                cv2.VideoWriter_fourcc(*codec),
                fps,
                (width, height),
            )
            if candidate.isOpened():
                writer = candidate
                break
            candidate.release()
            temporary_path.unlink(missing_ok=True)
        if writer is None:
            raise RuntimeError("На этом устройстве не найден кодек для MP4")

        frame_count = 0
        for frame in frames:
            if not isinstance(frame, Image.Image):
                raise TypeError("MP4 frames must be Pillow images")
            rgb_frame = frame.convert("RGB")
            if rgb_frame.size != (width, height):
                raise ValueError("Every MP4 frame must have the same size")
            bgr_frame = cv2.cvtColor(np.asarray(rgb_frame), cv2.COLOR_RGB2BGR)
            writer.write(bgr_frame)
            frame_count += 1
        writer.release()
        writer = None
        if frame_count == 0:
            raise ValueError("At least one MP4 frame is required")
        payload = temporary_path.read_bytes()
        if len(payload) < 256 or b"ftyp" not in payload[:64]:
            raise RuntimeError("Видеокодек создал повреждённый MP4")
        return payload
    finally:
        if writer is not None:
            writer.release()
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
