#!/usr/bin/env python3
"""Home-network web controller for an MTTL-W01. Requires Python 3.9+."""

import argparse
import asyncio
import contextlib
import ipaddress
import json
import logging
import socket
import time
from pathlib import Path

from protocol import BOOT, DEVICE_PORT, EVENT, RSSI, VOLTAGE, parse_info
from web import RequestError, read_request, send_response

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("home-strip")
STALE_SECONDS = 20
COMMAND_TIMEOUT = 6
ASSETS = {
    "/": (ROOT / "static/index.html", "text/html; charset=utf-8"),
    "/app.js": (ROOT / "static/app.js", "text/javascript; charset=utf-8"),
    "/style.css": (ROOT / "static/style.css", "text/css; charset=utf-8"),
    "/provision.py": (ROOT / "provision.py", "text/x-python; charset=utf-8"),
}


class CommandError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


class Session:
    def __init__(self, reader, writer, identity):
        self.reader, self.writer = reader, writer
        self.mac = identity.group(2).upper()
        self.model, self.firmware = identity.group(1), identity.group(4)
        self.ip = writer.get_extra_info("peername")[0]
        self.connected = True
        self.outlets = {number: {"number": number, "on": None, "power_w": None,
                               "energy_kwh": None, "temperature_c": None}
                        for number in range(1, 5)}
        self.updated = {number: 0.0 for number in self.outlets}
        self.versions = {number: 0 for number in self.outlets}
        self.last_report_at = None
        self.voltage_v, self.rssi_dbm = None, None
        self.changed = asyncio.Event()
        self.command_lock = asyncio.Lock()
        self.busy = False

    @property
    def ready(self):
        now = time.monotonic()
        return self.connected and all(updated and now - updated < STALE_SECONDS
                                      for updated in self.updated.values())

    def snapshot(self):
        ready = self.ready
        measured = all(outlet["on"] is not None for outlet in self.outlets.values())
        return {
            "id": self.mac, "name": f"MTTL-W01 · {self.mac[-7:]}",
            "model": self.model, "firmware": self.firmware, "ip": self.ip,
            "connected": self.connected, "ready": ready, "busy": self.busy,
            "status": "online" if ready else "waiting" if self.connected and not measured
                      else "stale" if self.connected else "offline",
            "last_report_at": self.last_report_at,
            "power_w": round(sum(outlet["power_w"] for outlet in self.outlets.values()), 3) if measured else None,
            "energy_kwh": round(sum(outlet["energy_kwh"] for outlet in self.outlets.values()), 3) if measured else None,
            "voltage_v": self.voltage_v, "rssi_dbm": self.rssi_dbm,
            "outlets": [dict(outlet) for outlet in self.outlets.values()],
        }

    async def send(self, command):
        if not self.connected or self.writer.is_closing():
            raise CommandError("The strip disconnected. Wait for it to reconnect.", 503)
        self.writer.write((command + "\r\n").encode("ascii"))
        await self.writer.drain()

    def receive(self, line):
        records = parse_info(line)
        if records:
            for record in records:
                number = record["number"]
                self.outlets[number] = record
                self.updated[number] = time.monotonic()
                self.versions[number] += 1
            self.last_report_at = time.time()
            self.changed.set()
        elif EVENT.fullmatch(line):
            # Events trigger an immediate poll, but do not replace a full report.
            return "poll"
        elif match := VOLTAGE.fullmatch(line):
            millivolts = int(match.group(1))
            if 50000 <= millivolts <= 300000:
                self.voltage_v = millivolts / 1000
        elif match := RSSI.fullmatch(line):
            self.rssi_dbm = int(match.group(1))
        return None

    async def set_power(self, number, on):
        if self.busy:
            raise CommandError("Another command is pending. Wait for its result.", 409)
        if not self.ready:
            raise CommandError("The strip is offline or its readings are stale. Wait for fresh readings.", 503)
        self.busy = True
        channels = list(self.outlets) if number == 0 else [number]
        try:
            async with self.command_lock:
                for channel in channels:
                    await self.send(f"up:onoff:{channel}:{'on' if on else 'off'}")
                # Allow relays to settle; only later reports can confirm this operation.
                await asyncio.sleep(0.2)
                baseline = dict(self.versions)
                await self.send("up:getinfo:all")
                await self.wait_for_confirmation(channels, on, baseline)
        except (ConnectionError, OSError):
            raise CommandError("Connection lost before confirmation. Check the strip's state after reconnecting.", 503) from None
        finally:
            self.busy = False
        return self.snapshot()

    async def wait_for_confirmation(self, channels, on, baseline):
        deadline = time.monotonic() + COMMAND_TIMEOUT
        while True:
            self.changed.clear()
            if not self.connected:
                raise CommandError("The strip disconnected before confirming. Check its state after reconnecting.", 503)
            if all(self.versions[channel] > baseline[channel] and
                   self.outlets[channel]["on"] == on for channel in channels):
                return
            remaining = max(0, deadline - time.monotonic())
            try:
                await asyncio.wait_for(self.changed.wait(), remaining)
            except asyncio.TimeoutError:
                raise CommandError("The strip did not confirm the requested state. Check the outlets before trying again.") from None

    async def poll(self):
        counter = 0
        while self.connected:
            if not self.busy:
                async with self.command_lock:
                    await self.send("up:getinfo:all")
                    if counter % 3 == 0:
                        await self.send("up:power_report:1:vol")
                        await self.send("up:query:wifirssi")
                    counter += 1
            await asyncio.sleep(5)


class Controller:
    def __init__(self, server_ip, web_port=8080):
        self.server_ip, self.web_port = server_ip, web_port
        self.sessions = {}
        self.connections = set()
        self.tasks = set()
        self.device_server = self.web_server = None

    async def start(self, bind="0.0.0.0", device_port=DEVICE_PORT):
        self.device_server = await asyncio.start_server(self.handle_device, bind, device_port, limit=8192)
        try:
            self.web_server = await asyncio.start_server(self.handle_http, bind, self.web_port, limit=8192)
        except (OSError, asyncio.CancelledError):
            self.device_server.close()
            await self.device_server.wait_closed()
            raise
        self.web_port = self.web_server.sockets[0].getsockname()[1]

    async def close(self):
        for server in (self.device_server, self.web_server):
            if server:
                server.close()
                await server.wait_closed()
        for writer in list(self.connections):
            writer.close()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def handle_device(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.connections.add(writer)
        session, poll_task = None, None
        try:
            while True:
                raw = await asyncio.wait_for(reader.readline(), 30)
                if not raw:
                    break
                line = raw.replace(b"\x00", b"").decode("ascii", "replace").strip()
                if not session:
                    identity = BOOT.fullmatch(line)
                    if not identity:
                        continue
                    session = self.register_session(reader, writer, identity)
                    poll_task = asyncio.create_task(session.poll())
                    # A failed writer must also release the reader/session.
                    poll_task.add_done_callback(lambda _: writer.close())
                elif session.receive(line) == "poll" and not session.busy:
                    await session.send("up:getinfo:all")
        except (OSError, ValueError, asyncio.TimeoutError, CommandError):
            LOG.info("Strip connection closed or timed out")
        finally:
            if session:
                session.connected = False
                session.changed.set()
            if poll_task:
                poll_task.cancel()
                await asyncio.gather(poll_task, return_exceptions=True)
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
            self.connections.discard(writer)
            self.tasks.discard(task)

    def register_session(self, reader, writer, identity):
        session = Session(reader, writer, identity)
        previous = self.sessions.get(session.mac)
        if previous:
            previous.writer.close()
            previous.connected = False
            previous.changed.set()
        self.sessions[session.mac] = session
        LOG.info("Strip %s connected; firmware %s", session.mac, session.firmware)
        return session

    def snapshot(self):
        return {"server_ip": self.server_ip, "web_port": self.web_port,
                "device_port": DEVICE_PORT, "devices": [session.snapshot() for session in self.sessions.values()]}

    async def route(self, request):
        if request.method == "GET" and request.path == "/api/state":
            return 200, "application/json", json.dumps(self.snapshot()).encode()
        if request.method == "GET" and request.path in ASSETS:
            file, content_type = ASSETS[request.path]
            return 200, content_type, file.read_bytes()
        if request.method != "POST" or request.path != "/api/power":
            raise CommandError("Not found.", 404)
        command = parse_power_request(request)
        session = self.sessions.get(command["device_id"].upper())
        if not session:
            raise CommandError("This strip is not connected.", 503)
        device = await session.set_power(command["outlet"], command["on"])
        return 200, "application/json", json.dumps({"confirmed": True, "device": device}).encode()

    async def response_for(self, reader):
        try:
            return await self.route(await read_request(reader))
        except (CommandError, RequestError) as error:
            return error.status, "application/json", json.dumps({"error": str(error)}).encode()
        except (ValueError, UnicodeDecodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            return 400, "application/json", b'{"error":"Malformed HTTP request."}'
        except asyncio.TimeoutError:
            return 408, "application/json", b'{"error":"Request timed out."}'
        except OSError:
            LOG.exception("HTTP I/O failed")
            return 500, "application/json", b'{"error":"Server error. Check the server terminal."}'

    async def handle_http(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.connections.add(writer)
        try:
            await send_response(writer, await self.response_for(reader))
        except OSError:
            LOG.debug("Browser connection closed before response completed")
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
            self.connections.discard(writer)
            self.tasks.discard(task)


def parse_power_request(request):
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin != "http://" + request.headers.get("host", "")):
        raise CommandError("Open the controls directly from your home server.", 403)
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise CommandError("Expected a JSON request.", 415)
    try:
        command = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise CommandError("Invalid JSON.", 400) from None
    if (not isinstance(command, dict) or not isinstance(command.get("device_id"), str)
            or type(command.get("outlet")) is not int or command["outlet"] not in range(5)
            or type(command.get("on")) is not bool):
        raise CommandError("Choose outlet 0–4 and an on/off boolean.", 400)
    return command


def detect_ip():
    # Select the default LAN interface without transmitting any data.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


async def serve(args):
    controller = Controller(args.server_ip or detect_ip(), args.web_port)
    try:
        await controller.start(args.bind)
        LOG.info("Browser controls: http://%s:%s", controller.server_ip, controller.web_port)
        LOG.info("Strip listener: TCP %s. Pair using this server's LAN IPv4 address.", DEVICE_PORT)
        await asyncio.Future()
    finally:
        await controller.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-ip", type=ipaddress.IPv4Address, help="LAN IP displayed in pairing instructions")
    parser.add_argument("--web-port", type=int, default=8080)
    parser.add_argument("--bind", default="0.0.0.0", help="listener address (default: all IPv4 interfaces)")
    args = parser.parse_args()
    if not 1 <= args.web_port <= 65535 or args.web_port == DEVICE_PORT:
        parser.error("--web-port must be 1–65535 and different from 10086")
    if args.server_ip:
        args.server_ip = str(args.server_ip)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        return 0
    except OSError as error:
        LOG.error("Could not start: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
