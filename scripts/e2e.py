"""End-to-end smoke test: a real Home Assistant against simulated WattBoxes.

Boots ``hass`` from the current interpreter with this repository's
``custom_components`` linked into a throwaway config directory, onboards a
user over the API, then drives the WattBox config flow exactly as the UI does
and reports what it produced: the flow outcome, the entities created, and
every log line from the integration at WARNING or above.

The simulators need the integration's real ports (23 for telnet, 80 for
HTTP), because the config flow derives the port from the connection type.
They bind loopback aliases, so this needs to run as root (or with
CAP_NET_BIND_SERVICE)::

    sudo python scripts/e2e.py            # whichever HA is installed

Exits non-zero when any scenario does not end the way it is expected to.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.simulator import (  # noqa: E402
    HttpSimulator,
    SimState,
    SshSimulator,
    TelnetSimulator,
)

HA_PORT = 8124
BASE = f"http://127.0.0.1:{HA_PORT}"
CLIENT_ID = f"{BASE}/"

CONFIGURATION = """
homeassistant:
  name: WattBox E2E
  time_zone: UTC
http:
  server_host: 127.0.0.1
  server_port: {port}
api:
config:
onboarding:
person:
logger:
  default: warning
  logs:
    custom_components.wattbox: debug
"""

# (title, simulator host, connection type, password, expected flow outcome)
SCENARIOS: list[tuple[str, str, str, str, str]] = [
    ("800 series over telnet", "127.0.0.2", "telnet", "wattbox", "create_entry"),
    ("800 series, wrong password", "127.0.0.2", "telnet", "nope", "invalid_auth"),
    ("300 series over HTTP", "127.0.0.3", "http", "wattbox", "create_entry"),
    ("700 series, wrong password (#67)", "127.0.0.4", "http", "nope", "invalid_auth"),
    ("800 series picked as HTTP (#56)", "127.0.0.5", "http", "wattbox", "invalid_auth"),
    ("Integration Protocol over SSH", "127.0.0.6", "ssh", "wattbox", "create_entry"),
]


async def _wait_for_api(client: httpx.AsyncClient, proc: subprocess.Popen) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"hass exited with {proc.returncode}")
        with contextlib.suppress(httpx.HTTPError):
            r = await client.get(f"{BASE}/api/onboarding")
            if r.status_code == 200:
                return
        await asyncio.sleep(1)
    raise TimeoutError("Home Assistant did not come up")


async def _onboard(client: httpx.AsyncClient) -> str:
    r = await client.post(
        f"{BASE}/api/onboarding/users",
        json={
            "client_id": CLIENT_ID,
            "name": "E2E",
            "username": "e2e",
            "password": "e2e-password",
            "language": "en",
        },
    )
    r.raise_for_status()
    r = await client.post(
        f"{BASE}/auth/token",
        data={
            "grant_type": "authorization_code",
            "code": r.json()["auth_code"],
            "client_id": CLIENT_ID,
        },
    )
    r.raise_for_status()
    return r.json()["access_token"]


async def _run_flow(
    client: httpx.AsyncClient, name: str, host: str, conn: str, password: str
) -> dict[str, Any]:
    r = await client.post(
        f"{BASE}/api/config/config_entries/flow", json={"handler": "wattbox"}
    )
    r.raise_for_status()
    flow = r.json()
    r = await client.post(
        f"{BASE}/api/config/config_entries/flow/{flow['flow_id']}",
        json={
            "host": host,
            "connection_type": conn,
            "username": "wattbox",
            "password": password,
            "name": name,
        },
    )
    r.raise_for_status()
    return r.json()


def _outcome(result: dict[str, Any]) -> str:
    if result.get("type") == "create_entry":
        return "create_entry"
    return (result.get("errors") or {}).get("base") or result.get("type", "?")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep the config dir")
    args = parser.parse_args()

    telnet = TelnetSimulator(SimState.with_outlets(12), "127.0.0.2", 23)
    http300 = HttpSimulator(
        SimState.with_outlets(3, model="WB-300-IP-3", service_tag="ST-SIM300"),
        "127.0.0.3",
        80,
    )
    http700 = HttpSimulator(
        SimState.with_outlets(12, model="WB-700-IPV-12", service_tag="ST-SIM700"),
        "127.0.0.4",
        80,
        bad_auth="blank",
    )
    # An 800 has no XML API: it rejects every HTTP request, credentials or not.
    http800 = HttpSimulator(
        SimState.with_outlets(12, password="\0never"), "127.0.0.5", 80
    )
    ssh = SshSimulator(
        SimState.with_outlets(6, service_tag="ST-SIMSSH"), "127.0.0.6", 22
    )
    for sim in (telnet, http300, http700, http800, ssh):
        await sim.start()

    config_dir = Path(tempfile.mkdtemp(prefix="wattbox-e2e-"))
    (config_dir / "configuration.yaml").write_text(CONFIGURATION.format(port=HA_PORT))
    (config_dir / "custom_components").mkdir()
    os.symlink(
        ROOT / "custom_components" / "wattbox",
        config_dir / "custom_components" / "wattbox",
    )
    log_path = config_dir / "hass.log"
    log_file = log_path.open("w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "homeassistant", "-c", str(config_dir)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    failures = 0
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            await _wait_for_api(client, proc)
            client.headers["Authorization"] = f"Bearer {await _onboard(client)}"
            r = await client.get(f"{BASE}/api/config")
            print(
                f"Home Assistant {r.json()['version']} on Python {sys.version.split()[0]}"
            )

            for index, (title, host, conn, password, expected) in enumerate(SCENARIOS):
                result = await _run_flow(client, f"WB{index}", host, conn, password)
                got = _outcome(result)
                ok = got == expected
                failures += not ok
                print(
                    f"  [{'PASS' if ok else 'FAIL'}] {title}: {got} (expected {expected})"
                )

            # Give the coordinator a poll, then look at what was created.
            await asyncio.sleep(3)
            states = (await client.get(f"{BASE}/api/states")).json()
            ours = [s for s in states if s["entity_id"].split(".")[1].startswith("wb")]
            by_device: dict[str, list[dict[str, Any]]] = {}
            for s in ours:
                by_device.setdefault(s["entity_id"].split(".")[1][:3], []).append(s)
            for prefix, entities in sorted(by_device.items()):
                domains: dict[str, int] = {}
                for s in entities:
                    domain = s["entity_id"].split(".")[0]
                    domains[domain] = domains.get(domain, 0) + 1
                unavailable = sum(s["state"] == "unavailable" for s in entities)
                print(f"  {prefix}: {json.dumps(domains)}, {unavailable} unavailable")
                for s in entities:
                    if s["entity_id"].endswith(("_voltage", "_power")) and s[
                        "entity_id"
                    ].startswith("sensor."):
                        print(f"      {s['entity_id']} = {s['state']}")

            # Toggle an outlet through the service layer, as a dashboard would.
            switches = [
                s["entity_id"] for s in ours if s["entity_id"].startswith("switch.wb0_")
            ]
            if switches:
                target = next(e for e in switches if "master" not in e)
                await client.post(
                    f"{BASE}/api/services/switch/turn_off", json={"entity_id": target}
                )
                await asyncio.sleep(2)
                state = (await client.get(f"{BASE}/api/states/{target}")).json()[
                    "state"
                ]
                outlet_on = telnet.state.outlets[0].on
                ok = state == "off" and not outlet_on
                failures += not ok
                print(
                    f"  [{'PASS' if ok else 'FAIL'}] turn_off {target}: entity={state}, "
                    f"device outlet on={outlet_on}"
                )

            # Reload the telnet entry: the old session has to be released.
            entries = (
                await client.get(f"{BASE}/api/config/config_entries/entry")
            ).json()
            wb0 = next((e for e in entries if e["title"] == "WB0"), None)
            if wb0 is not None:
                before = len(telnet.sessions)
                for _ in range(3):
                    await client.post(
                        f"{BASE}/api/config/config_entries/entry/{wb0['entry_id']}/reload"
                    )
                await asyncio.sleep(1)
                ok = len(telnet.sessions) <= max(before, 1)
                failures += not ok
                print(
                    f"  [{'PASS' if ok else 'FAIL'}] sessions after 3 reloads: "
                    f"{len(telnet.sessions)} (before {before})"
                )
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=30)
        log_file.close()

    # Home Assistant does not unload entries on shutdown; the session must be
    # handed back regardless, or a restart leaves it occupying a slot.
    await asyncio.sleep(0.5)
    ok = not telnet.sessions and "!Exit" in telnet.commands[-3:]
    failures += not ok
    print(
        f"  [{'PASS' if ok else 'FAIL'}] sessions after Home Assistant stopped: "
        f"{len(telnet.sessions)}, last commands {telnet.commands[-2:]}"
    )
    for sim in (telnet, http300, http700, http800, ssh):
        await sim.stop()

    print("Integration log lines at WARNING or above:")
    seen = set()
    for line in log_path.read_text().splitlines():
        if (
            "wattbox" in line.lower()
            or "Traceback" in line
            or "blocking call" in line.lower()
        ) and any(level in line for level in ("WARNING", "ERROR", "CRITICAL")):
            msg = line.split("] ", 1)[-1][:220]
            if msg not in seen:
                seen.add(msg)
                print("   ", msg)

    if args.keep:
        print(f"Config dir kept at {config_dir}")
    else:
        shutil.rmtree(config_dir, ignore_errors=True)
    print("FAILED" if failures else "ALL PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
