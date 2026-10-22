"""Small asyncio client for the confirmed Allo Plus QUII live-video path."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import struct
import time
from collections.abc import AsyncIterator

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

QUII_PORT = 34567
QUII_SETUP = 0xA9
QUII_MEDIA_TYPES = range(0xA0, 0xA4)
QUII_VIDEO_FRAME_TYPES = (0xE0, 0xE1)
AES_IV = b"0" * 16
AES_BLOCK_SIZE = 16
SHA256_SIZE = 32
SETUP_TIMEOUT_S = 10
KEEPALIVE_INTERVAL_S = 5
MAX_RECORD_SIZE = 8 * 1024 * 1024
MAX_FRAME_SIZE = 8 * 1024 * 1024


class QuIIStreamError(Exception):
    """The monitor returned a malformed or unsupported QUII stream."""


class QuIIAuthenticationError(QuIIStreamError):
    """The monitor rejected the local QUII login."""


def encode_device_password(auth_code: str) -> str:
    """Mirror QvEncrypt.EncodeDevicePassword and getCorrectPassword."""
    password = (
        auth_code
        if len(auth_code) >= 64
        else hashlib.sha256(auth_code.encode("utf-8")).hexdigest()
    )
    return password.replace("@", "@@")


class QuIIStreamClient:
    """Connect to one wT7 live H.264 stream and yield complete video frames."""

    def __init__(
        self,
        host: str,
        stream_key: str,
        auth_code: str,
        client_id: str,
        *,
        username: str = "adminapp2",
        custom_id: str = "A0077G0077",
        channel: int = 1,
        stream: int = 1,
        port: int = QUII_PORT,
    ) -> None:
        key = stream_key.encode("ascii", errors="strict")
        if len(key) != 32:
            raise QuIIStreamError("The monitor did not return a 32-byte stream key")
        if not 1 <= channel <= 0xFFFF or not 1 <= stream <= 0xFFFF:
            raise QuIIStreamError("Invalid channel or stream number")

        self.host = host
        self.port = port
        self._key = key
        self._username = username
        self._password = encode_device_password(auth_code)
        self._custom_id = custom_id
        # The native URL parser turns ids=1 into stream index 0.
        self._stream_index = stream - 1
        self._channel = channel

        client_suffix = client_id.rsplit("-", 1)[-1]
        if not client_suffix or len(client_suffix) > 64:
            raise QuIIStreamError("Invalid QUII client identifier")
        self._client_suffix = client_suffix

    async def video_frames(self) -> AsyncIterator[bytes]:
        """Yield Annex-B H.264 frames from the monitor until the socket closes."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=SETUP_TIMEOUT_S
            )
        except (TimeoutError, OSError) as err:
            raise QuIIStreamError(
                f"Cannot connect to monitor at {self.host}:{self.port}"
            ) from err

        keepalive_task: asyncio.Task[None] | None = None
        try:
            writer.write(bytes([QUII_SETUP]) + bytes(31))
            await writer.drain()
            setup = await asyncio.wait_for(
                reader.readexactly(32), timeout=SETUP_TIMEOUT_S
            )
            if setup[0] != QUII_SETUP:
                raise QuIIStreamError("Unexpected QUII setup response")
            if setup[9] != 0:
                raise QuIIStreamError(f"QUII setup rejected (status {setup[9]})")
            if setup[10] != 2 or setup[11] != 1:
                raise QuIIStreamError(
                    "Unsupported QUII cipher or digest; expected AES-256 and SHA-256"
                )

            await self._send_open(writer)
            keepalive_task = asyncio.create_task(self._keepalive_loop(writer))
            read_task = asyncio.create_task(reader.read(64 * 1024))
            pending = bytearray()
            try:
                while True:
                    done, _ = await asyncio.wait(
                        {read_task, keepalive_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if keepalive_task in done:
                        # Propagate any socket write failure to the stream owner.
                        keepalive_task.result()
                    if read_task not in done:
                        continue

                    chunk = read_task.result()
                    if not chunk:
                        raise QuIIStreamError("The monitor closed the video stream")
                    pending.extend(chunk)
                    if len(pending) > MAX_RECORD_SIZE * 2:
                        raise QuIIStreamError("QUII receive buffer exceeded its limit")

                    while len(pending) >= 32:
                        header = self._decrypt(bytes(pending[:32]))
                        message_type = header[0]
                        if message_type in QUII_MEDIA_TYPES:
                            payload_length = struct.unpack_from("<I", header, 11)[0]
                        else:
                            payload_length = struct.unpack_from("<H", header, 9)[0]
                        if payload_length > MAX_RECORD_SIZE:
                            raise QuIIStreamError("QUII record exceeds the size limit")
                        record_length = 32 + payload_length
                        if len(pending) < record_length:
                            break

                        payload = bytes(pending[32:record_length])
                        del pending[:record_length]

                        if message_type in QUII_MEDIA_TYPES:
                            for frame in self._video_frames_from_record(
                                header, payload
                            ):
                                yield frame
                        else:
                            self._check_command(header, payload)
                            if message_type in (0x81, 0x82, 0x83) and header[11] != 0:
                                raise QuIIAuthenticationError(
                                    f"Monitor rejected QUII login (status {header[11]})"
                                )
                            if message_type == 0x83 and header[12] != 1:
                                raise QuIIStreamError(
                                    "Monitor did not start the live video stream"
                                )
                            if message_type == 0xFF:
                                raise QuIIStreamError(
                                    "The monitor ended the video stream"
                                )

                    read_task = asyncio.create_task(reader.read(64 * 1024))
            finally:
                if not read_task.done():
                    read_task.cancel()
                await asyncio.gather(read_task, return_exceptions=True)
        except asyncio.IncompleteReadError as err:
            raise QuIIStreamError("Incomplete QUII message from monitor") from err
        finally:
            if keepalive_task is not None:
                keepalive_task.cancel()
                await asyncio.gather(keepalive_task, return_exceptions=True)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def _send_open(self, writer: asyncio.StreamWriter) -> None:
        auth_data = (
            f"{self._username}&&{self._password}".encode()
            + b"\x00"
            + self._custom_id.encode("ascii")
            + b"\x00"
            + self._client_suffix.encode("ascii")
            + b"\x00"
        )
        encrypted_payload_length = _round_up(
            len(auth_data) + SHA256_SIZE, AES_BLOCK_SIZE
        )

        header = bytearray(32)
        header[0] = 0x01
        struct.pack_into("<Q", header, 1, int(time.time()))
        struct.pack_into("<H", header, 9, encrypted_payload_length)
        struct.pack_into("<H", header, 11, len(auth_data))
        struct.pack_into("<H", header, 13, self._channel)
        header[15] = 1
        struct.pack_into("<H", header, 16, self._stream_index)

        digest = hashlib.sha256(header + auth_data).digest()
        body = (
            auth_data
            + digest
            + bytes(encrypted_payload_length - len(auth_data) - len(digest))
        )
        writer.write(self._encrypt(bytes(header)) + self._encrypt(body))
        await writer.drain()

    async def _keepalive_loop(self, writer: asyncio.StreamWriter) -> None:
        while True:
            await asyncio.sleep(KEEPALIVE_INTERVAL_S)
            header = bytearray(32)
            header[0] = 0x00
            struct.pack_into("<Q", header, 1, int(time.time()))
            struct.pack_into("<H", header, 9, SHA256_SIZE)
            body = hashlib.sha256(header).digest()
            writer.write(self._encrypt(bytes(header)) + self._encrypt(body))
            await writer.drain()

    def _check_command(self, header: bytes, payload: bytes) -> None:
        if not payload:
            return
        if len(payload) % AES_BLOCK_SIZE:
            raise QuIIStreamError("QUII command body is not AES block-aligned")
        plain = self._decrypt(payload)
        parameter_length = (
            struct.unpack_from("<H", header, 11)[0] if header[0] == 0xFE else 0
        )
        digest_end = parameter_length + SHA256_SIZE
        if digest_end > len(plain):
            raise QuIIStreamError("QUII command digest is incomplete")
        expected = hashlib.sha256(header + plain[:parameter_length]).digest()
        if not hmac.compare_digest(expected, plain[parameter_length:digest_end]):
            raise QuIIStreamError("QUII command SHA-256 check failed")

    def _video_frames_from_record(self, header: bytes, payload: bytes) -> list[bytes]:
        prefix_length = struct.unpack_from("<h", header, 9)[0]
        media_offset = struct.unpack_from("<H", header, 16)[0]
        if prefix_length < 0 or prefix_length > len(payload):
            raise QuIIStreamError("Invalid QUII media prefix length")

        media = bytearray(payload)
        if prefix_length:
            media[:prefix_length] = self._decrypt(bytes(media[:prefix_length]))
        if media_offset > len(media):
            raise QuIIStreamError("Invalid QUII media offset")
        if header[15] != 0:
            encrypted_body = bytes(media[media_offset:])
            if len(encrypted_body) % AES_BLOCK_SIZE:
                raise QuIIStreamError("Encrypted QUII media body is not block-aligned")
            media[media_offset:] = self._decrypt(encrypted_body)

        frames: list[bytes] = []
        remaining = bytes(media[media_offset:])
        while remaining:
            if not remaining.strip(b"\x00"):
                break
            if len(remaining) < 20 or remaining[:3] != b"\x00\x00\x01":
                raise QuIIStreamError("Fragmented or unknown QUII media frame")
            inner_type = remaining[3]
            frame_length = struct.unpack_from("<I", remaining, 4)[0]
            if frame_length > MAX_FRAME_SIZE:
                raise QuIIStreamError("QUII media frame exceeds the size limit")
            total_length = 20 + frame_length
            if total_length > len(remaining):
                raise QuIIStreamError("Fragmented QUII media frame is unsupported")
            frame = remaining[20:total_length]
            if inner_type in QUII_VIDEO_FRAME_TYPES and frame:
                frames.append(frame)
            remaining = remaining[total_length:]
        return frames

    def _decrypt(self, data: bytes) -> bytes:
        if len(data) % AES_BLOCK_SIZE:
            raise QuIIStreamError("QUII AES data is not block-aligned")
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(AES_IV))
        decryptor = cipher.decryptor()
        return decryptor.update(data) + decryptor.finalize()

    def _encrypt(self, data: bytes) -> bytes:
        if len(data) % AES_BLOCK_SIZE:
            raise QuIIStreamError("QUII AES data is not block-aligned")
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(AES_IV))
        encryptor = cipher.encryptor()
        return encryptor.update(data) + encryptor.finalize()


def _round_up(value: int, block_size: int) -> int:
    return (value + block_size - 1) // block_size * block_size
