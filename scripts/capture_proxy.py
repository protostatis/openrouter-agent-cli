#!/usr/bin/env python3
"""Capture proxy: logs the FULL raw request/response bodies of every model
call, then forwards to an upstream proxy.

Sits in front of the sky-proxy (or any OpenAI-compatible upstream) so we can
inspect exactly what each harness sends into the model's context: system
prompts, messages, tool schemas, and the raw model responses.

Usage:
    uv run python scripts/capture_proxy.py \
        [--listen 8789] [--upstream http://localhost:8788] [--log /tmp/capture.jsonl]

Each captured call is one JSON object per line in the log file:
{ts, method, path, request_body, response_status, response_body}
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _decode_response(headers, raw: bytes) -> tuple:
    """Return (loggable_body, usage_or_None). Handles gzip and SSE streams."""
    encoding = (headers.get("Content-Encoding") or "").lower()
    data = gzip.decompress(raw) if "gzip" in encoding else raw
    usage = None
    try:
        return json.loads(data), None
    except Exception:
        pass
    text = data.decode("utf-8", "replace")
    if "data:" in text[:4000] and "usage" in text:
        # SSE stream: usage lives in the final chunk.
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload == "[DONE]":
                    continue
                try:
                    chunk = json.loads(payload)
                except Exception:
                    continue
                if isinstance(chunk, dict) and chunk.get("usage"):
                    usage = chunk["usage"]
    if text.startswith("\x1f") or any(ord(c) < 8 for c in text[:32]):
        return base64.b64encode(data).decode("ascii"), usage  # binary fallback
    return text, usage


class Handler(BaseHTTPRequestHandler):
    upstream: str = "http://localhost:8788"
    log_path: str = "/tmp/capture.jsonl"

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        entry: dict = {
            "ts": ts,
            "method": self.command,
            "path": self.path,
            "request_body": None,
            "response_status": None,
            "response_body": None,
        }
        try:
            if body:
                entry["request_body"] = json.loads(body)
        except Exception:
            entry["request_body"] = body.decode("utf-8", "replace")

        url = self.upstream.rstrip("/") + self.path
        req = urllib.request.Request(
            url, data=body if body else None, method=self.command
        )
        for name, value in self.headers.items():
            if name.lower() not in ("host", "content-length", "connection"):
                req.add_header(name, value)
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                resp_body = resp.read()
                entry["response_status"] = resp.status
                decoded, usage = _decode_response(resp.headers, resp_body)
                entry["response_body"] = decoded
                if usage:
                    entry["usage"] = usage
                self.send_response(resp.status)
                for name, value in resp.headers.items():
                    if name.lower() not in ("transfer-encoding", "connection", "content-length"):
                        self.send_header(name, value)
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as exc:
            resp_body = exc.read()
            entry["response_status"] = exc.code
            decoded, usage = _decode_response(exc.headers, resp_body)
            entry["response_body"] = decoded
            if usage:
                entry["usage"] = usage
            self.send_response(exc.code)
            self.send_header("Content-Length", str(len(resp_body)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(resp_body)
        except Exception as exc:
            entry["response_status"] = "ERR"
            entry["response_body"] = f"{type(exc).__name__}: {exc}"
            payload = json.dumps({"error": str(exc)}).encode()
            self.send_response(502)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
        finally:
            try:
                with open(self.log_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass

    do_POST = _handle
    do_GET = _handle

    def log_message(self, *args):  # silence request logging
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--listen", default=8789, type=int)
    ap.add_argument("--upstream", default="http://localhost:8788")
    ap.add_argument("--log", default="/tmp/capture.jsonl")
    args = ap.parse_args()
    Handler.upstream = args.upstream
    Handler.log_path = args.log
    server = ThreadingHTTPServer(("127.0.0.1", args.listen), Handler)
    print(f"capture proxy on :{args.listen} -> {args.upstream} -> {args.log}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())