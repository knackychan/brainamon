"""Wiskit's action wheel and drop handling, the parts without a window (projects/desktop-app plan 07b).
Run:  py -m unittest tests.test_widget_wheel -v
"""
import math
import struct
import sys
import tempfile
import unittest
from ctypes import wintypes
from pathlib import Path
from unittest import mock

try:
    from desktop import activity
    from desktop import dropwin
    from desktop import widget
    from desktop import widget_wheel as ww
except (ImportError, AttributeError) as e:       # Windows only (ctypes.WINFUNCTYPE, tkinter)
    if sys.platform == 'win32':
        raise
    raise unittest.SkipTest(f'Windows desktop modules: {e}')


class KeeperWatchTest(unittest.TestCase):
    def test_early_close_exits_after_grace_without_ever_observing_the_window(self):
        keeper = mock.Mock(exit_requested=False, grace_until=120, opening_until=0,
                           pref=False, off=True, owned=True, last_state='gone', tray_on=False)
        with mock.patch.object(widget.time, 'time', return_value=119) as now, \
                mock.patch.object(widget.sleep, 'window_state', return_value='gone'):
            widget.Widget._watch(keeper)
            keeper.quit.assert_not_called()
            now.return_value = 120
            widget.Widget._watch(keeper)
        keeper.quit.assert_called_once()

    def test_observed_window_does_not_wait_for_grace_on_close(self):
        keeper = mock.Mock(exit_requested=False, grace_until=120, opening_until=0,
                           pref=False, off=True, owned=True, last_state='gone', tray_on=False)
        with mock.patch.object(widget.time, 'time', return_value=100), \
                mock.patch.object(widget.sleep, 'window_state', side_effect=['awake', 'gone']):
            widget.Widget._watch(keeper)
            keeper.quit.assert_not_called()
            widget.Widget._watch(keeper)
        keeper.quit.assert_called_once()


class WheelTest(unittest.TestCase):
    def test_new_sprite_clearance_and_screen_edges(self):
        import json
        index = json.loads((Path(__file__).resolve().parents[1] / 'web/public/wiskit/sheet.json').read_text())
        bounds = index['states']['listen']['bounds']
        x, y, radius = ww.sprite_geometry(bounds, index['scale'])
        self.assertEqual(bounds, index['states']['hover']['bounds'])
        self.assertLessEqual(radius, 135)
        x0, y0, x1, y1 = [v * index['scale'] for v in bounds]
        self.assertEqual((x, y), (round((x0 + x1) / 2), round((y0 + y1) / 2)))
        for a in range(360):
            bx, by = x + math.cos(math.radians(a)) * radius, y + math.sin(math.radians(a)) * radius
            distance = math.hypot(bx - min(max(bx, x0), x1), by - min(max(by, y0), y1))
            self.assertGreaterEqual(distance, ww.BR + 7)
        for sw, sh in ((1366, 768), (1920, 1080)):
            for left in (0, sw // 2 - 144, sw - 288):
                for top in (0, sh // 2 - 84, sh - 168):
                    cx, cy = left + x, top + y
                    for n in (1, 2, 3, len(ww.ACTIONS)):
                        angs = ww.angles(cx, cy, sw, sh, n, radius=radius)
                        for i, a in enumerate(angs):
                            bx, by = cx + math.cos(a) * radius, cy + math.sin(a) * radius
                            self.assertTrue(ww.BR <= bx <= sw - ww.BR and ww.BR <= by <= sh - ww.BR)
                            self.assertEqual(ww.hit(angs, cx, cy, bx, by, radius=radius), i)
                        for a, b in zip(angs, angs[1:]):
                            self.assertAlmostEqual(2 * radius * math.sin((b - a) / 2), 2 * ww.BR + 8)
                        if n <= 3:
                            size = 2 * (radius + ww.BR + 34)
                            boxes = ww.label_boxes(angs, size // 2, size // 2, ['Inbox', 'Add to library', 'Ask Wiskit'][:n], size, radius)
                            for a, (bx0, by0, bx1, by1) in zip(angs, boxes):
                                self.assertTrue(0 <= bx0 < bx1 <= size and 0 <= by0 < by1 <= size)
                                for b in angs:
                                    bx, by = size // 2 + math.cos(b) * radius, size // 2 + math.sin(b) * radius
                                    self.assertGreaterEqual(math.hypot(bx - min(max(bx, bx0), bx1), by - min(max(by, by0), by1)), ww.BR)
                            for i, a in enumerate(boxes):
                                for b in boxes[i + 1:]:
                                    self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])

    def test_open_menu_keeps_listening_pose_while_a_job_runs(self):
        pet = mock.Mock(dragging=False, wheel=object(), job=True, busy=1)
        self.assertEqual(widget.Widget._want(pet), 'listen')
        pet.wheel = None
        self.assertEqual(widget.Widget._want(pet), 'work')

    def test_activity_dot_sits_in_the_window_clear_of_every_pose(self):
        import json
        index = json.loads((Path(__file__).resolve().parents[1] / 'web/public/wiskit/sheet.json').read_text())
        (cw, ch), s = index['cell'], index['scale']
        w, h = cw * s, ch * s
        x, y = ww.dot_xy(100, 200, w, h)
        self.assertTrue(100 <= x and x + ww.DOT <= 100 + w and 200 <= y and y + ww.DOT <= 200 + h)
        self.assertGreater(x - 100, max(st['bounds'][2] for st in index['states'].values()) * s)

    def test_fans_towards_the_room(self):
        sw, sh = 1920, 1080
        a = ww.angles(1850, 980, sw, sh)            # bottom right corner: the wheel opens up and left
        self.assertEqual(len(a), len(ww.ACTIONS))
        mid = (a[0] + a[-1]) / 2
        self.assertLess(math.cos(mid), 0)
        self.assertLess(math.sin(mid), 0)
        b = ww.angles(sw / 2, sh / 2, sw, sh)       # in the middle: opens upwards
        self.assertAlmostEqual((b[0] + b[-1]) / 2, -math.pi / 2)

    def test_buttons_do_not_overlap(self):
        a = ww.angles(1850, 980, 1920, 1080)
        step = a[1] - a[0]
        self.assertGreater(2 * ww.R * math.sin(step / 2), 2 * ww.BR)

    def test_icons_are_7x7_and_every_action_has_one(self):
        for name, _label in ww.ACTIONS:
            icon = ww.ICONS[name]
            self.assertEqual(len(icon), 7)
            self.assertTrue(all(len(r) == 7 for r in icon))

    def test_one_bubble_points_into_the_room(self):
        a = ww.angles(1850, 980, 1920, 1080, n=1)
        self.assertEqual(len(a), 1)
        self.assertLess(math.cos(a[0]), 0)

    def test_four_actions_and_no_nap(self):
        """WP D: Add a link and Paste screenshot live in the Drop panel; the hour-long nap is gone."""
        self.assertEqual([n for n, _ in ww.ACTIONS], ['ask', 'drop', 'write', 'record', 'open', 'quit'])
        for gone in ('link', 'shot', 'hide'):
            self.assertNotIn(gone, ww.ICONS)
        self.assertFalse(hasattr(widget.Widget, '_hide_hour'))
        self.assertFalse(hasattr(ww.Bubble, 'prompt'))

    def test_hit(self):
        a = [0.0, math.pi / 2]                     # right of the centre, then below it
        self.assertEqual(ww.hit(a, 100, 100, 100 + ww.R, 100), 0)
        self.assertEqual(ww.hit(a, 100, 100, 100, 100 + ww.R + ww.BR + 5, slack=8), 1)
        self.assertEqual(ww.hit(a, 100, 100, 100, 100 + ww.R + ww.BR + 5), -1)
        self.assertEqual(ww.hit(a, 100, 100, 100, 100), -1)            # Wiskit himself

    def test_drop_icons_and_labels(self):
        for name in ww.DROP_LABELS:
            icon = ww.ICONS[name]
            self.assertEqual(len(icon), 7)
            self.assertTrue(all(len(r) == 7 for r in icon), name)

    def test_pop_settles(self):
        self.assertAlmostEqual(ww._back(1.0), 1.0)
        self.assertGreater(max(ww._back(t / 10) for t in range(11)), 1.0)    # overshoots, the pop

    def test_drop_labels_fit_and_do_not_overlap(self):
        """Every drop bubble's label shows at once: inside the ring window, clear of each other and of
        every bubble, wherever Wiskit is parked."""
        size = 2 * (ww.R + ww.BR + 34)
        half = size // 2
        sets = [['inbox', 'library', 'ask'], ['inbox', 'video', 'ask'], ['inbox', 'ask'], ['inbox']]   # all drop_actions gives
        for sw, sh in ((1920, 1080), (1366, 768), (2560, 1440)):
            for cx in range(40, sw, 90):
                for cy in range(40, sh, 70):
                    for acts in sets:
                        angs = ww.angles(cx, cy, sw, sh, len(acts))
                        boxes = ww.label_boxes(angs, half, half, [ww.DROP_LABELS[a] for a in acts], size)
                        where = (sw, sh, cx, cy, acts)
                        self.assertEqual(len(boxes), len(acts))
                        for x0, y0, x1, y1 in boxes:
                            self.assertTrue(0 <= x0 < x1 <= size and 0 <= y0 < y1 <= size, where)
                            for a in angs:
                                bx, by = half + math.cos(a) * ww.R, half + math.sin(a) * ww.R
                                nx, ny = min(max(bx, x0), x1), min(max(by, y0), y1)
                                self.assertGreaterEqual(math.hypot(nx - bx, ny - by), ww.BR, where)
                        for i, a in enumerate(boxes):
                            for b in boxes[i + 1:]:
                                self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3], where)


class DropTest(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(dropwin.classify(['C:/a.txt'], 'https://x.y', 'z'), ('files', ['C:/a.txt']))
        self.assertEqual(dropwin.classify([], 'https://x.y/1\r\nignored', 'z'), ('url', 'https://x.y/1'))
        self.assertEqual(dropwin.classify(None, None, '  hello '), ('text', 'hello'))
        self.assertIsNone(dropwin.classify(None, '', '  '))

    def test_point_unpacks_pointl(self):
        import struct
        for x, y in ((10, 20), (-1920, 5), (3000, -40)):
            pt = struct.unpack('<q', struct.pack('<ii', x, y))[0]
            self.assertEqual(dropwin.point(pt), (x, y))

    @unittest.skipUnless(sys.platform == 'win32', 'OLE drop target')
    def test_callbacks_wait_for_pump(self):
        """Nothing runs inside the OLE call: entering tkinter there crashes Python ('PyEval_RestoreThread:
        the function must be called with the GIL held'). The calls queue up and pump() runs them in order."""
        seen = []
        t = dropwin.DropTarget(lambda *a: seen.append(('enter',) + a), lambda: seen.append(('leave',)),
                               lambda *a: seen.append(('drop',) + a), lambda *a: seen.append(('over',) + a))
        t._read = lambda d: ('url', 'https://x.y/1')
        pt = struct.unpack('<q', struct.pack('<ii', 5, 7))[0]
        eff = (wintypes.DWORD * 1)(dropwin.DROPEFFECT_COPY)
        with mock.patch.object(dropwin, '_Data', lambda p: None):
            t._enter(None, None, 0, pt, eff)
            t._over(None, 0, pt, eff)
            t._drop(None, None, 0, pt, eff)
        self.assertEqual(eff[0], dropwin.DROPEFFECT_COPY)
        self.assertEqual(seen, [])
        dropwin.pump()
        self.assertEqual(seen, [('enter', 'url', 'https://x.y/1', 5, 7), ('over', 5, 7), ('leave',),
                                ('drop', 'url', 'https://x.y/1', 5, 7)])
        dropwin.pump()
        self.assertEqual(len(seen), 4)

    def test_is_url(self):
        self.assertTrue(widget.is_url(' https://www.instagram.com/reel/abc/ '))
        self.assertFalse(widget.is_url('look at https://x.y'))
        self.assertFalse(widget.is_url('ftp://x.y'))
        self.assertTrue(widget.is_url('text.com'))

    def test_link_matches_the_server(self):
        from knowledge import inbox
        from tests.test_server_inbox import LINK_MISSES, SHARE_LINKS
        for raw in ('text.com', ' www.example.org/a?b=1 ', 'HTTPS://x.y/z', 'sub.domain.co.uk:8080/p', 'www.notes.md',
                    *LINK_MISSES, *(c[0] for c in SHARE_LINKS)):
            self.assertEqual(widget.link(raw), inbox.link(raw), raw)

    def test_panel_title_matches_the_app(self):
        from server import desktop
        self.assertEqual(widget.PANEL_TITLE, desktop.PANEL_TITLE)

    def test_on_screen(self):
        desk = (0, 0, 1920, 1080)
        self.assertEqual(widget.on_screen(2291, 734, 120, 102, desk), (1800, 734))   # second screen gone
        self.assertEqual(widget.on_screen(-50, -9, 120, 102, desk), (0, 0))
        self.assertEqual(widget.on_screen(300, 400, 120, 102, desk), (300, 400))

    def test_sort_files(self):
        with tempfile.TemporaryDirectory() as td:
            img, doc = Path(td) / 'shot.PNG', Path(td) / 'notes.pdf'
            img.write_bytes(b'x')
            doc.write_bytes(b'y')
            images, others, skipped = widget.sort_files([str(img), str(doc), td])
            self.assertEqual(images, [img])
            self.assertEqual(others, [doc])
            self.assertEqual(len(skipped), 1)


class DropActionsTest(unittest.TestCase):
    def test_which_bubbles(self):
        self.assertEqual(widget.drop_actions('url', 'https://x.y/1'), ['inbox', 'library', 'ask'])
        self.assertEqual(widget.drop_actions('text', ' https://x.y/1 '), ['inbox', 'library', 'ask'])
        self.assertEqual(widget.drop_actions('text', 'a thought'), ['inbox', 'ask'])
        self.assertEqual(widget.drop_actions('text', 'www.text.com'), ['inbox', 'library', 'ask'])
        self.assertEqual(widget.drop_actions('files', ['C:/a/clip.MP4']), ['inbox', 'video', 'ask'])
        self.assertEqual(widget.drop_actions('files', ['C:/a/n.md', 'C:/a/p.png']), ['inbox', 'ask'])
        self.assertEqual(widget.drop_actions('files', ['C:/a/n.md', 'C:/a/b.pdf']), ['inbox'])
        self.assertEqual(widget.drop_actions('files', ['C:/a/1.mp4', 'C:/a/2.mp4']), ['inbox'])

    def test_describe_drop(self):
        self.assertEqual(widget.describe_drop('files', ['C:/a/n.md']), '1 file: n.md')
        self.assertEqual(widget.describe_drop('files', [f'C:/{i}.txt' for i in range(5)]),
                         '5 files: 0.txt, 1.txt, 2.txt and 2 more')
        self.assertEqual(widget.describe_drop('url', 'https://x.y'), 'a link: https://x.y')
        self.assertEqual(widget.describe_drop('text', 'hello\n  world'), 'some text: hello world')

    def test_ext_sets_match_the_server(self):
        from knowledge import attachments
        from server.routes import io
        self.assertEqual(widget.ATTACH_EXTS, attachments.TEXT_EXTS | attachments.IMAGE_EXTS)
        self.assertEqual(widget.VIDEO_EXTS, io.VIDEO_EXTS)


class ActivityGlueTest(unittest.TestCase):
    """projects/wiskit-activity: the widget's side, with a mock in place of the window."""
    JOB = {'label': 'Describe', 'state': 'running', 'total': 40, 'done': 12, 'err': 0}

    def test_a_running_answer_animates_him_like_a_job(self):
        pet = mock.Mock(dragging=False, wheel=None, job=False, busy=0, asks=1, done_until=0, hover=False)
        self.assertEqual(widget.Widget._want(pet), 'work')
        pet.asks = 0
        self.assertEqual(widget.Widget._want(pet), 'sleep')

    def test_a_finished_job_leaves_the_last_line(self):
        pet = mock.Mock(job=True, last='')
        pet._job.side_effect = lambda running: setattr(pet, 'job', running)
        snap = {'current': None, 'last': dict(self.JOB, label='Categorize', state='finished', done=40)}
        widget.Widget._jobs(pet, snap)
        self.assertEqual(pet.last, 'Last: Categorize done, 40 items')
        self.assertEqual(pet.jobs_snap, snap)
        pet._show_activity.assert_called_once_with()
        pet.last = ''
        widget.Widget._jobs(pet, snap)                      # no job ran before: no new line
        self.assertEqual(pet.last, '')

    def test_a_saved_answer_plays_done_and_leaves_its_line(self):
        pet = mock.Mock(done_until=0, last='')
        with mock.patch.object(widget.time, 'time', return_value=100.0):
            widget.Widget._ask_saved(pet)
        self.assertEqual(pet.done_until, 100.0 + widget.DONE_S)
        self.assertEqual(pet.last, "Last: Wiskit's answer saved")

    def test_activity_reaches_the_dot_the_card_and_the_tooltip(self):
        pet = mock.Mock(jobs_snap={'current': self.JOB}, cloud={}, asks=0, last='', w=288, h=168, tip='Brainamon')
        pet.root.state.return_value = 'normal'
        pet.root.winfo_x.return_value, pet.root.winfo_y.return_value = 100, 200
        pet.card.win = object()
        widget.Widget._show_activity(pet)
        pet.dot.set.assert_called_once_with('busy', *ww.dot_xy(100, 200, 288, 168))
        pet.card.show.assert_called_once_with([('line', 'Describe 12 / 40'), ('bar', activity.bar(12, 40))])
        pet.tray.set_title.assert_called_once_with('Brainamon - Describe 12 / 40')
        pet.tray.set_title.reset_mock()
        widget.Widget._show_activity(pet)                   # the same tooltip: no new call to Windows
        pet.tray.set_title.assert_not_called()
        pet.root.state.return_value = 'withdrawn'           # Wiskit hidden: no dot, no card
        widget.Widget._show_activity(pet)
        pet.dot.set.assert_called_with('', *ww.dot_xy(100, 200, 288, 168))
        pet.card.close.assert_called_once_with()

    def test_the_card_waits_for_something_to_say_and_a_quiet_wiskit(self):
        def pet(**kw):
            p = mock.Mock(**{'jobs_snap': {}, 'cloud': {}, 'asks': 1, 'last': '', 'wheel': None, 'dragging': False,
                             'press': None, **kw})
            p.bubble.win = None
            p.root.state.return_value = 'normal'
            return p
        p = pet()
        widget.Widget._open_card(p)
        p.card.show.assert_called_once_with([('line', 'Wiskit is answering')])
        for kw in ({'wheel': object()}, {'dragging': True}, {'press': (0, 0, 0, 0, False)}, {'asks': 0}):
            p = pet(**kw)
            widget.Widget._open_card(p)
            p.card.show.assert_not_called()
        p = pet()
        p.bubble.win = object()                             # a bubble is up there
        widget.Widget._open_card(p)
        p.card.show.assert_not_called()

    def test_the_event_stream_feeds_the_activity(self):
        class Stop(BaseException):
            pass
        lines = [b'event: hello\n', b'data: {"jobs": {"current": null}, "asks": 1, "cloud": {"state": "idle"}}\n', b'\n',
                 b'event: cloud\n', b'data: {"state": "publishing", "running": true}\n', b'\n',
                 b'event: ask_run\n', b'data: {"running": 0}\n', b'\n',
                 b'event: ask_saved\n', b'data: {"run": "r", "slug": "s", "name": "n", "detached": true}\n', b'\n']
        resp = mock.MagicMock()
        resp.__enter__.return_value = iter(lines)
        pet = mock.Mock(on_quit=None, pref=None)
        pet.root.after.side_effect = lambda ms, fn, *args: fn(*args)
        with mock.patch.object(widget.urllib.request, 'urlopen', side_effect=[resp, Stop()]), \
                mock.patch.object(widget.local_auth, 'headers', return_value={}):
            with self.assertRaises(Stop):
                widget.Widget._events(pet)
        pet._hello.assert_called_once_with({'jobs': {'current': None}, 'asks': 1, 'cloud': {'state': 'idle'}})
        pet._jobs.assert_called_once_with({'current': None})
        pet._cloud.assert_called_once_with({'state': 'publishing', 'running': True})
        pet._asks.assert_called_once_with(0)
        pet._ask_saved.assert_called_once_with()
        pet._server_gone.assert_not_called()

    def test_a_lost_stream_clears_the_activity_once(self):
        class Stop(BaseException):
            pass
        pet = mock.Mock(on_quit=None)
        pet.root.after.side_effect = lambda ms, fn, *args: fn(*args)
        with mock.patch.object(widget.urllib.request, 'urlopen', side_effect=[OSError('refused'), OSError('refused'), Stop()]), \
                mock.patch.object(widget.time, 'sleep'), mock.patch.object(widget.local_auth, 'headers', return_value={}):
            with self.assertRaises(Stop):
                widget.Widget._events(pet)
        pet._server_gone.assert_called_once_with()          # once per outage, not on every retry


if __name__ == '__main__':
    unittest.main()
