import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class Embeddings(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/openapi.json":
            result = {}
        elif url.path == "/embedding/video":
            result = [0.0, 1.0] + [0.0] * 766
        elif url.path == "/embedding/text":
            text = parse_qs(url.query).get("text", [""])[0]
            result = ([1.0, 0.0] if text == "forest" else [0.0, 1.0]) + [0.0] * 766
        else:
            self.send_error(404)
            return
        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("", 4001), Embeddings).serve_forever()
