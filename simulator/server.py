"""Serve the local simulator. Run python3 simulator/server.py, then open its URL."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from model import Simulator, STEP

ROOT = Path(__file__).resolve().parent


class SimulatorServer(HTTPServer):
    def __init__(self, address):
        super().__init__(address, Handler)
        self.model = Simulator()
        self.updated_at = time.monotonic()
        self.accumulator = 0.0

    def advance(self):
        now = time.monotonic()
        elapsed = now - self.updated_at
        self.updated_at = now
        if elapsed > .5:
            self.model.interrupt()
            self.accumulator = 0
            return
        self.accumulator += elapsed
        ticks = int(self.accumulator / STEP)
        self.accumulator -= ticks * STEP
        self.model.advance(ticks * STEP)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def valid_origin(self):
        host = f"127.0.0.1:{self.server.server_port}"
        return (self.headers.get("Host") == host
                and self.headers.get("Origin", f"http://{host}") == f"http://{host}")

    def do_GET(self):
        if not self.valid_origin():
            self.respond(403, b"Use the printed loopback URL.", "text/plain")
            return
        path = urlsplit(self.path).path
        if path == "/":
            self.respond(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/state":
            self.server.advance()
            self.respond(200, json.dumps(self.server.model.state()).encode(), "application/json")
        else:
            self.respond(404, b"Not found", "text/plain")

    def do_POST(self):
        if not self.valid_origin() or self.path != "/api/command":
            self.respond(403, b"Invalid request.", "text/plain")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096 or self.headers.get("Content-Type") != "application/json":
                raise ValueError("Expected a small JSON command.")
            request = json.loads(self.rfile.read(size))
            self.server.advance()
            self.server.model.command(request["action"], request.get("payload", {}))
            self.respond(200, json.dumps(self.server.model.state()).encode(), "application/json")
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            self.respond(400, json.dumps({"error": str(error)}).encode(), "application/json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        server = SimulatorServer(("127.0.0.1", args.port))
    except OSError as error:
        parser.exit(1, f"Could not start simulator. {error}\nTry --port 8766.\n")
    print(f"Head mouse simulator → http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSimulator stopped.")
    finally:
        server.server_close()
