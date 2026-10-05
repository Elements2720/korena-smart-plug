#!/usr/bin/env python3
"""Pair an MTTL-W01 from a Windows or Linux computer on its setup Wi-Fi."""

import argparse
import getpass
import ipaddress
import socket
import sys

SETUP_HOST = "192.168.1.1"
SETUP_PORT = 30300


def validate_wifi(ssid, password):
    if not ssid or len(ssid.encode("utf-8")) > 32:
        raise ValueError("Wi-Fi name must be 1–32 UTF-8 bytes.")
    if any(char in ssid + password for char in ":\r\n\x00"):
        raise ValueError("This strip's setup protocol cannot carry colons, newlines, or NUL characters in Wi-Fi credentials.")


def exchange(host, command, expected):
    with socket.create_connection((host, SETUP_PORT), timeout=8) as connection:
        connection.settimeout(8)
        connection.sendall((command + "\r\n").encode("utf-8"))
        response = bytearray()
        while len(response) < 4096:
            chunk = connection.recv(512)
            if not chunk:
                break
            response.extend(chunk)
            clean = bytes(response).replace(b"\x00", b"")
            if b"\n" in clean:
                break
        text = bytes(response).replace(b"\x00", b"").decode("utf-8", "replace").strip()
        if text != expected:
            # Do not echo replies: firmware may include the submitted credentials.
            raise RuntimeError("The strip did not acknowledge the setup command. Check setup mode and try again.")


def pair(host, server_ip, ssid, password):
    address = ipaddress.IPv4Address(server_ip)
    if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local or not address.is_private:
        raise ValueError("Use the Linux server's home-network IPv4 address (for example 192.168.1.50).")
    validate_wifi(ssid, password)
    exchange(host, f"up:ip:{address}", "up:ip:ip_ok")
    print("Server address acknowledged.")
    exchange(host, f"up:connect:{ssid}:{password}", "up:connect:connect_ok")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-ip", required=True, help="Linux server's IP on your home network, not this PC's IP")
    parser.add_argument("--ssid", help="2.4 GHz home Wi-Fi name; prompted if omitted")
    parser.add_argument("--host", default=SETUP_HOST, help="strip setup address (default: 192.168.1.1)")
    args = parser.parse_args()
    print("Join TONLY_TAP_935CA80 first (reported password: LGU_935CA80).")
    print("No internet on that network is normal. Keep the Linux server on your home network.")
    try:
        ssid = args.ssid if args.ssid is not None else input("Home Wi-Fi name (2.4 GHz): ")
        password = getpass.getpass("Home Wi-Fi password (hidden): ")
        pair(args.host, args.server_ip, ssid, password)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.", file=sys.stderr)
        return 1
    print("Wi-Fi settings acknowledged. Reconnect this PC to your home network.")
    print(f"Watch the Linux server at {args.server_ip} for a device connection, then return to its browser controls.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
