"""The registry name migration for Start with Windows; no real registry writes."""
import sys
import unittest
from unittest import mock

from desktop import autostart


class Key:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Registry:
    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self, values=None, fail_write=False):
        self.values = dict(values or {})
        self.fail_write = fail_write

    def OpenKey(self, *args):
        return Key()

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, _reserved, _kind, value):
        if self.fail_write:
            raise OSError('write failed')
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


class AutostartMigrationTest(unittest.TestCase):
    def run_with(self, registry, fn):
        with mock.patch.object(autostart.sys, 'platform', 'win32'), \
                mock.patch.dict(sys.modules, {'winreg': registry}), \
                mock.patch.object(autostart, 'command', return_value='"Brainamon.exe" --background'):
            return fn()

    def test_read_migrates_old_values_after_writing_the_new_command(self):
        for old in ('Content Manager',):
            with self.subTest(old=old):
                registry = Registry({old: 'old command'})
                self.assertTrue(self.run_with(registry, autostart.is_on))
                self.assertEqual(registry.values, {'Brainamon': '"Brainamon.exe" --background'})

    def test_failed_write_keeps_old_autostart_values(self):
        registry = Registry({'Content Manager': 'old command'}, fail_write=True)
        with self.assertRaisesRegex(OSError, 'write failed'):
            self.run_with(registry, lambda: autostart.set_on(True))
        self.assertEqual(registry.values, {'Content Manager': 'old command'})

    def test_turning_autostart_off_removes_all_supported_names(self):
        registry = Registry({'Brainamon': 'new', 'Content Manager': 'older'})
        self.assertFalse(self.run_with(registry, lambda: autostart.set_on(False)))
        self.assertEqual(registry.values, {})


if __name__ == '__main__':
    unittest.main()
