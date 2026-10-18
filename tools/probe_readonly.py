#!/usr/bin/env python3
"""Read-only LAN probe for an Intelbras Allo wT7 monitor.

Sends a fixed list of *read* commands found in the Allo Plus app
(docs/reverse-engineering/) to the monitor's /tdkcgi endpoint and prints the
replies with identifiers redacted, so the result can be pasted into an issue.

It never sends set.* commands and never opens a door. Python 3 stdlib only.

Usage:
    python3 tools/probe_readonly.py --ip 192.168.1.42 --oac-file /config/.storage/allo_wt7_<entry_id>_oac
    python3 tools/probe_readonly.py --ip 192.168.1.42 --oac <64-hex OAC>

The OAC is the credential Home Assistant caches in
.storage/allo_wt7_<entry_id>_oac (key "oac"). Treat it like a password.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

# Read-only commands only. Names come from DeviceRequestHelp (XML) and
# DeviceJsonRequestHelp (JSON) in the Allo Plus 2.4.77.17 APK.
XML_COMMANDS = (
    "get.system.info",
    "get.product.info",
    "get.device.status",
    "get.system.status",
    "get.tfcard.info",
)
JSON_COMMANDS = (
    "get.audio.outvolume",
    "get.lock.status",
    "get.call.time",
)

# Values that identify the device, the network or a credential.
_SENSITIVE_TAGS = (
    "mac", "ssid", "ip", "ipaddr", "gateway", "submask", "dns", "umid", "id",
    "key", "password", "pwd", "tdc", "serial", "sn", "address",
)
_XML_SENSITIVE = re.compile(
    r"<(?P<tag>" + "|".join(_SENSITIVE_TAGS) + r")>[^<]*</(?P=tag)>", re.IGNORECASE
)


def _redact_xml(text: str) -> str:
    return _XML_SENSITIVE.sub(lambda m: f"<{m['tag']}>REDACTED</{m['tag']}>", text)


def _redact_json(value):
    if isinstance(value, dict):
        return {
            k: "REDACTED" if k.lower() in _SENSITIVE_TAGS else _redact_json(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_json(v) for v in value]
    return value


def _password(oac: str) -> str:
    # Same rule as the app's QvEncrypt.EncodeDevicePassword.
    return oac if len(oac) >= 64 else hashlib.sha256(oac.encode()).hexdigest()


def _post(ip: str, body: bytes, content_type: str, timeout: float) -> tuple[str, str]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    last = ""
    for scheme in ("https", "http"):
        req = urllib.request.Request(
            f"{scheme}://{ip}/tdkcgi",
            data=body,
            headers={"Content-Type": content_type, "User-Agent": "okhttp/3.12.13"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                req, timeout=timeout, context=ctx if scheme == "https" else None
            ) as resp:
                return scheme, resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as err:
            last = f"{scheme}: {err}"
    raise ConnectionError(last)


def probe_xml(ip: str, oac: str, command: str, timeout: float) -> str:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?><envelope><header>'
        f"<password>{escape(_password(oac))}</password><passwordencode>1</passwordencode>"
        "<security>username</security><username>adminapp2</username></header>"
        f"<body><command>{command}</command><content></content></body></envelope>"
    ).encode()
    scheme, text = _post(ip, body, "application/xml;charset=utf-8", timeout)
    return f"[{scheme}] " + _redact_xml(text)


def probe_json(ip: str, oac: str, command: str, timeout: float) -> str:
    body = json.dumps(
        {
            "header": {
                "security": "username",
                "username": "adminapp2",
                "password": _password(oac),
                "passwordencode": 1,
            },
            "body": {"command": command},
        }
    ).encode()
    scheme, text = _post(ip, body, "application/json;charset=utf-8", timeout)
    try:
        return f"[{scheme}] " + json.dumps(_redact_json(json.loads(text)), ensure_ascii=False)
    except ValueError:
        return f"[{scheme}] (not JSON) " + _redact_xml(text[:500])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ip", required=True, help="monitor IP on the LAN")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--oac", help="OAC (out-auth-code)")
    group.add_argument("--oac-file", help="Home Assistant .storage/allo_wt7_*_oac file")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()

    if args.oac_file:
        with open(args.oac_file, encoding="utf-8") as fh:
            oac = json.load(fh)["data"]["oac"]
    else:
        oac = args.oac

    print(f"OAC length: {len(oac)} (value not printed)")
    for command in XML_COMMANDS:
        try:
            print(f"\n== {command} (XML)\n{probe_xml(args.ip, oac, command, args.timeout)}")
        except ConnectionError as err:
            print(f"\n== {command} (XML)\nunreachable: {err}")
    for command in JSON_COMMANDS:
        try:
            print(f"\n== {command} (JSON)\n{probe_json(args.ip, oac, command, args.timeout)}")
        except ConnectionError as err:
            print(f"\n== {command} (JSON)\nunreachable: {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
