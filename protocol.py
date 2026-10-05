"""MTTL-W01 text protocol, based on the public powerk protocol reference."""

import re

DEVICE_PORT = 10086
SETUP_PORT = 30300
BOOT = re.compile(
    r"^up:bootinfo:([^;]+);([0-9a-f]{12});([0-9a-f]{12});([^;]+);connect$",
    re.IGNORECASE,
)
INFO = re.compile(
    r"(?:^|:)([1-4]):(-?\d+);(on|off);(-?\d+);([^;:]+);([^;:]+);"
    r"(-?\d+);([0-9a-f]{8});([0-9a-f]{8});([0-9a-f]{8});"
    r"([^;:]+);([0-9a-f]{2});(-?\d+)(?=:|$)", re.IGNORECASE,
)
EVENT = re.compile(r"^up:event:onoff:([0-4]):(on|off)$", re.IGNORECASE)
VOLTAGE = re.compile(r"^up:power_report:[1-5]:(\d+)$", re.IGNORECASE)
RSSI = re.compile(r"^up:query:(-?\d+)$", re.IGNORECASE)


def parse_info(line):
    """Accept individual outlet reports as well as combined getinfo frames."""
    if not line.lower().startswith("up:getinfo:"):
        return []
    records = []
    for match in INFO.finditer(line[len("up:getinfo:"):]):
        values = match.groups()
        records.append({
            "number": int(values[0]),
            "on": values[2].lower() == "on",
            "power_w": round(int(values[6]) / 1000, 3),
            "energy_kwh": int(values[7], 16) / 1000,
            "temperature_c": int(values[12]),
        })
    return records
