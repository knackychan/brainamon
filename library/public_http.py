"""Public-only connections, including DNS pinning, for previews and downloader proxying."""
import http.client
import ipaddress
import select
import socket
import threading
import tempfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from core.urls import http_url


class SecurityRefusal(ValueError):
    pass


def addresses(host, port):
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not infos:
        raise SecurityRefusal('No public destination.')
    for _, _, _, _, address in infos:
        ip = ipaddress.ip_address(address[0].split('%')[0])
        ip = ip.ipv4_mapped if ip.version == 6 and ip.ipv4_mapped else ip
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise SecurityRefusal('Private network destinations are refused.')
    return infos


def connect(address, timeout=10, source_address=None, **kwargs):
    last = None
    for family, kind, proto, _, target in addresses(*address):
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(target)  # numeric address from the validation above, no second lookup
            return sock
        except OSError as exc:
            sock.close()
            last = exc
    raise last or OSError('Destination unavailable.')


class HTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = connect


class HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = connect  # HTTPSConnection retains original TLS hostname verification


class _Proxy(BaseHTTPRequestHandler):
    timeout = 10
    def log_message(self, *args):
        pass

    def do_CONNECT(self):
        try:
            u = urlsplit('https://' + self.path)
            if not u.hostname or u.path or u.query or u.fragment or u.username or u.password:
                raise SecurityRefusal('Invalid tunnel destination.')
            with connect((u.hostname, u.port or 443)) as upstream:
                self.send_response(200)
                self.end_headers()
                while not self.server.stopping.is_set():
                    ready, _, _ = select.select([self.connection, upstream], [], [], .1)
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        (upstream if source is self.connection else self.connection).sendall(data)
        except (OSError, ValueError):
            self.close_connection = True

    def do_GET(self):
        conn = None
        try:
            if not http_url(self.path) or self.headers.get('Transfer-Encoding') or self.headers.get('Content-Length'):
                raise SecurityRefusal('Invalid proxy request.')
            u = urlsplit(self.path)
            if u.scheme != 'http':
                raise SecurityRefusal('Use CONNECT for TLS.')
            conn = HTTPConnection(u.hostname, u.port or 80, timeout=10)
            headers = {k: v for k, v in self.headers.items() if k.lower() not in ('host', 'connection', 'proxy-authorization', 'proxy-connection')}
            conn.request(self.command, (u.path or '/') + ('?' + u.query if u.query else ''), headers=headers)
            response = conn.getresponse()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in ('transfer-encoding', 'connection'):
                    self.send_header(key, value)
            self.send_header('Connection', 'close')
            self.end_headers()
            while not self.server.stopping.is_set():
                data = response.read(65536)
                if not data:
                    break
                self.wfile.write(data)
        except (OSError, ValueError, http.client.HTTPException):
            self.close_connection = True
        finally:
            if conn:
                conn.close()
            self.close_connection = True

    do_HEAD = do_GET


@contextmanager
def downloader(args, url):
    """Confine native yt-dlp requests; its unconstrained ffprobe/ffmpeg children stay disabled."""
    if not http_url(url):
        raise SecurityRefusal('A valid HTTP(S) URL is required.')
    u = urlsplit(url)
    addresses(u.hostname, u.port or (443 if u.scheme == 'https' else 80))
    server = ThreadingHTTPServer(('127.0.0.1', 0), _Proxy)
    server.daemon_threads = True
    server.stopping = threading.Event()
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
    thread.start()
    try:
        delimiter = args.index('--')
        with tempfile.TemporaryDirectory(prefix='brainamon-downloader-') as folder:
            yield args[:delimiter] + ['--proxy', f'http://127.0.0.1:{server.server_port}', '--downloader', 'native', '--hls-prefer-native', '--no-plugin-dirs',
                '--ffmpeg-location', folder, '--fixup', 'never', '--convert-thumbnails', 'none',
                '--match-filter', '!is_live',
                '--format', 'b[protocol^=http]/b[protocol=m3u8_native]'] + args[delimiter:]
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
        thread.join(2)
