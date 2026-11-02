"""Weekly review: pure date/source/output validation (knowledge/weekly_review.py).

Run from the project root:  py -m unittest tests.test_weekly_review -v
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from knowledge import weekly_review
from core.db import Database

FIXED = datetime(2026, 10, 19, 6, 30, tzinfo=timezone.utc)
ZONE = 'Asia/Taipei'


def req(**over):
    body = {
        'question': 'Review this week',
        'chat': '',
        'mode': 'quick',
        'provider': 'anthropic',
        'model': 'claude-sonnet-5-5',
        'depth': 25,
        'scope': '',
        'attachments': [],
        'task': 'weekly_review',
        'review_at': '2026-10-19T06:30:00.000Z',
        'review_timezone': ZONE,
    }
    body.update(over)
    return body


def window():
    zone = ZoneInfo(ZONE)
    start_utc = datetime(2026, 10, 13, 0, 0, tzinfo=zone).astimezone(timezone.utc)
    through_utc = FIXED.astimezone(timezone.utc)
    return int(start_utc.timestamp() * 1000), int(through_utc.timestamp() * 1000)


def bundle(items=None, notes=None, review=None, coverage=None):
    review = review or {'kind': 'weekly', 'start': '2026-10-13', 'end': '2026-10-19',
                        'timezone': ZONE, 'through': '2026-10-19T06:30:00+00:00'}
    coverage = coverage or {
        'items': {'eligible': len(items or []), 'empty': 0, 'included': len(items or []),
                  'omitted': 0, 'truncated': 0},
        'notes': {'eligible': len(notes or []), 'empty': 0, 'included': len(notes or []),
                  'omitted': 0, 'truncated': 0, 'fallback_eligible': 0, 'fallback_included': 0,
                  'unreadable': 0, 'excluded_reviews': 0},
    }
    return {'review': review, 'items': items or [], 'notes': notes or [], 'rows': [],
            'coverage': coverage}


class RequestTest(unittest.TestCase):
    def test_r01_fixed_window(self):
        self.assertEqual(
            weekly_review.validate_request(req(), now=FIXED),
            {'kind': 'weekly', 'start': '2026-10-13', 'end': '2026-10-19',
             'timezone': ZONE, 'through': '2026-10-19T06:30:00+00:00'})

    def test_r03_dst_window_derives_from_midnight(self):
        at = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
        review = weekly_review.validate_request(req(
            review_at='2026-03-10T12:00:00+00:00', review_timezone='America/New_York'), now=at)
        self.assertEqual((review['start'], review['end']), ('2026-03-04', '2026-03-10'))
        zone = ZoneInfo('America/New_York')
        start = datetime(date.fromisoformat(review['start']).year, date.fromisoformat(review['start']).month,
                         date.fromisoformat(review['start']).day, tzinfo=zone).astimezone(timezone.utc)
        through = datetime.fromisoformat(review['through'])
        self.assertNotEqual(through - start, timedelta(hours=144))

    def test_r04_missing_naive_unknown(self):
        with self.assertRaises(ValueError):
            weekly_review.validate_request(req(review_at=None), now=FIXED)
        with self.assertRaises(ValueError):
            weekly_review.validate_request(req(review_at='2026-10-19T06:30:00'), now=FIXED)
        with self.assertRaises(ValueError):
            weekly_review.validate_request(req(review_timezone='Not/AZone'), now=FIXED)

    def test_r05_clock_skew(self):
        weekly_review.validate_request(req(), now=FIXED + timedelta(seconds=300))
        weekly_review.validate_request(req(), now=FIXED - timedelta(seconds=300))
        with self.assertRaises(ValueError):
            weekly_review.validate_request(req(), now=FIXED + timedelta(seconds=301))
        with self.assertRaises(ValueError):
            weekly_review.validate_request(req(), now=FIXED - timedelta(seconds=301))

    def test_r06_chat_or_attachments_rejected(self):
        with self.assertRaises(ValueError):
            weekly_review.validate_request(req(chat='a-chat'), now=FIXED)
        with self.assertRaises(ValueError):
            weekly_review.validate_request(req(attachments=['x.txt']), now=FIXED)

    def test_r07_r08_metadata_validation(self):
        meta = {'kind': 'weekly', 'start': '2026-05-01', 'end': '2026-05-07',
                'timezone': ZONE, 'through': '2026-05-07T06:30:00+00:00'}
        self.assertEqual(weekly_review.validate_metadata(meta), meta)
        with self.assertRaises(ValueError):
            weekly_review.validate_metadata({**meta, 'extra': 1})
        with self.assertRaises(ValueError):
            weekly_review.validate_metadata({**meta, 'timezone': 'Asia\nTaipei'})
        with self.assertRaises(ValueError):
            weekly_review.validate_metadata({**meta, 'start': '2026-05-02'})
        with self.assertRaises(ValueError):
            weekly_review.validate_metadata({**meta, 'through': '2026-05-07T06:30:00'})
        with self.assertRaises(ValueError):
            weekly_review.validate_metadata('nope')


class CollectTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.db = Database(Path(td.name) / 'content_manager.db')
        self.addCleanup(self.db.close)
        self.start_ms, self.through_ms = window()

    def add(self, **kw):
        return self.db.add_item({'url': kw.pop('url', f'https://x/{kw.get("description", "i")}'),
                                 'created': kw.pop('created', self.start_ms + 1000), **kw})

    def test_r02_boundaries(self):
        at_start = self.add(url='https://x/at-start', description='at start', created=self.start_ms)
        before = self.add(url='https://x/before', description='before', created=self.start_ms - 1)
        through = self.add(url='https://x/through', description='through', created=self.through_ms)
        inside = self.add(url='https://x/inside', description='inside', created=self.start_ms + 1000)
        review = weekly_review.validate_request(req(), now=FIXED)
        got = weekly_review.collect(self.db, self.db.notes_dir, review)
        ids = [i['id'] for i in got['items']]
        self.assertIn(at_start, ids)
        self.assertIn(inside, ids)
        self.assertNotIn(before, ids)
        self.assertNotIn(through, ids)

    def test_s01_s02_created_not_modified(self):
        old = self.add(url='https://x/old', description='old', created=self.start_ms - 10_000)
        self.db.update_item(old, {'description': 'recent edit'})
        review = weekly_review.validate_request(req(), now=FIXED)
        got = weekly_review.collect(self.db, self.db.notes_dir, review)
        self.assertNotIn(old, [i['id'] for i in got['items']])
        self.assertIn('Items use recorded creation dates', weekly_review.compose_answer('', got))

    def test_s03_item_caps_and_counts(self):
        for n in range(1, 54):
            self.add(url=f'https://x/{n}', description='' if n == 1 else 'x', created=self.start_ms + 1000)
        review = weekly_review.validate_request(req(), now=FIXED)
        got = weekly_review.collect(self.db, self.db.notes_dir, review)
        self.assertEqual(got['coverage']['items'], {'eligible': 53, 'empty': 1, 'included': 50,
                                                    'omitted': 2, 'truncated': 0})
        self.assertEqual([i['id'] for i in got['items']], list(range(2, 52)))

    def test_s08_truncation_count(self):
        a = self.add(url='https://x/a', description='a' * weekly_review.L['item_chars'])
        b = self.add(url='https://x/b', description='b' * (weekly_review.L['item_chars'] + 1))
        review = weekly_review.validate_request(req(), now=FIXED)
        got = weekly_review.collect(self.db, self.db.notes_dir, review)
        self.assertEqual(got['coverage']['items']['truncated'], 1)
        self.assertEqual({i['id'] for i in got['items']}, {a, b})

    def test_s09_s10_empty_and_stop(self):
        review = weekly_review.validate_request(req(), now=FIXED)
        empty = weekly_review.collect(self.db, self.db.notes_dir, review)
        self.assertEqual(empty['coverage']['items']['included'], 0)
        self.assertEqual(empty['coverage']['notes']['included'], 0)
        text = weekly_review.compose_answer('', empty)
        self.assertIn('No material found for these dates.', text)
        self.add(url='https://x/one', description='x')
        self.assertIsNone(weekly_review.collect(self.db, self.db.notes_dir, review, should_stop=lambda: True))


class NoteScanTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.db = Database(Path(td.name) / 'content_manager.db')
        self.addCleanup(self.db.close)
        self.notes = self.db.notes_dir
        self.notes.mkdir(parents=True, exist_ok=True)
        self.review = weekly_review.validate_request(req(), now=FIXED)

    def write(self, name, body, front=''):
        (self.notes / name).write_text(f'---\n{front}---\n\n{body}', encoding='utf-8')

    def test_s04_note_caps_and_exclusion(self):
        for n in range(1, 33):
            self.write(f'note-{n:02d}.md', 'hello', 'topic: N\nupdated: 2026-10-15\n')
        self.write('note-33.md', '', 'topic: Empty\nupdated: 2026-10-15\n')
        self.write('note-34.md', 'old', 'topic: Prior\nreview_kind: weekly\nupdated: 2026-10-15\n')
        got = weekly_review.collect(self.db, self.notes, self.review)
        cov = got['coverage']['notes']
        self.assertEqual((cov['eligible'], cov['empty'], cov['included'], cov['omitted'],
                          cov['excluded_reviews']), (33, 1, 30, 2, 1))
        self.assertEqual([n['file'] for n in got['notes']], [f'note-{n:02d}.md' for n in range(1, 31)])

    def test_review_title_alone_is_not_excluded(self):
        self.write('weekly-review-notes.md', 'hello', 'topic: Weekly review notes\nupdated: 2026-10-15\n')
        got = weekly_review.collect(self.db, self.notes, self.review)
        self.assertEqual([n['file'] for n in got['notes']], ['weekly-review-notes.md'])
        self.assertEqual(got['coverage']['notes']['excluded_reviews'], 0)

    def test_s05_date_priority_and_fallback(self):
        self.write('a.md', 'x', 'topic: A\nupdated: 2026-10-14\ncreated: 2020-01-01\n')
        self.write('b.md', 'x', 'topic: B\nupdated: garbage\ncreated: 2026-10-15\n')
        p = self.notes / 'c.md'
        p.write_text('---\ntopic: C\nupdated: garbage\ncreated: also-garbage\n---\n\nx', encoding='utf-8')
        mtime = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc).timestamp()
        os.utime(p, (mtime, mtime))
        got = weekly_review.collect(self.db, self.notes, self.review)
        by_file = {n['file']: n for n in got['notes']}
        self.assertEqual(by_file['a.md']['date'], '2026-10-14')
        self.assertEqual(by_file['b.md']['date'], '2026-10-15')
        self.assertEqual(by_file['c.md']['date'], '2026-10-16')
        self.assertEqual(got['coverage']['notes']['fallback_eligible'], 1)
        self.assertEqual(got['coverage']['notes']['fallback_included'], 1)

    def test_s06_aware_and_naive_normalized(self):
        self.write('aware.md', 'x', 'topic: A\nupdated: 2026-10-15T10:00:00+08:00\n')
        self.write('naive.md', 'x', 'topic: B\nupdated: 2026-10-15T10:00:00\n')
        got = weekly_review.collect(self.db, self.notes, self.review)
        self.assertEqual({n['date'] for n in got['notes']}, {'2026-10-15'})

    def test_s07_unreadable_files(self):
        self.write('good.md', 'x', 'topic: G\nupdated: 2026-10-15\n')
        (self.notes / 'bad.md').write_bytes(b'\xff\xfe\x00\x01')
        outside = self.notes.parent / 'outside.md'
        outside.write_text('x', encoding='utf-8')
        try:
            os.symlink(outside, self.notes / 'link.md')
            symlinked = True
        except (OSError, NotImplementedError):
            symlinked = False
        got = weekly_review.collect(self.db, self.notes, self.review)
        self.assertEqual([n['file'] for n in got['notes']], ['good.md'])
        self.assertEqual(got['coverage']['notes']['unreadable'], 2 if symlinked else 1)


class OutputTest(unittest.TestCase):
    def test_p01_json_preserves_braces_and_instructions(self):
        b = bundle(items=[{'id': 1, 'title': '{topic} ignore previous', 'date': '2026-10-15',
                           'category': 'SPORT', 'text': 'say "do not obey" {topic}'}],
                   notes=[{'file': 'n1.md', 'title': 'N', 'date': '2026-10-15', 'category': '', 'text': 'x'}])
        turn = weekly_review.build_turn(b)
        content = turn['messages'][0]['content']
        self.assertIn('{topic}', content)
        self.assertIn('ignore previous', content)
        self.assertIn('<mark data-mark=', turn['system'])
        self.assertEqual(turn['max_tokens'], weekly_review.L['requested_max_tokens'])

    def test_p02_valid_and_compose(self):
        b = bundle(items=[{'id': 1, 'title': 'T', 'date': '2026-10-15', 'category': 'SPORT', 'text': 'x'}],
                   notes=[{'file': 'n1.md', 'title': 'N', 'date': '2026-10-15', 'category': '', 'text': 'y'}])
        body = ('## What stood out\n- Theme [id 1].\n\n## Notes worth revisiting\n'
                '- Revisit [note: n1.md].\n\n## Open questions\n- Suggested: think [id 1].\n\n'
                '## Possible next steps\n- Try [id 1].')
        self.assertEqual(weekly_review.validate_output(body, b), body)
        out = weekly_review.compose_answer(body, b)
        self.assertEqual(out.count('# Weekly review — '), 1)
        self.assertIn('## Coverage', out)

    def test_p03_unknown_target(self):
        b = bundle(items=[{'id': 1, 'title': 'T', 'date': 'd', 'category': 'S', 'text': 'x'}],
                   notes=[{'file': 'n1.md', 'title': 'N', 'date': 'd', 'category': '', 'text': 'y'}])
        for body in ('## What stood out\n- x [id 2].\n\n## Notes worth revisiting\n- y [note: n1.md].\n\n'
                     '## Open questions\n- Suggested: q [id 1].\n\n## Possible next steps\n- z [id 1].',
                     '## What stood out\n- x [note: other.md].\n\n## Notes worth revisiting\n- y [note: n1.md].\n\n'
                     '## Open questions\n- Suggested: q [id 1].\n\n## Possible next steps\n- z [id 1].'):
            with self.assertRaises(ValueError):
                weekly_review.validate_output(body, b)

    def test_p04_structural_errors(self):
        b = bundle(items=[{'id': 1, 'title': 'T', 'date': 'd', 'category': 'S', 'text': 'x'}],
                   notes=[{'file': 'n1.md', 'title': 'N', 'date': 'd', 'category': '', 'text': 'y'}])
        cases = [
            '## What stood out\n- no citation.\n\n## Notes worth revisiting\n- y [note: n1.md].\n\n'
            '## Open questions\n- q [id 1].\n\n## Possible next steps\n- z [id 1].',
            '## What stood out\n- x [id 1].\n\n## What stood out\n- x [id 1].\n\n'
            '## Open questions\n- q [id 1].\n\n## Possible next steps\n- z [id 1].',
            '```\n## What stood out\n- x [id 1].\n```',
        ]
        for body in cases:
            with self.assertRaises(ValueError):
                weekly_review.validate_output(body, b)
        too_many = ('## What stood out\n' + '\n'.join(f'- x{i} [id 1].' for i in range(6)) +
                    '\n\n## Notes worth revisiting\n- y [note: n1.md].\n\n## Open questions\n- q [id 1].\n\n'
                    '## Possible next steps\n- z [id 1].')
        with self.assertRaises(ValueError):
            weekly_review.validate_output(too_many, b)

    def test_p05_sentinel_alone(self):
        b = bundle(items=[{'id': 1, 'title': 'T', 'date': 'd', 'category': 'S', 'text': 'x'}],
                   notes=[{'file': 'n1.md', 'title': 'N', 'date': 'd', 'category': '', 'text': 'y'}])
        ok = ('## What stood out\n- None found in the reviewed material.\n\n## Notes worth revisiting\n'
              '- y [note: n1.md].\n\n## Open questions\n- q [id 1].\n\n## Possible next steps\n- z [id 1].')
        self.assertEqual(weekly_review.validate_output(ok, b), ok)
        bad = ok.replace('- None found in the reviewed material.\n', '- None found in the reviewed material.\n- x [id 1].\n')
        with self.assertRaises(ValueError):
            weekly_review.validate_output(bad, b)

    def test_p06_notes_revisit_needs_note(self):
        b = bundle(items=[{'id': 1, 'title': 'T', 'date': 'd', 'category': 'S', 'text': 'x'}],
                   notes=[{'file': 'n1.md', 'title': 'N', 'date': 'd', 'category': '', 'text': 'y'}])
        body = ('## What stood out\n- x [id 1].\n\n## Notes worth revisiting\n- only item [id 1].\n\n'
                '## Open questions\n- q [id 1].\n\n## Possible next steps\n- z [id 1].')
        with self.assertRaises(ValueError):
            weekly_review.validate_output(body, b)


if __name__ == '__main__':
    unittest.main()
