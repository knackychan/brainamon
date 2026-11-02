"""desktop/activity.py: Wiskit's dot, hover card and tray tooltip from the server snapshots
(projects/wiskit-activity). No window, no server.

Run from the project root:  py -m unittest tests.test_widget_activity -v
"""
import unittest

from desktop import activity

FULL, EMPTY = activity.LIT, activity.UNLIT
JOB = {'id': 3, 'kind': 'describe', 'label': 'Describe', 'state': 'running', 'total': 40, 'done': 11, 'err': 1,
       'current': 7, 'auto': False, 't0': 1.0, 't1': 0.0}
CLOUD_IDLE = {'running': True, 'state': 'idle', 'done': 0, 'total': 0,
              'vault_running': False, 'vault_state': 'off', 'vault_done': 0, 'vault_total': 0}
UPLOAD = dict(CLOUD_IDLE, state='publishing', done=3, total=18)


class LinesTest(unittest.TestCase):
    def test_nothing_runs(self):
        self.assertEqual(activity.lines({'current': None, 'last': None, 'request': None}, CLOUD_IDLE, 0), [])
        self.assertEqual(activity.lines({}, {}, 0), [])
        self.assertEqual(activity.lines(None, None, None), [])
        self.assertEqual(activity.dot(None, None, None), '')
        self.assertEqual(activity.dot({}, CLOUD_IDLE, 0), '')            # the idle upload loop is not activity

    def test_running_job_counts_done_and_failed_like_the_rail(self):
        self.assertEqual(activity.lines({'current': JOB}, {}, 0),
                         [('line', 'Describe 12 / 40, 1 failed'), ('bar', FULL * 3 + EMPTY * 9)])
        self.assertEqual(activity.dot({'current': JOB}, {}, 0), 'busy')

    def test_paused_job_and_job_without_a_total(self):
        paused = dict(JOB, state='paused', done=12, err=0)
        self.assertEqual(activity.lines({'current': paused}, {}, 0)[0], ('line', 'Describe paused 12 / 40'))
        self.assertEqual(activity.lines({'current': dict(JOB, total=0, done=0, err=0)}, {}, 0), [('line', 'Describe')])

    def test_answers(self):
        self.assertEqual(activity.lines({}, {}, 1), [('line', 'Wiskit is answering')])
        self.assertEqual(activity.lines({}, {}, 2), [('line', 'Wiskit is answering (2)')])
        self.assertEqual(activity.dot({}, {}, 1), 'busy')

    def test_drive_upload_and_vault_sync(self):
        self.assertEqual(activity.lines({}, UPLOAD, 0), [('line', 'Drive upload 3 / 18')])
        self.assertEqual(activity.lines({}, dict(UPLOAD, state='starting', total=0), 0), [('line', 'Drive upload starting')])
        self.assertEqual(activity.lines({}, dict(UPLOAD, running=False), 0), [])     # a state left by a stopped thread
        self.assertEqual(activity.lines({}, dict(CLOUD_IDLE, state='stopping'), 0), [('line', 'Stopping the upload')])
        self.assertEqual(activity.lines({}, dict(CLOUD_IDLE, state='disconnecting'), 0),
                         [('line', 'Disconnecting from Google Drive')])
        vault = dict(CLOUD_IDLE, vault_running=True, vault_state='syncing', vault_done=5, vault_total=40)
        self.assertEqual(activity.lines({}, vault, 0), [('line', 'Vault sync 5 / 40')])
        self.assertEqual(activity.lines({}, dict(vault, vault_total=0), 0), [('line', 'Vault sync starting')])
        self.assertEqual(activity.lines({}, dict(CLOUD_IDLE, vault_state='stopping'), 0), [('line', 'Stopping the vault sync')])
        self.assertEqual(activity.dot({}, UPLOAD, 0), 'busy')

    def test_a_waiting_request_wins_the_dot(self):
        jobs = {'current': JOB, 'request': {'id': 9, 'type': 'category_batch', 'source': 'Wiskit', 'state': 'pending'}}
        self.assertEqual(activity.lines(jobs, {}, 0)[-1], ('line', '1 request waits for you'))
        self.assertEqual(activity.dot(jobs, {}, 0), 'waiting')
        self.assertEqual(activity.dot({'request': {'state': 'pending'}}, {}, 0), 'waiting')
        for state in ('approving', 'approved', 'declined'):
            self.assertEqual(activity.dot({'request': {'state': state}}, {}, 0), '')

    def test_card_order_and_the_last_line(self):
        card = activity.lines({'current': JOB, 'request': {'state': 'pending'}}, UPLOAD, 1, 'Last: Categorize done, 40 items')
        self.assertEqual(card, [('line', 'Describe 12 / 40, 1 failed'), ('bar', FULL * 3 + EMPTY * 9),
                                ('line', 'Wiskit is answering'), ('line', 'Drive upload 3 / 18'),
                                ('line', '1 request waits for you'), ('last', 'Last: Categorize done, 40 items')])
        # after the finish: the card keeps the line, the dot is gone
        self.assertEqual(activity.lines({}, {}, 0, 'Last: x'), [('last', 'Last: x')])
        self.assertEqual(activity.dot({}, {}, 0), '')


class LastJobTest(unittest.TestCase):
    def test_finished_stopped_failed(self):
        self.assertEqual(activity.last_job(dict(JOB, label='Categorize', state='finished', done=40, err=0)),
                         'Last: Categorize done, 40 items')
        self.assertEqual(activity.last_job(dict(JOB, state='finished', done=1, err=0)), 'Last: Describe done, 1 item')
        self.assertEqual(activity.last_job(dict(JOB, state='finished', done=38, err=2)),
                         'Last: Describe done, 38 items, 2 failed')
        self.assertEqual(activity.last_job(dict(JOB, state='stopped', done=12, err=0)), 'Last: Describe stopped after 12 of 40')
        self.assertEqual(activity.last_job(None), '')


class BarAndTooltipTest(unittest.TestCase):
    def test_bar(self):
        self.assertEqual(activity.bar(0, 40), EMPTY * 12)
        self.assertEqual(activity.bar(40, 40), FULL * 12)
        self.assertEqual(activity.bar(99, 40), FULL * 12)
        self.assertEqual(activity.bar(5, 0), '')

    def test_tooltip(self):
        self.assertEqual(activity.tooltip([]), 'Brainamon')
        self.assertEqual(activity.tooltip(activity.lines({'current': JOB}, {}, 0)), 'Brainamon - Describe 12 / 40, 1 failed')
        self.assertEqual(activity.tooltip([('bar', FULL), ('line', 'Wiskit is answering')]), 'Brainamon - Wiskit is answering')
        self.assertEqual(activity.tooltip([('last', 'Last: x')]), 'Brainamon - Last: x')
        self.assertEqual(len(activity.tooltip([('line', 'x' * 300)])), activity.TIP_MAX)

    def test_tooltip_name_is_the_tray_icon_name(self):
        from desktop import tray
        self.assertEqual(activity.TIP, tray.TITLE)


if __name__ == '__main__':
    unittest.main()
