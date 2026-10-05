import asyncio
import contextlib
import io
import json
import unittest
from unittest.mock import patch

import provision
from protocol import parse_info
from server import Controller
from tests.simulator import MAC, SimulatedStrip, outlet_frame


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.controller = Controller("192.168.1.50", 0)
        await self.controller.start("127.0.0.1", 0)
        self.device_port = self.controller.device_server.sockets[0].getsockname()[1]
        self.strip = SimulatedStrip()

    async def asyncTearDown(self):
        await self.strip.close()
        await self.controller.close()

    async def http(self, path, payload=None, extra_headers=""):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.controller.web_port)
        body = json.dumps(payload).encode() if payload is not None else b""
        method = "POST" if payload is not None else "GET"
        headers = (f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.controller.web_port}\r\n"
                   f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n{extra_headers}\r\n")
        writer.write(headers.encode() + body)
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), 10)
        writer.close()
        await writer.wait_closed()
        head, body = response.split(b"\r\n\r\n", 1)
        return int(head.split()[1]), body

    async def connect_strip(self):
        await self.strip.connect(self.device_port)
        async with asyncio.timeout(2):
            while True:
                _, body = await self.http("/api/state")
                snapshot = json.loads(body)
                if snapshot["devices"] and snapshot["devices"][0]["ready"]:
                    return snapshot["devices"][0]
                await asyncio.sleep(.01)

    def command(self, outlet, on):
        return {"device_id": MAC, "outlet": outlet, "on": on}

    async def test_unpaired_server_serves_setup_and_no_invented_readings(self):
        status, body = await self.http("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["devices"], [])
        for path, marker in (("/", b"Let's connect your strip"), ("/provision.py", b"getpass")):
            with self.subTest(path=path):
                status, body = await self.http(path)
                self.assertEqual(status, 200)
                self.assertIn(marker, body)

    async def test_individual_reports_confirm_single_and_all_outlet_commands(self):
        device = await self.connect_strip()
        self.assertEqual([outlet["on"] for outlet in device["outlets"]], [False, True, False, False])
        self.assertEqual(device["power_w"], 5.3)
        self.assertEqual(device["energy_kwh"], .04)
        self.assertEqual(device["voltage_v"], 224.5)
        self.assertEqual(device["rssi_dbm"], -52)
        for outlet, on, expected in ((2, False, set()), (0, True, {1, 2, 3, 4}), (0, False, set())):
            with self.subTest(outlet=outlet, on=on):
                status, body = await self.http("/api/power", self.command(outlet, on))
                response = json.loads(body)
                self.assertEqual(status, 200, response)
                self.assertTrue(response["confirmed"])
                self.assertFalse(response["device"]["busy"])
                self.assertEqual({record["number"] for record in response["device"]["outlets"] if record["on"]}, expected)
                self.assertEqual(self.strip.on, expected)

    async def test_acknowledged_but_unchanged_relay_is_not_reported_as_success(self):
        await self.connect_strip()
        self.strip.ignore_outlet = 3
        status, body = await self.http("/api/power", self.command(0, True))
        self.assertEqual(status, 502)
        self.assertIn("did not confirm", json.loads(body)["error"])
        _, body = await self.http("/api/state")
        self.assertFalse(json.loads(body)["devices"][0]["outlets"][2]["on"])

    async def test_duplicate_command_is_rejected_while_confirmation_is_pending(self):
        await self.connect_strip()
        first = asyncio.create_task(self.http("/api/power", self.command(1, True)))
        await asyncio.wait_for(self.strip.command_seen.wait(), 1)
        status, _ = await self.http("/api/power", self.command(2, False))
        self.assertEqual(status, 409)
        self.assertEqual((await first)[0], 200)
        self.assertIn(2, self.strip.on)

    async def test_disconnect_and_reconnect_restore_controls_from_fresh_reports(self):
        await self.connect_strip()
        await self.strip.close()
        await asyncio.sleep(.03)
        status, _ = await self.http("/api/power", self.command(1, True))
        self.assertEqual(status, 503)
        self.strip = SimulatedStrip()
        device = await self.connect_strip()
        self.assertTrue(device["ready"])
        _, body = await self.http("/api/state")
        self.assertEqual(len(json.loads(body)["devices"]), 1)

    async def test_expired_readings_pause_commands_even_if_tcp_remains_connected(self):
        await self.connect_strip()
        self.strip.reply = False
        # Speed up only the freshness policy; socket I/O and state flow stay real.
        with patch("server.STALE_SECONDS", .05):
            await asyncio.sleep(.08)
            _, body = await self.http("/api/state")
            self.assertEqual(json.loads(body)["devices"][0]["status"], "stale")
            status, _ = await self.http("/api/power", self.command(1, True))
            self.assertEqual(status, 503)
        self.assertNotIn(1, self.strip.on)

    async def test_malformed_or_cross_site_commands_never_reach_the_strip(self):
        await self.connect_strip()
        invalid_payloads = [self.command(5, True), self.command(True, True), self.command(1, "false"), [], {}]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                status, _ = await self.http("/api/power", payload)
                self.assertEqual(status, 400)
        status, _ = await self.http("/api/power", self.command(1, True), "Origin: http://other.example\r\n")
        self.assertEqual(status, 403)
        self.assertEqual(self.strip.on, {2})


class ProtocolTests(unittest.TestCase):
    def test_combined_outlet_frame_preserves_channels_and_units(self):
        line = "up:getinfo:" + ":".join(outlet_frame(number, number == 4) for number in range(1, 5))
        records = parse_info(line)
        self.assertEqual([record["number"] for record in records], [1, 2, 3, 4])
        self.assertEqual(records[3]["power_w"], 5.3)
        self.assertTrue(records[3]["on"])
        self.assertEqual(records[3]["energy_kwh"], .01)


class ProvisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_pairing_sends_server_address_before_wifi_and_hides_credentials(self):
        commands = []

        async def setup_device(reader, writer):
            command = (await reader.readline()).decode().strip()
            commands.append(command)
            reply = "up:ip:ip_ok" if command.startswith("up:ip:") else "up:connect:connect_ok"
            writer.write((reply + "\x00\r\n").encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(setup_device, "127.0.0.1", 0)
        try:
            output = io.StringIO()
            with patch("provision.SETUP_PORT", server.sockets[0].getsockname()[1]), contextlib.redirect_stdout(output):
                await asyncio.to_thread(provision.pair, "127.0.0.1", "192.168.1.50", "Home WiFi", "test-secret")
            self.assertEqual(commands, ["up:ip:192.168.1.50", "up:connect:Home WiFi:test-secret"])
            self.assertNotIn("test-secret", output.getvalue())
        finally:
            server.close()
            await server.wait_closed()

    async def test_protocol_delimiters_and_non_lan_addresses_are_rejected_before_network_io(self):
        for address, ssid, password in (("127.0.0.1", "Home", "secret"), ("8.8.8.8", "Home", "secret"),
                                        ("192.168.1.50", "Home:WiFi", "secret"), ("192.168.1.50", "Home", "secret\n")):
            with self.subTest(address=address, ssid=ssid), self.assertRaises(ValueError):
                provision.pair("127.0.0.1", address, ssid, password)


if __name__ == "__main__":
    unittest.main()
