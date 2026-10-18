"""Protocol client tests: envelope helpers and LAN error mapping."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from custom_components.allo_wt7.client import (
    AlloWT7Client,
    AlloWT7ConnectionError,
    AlloWT7UnsupportedError,
    AlloWT7WrongPinError,
    _build_lan_envelope,
    _encode_device_password,
    _parse_envelope,
)


def _reply(error: str, extra: str = "") -> bytes:
    return (
        f"<?xml version='1.0'?><envelope><header><error>{error}</error></header>"
        f"<body>{extra}</body></envelope>"
    ).encode()


def _client() -> AlloWT7Client:
    return AlloWT7Client(
        AsyncMock(), client_id="003-test", monitor_retry_delay_s=0
    )


def test_encode_device_password() -> None:
    assert len(_encode_device_password("1234")) == 64
    oac = "a" * 64
    assert _encode_device_password(oac) == oac


def test_lan_envelope_escapes_xml() -> None:
    body = _build_lan_envelope("x<&>y", "get.x")
    assert "<password>x&lt;&amp;&gt;y</password>" in body


def test_parse_envelope_tolerates_garbage() -> None:
    env = _parse_envelope(b"HTTP junk" + _reply("0") + b"trailing")
    assert env is not None
    assert env.findtext(".//error") == "0"
    assert _parse_envelope(b"") is None
    assert _parse_envelope(b"<envelope>") is None


async def test_open_door_ok_and_errors() -> None:
    client = _client()
    with patch.object(client, "_lan_request", AsyncMock(return_value=(200, _reply("0")))):
        await client.open_door("10.0.0.2", "oac", "1234")

    client = _client()
    with patch.object(client, "_lan_request", AsyncMock(return_value=(200, _reply("-3")))):
        with pytest.raises(AlloWT7WrongPinError):
            await client.open_door("10.0.0.2", "oac", "1234")

    client = _client()
    with patch.object(client, "_lan_request", AsyncMock(return_value=(200, _reply("-1")))):
        with pytest.raises(AlloWT7UnsupportedError):
            await client.open_door("10.0.0.2", "oac", None)


async def test_open_door_omits_password_without_pin() -> None:
    client = _client()
    mock = AsyncMock(return_value=(200, _reply("0")))
    with patch.object(client, "_lan_request", mock):
        await client.open_door("10.0.0.2", "oac", None, lock_number=2)
    body = mock.call_args.args[1]
    assert "<locknumber>2</locknumber>" in body
    assert "<content><door>1</door><locknumber>2</locknumber></content>" in body


async def test_lan_timeout_becomes_connection_error() -> None:
    """A filtered port (timeout) must not escape as a raw TimeoutError."""
    client = _client()
    with patch.object(
        client, "_lan_request", AsyncMock(side_effect=asyncio.TimeoutError)
    ):
        with pytest.raises(AlloWT7ConnectionError):
            await client.check_pin("10.0.0.2", "oac", "1234")


async def test_lan_falls_back_to_http() -> None:
    client = _client()
    mock = AsyncMock(
        side_effect=[aiohttp.ClientConnectionError("refused"), (200, _reply("0"))]
    )
    with patch.object(client, "_lan_request", mock):
        assert await client.check_pin("10.0.0.2", "oac", "1234") is True
    urls = [c.args[0] for c in mock.call_args_list]
    assert urls == ["https://10.0.0.2/tdkcgi", "http://10.0.0.2/tdkcgi"]


async def test_lan_request_retries_dropped_keepalive() -> None:
    client = _client()

    class _Resp:
        status = 200

        async def read(self) -> bytes:
            return _reply("0")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    calls = 0

    def _post(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise aiohttp.ServerDisconnectedError()
        return _Resp()

    client._session.post = _post
    status, raw = await client._lan_request("https://10.0.0.2/tdkcgi", "<x/>")
    assert status == 200 and calls == 2


async def test_poll_last_picture_picks_newest_and_reuses_session() -> None:
    client = _client()
    page = (
        "<record><datalist>"
        "<data><filename>a.jpg</filename><starttime>2026-10-18t10:00:00z</starttime></data>"
        "<data><filename>b.jpg</filename><starttime>2026-10-18t11:00:00z</starttime></data>"
        "</datalist></record>"
    )
    responses = [
        (200, _reply("0", "<record><id>42</id></record>")),
        (200, _reply("0", page)),
        (200, _reply("0")),
    ]
    with patch.object(client, "_lan_request", AsyncMock(side_effect=responses)):
        fn, st, sess, err = await client.poll_last_picture("10.0.0.2", "oac")
    assert (fn, st, sess, err) == ("b.jpg", "2026-10-18t11:00:00z", "42", None)

    mock = AsyncMock(return_value=(200, _reply("0")))
    with patch.object(client, "_lan_request", mock):
        fn, st, sess, err = await client.poll_last_picture(
            "10.0.0.2", "oac", session_id="42"
        )
    assert (fn, sess, err) == (None, "42", None)
    assert "get.record.session" not in mock.call_args_list[0].args[1]
