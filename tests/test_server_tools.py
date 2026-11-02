"""Settings > Tools (server/routes/settings.py): which of ffmpeg, ffprobe and yt-dlp resolve, the saved
tools folder, and the plain missing-tool messages. The tools.json pointer and PATH are redirected to a temp
folder; nothing real is touched.

Run from the project root:  py -m unittest tests.test_server_tools -v
"""
import os
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import app_paths
from core import config
from core.db import Database
from library import video_analyzer
from library import ytdlp
from server.app import create_app

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


class _Base(unittest.TestCase):
    _real_merge = staticmethod(app_paths.merge_registry_path)

    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.data = self.root / 'data'
        Database(self.data / 'content_manager.db').close()
        for p in (mock.patch.object(config, 'ENV_PATH', self.root / '.env'),
                  mock.patch.object(ytdlp, 'registry_get', lambda name: ''),
                  mock.patch.object(app_paths, 'TOOLS_POINTER', self.root / 'tools.json'),
                  mock.patch.object(app_paths, 'merge_registry_path', lambda: None),      # the real PATH of this PC
                  mock.patch.dict(os.environ, {'PATH': str(self.root / 'empty')})):
            p.start()
            self.addCleanup(p.stop)
        self.c = TestClient(create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.root / 'x', cards_dir=self.root / 'x'), base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)


class ToolsTest(_Base):
    def test_slow_tool_checks_leave_app_settings_available(self):
        import anyio.to_thread
        from library import scraper_runtime
        from server.routes import settings as st

        async def pool_size(size):
            limiter = anyio.to_thread.current_default_thread_limiter()
            old = limiter.total_tokens
            limiter.total_tokens = size
            return old

        old_size = self.c.portal.call(pool_size, 1)
        try:
            for path, target, name in [('/api/settings/tools', st, 'tools_view'),
                                       ('/api/settings/scraper-runtime', scraper_runtime, 'status')]:
                with self.subTest(path=path):
                    started, release = threading.Event(), threading.Event()

                    def slow_check(*args, **kwargs):
                        started.set()
                        if not release.wait(10):
                            raise AssertionError('Test did not release the tool check')
                        return {'state': 'missing'}

                    with mock.patch.object(target, name, side_effect=slow_check), ThreadPoolExecutor(2) as requests:
                        check = requests.submit(self.c.get, path)
                        try:
                            self.assertTrue(started.wait(3))
                            app = requests.submit(self.c.get, '/api/app').result(timeout=2)
                            self.assertEqual(app.status_code, 200)
                            self.assertIn('autostart', app.json())
                            self.assertFalse(check.done())
                        finally:
                            release.set()
                        self.assertEqual(check.result(timeout=3).status_code, 200)
        finally:
            self.c.portal.call(pool_size, old_size)

    def test_local_version_probes(self):
        from server.routes import settings as st
        for name, output, expected in [('deno', 'deno 2.2.0', 'older'), ('deno', 'deno 2.3.0', 'ready'),
                                        ('ffmpeg', 'ffmpeg version 7.1-full_build', 'ready'),
                                        ('ffprobe', 'ffprobe version 7.1', 'ready'), ('yt-dlp', '2026.10.14', 'ready')]:
            with mock.patch.object(st.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')):
                self.assertEqual(st.tool_probe(name, 'selected')['state'], expected)
        with mock.patch.object(st.subprocess, 'run', side_effect=subprocess.TimeoutExpired('probe', 10)):
            self.assertEqual(st.tool_probe('deno', 'selected')['state'], 'failed')
        self.assertEqual(st.tool_probe('deno', None)['state'], 'missing')

    def names(self, view):
        return {t['name']: t['found'] for t in view['tools']}

    @unittest.skipUnless(os.name == 'nt', 'the registry PATH is Windows only')
    def test_registry_path_adds_what_the_process_lacks(self):
        extra = str(self.root / 'installed-later')
        import winreg
        key = mock.MagicMock()
        key.__enter__.return_value = key
        with mock.patch.object(app_paths, 'merge_registry_path', self._real_merge),                 mock.patch.object(winreg, 'OpenKey', return_value=key),                 mock.patch.object(winreg, 'QueryValueEx', return_value=(extra, 1)):
            app_paths.merge_registry_path()
            app_paths.merge_registry_path()
        parts = os.environ['PATH'].split(os.pathsep)
        self.assertEqual(parts[0], str(self.root / 'empty'))        # the process's own folders stay first
        self.assertEqual(parts.count(extra), 1)                     # added once

    def test_nothing_found(self):
        v = self.c.get('/api/settings/tools').json()
        self.assertEqual(self.names(v), {'ffmpeg': False, 'ffprobe': False, 'yt-dlp': False, 'deno': False})
        self.assertEqual((v['tools_dir'], v['all_found']), ('', False))

    def test_folder_is_saved_and_put_on_path(self):
        tools = self.root / 'tools'
        tools.mkdir()
        for n in ('ffmpeg.exe', 'ffprobe.exe', 'yt-dlp.exe', 'deno.exe'):
            (tools / n).write_bytes(b'')
        r = self.c.put('/api/settings/tools', json={'tools_dir': str(tools)}, headers=W)
        self.assertEqual(r.status_code, 200)
        v = r.json()
        self.assertEqual(v['tools_dir'], str(tools.resolve()))
        self.assertTrue(os.environ['PATH'].startswith(str(tools.resolve())))
        if os.name == 'nt':                                     # .exe is only runnable by name on Windows
            self.assertTrue(v['all_found'])
        self.assertEqual(app_paths.tools_dir(), str(tools.resolve()))

    def test_bad_folder_is_refused(self):
        for bad in (str(self.root / 'missing'), 'relative'):
            r = self.c.put('/api/settings/tools', json={'tools_dir': bad}, headers=W)
            self.assertEqual(r.status_code, 400)
        self.assertEqual(self.c.put('/api/settings/tools', json={'tools_dir': 3}, headers=W).status_code, 400)
        self.assertEqual(app_paths.tools_dir(), '')

    def test_individual_folders_preserve_other_choices_and_shared_folder(self):
        from server.routes import settings as st
        first, second = self.root / 'video', self.root / 'downloads'
        first.mkdir(); second.mkdir()
        suffix = '.exe' if os.name == 'nt' else ''
        for folder, name in ((first, 'ffmpeg'), (second, 'yt-dlp')):
            exe = folder / (name + suffix); exe.write_bytes(b''); exe.chmod(0o755)
        with mock.patch.object(st, 'youtube_tools', return_value={'deno': False, 'ejs': 'unknown', 'functional': True}), mock.patch.object(st, 'tool_probe', return_value={'state': 'ready', 'version': 'test'}):
            for name, folder in (('ffmpeg', first), ('yt-dlp', second)):
                r = self.c.put('/api/settings/tools', json={'tool': name, 'folder': str(folder)}, headers=W)
                self.assertEqual(r.status_code, 200, r.text)
            self.c.put('/api/settings/tools', json={'tools_dir': str(self.root)}, headers=W)
            self.assertEqual(app_paths.tool_folders(), {'ffmpeg': str(first), 'yt-dlp': str(second)})
            self.assertEqual(Path(app_paths.find_tool('ffmpeg')), first / ('ffmpeg' + suffix))
            self.assertEqual(Path(ytdlp.find_ytdlp()), second / ('yt-dlp' + suffix))
            (second / ('yt-dlp' + suffix)).unlink()
            self.assertIsNone(ytdlp.find_ytdlp(), 'A missing selected tool must not silently use a different installation')
        for payload in ({'tool': 'unknown', 'folder': str(first)}, {'tool': 'ffmpeg', 'folder': str(second)}, {'tool': 'ffmpeg', 'folder': 'relative'}, {'tool': 'ffmpeg', 'folder': 42}):
            self.assertEqual(self.c.put('/api/settings/tools', json=payload, headers=W).status_code, 400)
        self.assertEqual(app_paths.tool_folders()['ffmpeg'], str(first))

    def test_selected_deno_is_used_by_downloads(self):
        with mock.patch.object(app_paths, 'tool_folders', return_value={'deno': 'chosen'}), mock.patch.object(app_paths, 'find_tool', return_value='chosen/deno.exe'):
            args = ytdlp.download_args('selected-yt-dlp', 'https://example.com/video', self.root, False)
        self.assertEqual(args[args.index('--js-runtimes') + 1], 'deno:chosen/deno.exe')

    def test_clear(self):
        self.c.put('/api/settings/tools', json={'tools_dir': str(self.root)}, headers=W)
        v = self.c.put('/api/settings/tools', json={'tools_dir': ''}, headers=W).json()
        self.assertEqual(v['tools_dir'], '')

    def test_put_needs_the_header(self):
        self.assertEqual(self.c.put('/api/settings/tools', json={'tools_dir': ''}).status_code, 403)


class InstallTest(_Base):
    def view(self, bad=(), ejs='detected'):
        return {'tools': [{'name': n, 'state': 'older' if n in bad else 'ready'}
                          for n in ('ffmpeg', 'ffprobe', 'yt-dlp', 'deno')],
                'youtube': {'functional': 'yt-dlp' not in bad, 'deno': 'deno' not in bad, 'ejs': ejs}}

    def test_installer_skips_detected_packages(self):
        from server.routes import settings as st
        with mock.patch.object(st, 'tools_view', side_effect=[self.view(['deno']), self.view()]), \
                mock.patch.object(st.shutil, 'which', return_value='winget'), \
                mock.patch.object(st.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            st._run_install()
        self.assertEqual([c.args[0][3] for c in run.call_args_list], ['DenoLand.Deno'])
        self.assertEqual(st._install['state'], 'done')

    def test_healthy_manual_tools_need_no_winget(self):
        from server.routes import settings as st
        with mock.patch.object(st, 'tools_view', return_value=self.view()), \
                mock.patch.object(st.shutil, 'which', side_effect=AssertionError('No installation needed')):
            st._run_install()
        self.assertEqual(st._install['state'], 'done')

    def test_missing_ejs_repairs_existing_ytdlp(self):
        from server.routes import settings as st
        with mock.patch.object(st, 'tools_view', side_effect=[self.view(ejs='not detected'), self.view()]), \
                mock.patch.object(st.shutil, 'which', return_value='winget'), \
                mock.patch.object(st.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            st._run_install()
        self.assertEqual(run.call_args.args[0][3], 'yt-dlp.yt-dlp')
        self.assertIn('--force', run.call_args.args[0])
        self.assertIn('--disable-interactivity', run.call_args.args[0])
        self.assertEqual(st._install['state'], 'done')

    def test_ytdlp_dependencies_are_rechecked_before_installing_again(self):
        from server.routes import settings as st
        with mock.patch.object(st, 'tools_view', side_effect=[self.view(['yt-dlp', 'ffmpeg', 'ffprobe', 'deno']), self.view()]), \
                mock.patch.object(st.shutil, 'which', return_value='winget'), \
                mock.patch.object(st.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            st._run_install()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(st._install['state'], 'done')

    def test_success_exit_or_no_update_cannot_hide_failed_probe(self):
        from server.routes import settings as st
        for code in (0, 0x8a15002b - 2**32):
            with self.subTest(code=code), \
                    mock.patch.object(st, 'tools_view', return_value=self.view(ejs='unknown')), \
                    mock.patch.object(st.shutil, 'which', return_value='winget'), \
                    mock.patch.object(app_paths, 'set_tool_folder') as folder, \
                    mock.patch.object(st.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, '', '')):
                st._run_install()
            self.assertEqual(st._install['state'], 'error')
            self.assertIn('folder choices were kept', st._install['error'])
            folder.assert_not_called()

    def test_permission_failure_and_timeout_offer_terminal(self):
        from server.routes import settings as st
        for failure in (subprocess.CompletedProcess([], 5, '', 'Access denied'), subprocess.TimeoutExpired('winget', 900)):
            with self.subTest(failure=str(failure)), \
                    mock.patch.object(st, 'tools_view', return_value=self.view(['deno'])), \
                    mock.patch.object(st.shutil, 'which', return_value='winget'), \
                    mock.patch.object(st.subprocess, 'run', **({'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure})):
                st._run_install()
            self.assertEqual(st._install['state'], 'error')
            self.assertIn('administrator terminal', st._install['error'])

    def setUp(self):
        super().setUp()
        from server.routes import settings as st
        self.addCleanup(st._install.update, state='idle', step='', error='')
        st._install.update(state='idle', step='', error='')

    def test_status_idle_and_command(self):
        v = self.c.get('/api/settings/tools/install').json()
        self.assertEqual(v['state'], 'idle')
        self.assertIn('winget install --id yt-dlp.FFmpeg', v['command'])
        self.assertIn('winget install --id yt-dlp.yt-dlp', v['command'])
        self.assertIn('--source winget', v['command'])

    def test_post_needs_the_header(self):
        self.assertEqual(self.c.post('/api/settings/tools/install').status_code, 403)
        self.assertEqual(self.c.post('/api/settings/tools/install/terminal').status_code, 403)
        self.assertEqual(self.c.post('/api/settings/tools/install/terminal', headers={**W, 'Authorization': 'Bearer wrong'}).status_code, 403)

    @unittest.skipUnless(os.name == 'nt', 'the terminal is Windows only')
    def test_terminal_is_explicit_fixed_and_handles_denied_elevation(self):
        import ctypes
        from server.routes import settings as st
        with mock.patch.object(ctypes.windll.shell32, 'ShellExecuteW', return_value=42) as launch:
            result = self.c.post('/api/settings/tools/install/terminal', headers=W, json={'command': 'ignored-untrusted-command'})
        self.assertEqual(result.status_code, 200)
        args = launch.call_args.args
        self.assertEqual(args[1], 'runas')
        self.assertTrue(args[2].endswith('System32\\cmd.exe'))
        self.assertEqual(args[3], '/d /k ' + st.INSTALL_COMMAND.replace('\n', ' & '))
        self.assertEqual(args[5], 1)
        with mock.patch.object(ctypes.windll.shell32, 'ShellExecuteW', return_value=5):
            self.assertEqual(self.c.post('/api/settings/tools/install/terminal', headers=W).status_code, 409)
        st._install['state'] = 'running'
        with mock.patch.object(ctypes.windll.shell32, 'ShellExecuteW') as launch:
            self.assertEqual(self.c.post('/api/settings/tools/install/terminal', headers=W).status_code, 409)
            self.assertEqual(self.c.post('/api/settings/tools/install', headers=W).status_code, 409)
        launch.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'winget is Windows only')
    def test_install_runs_winget_without_a_console_window(self):
        from server.routes import settings as st
        ran = []

        def fake_run(cmd, **kw):
            ran.append((cmd, kw))
            return subprocess.CompletedProcess(cmd, 0, '', '')
        views = [self.view(['yt-dlp', 'ffmpeg', 'ffprobe', 'deno']), self.view(['ffmpeg', 'ffprobe', 'deno']), self.view(['deno']), self.view()]
        with mock.patch.object(st, 'tools_view', side_effect=views), mock.patch.object(st.shutil, 'which', return_value='C:/winget.exe'), mock.patch.object(st.subprocess, 'run', fake_run):
            st._run_install()
        self.assertEqual([c[0][3] for c in ran], ['yt-dlp.yt-dlp', 'yt-dlp.FFmpeg', 'DenoLand.Deno'])
        self.assertTrue(all(c[1]['creationflags'] == app_paths.NO_WINDOW for c in ran))
        self.assertEqual(st._install['state'], 'done')

    def test_install_without_winget_reports_it(self):
        from server.routes import settings as st
        with mock.patch.object(st, 'tools_view', return_value=self.view(['deno'])), mock.patch.object(st.shutil, 'which', lambda n: None):
            st._run_install()
        self.assertEqual(st._install['state'], 'error')
        self.assertIn('winget was not found', st._install['error'])


class MessagesTest(unittest.TestCase):
    def test_messages_point_to_settings(self):
        for msg in (video_analyzer.FFMPEG_MISSING, ytdlp.NOT_FOUND):
            self.assertIn('Settings > Tools', msg)
            self.assertNotIn('restart', msg.lower())

    def test_missing_ffmpeg_names_the_tool(self):
        with mock.patch.object(subprocess, 'run', side_effect=FileNotFoundError):
            with self.assertRaises(RuntimeError) as cm:
                video_analyzer.extract_audio_compressed('x.mp4', str(tempfile.gettempdir()))
        self.assertEqual(str(cm.exception), video_analyzer.FFMPEG_MISSING)

    def test_missing_ytdlp_on_launch(self):
        with mock.patch.object(subprocess, 'Popen', side_effect=FileNotFoundError):
            ok, rc, hint = ytdlp._run_streaming(['yt-dlp'], 'https://example.com/v', '.', lambda s: None, lambda: False)
        self.assertEqual((ok, rc, hint), (False, -1, ytdlp.NOT_FOUND))


if __name__ == '__main__':
    unittest.main()
