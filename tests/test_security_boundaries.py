"""Proxy, protected migration and release gates using synthetic files and sockets only."""
import http.client
import importlib.util
import json
import socket
import sys
import tempfile
import unittest
import shutil
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

from core import private_storage as storage
from library import public_http, ytdlp


class Proxy(unittest.TestCase):
    def test_local_media_readers_refuse_nested_network_resources(self):
        from library import video_analyzer
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_error(404)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                media = root / 'synthetic.mp4'
                media.write_text(f'#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:{server.server_port}/secondary.ts\n#EXT-X-ENDLIST\n')
                if shutil.which('ffprobe'):
                    self.assertIsNone(video_analyzer._audio_duration_seconds(str(media)))
                if shutil.which('ffmpeg'):
                    with self.assertRaises(RuntimeError):
                        video_analyzer.extract_frames(str(media), 1, str(root))
                self.assertEqual(requests, [])
            with mock.patch.object(video_analyzer, 'ffmpeg_available', return_value=False):
                self.assertEqual(video_analyzer.preflight(True, False, False), video_analyzer.FFMPEG_MISSING)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_pins_numeric_address_and_preserves_tls_hostname(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        sock = mock.Mock()
        with mock.patch.object(public_http.socket, 'getaddrinfo', return_value=addresses) as dns, mock.patch.object(public_http.socket, 'socket', return_value=sock):
            self.assertIs(public_http.connect(('public.invalid', 443)), sock)
            dns.assert_called_once_with('public.invalid', 443, type=socket.SOCK_STREAM)
            sock.connect.assert_called_once_with(('8.8.8.8', 443))
        context = mock.Mock()
        with mock.patch.object(public_http, 'connect', return_value=sock):
            conn = public_http.HTTPSConnection('public.invalid', context=context)
            conn.connect()
        self.assertEqual(context.wrap_socket.call_args.kwargs['server_hostname'], 'public.invalid')

    def test_native_flags_parse_and_private_secondary_http_and_connect_are_denied(self):
        import yt_dlp
        args = ytdlp.download_args('yt-dlp', 'https://example.com/video', Path('synthetic'), False)
        # Only initial validation is mocked. Every proxy request below uses real private-address rejection.
        with mock.patch.object(public_http, 'addresses', return_value=[]) as dns:
            context = public_http.downloader(args, args[-1])
            confined = context.__enter__()
        try:
            opts = yt_dlp.parse_options(confined[1:])
            self.assertEqual(opts.urls, [args[-1]])
            self.assertEqual(opts.ydl_opts['external_downloader'], {'default': 'native'})
            self.assertEqual(opts.ydl_opts['fixup'], 'never')
            self.assertNotIn('+', opts.ydl_opts['format'])
            from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor
            processor = FFmpegPostProcessor(yt_dlp.YoutubeDL(opts.ydl_opts))
            self.assertFalse(processor.available)
            self.assertFalse(processor.probe_available)
            self.assertNotIn('FFmpegThumbnailsConvertor', [p['key'] for p in opts.ydl_opts['postprocessors']])
            self.assertIn('--no-plugin-dirs', confined)
            from urllib.parse import urlsplit
            proxy = urlsplit(confined[confined.index('--proxy') + 1])
            for request in ('GET http://127.0.0.1/secondary HTTP/1.0\r\n\r\n', 'CONNECT 127.0.0.1:443 HTTP/1.0\r\n\r\n', 'CONNECT public.invalid:443?bad HTTP/1.0\r\n\r\n'):
                with socket.create_connection(('127.0.0.1', proxy.port), timeout=2) as client:
                    client.sendall(request.encode())
                    self.assertNotIn(b'200', client.recv(4096))
        finally:
            context.__exit__(None, None, None)

    def test_proxy_redirect_is_not_followed_and_host_is_rebuilt(self):
        args = ['yt-dlp', '--', 'http://example.com/v']
        response = mock.Mock(status=302)
        response.getheaders.return_value = [('Location', 'http://127.0.0.1/private'), ('Content-Length', '0')]
        response.read.return_value = b''
        upstream = mock.Mock()
        upstream.getresponse.return_value = response
        with mock.patch.object(public_http, 'addresses', return_value=[]), mock.patch.object(public_http, 'HTTPConnection', return_value=upstream):
            with public_http.downloader(args, args[-1]) as confined:
                from urllib.parse import urlsplit
                proxy = urlsplit(confined[confined.index('--proxy') + 1])
                connection = http.client.HTTPConnection('127.0.0.1', proxy.port, timeout=2)
                connection.request('GET', args[-1], headers={'Host': 'evil.invalid', 'Proxy-Authorization': 'synthetic'})
                result = connection.getresponse()
                self.assertEqual((result.status, result.getheader('Location')), (302, 'http://127.0.0.1/private'))
                result.read()
                connection.close()
        upstream.request.assert_called_once_with('GET', '/v', headers={'Accept-Encoding': 'identity'})


class StorageInterruption(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'mirror.key'
        def crypt(raw, decrypt=False):
            if decrypt:
                if not raw.startswith(b'protected:'):
                    raise RuntimeError('Synthetic decrypt failure')
                return raw[10:]
            return b'protected:' + raw
        for patch in (mock.patch.object(storage, 'sys', SimpleNamespace(platform='win32')), mock.patch.object(storage.site_sessions, '_acl'), mock.patch.object(storage.site_sessions, '_crypt', side_effect=crypt)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_interruption_after_commit_retries_plaintext_retirement(self):
        self.path.write_bytes(b'exact-old-key')
        with mock.patch.object(storage, '_retire', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                storage.read(self.path)
        self.assertEqual(self.path.read_bytes(), b'exact-old-key')
        self.assertEqual(storage.read(self.path), b'exact-old-key')
        self.assertEqual(self.path.read_bytes(), storage.SENTINEL)

    def test_missing_or_corrupt_target_recovers_verified_previous(self):
        storage.write(self.path, b'exact-old-key')
        target = storage.location(self.path)
        previous = target.with_name(target.name + '.previous')
        for corrupt in (False, True):
            previous.write_bytes(target.read_bytes())
            if corrupt:
                target.write_bytes(b'corrupt')
            else:
                target.unlink()
            self.assertEqual(storage.read(self.path), b'exact-old-key')
        target.unlink()
        from library.mirror import MirrorKey, MirrorKeyError
        with self.assertRaises(MirrorKeyError):
            MirrorKey.load(self.path)

    def test_windows_marker_newline_is_not_a_conflicting_secret(self):
        storage.write(self.path, b'exact-protected-key')
        target = storage.location(self.path)
        protected = target.read_bytes()
        windows_marker = storage.SENTINEL.replace(b'\n', b'\r\n')
        self.path.write_bytes(windows_marker)
        self.assertEqual(storage.read(self.path, readonly=True), b'exact-protected-key')
        self.assertEqual(self.path.read_bytes(), windows_marker)
        self.assertEqual(storage.read(self.path), b'exact-protected-key')
        self.assertEqual(self.path.read_bytes(), storage.SENTINEL)
        self.assertEqual(target.read_bytes(), protected)

    def test_real_secrets_are_never_normalized_to_resolve_a_conflict(self):
        storage.write(self.path, b'synthetic-key\n')
        protected = storage.location(self.path).read_bytes()
        for legacy in (b'synthetic-key\r\n', storage.SENTINEL + b'extra', storage.SENTINEL.rstrip()):
            self.path.write_bytes(legacy)
            for readonly in (True, False):
                with self.assertRaisesRegex(RuntimeError, 'differ'):
                    storage.read(self.path, readonly=readonly)
            self.assertEqual(self.path.read_bytes(), legacy)
            self.assertEqual(storage.location(self.path).read_bytes(), protected)

    def test_conflicting_legacy_and_failed_replace_keep_recoverable_secret(self):
        storage.write(self.path, b'old')
        with mock.patch.object(storage.os, 'replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                storage.write(self.path, b'new')
        self.assertEqual(storage.read(self.path), b'old')
        self.path.write_bytes(b'different-legacy')
        with self.assertRaisesRegex(RuntimeError, 'differ'):
            storage.read(self.path)
        self.assertEqual(self.path.read_bytes(), b'different-legacy')

    def test_parent_junction_is_rejected_before_read(self):
        with mock.patch.object(Path, 'is_junction', lambda p: p == self.path.parent):
            with self.assertRaises(RuntimeError):
                storage.read(self.path)

    def test_config_update_recovers_previous_and_preserves_other_keys(self):
        from core import config
        path = self.path.with_name('.env')
        storage.write(path, b'OPENAI_API_KEY=synthetic-old\nANTHROPIC_API_KEY=synthetic-keep\n')
        target = storage.location(path)
        target.replace(target.with_name(target.name + '.previous'))
        with mock.patch.object(config, 'ENV_PATH', path), mock.patch.dict('os.environ'):
            config.write_env_file({'OPENAI_API_KEY': 'synthetic-new'})
        self.assertIn(b'ANTHROPIC_API_KEY=synthetic-keep', storage.read(path))
        self.assertIn(b'OPENAI_API_KEY=synthetic-new', storage.read(path))


class Release(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path(__file__).resolve().parents[1] / 'packaging'
        spec = importlib.util.spec_from_file_location('security_release', folder / 'release_check.py')
        cls.release = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, 'path', [str(folder), *sys.path]):
            spec.loader.exec_module(cls.release)

    def test_windows_requires_exact_valid_production_certificate(self):
        for status, actual, wanted, ok in [('Valid', 'ABC', 'abc', True), ('NotSigned', 'ABC', 'ABC', False), ('Valid', 'ABC', 'DEF', False), ('Valid', 'ABC', '', False)]:
            with mock.patch.object(self.release.subprocess, 'run', return_value=mock.Mock(stdout=json.dumps({'status': status, 'thumbprint': actual}))):
                if ok:
                    self.release.windows_signature(Path('synthetic.exe'), wanted)
                else:
                    with self.assertRaises(ValueError):
                        self.release.windows_signature(Path('synthetic.exe'), wanted)

    def test_android_debug_mismatched_and_missing_inspection_tools_fail_closed(self):
        digest = 'a' * 64
        with mock.patch.object(self.release.shutil, 'which', return_value=None):
            with self.assertRaises(ValueError):
                self.release.android_signature(Path('synthetic.apk'), digest)
        for signer, debug, ok in [(digest, 'false', True), (digest, 'true', False), ('b' * 64, 'false', False)]:
            results = [mock.Mock(stdout='Signer #1 certificate SHA-256 digest: ' + signer), mock.Mock(stdout=debug)]
            with mock.patch.object(self.release.shutil, 'which', return_value='synthetic-tool'), mock.patch.object(self.release.subprocess, 'run', side_effect=results):
                if ok:
                    self.release.android_signature(Path('synthetic.apk'), digest)
                else:
                    with self.assertRaises(ValueError):
                        self.release.android_signature(Path('synthetic.apk'), digest)

    def test_installer_requires_actual_extraction(self):
        with mock.patch.object(self.release.shutil, 'which', return_value=None):
            with self.assertRaises(ValueError):
                self.release.windows_payload(Path('synthetic.exe'), Path('synthetic'), 'public-fingerprint')

    def test_android_batch_analyzer_runs_without_command_echo(self):
        digest = 'a' * 64
        results = [mock.Mock(stdout='Signer #1 certificate SHA-256 digest: ' + digest), mock.Mock(stdout='false')]
        with mock.patch.object(self.release.os, 'name', 'nt'), mock.patch.object(self.release.shutil, 'which', side_effect=['signer.bat', 'analyzer.bat']), mock.patch.object(self.release.subprocess, 'run', side_effect=results) as run:
            self.release.android_signature(Path('synthetic.apk'), digest)
        self.assertEqual(run.call_args_list[1].args[0][:4], ['cmd', '/q', '/c', 'analyzer.bat'])

    def test_compiled_dependency_report_is_complete_and_not_affected(self):
        good = {'Pillow': '13.0.0', 'pypdf': '6.21.2', 'OpenJPEG': '2.5.2'}
        self.assertEqual(self.release.dependency_versions(good), good)
        patched = {**good, 'OpenJPEG': '2.5.4'}
        self.assertEqual(self.release.dependency_versions(patched), patched)
        for bad in ({}, None, {**good, 'Pillow': '12.3.0'}, {**patched, 'Pillow': '12.3.0'}, {**good, 'pypdf': '6.19.0'}, {**good, 'OpenJPEG': None}, {**good, 'OpenJPEG': '2.5.3'}):
            with self.assertRaises(ValueError):
                self.release.dependency_versions(bad)

    def test_actual_extracted_payload_must_match_and_have_patched_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            expanded = Path(folder) / 'expanded'
            expanded.mkdir()
            (expanded / 'Brainamon.exe').write_bytes(b'synthetic executable never run')
            (expanded / '_internal').mkdir()
            (expanded / '_internal/build-channel.json').write_text('{"channel":"official"}')
            for failure in ('', 'mismatch', 'private', 'parser'):
                def run(args, **kwargs):
                    if args[0] == 'synthetic-extractor':
                        app = Path(args[3]) / 'app'
                        shutil.copytree(expanded, app)
                        if failure == 'mismatch':
                            (app / 'extra.txt').write_text('different payload')
                        if failure == 'private':
                            (app / 'google_token.json').write_text('synthetic')
                        return mock.Mock()
                    self.assertEqual(kwargs['env']['TEMP'], kwargs['env']['BRAINAMON_HOME'])
                    return mock.Mock(stdout=json.dumps({'Pillow': '12.3.0' if failure == 'parser' else '13.0.0', 'pypdf': '6.21.2', 'OpenJPEG': '2.5.2'}))
                with mock.patch.object(self.release.shutil, 'which', return_value='synthetic-extractor'), mock.patch.object(self.release, 'windows_signature'), mock.patch.object(self.release.update_signing, 'verify_file'), mock.patch.object(self.release.subprocess, 'run', side_effect=run):
                    if failure:
                        with self.assertRaises(ValueError):
                            self.release.windows_payload(Path('synthetic-installer.exe'), expanded, 'public')
                    else:
                        self.assertEqual(self.release.windows_payload(Path('synthetic-installer.exe'), expanded, 'public')['Pillow'], '13.0.0')

    def test_public_certificates_can_ship_but_private_pem_cannot(self):
        self.assertFalse(self.release.inspect_payload.__globals__['forbidden']('public.pem', b'-----BEGIN CERTIFICATE-----\nsynthetic'))
        self.assertTrue(self.release.inspect_payload.__globals__['forbidden']('arbitrary.pem', b'-----BEGIN PRIVATE KEY-----\nsynthetic'))
