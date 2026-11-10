"""Phone fixes of the 2026-10-14 milestone (projects/milestone-2026-10-14/plans/E-phone-fixes.md): where Back
goes, the Library box over the full text, Describe / Categorize prompts against the PC's, and the PC
accepting an `ai_desc` edit."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from knowledge import tasks
from tests import test_phone_js
from tests.test_phone_js import _node_ok, node
from tests.test_phone_mirror import ChangeIntakeTest

CATS = ['SPORT', 'COOKING', 'INTERESTING']
ITEMS = [
    {'id': 11, 'category': 'COOKING', 'creator': 'chef', 'type': 'Reel', 'description': 'Breakfast bowl in five minutes', 'short_desc': 'Fast breakfast ideas',
     'url': 'https://www.instagram.com/reel/X/', 'analysis_done': 0, 'transcript': ''},
    {'id': 12, 'category': 'AI', 'creator': 'dev', 'type': 'Video', 'description': 'Build a local search tool', 'short_desc': 'Build a local search tool',
     'url': 'https://youtu.be/abc', 'analysis_done': 0, 'transcript': ''},
    {'id': 13, 'category': 'SPORT', 'creator': 'coach', 'type': 'Reel', 'description': 'Knee prehab', 'short_desc': 'A gentle warm-up',
     'url': 'https://www.facebook.com/reel/1', 'analysis_done': 1, 'transcript': '  Step one, warm up.  '},
    {'id': 14, 'category': 'X', 'creator': '', 'type': 'Post', 'description': 'A useful discussion',
     'url': 'https://www.reddit.com/r/a/comments/b/c/', 'analysis_done': 0, 'transcript': ''},
    {'id': 15, 'category': 'SPORT', 'creator': 'r/bodyweightfitness', 'type': 'Post',
     'description': 'Knee drill\n\nDo it daily.\n\nTop comments:\n- u/a (12): Works for me',
     'url': 'https://www.reddit.com/r/bodyweightfitness/comments/b/c/', 'analysis_done': 0, 'transcript': ''},
    {'id': 16, 'category': 'X', 'creator': '', 'type': 'Post', 'description': 'NO_CONTENT', 'notes': 'Specific note',
     'url': 'https://example.com/16', 'analysis_done': 0, 'transcript': 'NO_CONTENT'},
]
REPLIES = ['{"category": "cooking", "tags": "Recipe, Breakfast"}', '```json\n{"category": "SPORT", "tags": ""}\n```',
           'Sure: {"category": "SPORT", "tags": "mobility"} done', '{"category": "NOPE", "tags": "x"}', 'no json here']
ROWS = [
    {'id': 1, 'title': 'Pancakes', 'creator': 'x', 'tags': '', 'desc': '', 'cat': 'COOKING', 'url': 'https://x.test/a'},
    {'id': 2, 'title': 'Eggs', 'creator': 'x', 'tags': '', 'desc': '', 'cat': 'COOKING', 'url': 'https://x.test/a'},
    {'id': 3, 'title': 'Breakfast bowl', 'creator': 'x', 'tags': '', 'desc': '', 'cat': 'COOKING', 'url': 'https://x.test/a'},
    {'id': -1, 'title': 'Breakfast burrito', 'creator': 'x', 'tags': '', 'desc': '', 'cat': 'COOKING', 'url': 'https://x.test/p'},
]
ROUTES = [
    {'tab': 'lib'}, {'tab': 'lib', 'item': 5}, {'tab': 'cv', 'canvas': 'abc'}, {'tab': 'cv', 'canvas': None},
    {'tab': 'cap'}, {'tab': 'notes', 'note': 'a.md'}, {'tab': 'notes', 'mynote': 'b.md'}, {'tab': 'notes', 'synth': ''},
    {'tab': 'notes'}, {'tab': 'jv', 'chats': True}, {'tab': 'jv', 'chats': False}, {'tab': 'cap', 'imp': True}, {'tab': 'more'},
]


def py_describe(item: dict, thumb: bool) -> str:
    """The prompt tasks.describe_item builds, caught at the model call."""
    got = {}

    def fake(provider, model, prompt='', images=None, max_tokens=0, **kw):
        got['prompt'] = prompt
        return 'ok'

    with tempfile.TemporaryDirectory() as d:
        if thumb:
            p = Path(d) / 'items' / str(item['id'])
            p.mkdir(parents=True)
            (p / 'thumb.jpg').write_bytes(b'x')
        with mock.patch.object(tasks.ai_client, 'complete_vision', fake):
            tasks.describe_item(item, 'anthropic', 'm', d)
    return got['prompt']


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneFixesTest(unittest.TestCase):
    def test_back_goes_to_the_parent_screen(self):
        out = json.loads(node("""
            import { parentHash } from './web/src/mobile/back.ts'
            console.log(JSON.stringify(__DATA__.map(r => parentHash(r))))
        """.replace('__DATA__', json.dumps(ROUTES))))
        self.assertEqual(out, ['', '#/lib', '#/canvas', '#/lib', '#/lib', '#/notes', '#/notes', '#/notes', '#/lib',
                               '#/jv', '#/lib', '#/cap', '#/lib'])

    def test_library_box_uses_the_full_text_ids(self):
        out = json.loads(node(test_phone_js.TS_RESOLVE + """
            const { libraryIds } = await import('./web/src/mobile/source/find.ts')
            const rows = __ROWS__
            console.log(JSON.stringify([
              libraryIds(rows, 'breakfast', [2, 1, 99]),
              libraryIds(rows, 'breakfast', null),
              libraryIds(rows, '2', [1]),
              libraryIds(rows, 'breakfast', []),
            ]))
        """.replace('__ROWS__', json.dumps(ROWS))))
        self.assertEqual(out[0], [2, 1, -1])    # the full-text ids (99 is gone), then the phone-only link
        self.assertEqual(out[1], [3, -1])       # no search text yet: the old scan over the rows
        self.assertEqual(out[2], [2, 1])        # a whole number also means that item, first
        self.assertEqual(out[3], [-1])          # nothing in the full text, the phone link still matches

    def test_describe_and_categorize_prompts_match_the_pc(self):
        out = json.loads(node("""
            import { describePrompt, categorizeSystem, categorizeUser, parseCategory, mergeTags } from './web/src/mobile/ai/describe.ts'
            const D = __DATA__
            console.log(JSON.stringify({
              describe: D.items.flatMap(it => [describePrompt(it, true), describePrompt(it, false)]),
              system: categorizeSystem(D.cats),
              user: D.items.map(it => categorizeUser(it)),
              parse: D.replies.map(t => { try { return parseCategory(t, D.cats) } catch (e) { return String(e.message) } }),
              merge: [mergeTags('a, b', 'B, c'), mergeTags('', 'x, y'), mergeTags('keep', '')],
            }))
        """.replace('__DATA__', json.dumps({'items': ITEMS, 'cats': CATS, 'replies': REPLIES}))))
        want = []
        for it in ITEMS:
            analysed = bool(it['analysis_done'])
            want += [py_describe(it, True), py_describe(it, False)]
            if analysed:      # a transcript wins over the thumbnail on the PC: both forms are the same text
                self.assertEqual(want[-1], want[-2])
        self.assertEqual(out['describe'], want)
        for index, item in enumerate(ITEMS):
            if item.get('short_desc'):
                for prompt in out['describe'][index * 2:index * 2 + 2]:
                    self.assertIn(item['short_desc'], prompt)
        self.assertEqual(out['system'], tasks.categorize_system_prompt(CATS))
        self.assertEqual(out['user'], [tasks.categorize_user_prompt(it, CATS, 'anthropic') for it in ITEMS])
        self.assertEqual(out['parse'][:4], [
            {'category': 'COOKING', 'tags': 'recipe, breakfast'}, {'category': 'SPORT', 'tags': ''},
            {'category': 'SPORT', 'tags': 'mobility'}, {'category': 'INTERESTING', 'tags': 'x'}])
        self.assertIn('did not answer', out['parse'][4])
        self.assertEqual(out['merge'], ['a, b, c', 'x, y', 'keep'])

    def test_describe_content_rules_match_the_phone(self):
        cases = [
            {'url': 'https://test.com/', 'description': 'test.com'},
            {'url': 'https://www.test.com/', 'description': 'test.com/'},
            {'url': 'https://test.com/', 'description': 'www.test.com'},
            {'url': 'https://www.test.com/', 'description': 'test.com/ A caption'},
            {'url': 'https://test.com/', 'description': 'https://test.com/ A caption'},
            {'url': 'https://test.com/', 'description': 'NO_CONTENT'},
            {'url': 'https://test.com/', 'notes': 'A note'},
            {'url': 'https://test.com/', 'transcript': 'words'},
            {'url': 'https://test.com/', 'report': 'A report'},
        ]
        got = json.loads(node("""
            import { hasDescribeContent } from './web/src/mobile/ai/describe.ts'
            console.log(JSON.stringify(__DATA__.map(it => [hasDescribeContent(it, false), hasDescribeContent(it, true)])))
        """.replace('__DATA__', json.dumps(cases))))
        self.assertEqual(got, [[tasks.has_describe_content(it, False), tasks.has_describe_content(it, True)] for it in cases])
        self.assertEqual([x[0] for x in got], [False, False, False, True, True, False, True, True, True])

    def test_describe_skips_empty_and_sentinel_without_storing(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(tasks.ai_client, 'complete_vision', return_value='NO_CONTENT') as ai:
            bare = {'id': 5, 'url': 'https://test.com/', 'description': 'test.com'}
            self.assertIsNone(tasks.describe_item(bare, 'anthropic', 'm', d))
            ai.assert_not_called()
            self.assertIsNone(tasks.describe_item({**bare, 'description': 'Caption'}, 'anthropic', 'm', d))
            ai.assert_called_once()
            thumb = Path(d) / 'items' / '5' / 'thumb.jpg'
            thumb.parent.mkdir(parents=True)
            thumb.write_bytes(b'image')
            self.assertIsNone(tasks.describe_item(bare, 'anthropic', 'm', d))
            self.assertEqual(ai.call_count, 2)

    def test_mirror_card_does_not_count_sentinel_as_done(self):
        from library import mirror
        item = {'id': 5, 'creator': '', 'type': 'Post', 'category': 'INTERESTING', 'tags': [],
                'description': 'https://test.com/', 'ai_desc': ' NO_CONTENT ', 'url': 'https://test.com/',
                'platform': 'web', 'has_thumb': False, 'processed': True, 'created': 0}
        card = mirror.row(item, None)
        self.assertFalse(card['ai'])
        self.assertEqual(card['desc'], item['description'])
        self.assertEqual(card['title'], item['description'])


class AiDescIntakeTest(ChangeIntakeTest):
    def test_ai_desc_edit_is_applied(self):
        i = self.ids[0]
        self.phone([{'op': 'edit', 'uid': self.uid[i], 'fields': {'ai_desc': 'Written on the phone'},
                     'was': {'ai_desc': self.item(i)['ai_desc'] or ''}}])
        self.assertTrue(self.svc._intake())
        self.assertEqual(self.item(i)['ai_desc'], 'Written on the phone')


def load_tests(loader, tests, pattern):
    # only this module's tests: AiDescIntakeTest borrows ChangeIntakeTest's set-up, not its tests
    suite = unittest.TestSuite(loader.loadTestsFromTestCase(PhoneFixesTest))
    suite.addTest(AiDescIntakeTest('test_ai_desc_edit_is_applied'))
    return suite
