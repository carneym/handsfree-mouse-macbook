"""Optional, isolated flight game. No calibration imports or device access."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import urlsplit
import webbrowser

ROOT = Path(__file__).resolve().parent / "game"
FILES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/game.js": ("game.js", "text/javascript; charset=utf-8"),
         "/flight.mjs": ("flight.mjs", "text/javascript; charset=utf-8"),
         "/style.css": ("style.css", "text/css; charset=utf-8"),
         "/favicon.svg": ("favicon.svg", "image/svg+xml")}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected:
            self.send_error(403, "Use the printed local URL")
            return
        resource = FILES.get(urlsplit(self.path).path)
        if resource is None:
            self.send_error(404)
            return
        filename, kind = resource
        data = (ROOT / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--open", action="store_true", help="Open the game in your default browser")
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as error:
        raise SystemExit(f"Could not start flight lab: {error}. Try --port 8767.")
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Neon Drift flight lab: {url}\nStop with Ctrl+C. This is separate from Head Mouse.", flush=True)
    if args.open:
        threading.Timer(.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
