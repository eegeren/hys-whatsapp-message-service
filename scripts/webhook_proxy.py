"""Expose only the FastAPI webhook path to a local HTTPS tunnel."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

BACKEND = 'http://127.0.0.1:3000'
MAX_BODY = 2 * 1024 * 1024

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        # Never log query strings: Meta GET verification carries Verify Token.
        return

    def respond(self, status, payload=b'', content_type='text/plain; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path != '/api/webhook' or len(parsed.query) > 4096:
            return self.respond(404, b'Not Found')
        self.forward('GET', self.path)

    def do_POST(self):
        parsed = urlsplit(self.path)
        if parsed.path != '/api/webhook' or parsed.query:
            return self.respond(404, b'Not Found')
        length = self.headers.get('Content-Length', '')
        if not length.isdigit() or int(length) > MAX_BODY:
            return self.respond(413, b'Request too large')
        body = self.rfile.read(int(length))
        if len(body) != int(length):
            return self.respond(400, b'Invalid request')
        self.forward('POST', self.path, body)

    def do_HEAD(self):
        self.respond(404, b'Not Found')

    def do_PUT(self):
        self.respond(404, b'Not Found')

    def do_DELETE(self):
        self.respond(404, b'Not Found')

    def do_PATCH(self):
        self.respond(404, b'Not Found')

    def do_OPTIONS(self):
        self.respond(404, b'Not Found')

    def forward(self, method, path, body=None):
        headers = {}
        for name in ('X-Hub-Signature-256', 'Content-Type'):
            value = self.headers.get(name)
            if value:
                headers[name] = value
        req = Request(BACKEND + path, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=15) as result:
                payload = result.read(MAX_BODY + 1)
                if len(payload) > MAX_BODY:
                    return self.respond(502, b'Invalid upstream response')
                self.respond(result.status, payload, result.headers.get('Content-Type', 'text/plain; charset=utf-8'))
        except HTTPError as error:
            payload = error.read(MAX_BODY + 1)
            if len(payload) > MAX_BODY:
                return self.respond(502, b'Invalid upstream response')
            self.respond(error.code, payload, error.headers.get('Content-Type', 'text/plain; charset=utf-8'))
        except (URLError, TimeoutError, OSError):
            self.respond(502, b'Webhook backend unavailable')

if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 3080), Handler).serve_forever()
