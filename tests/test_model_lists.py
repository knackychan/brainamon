"""Model lists fetched from the providers (projects/model-lists/PLAN.md): the filter, the merge
after the built-in lists, the DB cache and POST /api/settings/models/refresh. No network: the
provider call is a mock.

Run from the project root:  py -m unittest tests.test_model_lists -v
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client, config
from core.db import Database
from library import ytdlp
from server.app import create_app
from tests import test_phone_js

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}
REFRESH = '/api/settings/models/refresh'


class FilterTest(unittest.TestCase):
    def test_openai_keeps_chat_models_newest_first(self):
        rows = [NS(id='gpt-5.4-mini', created=2), NS(id='gpt-7', created=9), NS(id='o5-pro', created=5),
                NS(id='gpt-4o-2024-08-06', created=8), NS(id='text-embedding-3-small', created=7),
                NS(id='gpt-4o-realtime-preview', created=6), NS(id='gpt-4.1', created=4),
                NS(id='dall-e-3', created=3)]
        ids = [m['id'] for m in ai_client.chat_models_from_list('openai', rows)]
        self.assertEqual(ids, ['gpt-7', 'o5-pro', 'gpt-5.4-mini'])

    def test_anthropic_uses_display_name_and_keeps_order(self):
        rows = [NS(id='claude-opus-5-5', display_name='Claude Opus 5.5'), NS(id='claude-haiku-5-5', display_name='')]
        self.assertEqual(ai_client.chat_models_from_list('anthropic', rows),
                         [{'id': 'claude-opus-5-5', 'label': 'Claude Opus 5.5'},
                          {'id': 'claude-haiku-5-5', 'label': 'claude-haiku-5-5'}])

    def test_found_models_come_after_the_built_in_ones(self):
        built_in = ai_client.feature_models('openai')
        extra = {'id': 'gpt-7', 'label': 'gpt-7'}
        self.assertEqual(ai_client.feature_models('openai', [extra, built_in[0]]), built_in + [extra])
        self.assertEqual(ai_client.feature_models('nope', [extra]), [])
        phone = ai_client.phone_settings('anthropic', 'm', found={'anthropic': [{'id': 'claude-x', 'label': 'X'}]})
        self.assertEqual(phone['ask']['models']['anthropic'][-1], {'id': 'claude-x', 'label': 'X'})


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneFilterTest(unittest.TestCase):
    """More > Wiskit > Refresh on the phone (web/src/mobile/ai/providers.ts chatModels) keeps the same
    models as chat_models_from_list, retired ids taken from phone_settings."""
    def test_the_phone_filter_matches(self):
        rows = {'openai': [{'id': 'gpt-5.4-mini', 'created': 2}, {'id': 'gpt-7', 'created': 9}, {'id': 'o5-pro', 'created': 5},
                           {'id': 'gpt-4o-2024-08-06', 'created': 8}, {'id': 'text-embedding-3-small', 'created': 7},
                           {'id': 'gpt-4o-realtime-preview', 'created': 6}, {'id': 'gpt-4.1', 'created': 4},
                           {'id': 'dall-e-3', 'created': 3}],
                'anthropic': [{'id': 'claude-opus-5-5', 'display_name': 'Claude Opus 5.5'},
                              {'id': 'claude-haiku-5-5', 'display_name': ''}, {'id': 'claude-opus-5-5'}]}
        retired = ai_client.phone_settings('anthropic', 'm')['retired']
        got = json.loads(test_phone_js.node(
            "import { chatModels } from './web/src/mobile/ai/providers.ts'\n"
            f"const rows = {json.dumps(rows)}, retired = {json.dumps(retired)}\n"
            "console.log(JSON.stringify({ openai: chatModels('openai', rows.openai, retired), anthropic: chatModels('anthropic', rows.anthropic, retired) }))"))
        for p, r in rows.items():
            self.assertEqual(got[p], ai_client.chat_models_from_list(p, [NS(**x) for x in r]), p)


class RefreshTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.data = self.root / 'data'
        Database(self.data / 'content_manager.db').close()
        env = {'ANTHROPIC_API_KEY': 'sk-ant-test', 'OPENAI_API_KEY': '', 'FREELLMAPI_API_KEY': '',
               config.LOCAL_OPENAI_BASE_URL: ''}
        for p in (mock.patch.object(config, 'ENV_PATH', self.root / '.env'),
                  mock.patch.object(ytdlp, 'registry_get', lambda name: ''),
                  mock.patch.dict(os.environ, env)):
            p.start()
            self.addCleanup(p.stop)
        self.c = TestClient(create_app(data_dir=self.data, port=8765, web_dist=self.root / 'x', cards_dir=self.root / 'x',
                                       cloud_dir=self.root / 'cloud'), base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def test_refresh_saves_the_list_and_feeds_every_picker(self):
        new = {'id': 'claude-new-9', 'label': 'Claude New 9'}
        with mock.patch.object(ai_client, 'discover_cloud_models', return_value=[new]) as disc:
            r = self.c.post(REFRESH, json={}, headers=W).json()
        disc.assert_called_once_with('anthropic', 'sk-ant-test')
        self.assertEqual(r['results']['anthropic'], {'ok': True, 'count': 1, 'error': ''})
        self.assertEqual(r['results']['openai'], {'ok': False, 'count': 0, 'error': 'No API key saved.'})
        self.assertEqual(r['models']['models']['anthropic'][-1], new)
        self.assertTrue(r['models']['found_at']['anthropic'])
        self.assertEqual(self.c.get('/api/settings').json()['models']['models']['anthropic'][-1], new)
        self.assertEqual(self.c.get('/api/ask/options').json()['models']['anthropic'][-1]['id'], 'claude-new-9')
        put = self.c.put('/api/settings', json={'models': {'jarvis': {'provider': 'anthropic', 'model': 'claude-new-9'}}},
                         headers=W)
        self.assertEqual(put.status_code, 200)
        self.assertEqual(put.json()['models']['jarvis'], {'provider': 'anthropic', 'model': 'claude-new-9'})

    def test_a_failed_refresh_keeps_the_previous_list(self):
        with mock.patch.object(ai_client, 'discover_cloud_models', return_value=[{'id': 'claude-a', 'label': 'A'}]):
            self.c.post(REFRESH, json={}, headers=W)
        with mock.patch.object(ai_client, 'discover_cloud_models', side_effect=RuntimeError('401 invalid key')):
            r = self.c.post(REFRESH, json={}, headers=W).json()
        self.assertEqual(r['results']['anthropic'], {'ok': False, 'count': 0, 'error': '401 invalid key'})
        self.assertEqual(r['models']['models']['anthropic'][-1]['id'], 'claude-a')

    def test_unknown_model_still_refused_and_header_required(self):
        bad = self.c.put('/api/settings', json={'models': {'jarvis': {'provider': 'anthropic', 'model': 'claude-nope'}}},
                         headers=W)
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.c.post(REFRESH, json={}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
