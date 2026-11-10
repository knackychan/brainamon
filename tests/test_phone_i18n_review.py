"""Review packet escaping, branch coverage, honest image links and output boundary."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('phone_review', ROOT/'projects/phone-languages/review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class PhoneReviewTest(unittest.TestCase):
    def test_all_branches_and_hostile_text_are_escaped_and_missing_screenshots_honest(self):
        hostile = '<script>alert("x")</script><a:bad>{name}</a>'
        data = dict(catalogs={language: {'common.plural': {'one': hostile, 'many': 'Many {n}', 'other': 'Other {n}'}}
                              for language, _ in review.LANGUAGES}, budgets={'common.plural': {'limit': 80, 'params': {'name': hostile}}})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            status = root/'local/i18n-review/09-validation-status.json'
            status.parent.mkdir(parents=True)
            status.write_text(hostile, encoding='utf-8')
            for name in ('08-policy-comparison.json', '08-source-revisions.json', '08-website-articles.json', '09-model-samples.json'):
                (status.parent/name).write_text(hostile, encoding='utf-8')
            target = review.write_report(root, data)
            self.assertEqual(target, root/'local/i18n-review/index.html')
            text = target.read_text(encoding='utf-8')
            self.assertNotIn('<script>', text)
            self.assertIn('&lt;script&gt;', text)
            for branch in ('one:', 'many:', 'other:'):
                self.assertEqual(text.count(branch), 3)
            self.assertIn('No key-specific screenshot', text)
            self.assertIn('n, name', text)
            self.assertIn('Links: bad', text)
            self.assertIn('lang="zh-Hant-TW"', text)
            for name in ('08-policy-comparison.json', '08-source-revisions.json', '08-website-articles.json', '09-model-samples.json'):
                self.assertIn('<summary>' + name + '</summary><pre>&lt;script&gt;', text)

    def test_output_path_rejects_redirected_local_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            original = Path.resolve
            def redirected(path, *args, **kwargs):
                return root/'elsewhere/index.html' if path.name == 'index.html' else original(path, *args, **kwargs)
            with mock.patch.object(Path, 'resolve', redirected), self.assertRaises(ValueError):
                review.output_path(root)

    def test_scene_claim_requires_existing_specific_image(self):
        data = dict(catalogs={language: {'canvas.waitingBackup': 'Original title'} for language, _ in review.LANGUAGES}, budgets={})
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'local/i18n-review';out.mkdir(parents=True)
            self.assertIn('No key-specific screenshot', review.render(root,data))
            (out/'09-fr-light-missing-backup.png').write_bytes(b'synthetic')
            text=review.render(root,data)
            self.assertIn('Missing-backup scene',text)
            self.assertNotIn('No key-specific screenshot',text)
