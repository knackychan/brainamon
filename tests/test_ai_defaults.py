"""Unified Wiskit defaults, legacy fallback, video overrides and phone synthesis."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core import ai_client, ai_defaults
from core.db import Database
from server.job_kinds import _analysis_ctx


class WiskitDefaultsTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.db = Database(Path(td.name) / 'content_manager.db')
        self.addCleanup(self.db.close)
        self.choice = (ai_client.ASK_PROVIDER_OPENAI, ai_client.ask_default_model(ai_client.ASK_PROVIDER_OPENAI))

    def assert_all(self, expected):
        for feature in (ai_defaults.DESCRIBE, ai_defaults.CATEGORIZE, ai_defaults.SYNTHESIZE,
                        ai_defaults.SUMMARIZE, ai_defaults.VIDEO, ai_defaults.CONNECTIONS):
            with self.subTest(feature=feature):
                self.assertEqual(ai_defaults.get(self.db, feature), expected)

    def test_fallback_and_unified_choice_preserve_legacy_rows(self):
        self.assert_all(ai_defaults._DEFAULT)
        old = json.dumps(dict(zip(('provider', 'model'), self.choice)))
        self.db.set_setting('ai_model_describe', old)
        self.db.set_setting('ai_model_video', json.dumps({'provider': 'ignored', 'model': 'ignored'}))
        self.assert_all(self.choice)
        ai_defaults.set(self.db, ai_defaults.SUMMARIZE, *ai_defaults._DEFAULT)
        self.assert_all(ai_defaults._DEFAULT)
        self.assertEqual(self.db.get_setting('ai_model_describe'), old)
        self.assertIn('ignored', self.db.get_setting('ai_model_video'))

    def test_malformed_choices(self):
        for key in ('ai_model_describe', ai_defaults.WISKIT_KEY):
            for raw in ('', '{', 'null', '[]', '3', '{}', '{"provider":[],"model":{}}',
                        '{"provider":"openai","model":""}'):
                with self.subTest(key=key, raw=raw):
                    self.db.set_setting(key, raw)
                    self.assert_all(ai_defaults._DEFAULT)

    def test_retired_ids_and_phone_synthesis(self):
        for retired, current in ai_client.RETIRED_MODELS.items():
            ai_defaults.set(self.db, ai_defaults.DESCRIBE, self.choice[0], retired)
            self.assert_all((self.choice[0], current))
        ai_defaults.set(self.db, ai_defaults.DESCRIBE, *self.choice)
        phone = ai_client.phone_settings(*ai_defaults.get(self.db, ai_defaults.SYNTHESIZE))
        self.assertEqual(phone['synth'], dict(zip(('provider', 'model'), self.choice)))
        self.assertEqual(ai_client.cheap_model(ai_defaults.get(self.db, ai_defaults.CONNECTIONS)[0]),
                         ai_client.cheap_model(self.choice[0]))

    @mock.patch('library.video_analyzer.preflight', return_value='')
    @mock.patch('core.config.analysis_key_for', return_value='test-key')
    @mock.patch('core.config.openai_api_key', return_value='test-key')
    def test_video_default_and_explicit_override(self, *_):
        ai_defaults.set(self.db, ai_defaults.VIDEO, *self.choice)
        self.db.set_setting('analyze_options', json.dumps({'analysis_provider': 'claude'}))
        for opts, provider, model in (({}, 'openai', self.choice[1]),
                                      ({'analysis_provider': 'claude'}, 'claude', None),
                                      ({'analysis_provider': 'none'}, 'none', None)):
            job = SimpleNamespace(opts=opts, ctx={})
            _analysis_ctx(self.db, job)
            self.assertEqual((job.ctx['provider'], job.ctx['model']), (provider, model))
        ai_defaults.set(self.db, ai_defaults.VIDEO, *ai_defaults._DEFAULT)
        job = SimpleNamespace(opts={}, ctx={})
        _analysis_ctx(self.db, job)
        self.assertEqual((job.ctx['provider'], job.ctx['model']), ('openai', ai_defaults._DEFAULT[1]))
