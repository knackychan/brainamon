"""Synthetic credentials only. No personal profiles, cookies or live sites."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import site_sessions as ss

JAR = b'# Netscape HTTP Cookie File\n#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tsynthetic-secret\n'
MIXED = JAR + b'.facebook.com\tTRUE\t/\tFALSE\t0\tlogin\tother-secret\n'


class ParserTest(unittest.TestCase):
    def test_header_and_strict_records(self):
        raw, info = ss.parse_cookies(JAR, 'instagram')
        self.assertEqual(info['usable'], 1)
        self.assertEqual(info['domains'], ['.instagram.com'])
        self.assertNotIn('synthetic-secret', json.dumps(info))
        for value in (b'# Netscape HTTP Cookie File\n', JAR.replace(b'TRUE', b'maybe'),
                      JAR.replace(b'\t0\t', b'\t-1\t'), JAR.replace(b'\t/\t', b'\tbad\t'),
                      JAR.replace(b'.instagram.com', b'bad..domain'), b'x' * (ss.MAX_BYTES + 1)):
            with self.subTest(value=value[:35]), self.assertRaises(ValueError):
                ss.parse_cookies(value)

    def test_filter_and_expired(self):
        raw, info = ss.parse_cookies(MIXED + JAR.split(b'\n')[1].replace(b'\t0\t', b'\t1\t') + b'\n', 'instagram')
        self.assertNotIn(b'other-secret', raw)
        self.assertEqual((info['usable'], info['expired']), (1, 1))
        with self.assertRaises(ValueError):
            ss.parse_cookies(JAR, 'reddit')

    def test_hostname_boundaries(self):
        self.assertEqual(ss.site_for('https://m.instagram.com/p/1'), 'instagram')
        self.assertEqual(ss.site_for('https://youtu.be/selected'), 'youtube')
        for url in ('https://instagram.com.evil/x', 'https://evil/?instagram.com',
                    'https://instagram.com@evil/x', 'https://evil/instagram.com', 'file://instagram.com'):
            self.assertEqual(ss.site_for(url), '')

    def test_state_origin_and_cookie_validation(self):
        state = {'cookies': [], 'origins': [{'origin': 'https://www.instagram.com', 'localStorage': [{'name': 'key', 'value': 'synthetic-secret'}]}]}
        ss.validate_state(json.dumps(state).encode(), 'instagram')
        for origin in ('https://instagram.com.evil', 'http://instagram.com', 'https://instagram.com@evil', 'https://instagram.com/path'):
            state['origins'][0]['origin'] = origin
            with self.assertRaises(ValueError):
                ss.validate_state(json.dumps(state).encode(), 'instagram')


class StorageTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name) / 'sessions'
        p = mock.patch.object(ss, 'ROOT', self.root)
        p.start(); self.addCleanup(p.stop)

    def fake_crypto(self):
        for p in (mock.patch.object(ss, '_acl'), mock.patch.object(ss, '_crypt', side_effect=lambda raw, decrypt=False: raw[::-1])):
            p.start(); self.addCleanup(p.stop)

    def test_atomic_failure_preserves_secret(self):
        self.fake_crypto()
        ss.save('instagram', JAR)
        before = ss.load('instagram')
        with mock.patch.object(ss.os, 'replace', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                ss.save('instagram', JAR.replace(b'synthetic-secret', b'replacement'))
        self.assertEqual(ss.load('instagram'), before)
        self.assertFalse(list(self.root.glob('*.new')))

    def test_cleanup_and_failed_refresh(self):
        self.fake_crypto()
        ss.save('instagram', JAR)
        with self.assertRaises(RuntimeError):
            with ss.cookies('https://instagram.com') as path:
                self.assertIn(b'synthetic-secret', path.read_bytes())
                path.write_bytes(JAR.replace(b'synthetic-secret', b'new'))
                raise RuntimeError('child failed')
        self.assertEqual(ss.load('instagram'), JAR)
        self.assertEqual(list((self.root / 'temp').iterdir()), [])
        with ss.cookies('https://instagram.com') as path:
            path.write_bytes(b'invalid child jar')
        self.assertEqual(ss.load('instagram'), JAR)

    def test_forget_overrides_snapshot_env_registry_cwd(self):
        self.fake_crypto()
        original = self.root.parent / 'cookies.txt'
        original.write_bytes(JAR)
        snap = {'instagram_cookies': str(original), 'yt_dlp_cookies': str(original),
                'session_mode_instagram': 'legacy', 'session_mode_general': 'legacy'}
        ss.save('instagram', JAR)
        with ss.cookies('https://instagram.com', [snap.get]) as path:
            ss.forget(['instagram'])
            path.write_bytes(JAR)
        self.assertFalse((self.root / 'instagram.bin').exists())
        with mock.patch.dict(os.environ, {'YTDLP_COOKIES': str(original)}):
            with ss.cookies('https://instagram.com', [snap.get]) as path:
                self.assertIsNone(path)
        self.assertEqual(original.read_bytes(), JAR)

    def test_no_new_implicit_discovery_and_legacy_original_unchanged(self):
        self.fake_crypto()
        original = self.root.parent / 'cookies.txt'; original.write_bytes(JAR)
        with mock.patch.dict(os.environ, {'YTDLP_COOKIES': str(original)}):
            with ss.cookies('https://instagram.com') as path:
                self.assertIsNone(path)
        with ss.cookies('https://instagram.com', [{'session_mode_instagram': 'legacy', 'instagram_cookies': str(original)}.get]) as path:
            self.assertNotEqual(path, original)
            path.write_bytes(b'changed')
        self.assertEqual(original.read_bytes(), JAR)

    def test_remember_is_opt_in_and_forget_blocks_active_writeback(self):
        self.fake_crypto()
        raw = b'{"cookies": [], "origins": []}'
        with ss.browser_state('facebook') as path:
            path.write_bytes(raw)
        self.assertFalse((self.root / 'browser-facebook.bin').exists())
        with ss.browser_state('facebook', True) as path:
            path.write_bytes(raw)
        self.assertEqual(ss.load('browser-facebook'), raw)
        with ss.browser_state('facebook', True) as path:
            path.write_bytes(raw)
            ss.forget(['browser-facebook'])
        self.assertFalse((self.root / 'browser-facebook.bin').exists())
        with ss.browser_state('facebook', True) as path:
            path.write_bytes(raw)
        self.assertEqual(ss.mode('browser-facebook'), 'protected')

    @unittest.skipUnless(ss.supported(), 'Windows DPAPI and ACL required')
    def test_real_windows_dpapi_acl_roundtrip_and_stale_cleanup(self):
        ss.save('instagram', JAR)
        self.assertNotIn(b'synthetic-secret', (self.root / 'instagram.bin').read_bytes())
        self.assertEqual(ss.load('instagram'), JAR)
        with ss.cookies('https://instagram.com') as path:
            ss.cleanup_stale()
            self.assertTrue(path.exists())
        stale = self.root / 'temp' / (str(os.getpid()) + '-' + 'f' * 32)
        stale.mkdir(); (stale / 'access.txt').write_bytes(JAR)
        ss.cleanup_stale()
        self.assertFalse(stale.exists())

    def test_acl_failure_fails_closed(self):
        with mock.patch.object(ss, '_crypt', return_value=b'encrypted'), mock.patch.object(ss, '_acl', side_effect=OSError('ACL')):
            with self.assertRaises(OSError):
                ss.save('instagram', JAR)
        self.assertFalse((self.root / 'instagram.bin').exists())

    def test_other_user_unlock_failure_and_corrupt_policy_fail_closed(self):
        self.fake_crypto()
        ss.save('instagram', JAR)
        with mock.patch.object(ss, '_crypt', side_effect=RuntimeError('Cannot unlock on this PC')):
            self.assertEqual(ss.summary('instagram')['status'], 'Cannot unlock on this PC')
        (self.root / 'modes.json').write_text('broken')
        with self.assertRaises(RuntimeError):
            with ss.cookies('https://instagram.com', [{'session_mode_instagram': 'legacy'}.get]):
                self.fail('corrupt policy enabled legacy fallback')
        ss.save('instagram', JAR)  # explicit re-import repairs policy with other slots disabled
        self.assertEqual(ss.mode('general'), 'disabled')

    def test_browser_cookie_reuse_requires_explicit_scoped_commit(self):
        self.fake_crypto()
        state = {'cookies': [{'domain': '.instagram.com', 'path': '/', 'expires': -1, 'name': 'sessionid',
                              'value': 'synthetic-secret', 'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}], 'origins': []}
        ss.save('browser-instagram', json.dumps(state).encode())
        review = ss.reuse_browser('instagram')
        self.assertFalse((self.root / 'instagram.bin').exists())
        with self.assertRaises(ValueError):
            ss.reuse_browser('instagram', True, 'stale-review')
        ss.reuse_browser('instagram', True, review['digest'])
        self.assertEqual(ss.parse_cookies(ss.load('instagram'))[1]['domains'], ['.instagram.com'])
        self.assertNotIn(b'localStorage', ss.load('instagram'))

    def test_cleanup_failure_is_not_reported_as_success(self):
        self.fake_crypto()
        with mock.patch.object(ss.shutil, 'rmtree', side_effect=PermissionError('file locked')):
            with self.assertRaises(PermissionError):
                with ss.temporary('.txt') as path:
                    path.write_bytes(JAR)
