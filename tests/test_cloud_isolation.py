"""Test app factories must never fall back to the user's cloud credentials."""
import ast
from pathlib import Path
import unittest


class CloudIsolationTest(unittest.TestCase):
    def test_app_fixtures_supply_cloud_folder(self):
        for path in Path(__file__).parent.glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, 'id', getattr(node.func, 'attr', ''))
                if name != 'create_app':
                    continue
                with self.subTest(file=path.name, line=node.lineno):
                    folders = [k.value for k in node.keywords if k.arg == 'cloud_dir']
                    self.assertTrue(folders, 'Pass a temporary cloud_dir explicitly')
                    for folder in folders:
                        self.assertNotEqual(ast.dump(folder), ast.dump(ast.Constant(None)))

    def test_default_cloud_folder_is_a_temporary_one(self):
        """An app or service built without a cloud folder (create_app's default) must not land in local/cloud/."""
        from server import settings
        from tests import cloud_guard
        self.assertNotEqual(Path(settings.CLOUD_DIR).resolve(), cloud_guard.REAL.resolve())
        self.assertTrue(Path(settings.CLOUD_DIR).is_dir())
        self.assertEqual(Path(settings.CLOUD_DIR).resolve(), cloud_guard.FOLDER.resolve())
