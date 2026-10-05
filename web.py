"""Bounded, connection-close HTTP transport for the home-network controller."""

import asyncio
from dataclasses import dataclass
from http import HTTPStatus
from urllib.parse import urlsplit

MAX_BODY = 4096


class RequestError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass
class Request:
    method: str
    path: str
    headers: dict
    body: bytes


def parse_headers(lines):
    headers = {}
    for line in lines:
        if not line:
            continue
        key, separator, header_value = line.partition(":")
        key = key.lower()
        if not separator or key in headers or key.strip() != key:
            raise RequestError("Malformed headers.")
        headers[key] = header_value.strip()
    if "transfer-encoding" in headers:
        raise RequestError("Chunked requests are not supported.")
    return headers


async def read_request(reader):
    raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
    lines = raw.decode("ascii").split("\r\n")
    method, target, version = lines[0].split()
    if version not in ("HTTP/1.0", "HTTP/1.1") or not target.startswith("/"):
        raise RequestError("Malformed request.")
    headers = parse_headers(lines[1:])
    length = int(headers.get("content-length", "0"))
    if length < 0:
        raise RequestError("Invalid body length.")
    if length > MAX_BODY:
        raise RequestError("Request is too large.", 413)
    body = await asyncio.wait_for(reader.readexactly(length), 5)
    return Request(method, urlsplit(target).path, headers, body)


async def send_response(writer, response):
    status, content_type, body = response
    head = (f"HTTP/1.1 {status} {HTTPStatus(status).phrase}\r\nContent-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\nCache-Control: no-store\r\n"
            "X-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\n"
            "Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'\r\n\r\n")
    writer.write(head.encode("ascii") + body)
    await writer.drain()
