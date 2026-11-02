"""Run synthetic regressions with isolated runtime paths and fixture-only sockets.

Usage: py scripts/security_tests.py tests.test_security_remediation [other modules]
"""
import os
import io
from contextlib import contextmanager
import socket
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='brainamon-security-', ignore_cleanup_errors=True) as folder:
        root = Path(folder)
        tempfile.tempdir = folder
        for name in list(os.environ):
            if any(part in name.upper() for part in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'SIGN_PFX', 'BRAINAMON_', 'CM_DATA_DIR', 'YTDLP_COOKIES')):
                os.environ.pop(name)
        os.environ.update(BRAINAMON_HOME=folder, CM_DATA_DIR=str(root / 'data'),
                          TEMP=folder, TMP=folder, LOCALAPPDATA=folder, APPDATA=folder)
        repository = Path(__file__).resolve().parents[1]
        forbidden = [repository / name for name in ('data', 'local', '.env', 'cookies.txt', 'Instagram_cookies.txt')]
        def audit(event, args):
            if event.startswith('winreg.'):
                raise OSError('Security tests blocked real registry access')
            indices = (0, 1) if event in ('os.rename', 'os.replace') else (0,)
            if event in ('open', 'sqlite3.connect', 'os.remove', 'os.rename', 'os.replace', 'os.mkdir', 'os.rmdir', 'os.chmod'):
                for index in indices:
                    value = args[index] if index < len(args) else None
                    if isinstance(value, (str, bytes, os.PathLike)):
                        target = Path(os.fsdecode(value)).resolve()
                        if any(target == path or path in target.parents for path in forbidden):
                            raise OSError('Security tests blocked repository runtime access')
        sys.addaudithook(audit)
        os.environ['PYTHON_DOTENV_DISABLED'] = '1'
        try:
            from dotenv.main import DotEnv
            original_stream = DotEnv._get_stream
            @contextmanager
            def isolated_stream(dotenv):
                if dotenv.dotenv_path and Path(dotenv.dotenv_path).resolve() == repository / '.env':
                    yield io.StringIO('')
                else:
                    with original_stream(dotenv) as stream:
                        yield stream
            DotEnv._get_stream = isolated_stream
        except ImportError:
            pass
        # Only explicit ephemeral loopback fixtures; never the user's running app or proxy.
        connect = socket.socket.connect
        resolve = socket.getaddrinfo
        def fixture_connect(sock, address):
            if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1') or address[1] in (18765, 5173, 3001):
                raise OSError('Security tests blocked a non-fixture connection')
            return connect(sock, address)
        def fixture_resolve(host, *args, **kwargs):
            if host not in ('127.0.0.1', '::1', 'localhost'):
                raise OSError('Security tests require mocked DNS')
            return resolve(host, *args, **kwargs)
        socket.socket.connect = fixture_connect
        socket.getaddrinfo = fixture_resolve
        suite = (unittest.defaultTestLoader.discover(str(repository / 'tests'), top_level_dir=str(repository)) if '--all' in sys.argv else
                 unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:] or ['tests.test_security_remediation']))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
