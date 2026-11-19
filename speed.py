#!/usr/bin/env python3
"""Measure full HTTP download time with ten sequential requests."""

import argparse
from dataclasses import dataclass
import math
from http.client import HTTPException
import sys
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


REQUEST_COUNT = 10
CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class Result:
    requests: int
    total_bytes: int
    total_seconds: float

    @property
    def average_seconds(self):
        return self.total_seconds / self.requests

    @property
    def bytes_per_second(self):
        return self.total_bytes / self.total_seconds


def http_url(value):
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname
        if not valid or parsed.username or parsed.password:
            raise ValueError
        parsed.port  # Validate the port, if present.
    except ValueError:
        raise argparse.ArgumentTypeError("use an HTTP(S) URL without credentials") from None
    return value


def positive_seconds(value):
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("timeout must be a positive finite number") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("timeout must be a positive finite number")
    return seconds


def measure(url, timeout=30.0):
    total_bytes = 0
    total_seconds = 0.0
    for _ in range(REQUEST_COUNT):
        request = Request(url, headers={
            "User-Agent": "download-speed/1.0",
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
        })
        started = perf_counter()
        downloaded = 0
        with urlopen(request, timeout=timeout) as response:
            while chunk := response.read(CHUNK_SIZE):
                downloaded += len(chunk)
            declared_length = response.headers.get("Content-Length")
            if declared_length is not None and downloaded != int(declared_length):
                raise OSError("incomplete response: received byte count differs from Content-Length")
        total_seconds += perf_counter() - started
        total_bytes += downloaded
    return Result(REQUEST_COUNT, total_bytes, total_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", type=http_url, help="HTTP(S) address of a downloadable file")
    parser.add_argument("--timeout", type=positive_seconds, default=30.0,
                        help="socket timeout in seconds (default: 30)")
    args = parser.parse_args()
    try:
        result = measure(args.url, args.timeout)
    except (HTTPError, URLError, HTTPException, OSError, ValueError) as error:
        print(f"Download failed: {error}", file=sys.stderr)
        return 1

    print(f"Requests: {result.requests} (sequential)")
    print(f"Downloaded: {result.total_bytes} bytes")
    print(f"Total request time: {result.total_seconds:.6f} s")
    print(f"Average request time: {result.average_seconds:.6f} s")
    print(f"Download speed: {result.bytes_per_second / 1024**2:.3f} MiB/s "
          f"({result.bytes_per_second * 8 / 1_000_000:.3f} Mbit/s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
