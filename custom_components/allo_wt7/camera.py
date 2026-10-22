"""Live camera entity for the Intelbras Allo wT7."""

from __future__ import annotations

import asyncio
import logging
import time

from aiohttp import web
from homeassistant.components.camera import Camera
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AlloWT7Coordinator
from .entity import AlloWT7Entity
from .quii import QuIIStreamError

_LOGGER = logging.getLogger(__name__)
FRAME_WAIT_TIMEOUT_S = 20
MAX_JPEG_BUFFER = 16 * 1024 * 1024


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the wT7 live camera."""
    async_add_entities(
        [AlloWT7LiveCamera(entry.runtime_data, entry, get_ffmpeg_manager(hass).binary)]
    )


class AlloWT7LiveCamera(AlloWT7Entity, Camera):
    """Turn the wT7's QUII/H.264 video into a Home Assistant MJPEG feed."""

    _attr_should_poll = False
    _attr_content_type = "image/jpeg"
    _attr_frame_interval = 0.2
    _attr_icon = "mdi:video"
    _attr_translation_key = "live_video"

    def __init__(
        self,
        coordinator: AlloWT7Coordinator,
        entry: ConfigEntry,
        ffmpeg_binary: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._ffmpeg_binary = ffmpeg_binary
        self._attr_unique_id = f"{self._device_key}_live_video"
        self._subscribers: set[asyncio.Queue[bytes | Exception]] = set()
        self._subscriber_lock = asyncio.Lock()
        self._worker_task: asyncio.Task[None] | None = None
        self._last_frame: bytes | None = None
        self._last_frame_at = 0.0

    @property
    def available(self) -> bool:
        """The video key request requires a configured TLS certificate pin."""
        return self._coordinator.video_tls_fingerprint_configured

    @property
    def is_streaming(self) -> bool:
        """Report the camera as streaming while a viewer is subscribed."""
        return bool(self._subscribers)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a recent decoded frame, opening a short stream if needed."""
        if self._last_frame and time.monotonic() - self._last_frame_at < 2:
            return self._last_frame
        queue = await self._subscribe()
        try:
            return await self._next_frame(queue)
        finally:
            await self._unsubscribe(queue)

    async def handle_async_mjpeg_stream(
        self, request: web.Request
    ) -> web.StreamResponse:
        """Serve the live feed through Home Assistant's camera proxy endpoint."""
        queue = await self._subscribe()
        try:
            first_frame = await self._next_frame(queue)
            response = web.StreamResponse(
                headers={
                    "Content-Type": "multipart/x-mixed-replace; boundary=frame",
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                }
            )
            await response.prepare(request)
            await response.write(_mjpeg_part(first_frame))

            while True:
                item = await queue.get()
                if isinstance(item, Exception):
                    break
                await response.write(_mjpeg_part(item))
        finally:
            await self._unsubscribe(queue)
        return response

    async def async_will_remove_from_hass(self) -> None:
        """Stop the shared decoder when this config entry unloads."""
        self._publish_error(HomeAssistantError("Allo wT7 camera was reloaded"))
        task = self._worker_task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await super().async_will_remove_from_hass()

    async def _subscribe(self) -> asyncio.Queue[bytes | Exception]:
        """Join the shared source or start it for the first viewer."""
        if not self._coordinator.video_tls_fingerprint_configured:
            raise HomeAssistantError(
                "Configure the monitor TLS SHA-256 fingerprint in the Allo wT7 options"
            )
        queue: asyncio.Queue[bytes | Exception] = asyncio.Queue(maxsize=1)
        async with self._subscriber_lock:
            self._subscribers.add(queue)
            if self._last_frame and time.monotonic() - self._last_frame_at < 2:
                queue.put_nowait(self._last_frame)
            if self._worker_task is None or self._worker_task.done():
                self._worker_task = self.hass.async_create_task(
                    self._run_stream(),
                    name=f"allo_wt7_video_{self._entry.entry_id}",
                )
        return queue

    async def _unsubscribe(self, queue: asyncio.Queue[bytes | Exception]) -> None:
        """Leave the shared source and stop it when its last viewer closes."""
        task: asyncio.Task[None] | None = None
        async with self._subscriber_lock:
            self._subscribers.discard(queue)
            if not self._subscribers and self._worker_task is not None:
                if not self._worker_task.done():
                    self._worker_task.cancel()
                task = self._worker_task
                self._worker_task = None
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def _next_frame(
        self, queue: asyncio.Queue[bytes | Exception]
    ) -> bytes:
        """Wait for a decoded frame or surface a safe, key-free error."""
        try:
            item = await asyncio.wait_for(queue.get(), timeout=FRAME_WAIT_TIMEOUT_S)
        except TimeoutError as err:
            raise HomeAssistantError("Timed out waiting for Allo wT7 video") from err
        if isinstance(item, Exception):
            raise HomeAssistantError(str(item)) from item
        return item

    async def _run_stream(self) -> None:
        """Run one QUII connection and FFmpeg process for all current viewers."""
        process: asyncio.subprocess.Process | None = None
        feed_task: asyncio.Task[None] | None = None
        read_task: asyncio.Task[None] | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                self._ffmpeg_binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-f",
                "h264",
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "mjpeg",
                "-q:v",
                "7",
                "-f",
                "image2pipe",
                "pipe:1",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            assert process.stdin is not None
            assert process.stdout is not None
            feed_task = self.hass.async_create_task(
                self._feed_video(process.stdin),
                name=f"allo_wt7_video_input_{self._entry.entry_id}",
            )
            read_task = self.hass.async_create_task(
                self._read_jpegs(process.stdout),
                name=f"allo_wt7_video_output_{self._entry.entry_id}",
            )
            done, _ = await asyncio.wait(
                {feed_task, read_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if read_task in done:
                await read_task
                raise QuIIStreamError("FFmpeg stopped before the monitor stream ended")

            await feed_task
            process.stdin.close()
            try:
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass
            await read_task
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001 - forward a safe message to viewers
            _LOGGER.warning("Allo wT7 live video stopped: %s", err)
            self._publish_error(HomeAssistantError(str(err)))
        finally:
            for task in (feed_task, read_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (feed_task, read_task) if task is not None),
                return_exceptions=True,
            )
            if process is not None and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except TimeoutError:
                    process.kill()
                    await process.wait()

    async def _feed_video(self, ffmpeg_input: asyncio.StreamWriter) -> None:
        """Pass complete H.264 frames from QUII into FFmpeg stdin."""
        async for frame in self._coordinator.async_video_frames():
            ffmpeg_input.write(frame)
            await ffmpeg_input.drain()

    async def _read_jpegs(self, ffmpeg_output: asyncio.StreamReader) -> None:
        """Split FFmpeg's image2pipe output into complete JPEG frames."""
        buffer = bytearray()
        while chunk := await ffmpeg_output.read(64 * 1024):
            buffer.extend(chunk)
            if len(buffer) > MAX_JPEG_BUFFER:
                raise HomeAssistantError("FFmpeg produced an oversized JPEG frame")
            while True:
                start = buffer.find(b"\xff\xd8")
                if start < 0:
                    if buffer.endswith(b"\xff"):
                        buffer[:] = b"\xff"
                    else:
                        buffer.clear()
                    break
                end = buffer.find(b"\xff\xd9", start + 2)
                if end < 0:
                    if start:
                        del buffer[:start]
                    break
                frame = bytes(buffer[start : end + 2])
                del buffer[: end + 2]
                self._publish_frame(frame)

    def _publish_frame(self, frame: bytes) -> None:
        self._last_frame = frame
        self._last_frame_at = time.monotonic()
        self._publish(frame)

    def _publish_error(self, error: Exception) -> None:
        self._publish(error)

    def _publish(self, item: bytes | Exception) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                pass


def _mjpeg_part(frame: bytes) -> bytes:
    return (
        b"--frame\r\n"
        b"Content-Type: image/jpeg\r\n"
        + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
        + frame
        + b"\r\n"
    )
