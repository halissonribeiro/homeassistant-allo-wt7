"""Unit tests for the QUII framing/parsing helpers (no network, no live key)."""

from __future__ import annotations

import hashlib
import struct

import pytest

from custom_components.allo_wt7.quii import (
    QuIIStreamClient,
    QuIIStreamError,
    encode_device_password,
)


def _client(key: str = "k" * 32) -> QuIIStreamClient:
    return QuIIStreamClient("10.0.0.2", key, "a" * 64, "003-4077-abc")


def test_encode_device_password() -> None:
    # Short codes are SHA-256 hex (64 chars); a >=64 char OAC passes through.
    assert encode_device_password("1234") == hashlib.sha256(b"1234").hexdigest()
    oac = "a" * 64
    assert encode_device_password(oac) == oac
    # '@' must be doubled for the native parser (applied after the >=64 check).
    assert encode_device_password("@" * 64) == "@@" * 64


def test_stream_key_must_be_32_bytes() -> None:
    with pytest.raises(QuIIStreamError):
        QuIIStreamClient("10.0.0.2", "short", "a" * 64, "003-4077-abc")


def test_invalid_channel_or_stream() -> None:
    with pytest.raises(QuIIStreamError):
        QuIIStreamClient("10.0.0.2", "k" * 32, "a" * 64, "003-4077-abc", channel=0)
    with pytest.raises(QuIIStreamError):
        QuIIStreamClient("10.0.0.2", "k" * 32, "a" * 64, "003-4077-abc", stream=0)


def test_invalid_client_identifier() -> None:
    with pytest.raises(QuIIStreamError):
        QuIIStreamClient("10.0.0.2", "k" * 32, "a" * 64, "003-4077-")


def _annexb(inner_type: int, data: bytes) -> bytes:
    """Build one QUII media sub-frame: start code, type, length, 12-byte pad."""
    return b"\x00\x00\x01" + bytes([inner_type]) + struct.pack("<I", len(data)) + bytes(12) + data


def _media_header(prefix_length: int, media_offset: int, encrypted_body: bool) -> bytes:
    header = bytearray(32)
    header[0] = 0xA0  # a media record type
    struct.pack_into("<h", header, 9, prefix_length)
    header[15] = 1 if encrypted_body else 0
    struct.pack_into("<H", header, 16, media_offset)
    return bytes(header)


def test_extract_h264_frames_from_cleartext_record() -> None:
    client = _client()
    payload = _annexb(0xE0, b"frame-one") + _annexb(0xE1, b"frame-two")
    header = _media_header(prefix_length=0, media_offset=0, encrypted_body=False)
    frames = client._video_frames_from_record(header, payload)
    assert frames == [b"frame-one", b"frame-two"]


def test_non_video_subframes_are_skipped() -> None:
    client = _client()
    # 0x90 is not a video type: it must not be yielded as an H.264 frame.
    payload = _annexb(0x90, b"audio") + _annexb(0xE0, b"video")
    header = _media_header(prefix_length=0, media_offset=0, encrypted_body=False)
    assert client._video_frames_from_record(header, payload) == [b"video"]


def test_trailing_zero_padding_stops_parsing() -> None:
    client = _client()
    payload = _annexb(0xE0, b"only") + bytes(8)
    header = _media_header(prefix_length=0, media_offset=0, encrypted_body=False)
    assert client._video_frames_from_record(header, payload) == [b"only"]


def test_unknown_media_frame_is_rejected() -> None:
    client = _client()
    header = _media_header(prefix_length=0, media_offset=0, encrypted_body=False)
    with pytest.raises(QuIIStreamError):
        client._video_frames_from_record(header, b"\xde\xad\xbe\xef" + bytes(20))


def test_invalid_media_offset_is_rejected() -> None:
    client = _client()
    header = _media_header(prefix_length=0, media_offset=999, encrypted_body=False)
    with pytest.raises(QuIIStreamError):
        client._video_frames_from_record(header, b"\x00" * 8)
