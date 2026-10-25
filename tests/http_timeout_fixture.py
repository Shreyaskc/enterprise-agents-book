# SPDX-License-Identifier: MIT
"""Finite loopback HTTP double; never a model or external server. Run only explicitly."""
import http.server, json, socket, threading, time, urllib.request
import sys
import socketserver
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from unittest.mock import patch
from northstar_agents.adapters import _http

class Fixture(http.server.BaseHTTPRequestHandler):
    mode = 'none'

    def log_message(self, *_):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        if self.mode in {'none', 'headers'}:
            time.sleep(0.15)
        if self.mode == 'none':
            return
        payload = b'{}'
        if self.mode == 'drip':
            payload = b'{"padding":"' + b'x' * 8 + b'"}'
        try:
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            for byte in payload:
                self.wfile.write(bytes([byte]))
                self.wfile.flush()
                if self.mode == 'drip':
                    time.sleep(0.02)
        except (BrokenPipeError, ConnectionResetError):
            pass

class LocalServer(http.server.HTTPServer):

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name = '127.0.0.1'
        self.server_port = self.server_address[1]
results = []
for mode in ['none', 'headers', 'drip']:
    Fixture.mode = mode
    with LocalServer(('127.0.0.1', 0), Fixture) as server:
        server.timeout = 0.5
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        port = server.server_port
        original = urllib.request.OpenerDirector.open

        def finite_open(self, request, timeout=30):
            request.full_url = f'http://127.0.0.1:{port}/api/chat'
            return original(self, request, timeout=0.05)
        start = time.monotonic()
        error = None
        try:
            with patch.object(urllib.request.OpenerDirector, 'open', finite_open):
                _http({})
        except Exception as exc:
            error = type(exc).__name__
        elapsed = time.monotonic() - start
        thread.join(timeout=2)
        results.append({'case': mode, 'socket_inactivity_timeout_seconds': 0.05, 'observed_elapsed_seconds': elapsed, 'error_type': error, 'fixture_thread_stopped': not thread.is_alive()})
print(json.dumps({'kind': 'finite_loopback_http_double_not_model_inference', 'results': results, 'server_cancellation_claimed': False}))
