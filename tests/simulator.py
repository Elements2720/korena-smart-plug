"""Test-only stock-protocol simulator; never used by the production server."""

import argparse
import asyncio
import contextlib

MAC = "AABBC935CA80"


def outlet_frame(number, on):
    return (f"{number}:120;{'on' if on else 'off'};0;0;0;{5300 if on else 0};"
            "0000000A;00000000;00000000;0;00;31")


class SimulatedStrip:
    def __init__(self):
        self.on = {2}
        self.ignore_outlet = None
        self.reply = True
        self.command_seen = asyncio.Event()
        self.reader = self.writer = self.task = None

    async def connect(self, port):
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", port)
        # Fragmentation and NUL padding occur at the device's network boundary.
        self.writer.write(b"\x00up:bootinfo:lgutap;AABBC935CA80;")
        await self.writer.drain()
        self.writer.write(b"001122334455;0.1.54-1.0.66;connect\r\n\x00")
        await self.writer.drain()
        self.task = asyncio.create_task(self.listen())

    async def listen(self):
        while raw := await self.reader.readline():
            command = raw.decode().strip()
            if command == "up:getinfo:all" and self.reply:
                for number in range(1, 5):
                    self.writer.write(f"up:getinfo:{outlet_frame(number, number in self.on)}\x00\r\n".encode())
            elif command.startswith("up:onoff:"):
                _, _, number, state = command.split(":")
                number = int(number)
                self.command_seen.set()
                if number != self.ignore_outlet:
                    (self.on.add if state == "on" else self.on.discard)(number)
                self.writer.write(f"{command}\r\n".encode())
            elif command == "up:power_report:1:vol":
                self.writer.write(b"up:power_report:1:224500\r\n")
            elif command == "up:query:wifirssi":
                self.writer.write(b"up:query:-52\r\n")
            await self.writer.drain()

    async def close(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, OSError):
                await self.task
        if self.writer:
            self.writer.close()
            with contextlib.suppress(OSError):
                await self.writer.wait_closed()


async def main(args):
    strip = SimulatedStrip()
    strip.ignore_outlet = args.ignore_outlet
    await strip.connect(args.port)
    print("SIMULATED strip connected; not physical hardware", flush=True)
    try:
        await strip.task
    finally:
        await strip.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=10086)
    parser.add_argument("--ignore-outlet", type=int, choices=range(1, 5))
    try:
        asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt:
        pass
