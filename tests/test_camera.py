"""Unit tests for the live camera entity's framing and lifecycle helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.allo_wt7.camera import AlloWT7LiveCamera, _mjpeg_part


def _camera(fingerprint_configured: bool = True) -> AlloWT7LiveCamera:
    coordinator = SimpleNamespace(
        video_tls_fingerprint_configured=fingerprint_configured,
        device_info=None,
    )
    entry = SimpleNamespace(unique_id="umid1", entry_id="e1")
    return AlloWT7LiveCamera(coordinator, entry, "/usr/bin/ffmpeg")


class _FakeReader:
    """Minimal asyncio.StreamReader stand-in yielding fixed chunks then EOF."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, _n: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


def test_mjpeg_part_frames_the_jpeg() -> None:
    part = _mjpeg_part(b"\xff\xd8body\xff\xd9")
    assert part.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n")
    assert b"Content-Length: 8\r\n\r\n" in part
    assert part.endswith(b"\xff\xd9\r\n")


def test_available_follows_fingerprint_configuration() -> None:
    assert _camera(True).available is True
    assert _camera(False).available is False


async def test_subscribe_without_fingerprint_raises() -> None:
    cam = _camera(fingerprint_configured=False)
    with pytest.raises(HomeAssistantError):
        await cam._subscribe()


async def test_read_jpegs_splits_concatenated_frames() -> None:
    cam = _camera()
    queue: asyncio.Queue = asyncio.Queue()
    cam._subscribers.add(queue)

    jpeg_a = b"\xff\xd8" + b"AAAA" + b"\xff\xd9"
    jpeg_b = b"\xff\xd8" + b"BBBBBB" + b"\xff\xd9"
    # Split across chunk boundaries to exercise the buffering.
    reader = _FakeReader([jpeg_a + jpeg_b[:3], jpeg_b[3:]])

    await cam._read_jpegs(reader)

    assert cam._last_frame == jpeg_b
    assert queue.get_nowait() == jpeg_a
    assert queue.get_nowait() == jpeg_b


def test_publish_drops_oldest_when_queue_is_full() -> None:
    cam = _camera()
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    cam._subscribers.add(queue)
    cam._publish(b"first")
    cam._publish(b"second")  # must evict "first", not block
    assert queue.get_nowait() == b"second"
    assert queue.empty()
