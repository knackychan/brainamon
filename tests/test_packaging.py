"""The installed build (packaging/): what the PyInstaller spec bundles.

Run from the project root:  py -m unittest tests.test_packaging -v
"""
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import app_paths, config
from library import scrape_watch

ROOT = Path(__file__).resolve().parent.parent
SPEC = (ROOT / 'packaging' / 'brainamon.spec').read_text(encoding='utf-8')
# packaging/ is not a package (and `packaging` is a pip module): load build.py by path
_spec = importlib.util.spec_from_file_location('cm_build', ROOT / 'packaging' / 'build.py')
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


class FrontendBuildTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patch = mock.patch.object(build, 'ROOT', self.root)
        patch.start()
        self.addCleanup(patch.stop)
        for name, content in {
            'web/package.json': '{}', 'web/package-lock.json': '{}',
            'web/src/app.ts': 'source', 'web/public/icon.svg': 'icon',
            'web/node_modules/native.node': 'locked dependency',
            'web/.env': 'VITE_PRIVATE_VALUE=synthetic-never-copy', 'web/.npmrc': 'synthetic-local-registry-auth',
            'web/dist/index.html': 'old output', 'web/dist/stale.js': 'old chunk',
            'core/license.py': 'PUBLIC_KEYS: tuple[str, ...] = ()',
            'knowledge/prompts/ask_quick.json': '{"prompt":"shared"}',
            'LICENSE': 'Synthetic software license\n',
            'THIRD_PARTY_NOTICES.md': 'Synthetic third-party notices\n',
            'mobile-shell/store/privacy-policy.md': 'Synthetic privacy policy\n',
            'mobile-shell/store/privacy-policy.fr.md': 'Synthetic French privacy policy\n',
            'mobile-shell/store/privacy-policy.zh-Hant.md': 'Synthetic Taiwan privacy policy\n',
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def test_build_is_isolated_and_replaces_stale_output(self):
        stages = []

        def run(cmd, cwd):
            self.assertTrue(cwd.is_relative_to(self.root / 'build'))
            if cmd == ['npm', 'ci']:
                stages.append(cwd.parent)
                self.assertFalse((cwd / 'node_modules').exists())
                self.assertFalse((cwd / 'dist').exists())
                self.assertFalse((cwd / '.env').exists())
                self.assertFalse((cwd / '.npmrc').exists())
                self.assertEqual((cwd / 'src/app.ts').read_text(), 'source')
                self.assertTrue((cwd / 'package-lock.json').is_file())
                self.assertTrue((cwd / 'public/icon.svg').is_file())
                self.assertEqual((cwd.parent / 'knowledge/prompts/ask_quick.json').read_text(),
                                 '{"prompt":"shared"}')
                for name in ('core/license.py', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'mobile-shell/store/privacy-policy.md',
                             'mobile-shell/store/privacy-policy.fr.md', 'mobile-shell/store/privacy-policy.zh-Hant.md'):
                    self.assertEqual((cwd.parent / name).read_bytes(), (self.root / name).read_bytes())
            else:
                self.assertEqual(cmd, ['npm', 'run', 'build'])
                (cwd / 'dist').mkdir()
                (cwd / 'dist/index.html').write_text('new output')

        with mock.patch.object(build, 'run', side_effect=run) as commands:
            build.build_web()
            build.build_web()
        self.assertEqual(commands.call_count, 4)
        self.assertNotEqual(stages[0], stages[1])
        self.assertTrue(all(not stage.exists() for stage in stages))
        self.assertEqual((self.root / 'web/dist/index.html').read_text(), 'new output')
        self.assertFalse((self.root / 'web/dist/stale.js').exists())
        self.assertEqual((self.root / 'web/node_modules/native.node').read_text(), 'locked dependency')

    def test_failed_build_preserves_previous_output_and_cleans_stage(self):
        for failure in (subprocess.CalledProcessError(1, ['npm', 'ci']), None):
            with self.subTest(failure=failure), mock.patch.object(build, 'run', side_effect=failure):
                with self.assertRaises((subprocess.CalledProcessError, SystemExit)):
                    build.build_web()
            self.assertEqual((self.root / 'web/dist/index.html').read_text(), 'old output')
            self.assertTrue((self.root / 'web/dist/stale.js').is_file())
            self.assertEqual(list((self.root / 'build').iterdir()), [])


class MCPBuildTest(unittest.TestCase):
    def test_frozen_smoke_inventory_matches_the_current_server(self):
        from mcp_local import app
        names = [tool.name for tool in asyncio.run(app.mcp.list_tools())]
        with tempfile.TemporaryDirectory() as td, mock.patch.object(build, 'ROOT', Path(td)):
            (Path(td) / 'build').mkdir()
            for extra in ([], ['unexpected_tool']):
                process = mock.Mock()
                process.stdout.readline.side_effect = [b'{"result":{}}\n', json.dumps({
                    'result': {'tools': [{'name': name} for name in names + extra]}}).encode()]
                with mock.patch.object(build.subprocess, 'Popen', return_value=process):
                    result = build.mcp_smoke(Path(td) / 'Brainamon.exe')
                self.assertEqual(bool(result), bool(extra))


class ScrapersBundledTest(unittest.TestCase):
    def test_scrapers_resolve_from_the_bundle(self):
        self.assertEqual(scrape_watch.SCRAPERS_DIR, app_paths.BUNDLE / 'scrapers')

    def test_spec_ships_every_platform_script(self):
        # The spec adds scrapers/*.js under 'scrapers' (CSV scrapes in that folder are user data).
        self.assertIn("(ROOT / 'scrapers').glob('*.js')", SPEC)
        self.assertNotIn("glob('*.csv')", SPEC)
        for key, (_label, js, _url, _prefix) in scrape_watch.PLATFORMS.items():
            with self.subTest(key=key):
                self.assertTrue(js.endswith('.js'))
                self.assertTrue((ROOT / 'scrapers' / js).is_file())
                self.assertTrue(scrape_watch.script_for(key).strip())
        for _label, worker, _profile in scrape_watch.PLAYWRIGHT.values():
            self.assertIn(worker, SPEC)
        self.assertIn("'threads.js'), 'scrapers/sites'", SPEC)
        self.assertIn('requirements-scraper.txt', SPEC)
        self.assertIn("'playwright'", SPEC)  # excluded package, only small workers ship


class GoogleOAuthPackagingTest(unittest.TestCase):
    def test_missing_registration_stops_packaging(self):
        for values in ({}, {config.GOOGLE_CLIENT_ID: 'id'}, {config.GOOGLE_CLIENT_SECRET: 'secret'}):
            with self.subTest(values=values), mock.patch.object(config, 'read_env_file', return_value=values), \
                    mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(SystemExit, 'Cannot package Google sign-in'):
                    build.write_google_oauth()

    def test_fresh_installed_home_needs_no_env_file(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td) / 'bundle'
            bundle.mkdir()
            (bundle / 'build-channel.json').write_text('{"channel":"official"}')
            (bundle / 'google-oauth.json').write_text(json.dumps({
                config.GOOGLE_CLIENT_ID: 'desktop-id', config.GOOGLE_CLIENT_SECRET: 'desktop-secret',
                config.GOOGLE_WEB_CLIENT_ID: 'web-id'}))
            env = {k: v for k, v in os.environ.items() if not k.startswith('BRAINAMON_GOOGLE_')
                   and k != 'BRAINAMON_HOME'}
            env['LOCALAPPDATA'] = str(Path(td) / 'fresh-user')
            code = ("import sys; sys.frozen = True; sys._MEIPASS = sys.argv[1]; "
                    "from core import config; config.load_env(); "
                    "assert not config.ENV_PATH.exists(); "
                    "assert config.google_client() == ('desktop-id', 'desktop-secret'); "
                    "assert config.google_web_client() == 'web-id'")
            subprocess.run([sys.executable, '-c', code, str(bundle)], cwd=ROOT, env=env, check=True)

    def test_only_app_registration_is_bundled_and_loaded_when_frozen(self):
        values = {config.GOOGLE_CLIENT_ID: 'desktop-id', config.GOOGLE_CLIENT_SECRET: 'desktop-secret',
                  config.GOOGLE_WEB_CLIENT_ID: 'web-id'}
        with tempfile.TemporaryDirectory() as td, mock.patch.object(build, 'ROOT', Path(td)), \
                mock.patch.object(config, 'read_env_file', return_value={**values, 'OPENAI_API_KEY': 'private'}), \
                mock.patch.dict(os.environ, {}, clear=True):
            build.write_google_oauth()
            bundle = Path(td) / 'build'
            self.assertEqual(json.loads((bundle / 'google-oauth.json').read_text()), values)
            with mock.patch.object(app_paths, 'BUNDLE', bundle), mock.patch.object(app_paths, 'FROZEN', True):
                self.assertEqual(config.bundled_google_oauth(), values)
                (bundle / 'google-oauth.json').write_text('[]')
                self.assertEqual(config.bundled_google_oauth(), {})
                (bundle / 'google-oauth.json').unlink()
                self.assertEqual(config.bundled_google_oauth(), {})
            os.environ[config.GOOGLE_CLIENT_ID] = 'override'
            build.write_google_oauth()
            self.assertEqual(json.loads((bundle / 'google-oauth.json').read_text())[config.GOOGLE_CLIENT_ID], 'override')
            with mock.patch.object(app_paths, 'BUNDLE', bundle), mock.patch.object(app_paths, 'FROZEN', False):
                self.assertEqual(config.bundled_google_oauth(), {})
        self.assertIn("(str(ROOT / 'build' / 'google-oauth.json'), '.')", SPEC)

    def test_local_override_does_not_use_another_clients_secret(self):
        with mock.patch.object(config, 'GOOGLE_CLIENT_DEFAULT', ('bundled-id', 'bundled-secret')), \
                mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.google_client(), ('bundled-id', 'bundled-secret'))
            os.environ[config.GOOGLE_CLIENT_ID] = 'local-id'
            self.assertEqual(config.google_client(), ('local-id', ''))
            os.environ[config.GOOGLE_CLIENT_SECRET] = 'local-secret'
            self.assertEqual(config.google_client(), ('local-id', 'local-secret'))


class SigningTest(unittest.TestCase):
    def test_unsigned_unless_required(self):
        self.assertIsNone(build.cert_args({}))
        with self.assertRaises(SystemExit):
            build.cert_args({}, required=True)

    def test_thumbprint(self):
        self.assertEqual(build.cert_args({'SIGN_THUMBPRINT': 'ab cd'}, required=True), ['/s', 'My', '/sha1', 'abcd'])

    def test_pfx(self):
        with tempfile.TemporaryDirectory() as td:
            pfx = Path(td) / 'c.pfx'
            pfx.write_bytes(b'x')
            self.assertEqual(build.cert_args({'SIGN_PFX': str(pfx), 'SIGN_PFX_PASSWORD': 'pw'}),
                             ['/f', str(pfx), '/p', 'pw'])
            with self.assertRaises(SystemExit):
                build.cert_args({'SIGN_PFX': str(pfx), 'SIGN_THUMBPRINT': 'ab'})
        with self.assertRaises(SystemExit):
            build.cert_args({'SIGN_PFX': str(ROOT / 'missing.pfx')})


class ToolsAndSecretsTest(unittest.TestCase):
    def test_tools_are_not_bundled(self):
        for needle in ('ffmpeg.exe', 'ffprobe.exe', 'yt-dlp.exe', 'BRAINAMON_TOOLS_DIR', 'VERSIONS.txt',
                       "'packaging' / 'tools'", "'tools')"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, SPEC)
        self.assertNotIn('cookie', SPEC.replace('Never a cookies file', '').lower())
        for gone in ('TOOLS_DIR', 'TOOLS', 'check_tools', 'record_tools', 'MIN_YTDLP', 'VERSIONS'):
            self.assertFalse(hasattr(build, gone), gone)

    def test_build_main_names_resolve(self):
        # main() never runs in tests; a name left over from a removed helper would stop the real build.
        import ast
        import builtins
        tree = ast.parse((ROOT / 'packaging' / 'build.py').read_text(encoding='utf-8'))
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        local = {n.id for n in ast.walk(main) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        for node in ast.walk(main):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in local:
                with self.subTest(name=node.id):
                    self.assertTrue(hasattr(build, node.id) or hasattr(builtins, node.id), node.id)

    def _frozen_path(self, td, pointer=None):
        # A fresh interpreter posing as the frozen app; LOCALAPPDATA is a temp folder, so no real home is touched.
        home = Path(td) / 'local' / 'Brainamon'
        bundle = Path(td) / 'bundle'
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / 'build-channel.json').write_text('{"channel":"official"}')
        if pointer is not None:
            home.mkdir(parents=True)
            (home / 'tools.json').write_text(json.dumps({'tools_dir': pointer}), encoding='utf-8')
        code = ('import os, sys; sys.frozen = True; sys._MEIPASS = sys.argv[1]; from core import app_paths; '
                'print(os.environ["PATH"].split(os.pathsep)[0])')
        env = {**{k: v for k, v in os.environ.items() if k != 'BRAINAMON_HOME'}, 'LOCALAPPDATA': str(Path(td) / 'local'), 'PATH': 'X-ORIG' + os.pathsep + os.environ['PATH']}
        return subprocess.run([sys.executable, '-c', code, str(Path(td) / 'bundle')], cwd=ROOT, env=env,
                              capture_output=True, text=True, check=True).stdout.strip()

    def _frozen_home(self, local, extra_env=None):
        bundle = Path(local) / 'bundle'
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / 'build-channel.json').write_text('{"channel":"official"}')
        code = ('import sys; sys.frozen = True; sys._MEIPASS = sys.argv[1]; '
                'from core import app_paths; print(app_paths.HOME); print(app_paths.data_dir())')
        env = {**{k: v for k, v in os.environ.items() if k != 'BRAINAMON_HOME'}, 'LOCALAPPDATA': str(local), **(extra_env or {})}
        return subprocess.run([sys.executable, '-c', code, str(Path(local) / 'bundle')], cwd=ROOT, env=env,
                              capture_output=True, text=True)

    def test_installed_app_leaves_path_alone_without_a_saved_folder(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / 'bundle' / 'tools').mkdir(parents=True)      # a stray tools/ folder is no longer used
            self.assertEqual(self._frozen_path(td), 'X-ORIG')

    def test_installed_app_puts_the_saved_tools_folder_first_on_path(self):
        with tempfile.TemporaryDirectory() as td:
            folder = str(Path(td) / 'my tools')
            self.assertEqual(self._frozen_path(td, pointer=folder), folder)

    def test_old_content_manager_home_is_not_renamed(self):
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / 'local'
            old = local / 'Content Manager'
            old.mkdir(parents=True)
            (old / '.env').write_text('preserve', encoding='utf-8')
            result = self._frozen_home(local)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.splitlines()[0]), old)
            self.assertEqual((old / '.env').read_text(encoding='utf-8'), 'preserve')
            self.assertFalse((local / 'Brainamon').exists())

    def test_multiple_populated_homes_require_explicit_selection(self):
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / 'local'
            for name in ('Brainamon', 'Content Manager'):
                folder = local / name
                folder.mkdir(parents=True)
                (folder / 'location.json').write_text('{}', encoding='utf-8')
            result = self._frozen_home(local)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Set BRAINAMON_HOME', result.stderr)
            self.assertTrue((local / 'Brainamon' / 'location.json').is_file())
            self.assertTrue((local / 'Content Manager' / 'location.json').is_file())

    def test_explicit_home_selection_keeps_cm_data_dir_precedence(self):
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / 'local'
            selected = local / 'Content Manager'
            selected.mkdir(parents=True)
            cm_data = Path(td) / 'external-data'
            result = self._frozen_home(local, {'BRAINAMON_HOME': str(selected), 'CM_DATA_DIR': str(cm_data)})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual([Path(p) for p in result.stdout.splitlines()], [selected, cm_data])

    def test_set_tools_dir_saves_and_applies(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(app_paths, 'TOOLS_POINTER', Path(td) / 'tools.json'),                 mock.patch.dict(os.environ, {'PATH': 'X-ORIG'}):
            self.assertEqual(app_paths.tools_dir(), '')
            app_paths.set_tools_dir(td)
            self.assertEqual(app_paths.tools_dir(), str(Path(td).resolve()))
            self.assertEqual(os.environ['PATH'].split(os.pathsep), [str(Path(td).resolve()), 'X-ORIG'])
            app_paths.apply_tools_dir(str(Path(td).resolve()))               # once only
            self.assertEqual(os.environ['PATH'].count(str(Path(td).resolve())), 1)
            app_paths.set_tools_dir('')
            self.assertEqual(app_paths.tools_dir(), '')

    def test_leaked_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / '_internal').mkdir()
            for name in ('cookies.txt', '_internal/Instagram_cookies.txt', '.env', 'Brainamon.exe',
                         '_internal/http_cookiejar.pyc', '_internal/LICENSE'):
                (d / name).write_text('x')
            self.assertEqual([p.name for p in build.leaked_secrets(d)], ['.env', 'Instagram_cookies.txt', 'cookies.txt'])

    def test_session_and_profile_directories_cannot_ship(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for folder in ('site-sessions', 'instagram-profile', 'facebook-profile', 'reddit-profile', 'playwright'):
                path = root / '_internal' / folder / 'arbitrary.bin'
                path.parent.mkdir(parents=True)
                path.write_bytes(b'synthetic')
            self.assertEqual(len(build.leaked_secrets(root)), 5)


class TimezoneDataTest(unittest.TestCase):
    def test_spec_bundles_tzdata(self):
        self.assertIn("collect_data_files('tzdata')", SPEC)
        self.assertIn('collect_submodules(\'tzdata\')', SPEC)

    def test_zoneinfo_resolves_named_zones_without_host_tzpath(self):
        code = ("from zoneinfo import ZoneInfo; "
                "print(ZoneInfo('Asia/Taipei').key, ZoneInfo('America/New_York').key)")
        env = {**os.environ, 'PYTHONTZPATH': ''}
        r = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                           capture_output=True, text=True, check=True)
        self.assertEqual(r.stdout.strip(), 'Asia/Taipei America/New_York')


if __name__ == '__main__':
    unittest.main()
