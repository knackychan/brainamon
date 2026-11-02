"""Backup & phones Settings page and the Recover a library window against mocked Drive responses; never signs into Google.

Run after building web/: py tests/check_settings_cloud_browser.py
Uses the existing screenshot harness and its throwaway library (its own cloud folder). The rules of the approved mockup
(projects/backup-phones-mockup/check.py) are asserted on every state: one primary key in the window, a reason next to every
disabled control, no dead end, no link off the page, no horizontal overflow, in light and dark at 1440 and 390 px.
"""
import importlib.util
import tempfile
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('shots', ROOT / 'tests/helpers/shots.py')
shots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shots)

NOW = int(shots.FIXED_TIME.timestamp() * 1000)
HOUR = 3600 * 1000
DAY = 24 * HOUR
ACCOUNT = 'sample@example.com'

# what GET /api/cloud answers for a signed-in, backed-up PC; a state changes only what it names
CONNECTED = dict(signed_in=True, configured=True, licensed=True, account=ACCOUNT, on=True, running=True, state='idle', last_publish=NOW - 2 * HOUR,
                 last_summary='Already up to date', files=5678, size=9_800_000_000, used=1073741824, limit=16106127360,
                 options={'videos': 'fav', 'canvases': True}, phone_keys=['openai'], phones=None, task=None, paused_since=0, key_missing=False,
                 token_expired=False, token_issued=(NOW - 2 * DAY) // 1000, error='', error_code='', error_action='', error_at=0, error_account='', done=0, total=0,
                 bytes_done=0, bytes_total=0, rotation='', rotation_locked_at=0, rotation_locked_by=0, ignored_changes=0, upload_since=NOW - 360_000, upload_step='')
REC_OK = dict(configured=True, enrolled=True, verified=True, verified_at=NOW // 1000 - DAY // 1000, setup_at=NOW // 1000 - 20 * DAY // 1000,
              saved_at=NOW // 1000 - DAY // 1000, account=ACCOUNT)
# the sentence library/mirror.py skipped_note(2) makes: the Backup card (the cloud status) and the recovery preview (its omissions) show it as it comes
SKIPPED = '2 files were not uploaded because they are too big to recover (over 512 MiB for a video, over 64 MiB for anything else). They are not in the backup.'
FOUND = dict(items=1234, files=5678, bytes=10_522_669_875, published=NOW - 3 * DAY, videos='fav', canvases=True, omissions=[SKIPPED], duplicates=0,
             generation={'created': NOW // 1000, 'fingerprint': 'abc'}, reconnect={'ok': True, 'reason': '', 'message': ''}, password_known=True,
             notice='Used the recovery setup from 12 Oct. The newer one from 30 Oct has no backup because removing phones did not finish.')
# Update this folder (S9): another PC with the same key moved the backup on; this folder can take it in place
UPDATE_OK = dict(eligible=True, reason='eligible', message='', bytes=120 * 1048576, files=46, nothing=False, local_changes=0, published=NOW - DAY,
                 owner_at=NOW - 2 * DAY, last_backup=NOW - 3 * DAY, account=ACCOUNT)
NOT_OWNER = dict(state='error', error='x', error_code='not_owner', error_action='recover', error_at=NOW - 2 * DAY)


def updating(stage, **more):
    t = task('update_folder', 'Updating this folder', 1 if stage in ('queued', 'downloading') else 2, 3)
    t.update(stage=stage, **more)
    return t


SAFE = 'Your library is safe: backed up at 10:00, unlocked by your passphrase or recovery file.'
TWO_COPIES = 'Another Brainamon on this PC (the installed app) made this backup with a different key. Use that copy, or quit it before using this one.'


def task(kind, title, step, of, **more):
    return dict(id=kind, kind=kind, stage='x', title=title, step=step, of=of, steps=[dict(label=f'Step {n}', state='done' if n < step else 'active' if n == step else 'waiting')
                                                                                  for n in range(1, of + 1)], done=0, total=0, bytes_done=0, bytes_total=0, since=NOW - 360_000,
                error='', code='', lock='', **more)


REMOVING = task('remove_phones', 'Removing all phones', 3, 5, **{})
REMOVING.update(done=2345, total=5678, bytes_done=4_100_000_000, bytes_total=9_800_000_000)
RESETTING = task('reset_backup', 'Resetting the backup', 2, 3)
RESETTING.update(stage='backing-up', steps=[dict(label=label, state=state) for label, state in
                 [('New key ready', 'done'), ('Backing up again', 'active'), ('Deleting the old backup', 'waiting')]])
SIGNED_OUT = dict(signed_in=False, running=False, on=False, state='off')

# (name, what GET /api/cloud changes, what GET /api/cloud/recovery changes, texts that show, the primary keys of the window, texts that do not)
STATES = [
    ('t1-not-connected', dict(SIGNED_OUT, account='', last_publish=0), {},
     ['Your library is only on this PC.', 'Back it up to your own Google Drive, encrypted: Google cannot read it.', 'Starts when you back up to Google Drive.',
      'Available once the backup has started.', 'Phones read your backup in Google Drive, so back up first.', 'Recover a library…'], ['Back up to Google Drive'], []),
    ('t1b-sign-in-not-set-up', dict(SIGNED_OUT, account='', last_publish=0, configured=False), {}, ['Google sign-in is not set up in this build.'], ['Done'], []),
    ('t2-signing-in', dict(SIGNED_OUT, state='signing-in', account='', last_publish=0), {},
     ['Finish signing in in the browser window that opened.', "Choose the Google account for this library's backup.", 'Cancel sign-in'], ['Done'], []),
    ('t3-foreign-backup', dict(state='error', last_publish=0, error='x', error_code='foreign_backup', error_action='recover', error_at=NOW - 3 * DAY), dict(REC_OK),
     [f'{ACCOUNT} already holds a Brainamon backup from another PC (last backup', 'Recover it, replace it with this PC’s library, or use another Google account.', 'Use another account…', 'Replace cloud backup with this PC’s library…'],
     ['Recover this backup…'], ['Recover a library…']),
    ('t4-first-backup', dict(last_publish=0, state='publishing', done=1204, total=5678, bytes_done=2_100_000_000, bytes_total=9_800_000_000), dict(configured=False),
     ['Backing up for the first time: 1,204 of 5,678 files (2.0 of 9.1 GB).', 'You can close Settings. Quitting Brainamon pauses this; it continues at the next start.',
      'First backup running (progress above)', 'Pause backup', 'Choose a recovery passphrase', 'You can do this while the first backup runs.'], ['Save passphrase'], []),
    ('t4b-first-backup-recovered', dict(last_publish=0, state='publishing', done=10, total=5678, bytes_done=1_000_000, bytes_total=9_800_000_000), dict(REC_OK),
     ['Backing up for the first time: 10 of 5,678 files'], ['Done'], ['Choose a recovery passphrase']),
    ('reset-preparing', dict(task=RESETTING, state='publishing', upload_step='Preparing the encrypted library for upload…'), dict(REC_OK),
     ['Preparing the encrypted library for upload…', 'Backing up again · in progress', 'Deleting the old backup · waiting', 'Drive temporarily holds both copies.'], ['Done'], ['0%']),
    ('reset-uploading', dict(task=dict(RESETTING, done=250, total=1000, bytes_done=25 * 1048576, bytes_total=100 * 1048576), state='publishing'), dict(REC_OK),
     ['Uploading replacement backup: 25% · 250 of 1,000 files (25 MB of 100 MB).', 'Deleting the old backup · waiting'], ['Done'], []),
    ('reset-small-progress', dict(task=dict(RESETTING, done=10, total=1000, bytes_done=1048576, bytes_total=1000 * 1048576), state='publishing'), dict(REC_OK),
     ['Uploading replacement backup: <1% · 10 of 1,000 files (1 MB of 1000 MB).'], ['Done'], []),
    ('reset-deleting', dict(task=dict(RESETTING, stage='cleanup', step=3, done=4, total=10, steps=[dict(label=x['label'], state='active' if n == 2 else 'done') for n, x in enumerate(RESETTING['steps'])])), dict(REC_OK),
     ['Deleting the old backup: 4 of 10 files confirmed.', 'Backing up again · done', 'Deleting the old backup · in progress'], ['Done'], ['Uploading replacement backup:']),
    ('t5-no-recovery', dict(), dict(configured=False),
     ['Backed up at 10:00, but if this PC is lost nothing can unlock the backup.', 'A recovery passphrase unlocks it on another PC.',
      'If this PC is lost, your passphrase or a recovery file unlocks the backup on another PC.'], ['Create recovery passphrase'], ['Choose a recovery passphrase']),
    ('t6-safe', dict(), dict(REC_OK),
     [SAFE, 'Up to date · 10:00', 'Changes back up about a minute after you make them.', 'Passphrase set', 'recovery file checked', 'Keep the file outside this PC.',
      'Phones read your backup', 'This PC cannot tell which phones are paired.', 'Pause backup', 'Reset backup…', 'Included'], ['Done'], ['too big to recover', 'Next: 6 Oct.']),
    ('t6b-phones-named', dict(phones=[dict(device='a', name='Pixel 8', seen=NOW - 120_000), dict(device='b', name='Galaxy A54', seen=NOW - 3 * HOUR)]), dict(REC_OK),
     ['2 phones', 'Pixel 8 · synced 2 min ago', 'Galaxy A54 · synced 3.0 h ago', '1 of 2 phones in sync.'], ['Done'], ['This PC cannot tell which phones are paired.']),
    ('t6c-left-out', dict(skipped=2, skipped_note=SKIPPED), dict(REC_OK), [SKIPPED], ['Done'], []),
    ('t7-changes', dict(state='publishing', total=12, done=3), dict(REC_OK), ['Backing up 12 changes. Last complete backup 10:00.'], ['Done'], []),
    ('t8-paused', dict(on=False, running=False, state='off', paused_since=NOW - 3 * DAY), dict(REC_OK),
     ['Backup paused. Changes since 10:00 are only on this PC.', 'Paused'], ['Resume backup'], ['Pause backup']),
    ('t9-pausing', dict(state='stopping'), dict(REC_OK), ['Pausing after the current upload request (up to a minute).', 'Keep backing up'], ['Done'], []),
    ('t10-offline', dict(state='error', error="Can't reach Google Drive.", error_code='offline', error_action='none'), dict(REC_OK),
     ["Can't reach Google Drive. Changes stay on this PC and back up when the connection returns.", 'Phones keep syncing for up to an hour; after that their edits wait on the phone.',
      'Waiting: offline'], ['Done'], []),
    ('t11-expired', dict(token_expired=True, state='error', error_code='auth_expired', error='x', error_action='sign_in_again'), dict(REC_OK),
     [f"Google stopped accepting this PC's sign-in for {ACCOUNT}. Nothing was deleted.", 'Backup waits, and phones pause within an hour, until you sign in again.',
      f'Sign-in expired · {ACCOUNT}', 'Waiting: sign-in expired'], ['Sign in again'], ["Google asks again every 7 days while Brainamon's Google sign-in is in testing."]),
    ('t12-wrong-account', dict(token_expired=True, state='error', error_code='wrong_account', error_action='sign_in_again', error_account='b@example.com',
                               error=f'You signed in as b@example.com, but this library backs up to {ACCOUNT}. Nothing changed.'), dict(REC_OK),
     [f'You signed in as b@example.com, but this library backs up to {ACCOUNT}. Nothing changed.', 'Switch this library to b@example.com…'], ['Sign in again'], []),
    ('t13-drive-full', dict(state='error', error='x', error_code='drive_full', error_action='free_space'), dict(REC_OK),
     ['Google Drive is full. Recent changes are not backed up yet.', 'Waiting: Google Drive full'], ['Try again'], []),
    ('t13b-first-backup-full', dict(last_publish=0, state='error', error='x', error_code='drive_full', done=100, total=1204, used=16106127360), dict(REC_OK),
     ['Google Drive is full (15.0 of 15.0 GB). 1,104 files are not backed up yet.', 'Free space in Google Drive, or back up fewer videos in Backup below.'], ['Try again'], []),
    ('t14-another-pc', dict(state='error', error='x', error_code='not_owner', error_action='recover', error_at=NOW - 2 * DAY), dict(REC_OK),
     ['Another PC became the backup PC on', 'This PC stopped backing up so it does not overwrite newer changes.', 'Keep working on this PC only', 'Stopped: another PC backs up'],
     ['Get the newer library…'], ['Recover a library…']),
    ('t14b-update-offered', dict(NOT_OWNER), dict(REC_OK, update=UPDATE_OK),
     ['Another PC became the backup PC on', 'Google Drive has a newer version of this library (backup from',
      "Update this folder downloads only what changed: 120 MB, 46 files. Then this PC backs up again. Phones paired with this PC keep working; phones paired with another PC scan this PC's code once (Add a phone).", 'Copy into a new folder…',
      'Keep working on this PC only'], ['Update this folder…'], ['Get the newer library…', 'This PC stopped backing up']),
    ('t14b-nothing-changed', dict(NOT_OWNER), dict(REC_OK, update=dict(UPDATE_OK, bytes=0, files=0, nothing=True)),
     ["Nothing changed there since this PC's last backup: updating only makes this PC the backup PC again."], ['Update this folder…'], ['Update this folder downloads']),
    ('t14b-other-key', dict(NOT_OWNER), dict(REC_OK, update=dict(eligible=False, reason='other_key', message='x')),
     ['This PC stopped backing up so it does not overwrite newer changes.'], ['Get the newer library…'], ['Update this folder…']),
    ('t14d-updating', dict(NOT_OWNER, task=updating('downloading', done=12, total=46, bytes_done=50 * 1048576, bytes_total=120 * 1048576)), dict(REC_OK, update=UPDATE_OK),
     ['Updating this folder: 50 MB of 120 MB.', 'Only what the other PC changed is downloaded. Your library stays usable meanwhile; edits you make now are kept with the earlier ones.',
      'You can close Settings. Quitting Brainamon pauses this; it continues at the next start.', 'Stop updating'], ['Done'], ['Another PC became the backup PC']),
    ('t14e-downloaded', dict(NOT_OWNER, task=updating('downloaded')), dict(REC_OK, update=UPDATE_OK),
     ['Downloaded. Restart Brainamon to switch to the newer library; this PC then backs up again.'], ['Restart now'], ['Stop updating']),
    ('t14e-update-failed', dict(NOT_OWNER, task=updating('downloading', error="Can't reach Google Drive. Nothing changed. Brainamon retries when the connection is back.")),
     dict(REC_OK, update=UPDATE_OK), ['Updating this folder stopped.', "Can't reach Google Drive. Nothing changed.", 'Stop updating'], ['Try again'], []),
    ('t14e-updated', dict(), dict(REC_OK, updated=dict(at=NOW - HOUR, published=NOW - DAY, kept=3, folder='C:/synthetic/data/before-update-2026-10-05')),
     ['This PC is the backup PC again.', "Kept this PC's 3 earlier changes in a copy of its library database (before update,", 'Hide'], ['Done'], [SAFE]),
    ('t15-two-copies', dict(state='error', error=TWO_COPIES, error_code='other_copy', error_action='none'), dict(REC_OK), [TWO_COPIES], ['Done'], ['Restore from', 'Reconnect']),
    ('t16-removing-phones', dict(rotation='pending', rotation_locked_at=NOW, state='publishing', done=2345, total=5678, bytes_done=4_100_000_000, bytes_total=9_800_000_000,
                                 task=REMOVING), dict(REC_OK),
     ['Removing all phones · step 3 of 5.', 'New key ready.', 'Phones locked out at 12:00.', 'Re-encrypting: 2,345 of 5,678 files (3.8 of 9.1 GB).', 'Delete the old copy.',
      'You can close Settings. Quitting Brainamon pauses this; it continues at the next start.', 'Re-encrypting with the new key (progress above)', 'Locked out at 12:00',
      'Phones you keep: add them again now. They load the library when re-encrypting finishes.', 'Lost or stolen? Also sign that phone out of your Google account.',
      'How to sign a phone out', 'Pause backup', 'Add a phone'], ['Done'], ['Remove all phones…', 'Reset backup…']),
    ('t16b-removing-needs-the-new-file', dict(rotation='pending', rotation_locked_at=NOW, state='publishing', task=REMOVING), dict(REC_OK, file_outdated=True, replaced_at=NOW // 1000),
     ['Removing all phones · step 3 of 5.', 'Save new recovery file…'], ['Save new recovery file…'], []),
    ('t16c-passphrase-created-during-rotation', dict(rotation='pending', state='publishing', task=REMOVING), dict(REC_OK, enrolled=False, verified=False, rotation_pending=True),
     ['Passphrase created', 'Recovery checks and passphrase changes are available after upload, verification and cleanup finish.',
      'Available after the backup update finishes. Progress is shown above.'], ['Done'], ['Recovery setup not finished', 'Check recovery']),
    ('t16d-first-backup-rotation-without-recovery', dict(rotation='pending', state='publishing', last_publish=0, task=REMOVING), {},
     ['Recovery setup waits for the backup update', 'Available after the backup update finishes. Progress is shown above.'], ['Done'], ['Choose a recovery passphrase']),
    ('t18-phones-removed', dict(rotation='complete', rotation_locked_at=NOW - HOUR), dict(REC_OK),
     ['All phones removed at 11:00.', 'Add each phone you keep again: its unsent edits arrive then.', 'Hide'], ['Add a phone'], []),
    ('t19-old-file', dict(), dict(REC_OK, file_outdated=True, replaced_at=NOW // 1000),
     ['Your library is safe, but your old recovery file stopped working when phones were removed.', 'Your passphrase still unlocks the backup.', 'Recovery file outdated since',
      'Removing phones made a new key. The old recovery file no longer opens your backup; your passphrase still does.'], ['Save new recovery file…'], []),
    ('t20-restart', dict(), dict(restored=True, restart_required=True, configured=True),
     ['The restored library is ready. Restart Brainamon to open it.', 'Your current library stays in its folder.'], ['Restart now'], []),
    ('t21-restored', dict(), dict(restored=True, configured=True),
     ['This restored library is not backed up yet.', 'Make this PC the backup PC once the old PC is off or closed.'], ['Make this PC the backup PC…'], []),
    ('t22-disconnected', dict(SIGNED_OUT), dict(REC_OK), ['Google Drive disconnected. Backup is off. The copy in sample@example.com from', 'stays in Drive.', 'Not connected'],
     ['Back up to Google Drive'], []),
    ('key-missing', dict(key_missing=True), dict(configured=False),
     [f"{ACCOUNT} already holds this library's backup", 'but this PC no longer has the key that opens it.', 'Unlock backup…', 'Reset backup instead…'], ['Unlock backup…'], ['Recover a library…']),
    ('backup-off', dict(on=False, running=False, state='off'), dict(REC_OK), ['Backup is off. Last backup:'], ['Turn on backup'], []),
    ('switching-account', dict(state='publishing', last_publish=0, done=5, total=100, task=task('switch_account', 'Switching Google account', 2, 3)), dict(REC_OK),
     ['Switching Google account · step 2 of 3.'], ['Done'], []),
    ('saving-the-passphrase', dict(task=task('enroll', 'Saving the recovery passphrase', 1, 3)), dict(configured=False),
     ['Backed up at 10:00. Saving your recovery passphrase…', 'Saving your passphrase · step 1 of 3', 'Backup pauses for these few seconds, then continues.',
      'Waiting for the current upload request: about 2 s, up to a minute on a slow connection.'], ['Done'], ['Create recovery passphrase']),
    ('recovery-file-saved-not-checked', dict(), dict(REC_OK, verified=False, verified_at=0),
     ['Recovery file saved', 'not checked', 'Open it once so you know it unlocks your backup.', 'Check recovery file…', 'Save another copy…'], ['Done'], []),
    ('passphrase-only', dict(), dict(REC_OK, verified=False, verified_at=0, saved_at=0),
     ['Recommended: also save a recovery file, in case you forget the passphrase.', 'Save recovery file…', 'Change passphrase…'], ['Done'], []),
    ('license-needed', dict(licensed=False), dict(REC_OK), ['Update this PC', 'Update Brainamon on this PC for payment-free phone sync. Your backup and recovery stay available.'], ['Done'], ['Add a phone']),
    ('phones-ignored', dict(ignored_changes=2), dict(REC_OK), ['2 changes from removed phones were ignored.'], ['Done'], []),
]

AUDIT = r"""() => {
  const vis = el => el.getClientRects().length > 0 && !el.closest('[hidden]')
  const win = document.querySelector('.cw.set-win')
  const body = win.querySelector('#set-panel > div:not([hidden])')
  const pri = [...win.querySelectorAll('.wkey.pri')].filter(vis).map(b => b.textContent.trim())
  const disabled = [...win.querySelectorAll('button:disabled, input:disabled, select:disabled')].filter(vis)
    .filter(el => !el.getAttribute('aria-describedby') && !el.title).map(el => el.textContent.trim() || el.id)
  // a status that asks for action ("next") needs a control in its own box or in the summary
  // (a key that is off for a reason shown beside it, like Google sign-in missing in a build, still tells the user what is needed)
  const controls = box => [...box.querySelectorAll('button, input')].filter(vis).filter(el => !el.disabled || el.getAttribute('aria-describedby'))
  const summary = body.querySelector('.group-box.summary')
  const dead = []
  for (const box of body.querySelectorAll('.group-box'))
    for (const s of box.querySelectorAll('.status-dot.next'))
      if (vis(s) && !controls(box).length && !(summary && controls(summary).length)) dead.push((s.closest('.status-line')?.textContent ?? '').trim().slice(0, 90))
  const links = [...body.querySelectorAll('a[href]')].filter(vis).map(a => a.textContent.trim())
  const panel = win.querySelector('#set-panel')
  const box = win.getBoundingClientRect()
  const overflow = panel.scrollWidth > panel.clientWidth + 1 || box.left < 0 || box.right > innerWidth + 1
  return { pri, disabled, dead, links, overflow }
}"""


class Review(shots.Run):
    def first_start(self, browser, theme):
        pass

    def phone(self, browser, theme):
        pass

    def desktop(self, browser, theme):
        ctx = self.context(browser, theme)
        view = self.api('GET', '/api/cloud')
        base = dict(view)
        calls = []
        recovery = {}
        sizes = dict(base=2_400_000_000, canvases=100_000_000, videos_fav=7_300_000_000, videos_all=19_000_000_000, videos_fav_count=12, videos_all_count=40, items=3000, files=5678)
        idle_recovery = dict(configured=False, enrolled=False, verified=False, verified_at=0, saved_at=0, setup_at=0, account='', restored=False, restart_required=False,
                             rotation_pending=False, file_outdated=False, replaced_at=0, takeover_ready=False, check=None, activity=None,
                             job={'state': 'idle', 'done': 0, 'total': 0, 'error': '', 'destination': ''}, preview=None)
        failing = {}
        update_answer = [None]      # what update-preview answers (W4b)

        def reset(cloud_changes, recovery_changes):
            view.clear()
            view.update(base)
            view.update(CONNECTED)
            view.update(cloud_changes)
            recovery.clear()
            recovery.update(idle_recovery)
            recovery.update(recovery_changes)

        def cloud_route(route):
            path = urlparse(route.request.url).path
            method = route.request.method
            if path == '/api/cloud/sizes':
                route.fulfill(json=sizes)
                return
            if path == '/api/cloud/recovery':
                route.fulfill(json=recovery)
                return
            if method == 'GET':
                route.fulfill(json=view)
                return
            body = route.request.post_data_json if route.request.post_data else {}
            calls.append((path, body))
            if path in failing:
                route.fulfill(status=409, json={'detail': failing[path]})
                return
            view['seq'] += 1
            if path.startswith('/api/cloud/recovery/'):
                action = path.rsplit('/', 1)[1]
                if action == 'preflight':
                    route.fulfill(json=dict(state='ready', message='Ready.', account=view['account'], enrolled=False))
                elif action == 'enroll':
                    recovery.update(configured=True, enrolled=True, account=view['account'], setup_at=NOW // 1000)
                    route.fulfill(json={'ok': True})
                elif action == 'kit':
                    route.fulfill(json={'synthetic': 'kit'})
                elif action == 'save-kit':
                    recovery.update(saved_at=NOW // 1000, verified=True, verified_at=NOW // 1000)
                    route.fulfill(json=dict(path=body['path'], saved=True, verified=True))
                elif action == 'verify':
                    recovery.update(verified=True, verified_at=NOW // 1000)
                    route.fulfill(json=recovery)
                elif action == 'preview':
                    recovery.update(preview=FOUND, job={'state': 'preview', 'done': 0, 'total': 3, 'error': '', 'destination': ''})
                    route.fulfill(json=recovery)
                elif action == 'restore':
                    recovery['job'].update(state='restoring', done=2, total=5, destination=body['destination'])
                    route.fulfill(json=recovery)
                elif action == 'cancel':
                    recovery['job'].update(state='cancelled')
                    route.fulfill(json=recovery)
                elif action == 'reconnect':
                    recovery.update(preview=None, job={'state': 'idle', 'done': 0, 'total': 0, 'error': '', 'destination': ''})
                    route.fulfill(json=recovery)
                elif action == 'update-preview':
                    recovery.update(update=update_answer[0])
                    route.fulfill(json=recovery)
                elif action == 'sign-in':
                    view.update(state='signing-in')
                    route.fulfill(json=view)
                else:
                    route.fulfill(json=recovery)
                return
            if path == '/api/cloud/pair':
                route.fulfill(json={'svg': '<svg viewBox="0 0 8 8"><rect width="8" height="8"/></svg>', 'fingerprint': '4F2A', 'url': 'https://example.invalid/pair', 'keys': ['openai']})
                return
            if path == '/api/cloud/pause':
                view.update(running=False, on=False, state='off', paused_since=NOW)
            elif path == '/api/cloud/resume' or path == '/api/cloud/connect':
                view.update(running=True, on=True, state='idle', paused_since=0)
            elif path == '/api/cloud/unpair':
                view.update(rotation='pending', task=dict(id='u', kind='remove_phones', stage='requested', title='Removing all phones', step=2, of=5, steps=[], done=0, total=0,
                                                         bytes_done=0, bytes_total=0, since=NOW, error='', code='', lock=''))
            elif path == '/api/cloud/options':
                view['options'].update(body)
            elif path == '/api/cloud/cancel-sign-in':
                view.update(state='off')
            elif path in ('/api/cloud/reauth', '/api/cloud/switch'):
                view.update(state='signing-in')
            elif path == '/api/cloud/sign-out':
                view.update(signed_in=False, running=False, on=False, state='off', account='' if body.get('delete_mirror') else view['account'])
            elif path == '/api/cloud/reset' or path == '/api/cloud/publish':
                view.update(state='publishing')
            route.fulfill(json=view)

        ctx.route('**/api/cloud**', cloud_route)
        ctx.add_init_script('''window.__cloudStreams = [];
            window.EventSource = class extends EventSource {
                constructor(...args) { super(...args); window.__cloudStreams.push(this) }
            };''')
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(self.url())
        page.wait_for_selector('.cell[data-id]')
        panel = page.locator('.set-win [role=tabpanel]')

        def open_view(cloud_changes=None, recovery_changes=None, settle=True):
            reset(cloud_changes or {}, recovery_changes or {})
            self.close_windows(page)
            page.keyboard.press('Control+Comma')
            page.wait_for_selector('.cw.set-win')
            if page.viewport_size['width'] < 700:
                page.locator('#set-section').select_option('backup')
            else:
                page.locator('#set-tbackup').click()
            if settle:
                self.settle(page)
                page.wait_for_timeout(250)

        def go(destination):
            if page.viewport_size['width'] < 700:
                page.locator('#set-section').select_option(destination)
            else:
                page.locator(f'#set-t{destination}').click()

        def button(name):
            return panel.get_by_role('button', name=name, exact=True)

        def audit(where):
            """The mockup's rules (projects/backup-phones-mockup/check.py): one primary in the window, a reason for every disabled
            control, no dead end, no link off the page, no horizontal overflow."""
            a = page.evaluate(AUDIT)
            assert len(a['pri']) <= 1, f'{where}: {len(a["pri"])} primaries: {a["pri"]}'
            assert not a['disabled'], f'{where}: disabled without a reason: {a["disabled"]}'
            assert not a['dead'], f'{where}: dead end: {a["dead"]}'
            assert not a['links'], f'{where}: a link leaves the page: {a["links"]}'
            assert not a['overflow'], f'{where}: horizontal overflow at {page.viewport_size["width"]}px'
            return a

        def capture(name):
            page.locator('.set-win .cw-body').evaluate('(e) => e.scrollTop = 0')
            self.shot(page, f'desktop-{theme}-settings-backup-{name}')

        def tab_to(locator):
            """Keyboard only: Tab from the top of the page until `locator` has the focus."""
            handle = locator.element_handle()
            page.locator('#set-panel').focus()
            for _ in range(400):
                page.keyboard.press('Tab')
                if page.evaluate('el => el === document.activeElement', handle):
                    return
            raise AssertionError(f'{locator} is not reachable with Tab')

        def tab_names():
            """Keyboard only: Tab from the top of the page and return the accessible names of the controls reached inside the
            Settings window, in order, until the focus leaves it or comes back to a control it already stopped on (a focus trap
            cycles). Controls are told apart by the element, not by the name: two keys can share one (None, All)."""
            page.locator('#set-panel').focus()
            page.evaluate('() => { window.__tabbed = new Set() }')
            names = []
            for _ in range(400):
                page.keyboard.press('Tab')
                info = page.evaluate('''() => {
                    const el = document.activeElement
                    if (!el || !el.closest('.set-win')) return null
                    const again = window.__tabbed.has(el)
                    window.__tabbed.add(el)
                    return { again, name: (el.getAttribute('aria-label') || el.textContent || '').trim() }
                }''')
                if info is None or info['again']:
                    break
                names.append(info['name'])
            return names

        def last():
            page.wait_for_timeout(250)          # the page's request reaches the mocked route
            return calls[-1]

        def calls_since(n):
            page.wait_for_timeout(250)
            return [path for path, _ in calls[n:]]

        if '--progress-only' in sys.argv:
            for width in (1440, 390):
                page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
                uploading = dict(RESETTING, done=250, total=1000, bytes_done=25 * 1048576, bytes_total=100 * 1048576, items_done=750, items_total=3000)
                open_view(dict(task=uploading, state='publishing'), dict(REC_OK))
                steps = panel.get_by_role('list', name='Backup steps')
                expect(steps.get_by_role('listitem')).to_have_count(3)
                expect(steps.locator('.cycle')).to_have_count(1)
                expect(steps.locator('li').first.locator('path')).to_have_count(1)
                expect(panel.get_by_text('750 / 3,000 item records backed up.', exact=False)).to_be_visible()
                expect(panel.get_by_text('Library · 3,000 items', exact=False)).to_be_visible()
                expect(panel.get_by_text('5,678 files in the backup.', exact=False)).to_be_visible()
                expect(panel.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '25')
                audit(f'progress-{width}')
                capture(f'progress-{width}')
                view.update(seq=view['seq'] + 1, task=dict(uploading, done=500, bytes_done=50 * 1048576, items_done=1500))
                page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
                expect(panel.get_by_text('1,500 / 3,000 item records backed up.', exact=False)).to_be_visible()
                expect(panel.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '50')
                cleanup = dict(RESETTING, stage='cleanup', step=3, done=100, total=1000, uploaded_items=3000, uploaded_items_total=3000, uploaded_files=4000)
                open_view(dict(task=cleanup), dict(REC_OK))
                expect(panel.get_by_role('list', name='Backup steps')).to_contain_text('3,000 / 3,000 item records · 4,000 / 4,000 files')
                expect(panel.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '10')
                expect(panel.get_by_text('100 of 1,000 files confirmed.', exact=False)).to_be_visible()
                view.update(seq=view['seq'] + 1, task=dict(cleanup, done=120))
                page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
                expect(panel.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '12')
                expect(panel.get_by_text('120 of 1,000 files confirmed.', exact=False)).to_be_visible()
                expect(panel.locator('.task-steps li:nth-child(2) path')).to_have_count(1)
                page.emulate_media(reduced_motion='no-preference')
                page.evaluate("document.documentElement.classList.remove('motion-off')")
                expect(panel.locator('.deletion-estimate')).to_be_visible()
                page.wait_for_function("() => Number(document.querySelector('.deletion-estimate').textContent.match(/: ([0-9,]+)/)[1].replaceAll(',',''))>120")
                expect(panel.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '12')

                page.emulate_media(reduced_motion='reduce')
                assert panel.locator('.task-steps .cycle').evaluate("e => getComputedStyle(e).animationName") == 'none'
                expect(panel.locator('.deletion-estimate')).to_be_hidden()
                page.emulate_media(reduced_motion='no-preference')
                audit(f'cleanup-{width}')
                capture(f'cleanup-{width}')
            assert not errors, errors
            ctx.close()
            print(f'{theme}: live upload/item counts, checklist, cleanup, layouts and reduced motion passed', flush=True)
            return

        # ── A15: every state keeps the rules; each says its words and offers its one primary (README: T, G, B, R, P) ──
        open_view({}, REC_OK)
        card = panel.get_by_role('region', name='Recovery', exact=True)
        guide = card.locator('details').first
        guide.locator('summary').first.focus()
        page.keyboard.press('Enter')
        before = len(calls)
        for situation in ('I can still open my library', 'I have a recovery file', 'I have a recovery code or a paired phone', 'I have none of these'):
            guide.get_by_text(situation, exact=True).click()
        expect(guide.get_by_text('Google sign-in alone cannot unlock', exact=False)).to_be_visible()
        assert len(calls) == before
        guide.get_by_role('button', name='Change passphrase…', exact=True).click()
        expect(card.get_by_text("You don't need the old one.", exact=False)).to_be_visible()
        expect(card.get_by_text('Recovery file checked.', exact=False)).to_be_visible()
        card.get_by_role('button', name='Cancel', exact=True).click()
        assert len(calls) == before
        # A previous preview must not override an explicitly selected method.
        recovery.update(preview=FOUND, job={'state': 'preview', 'done': 0, 'total': 3, 'error': '', 'destination': ''})
        guide.get_by_role('button', name='Use recovery file', exact=True).click()
        rw = page.get_by_role('dialog', name='Recover a library', exact=True)
        expect(rw.get_by_role('button', name='Recovery file', exact=True)).to_have_attribute('aria-pressed', 'true')
        rw.get_by_text('Forgot passphrase?', exact=True).click()
        rw.get_by_text('I have a recovery code or a paired phone', exact=True).click()
        before = len(calls)
        rw.get_by_role('button', name='Use recovery code', exact=True).click()
        rw.get_by_label('Phone code', exact=True).fill('synthetic-unsent-code')
        rw.get_by_role('button', name='Recovery file', exact=True).click()
        rw.get_by_role('button', name='Phone code', exact=True).click()
        expect(rw.get_by_label('Phone code', exact=True)).to_have_value('')
        assert len(calls) == before
        for width in (390, 1440):
            page.set_viewport_size({'width': width, 'height': 844})
            rw.get_by_text('I have none of these', exact=True).click()
            assert rw.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
            self.shot(page, f'forgot-{theme}-{width}')
            rw.get_by_text('I have none of these', exact=True).click()
        open_view({'rotation': 'pending', 'task': REMOVING}, dict(REC_OK, rotation_pending=True))
        card = panel.get_by_role('region', name='Recovery', exact=True)
        card.get_by_text('Forgot passphrase?', exact=True).click()
        card.get_by_text('I can still open my library', exact=True).click()
        expect(card.locator('details').get_by_role('button', name='Change passphrase…', exact=True)).to_be_disabled()
        expect(card.get_by_text('Passphrase changes wait until', exact=False)).to_be_visible()

        if '--guide-only' in sys.argv:
            assert not errors, errors
            ctx.close()
            print(f'{theme}: forgot-passphrase navigation, cancellation, rotation and layouts passed')
            return

        for name, cloud_changes, recovery_changes, see, pri, absent in STATES:
            open_view(cloud_changes, recovery_changes)
            window = page.locator('.set-win')
            for text in see:
                expect(window.get_by_text(text, exact=False).locator('visible=true').first, f'{name}: {text}').to_be_visible()
            for text in absent:
                expect(window.get_by_text(text, exact=False).locator('visible=true'), f'{name}: {text} is not shown').to_have_count(0)
            got = audit(name)['pri']
            assert got == pri, f'{name}: primary keys {got}, expected {pri}'
            if name in ('t6-safe', 't4-first-backup', 't16-removing-phones', 't1-not-connected') or name.startswith('reset-'):
                capture(name)
            if name == 'reset-preparing':
                assert window.get_by_role('progressbar', name='Resetting the backup').get_attribute('aria-valuenow') is None
            elif name == 'reset-uploading':
                expect(window.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '25')
            if name.startswith('reset-'):
                page.set_viewport_size({'width': 390, 'height': 844})
                audit(name + '-390')
                capture(name + '-390')
                page.set_viewport_size({'width': 1440, 'height': 1000})
            if name == 'reset-uploading':
                view.update(seq=view['seq'] + 1, task=dict(RESETTING, done=500, total=1000, bytes_done=50 * 1048576, bytes_total=100 * 1048576))
                page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
                expect(window.get_by_text('Uploading replacement backup: 50% · 500 of 1,000 files (50 MB of 100 MB).', exact=False)).to_be_visible()
                expect(window.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '50')
        assert not errors, errors

        # C4: the vault line names the files the last round left out for their size and says "Up to date" only when none were
        vault_note = '2 files over 50 MiB are not synced.'
        vault_on = dict(vault_running=True, vault_state='idle', vault_last=NOW - HOUR, vault=dict(on=True, folder='C:/synthetic/Vault'))
        open_view(dict(vault_on, vault_summary='2 files over 50 MiB are not synced', vault_skipped=2, vault_skipped_note=vault_note), dict(REC_OK))
        go('obsidian')
        expect(page.get_by_text('Vault sync is on. ' + vault_note, exact=True).first).to_be_visible()
        expect(page.get_by_text('Vault sync is on. Up to date.', exact=True)).to_have_count(0)
        open_view(dict(vault_on, vault_summary='Already in step'), dict(REC_OK))
        go('obsidian')
        expect(page.get_by_text('Vault sync is on. Up to date.', exact=True).first).to_be_visible()
        assert not errors, errors

        # A15, keyboard: every visible enabled key of the page is reached with Tab alone (sub-plan 09, deviation 9), and Enter works the primary
        by_name = {s[0]: s for s in STATES}
        for name in ('t1-not-connected', 't6-safe', 't12-wrong-account'):
            _, cloud_changes, recovery_changes, _, pri, _ = by_name[name]
            open_view(cloud_changes, recovery_changes)
            window = page.locator('.set-win')
            expected = window.get_by_role('button').locator('visible=true').evaluate_all(
                'els => els.filter(e => !e.disabled).map(e => (e.getAttribute("aria-label") || e.textContent || "").trim())')
            reached = tab_names()
            missing = sorted({n for n in expected if reached.count(n) < expected.count(n)})
            assert not missing, f'{name}: not reachable with Tab: {missing}'
            assert pri[0] in reached, f'{name}: the primary {pri[0]!r} is not reachable with Tab'
        open_view(by_name['t12-wrong-account'][1], by_name['t12-wrong-account'][2])
        tab_to(button('Sign in again'))
        page.keyboard.press('Enter')
        assert last()[0] == '/api/cloud/reauth', calls[-3:]

        # first setup, keyboard only: Back up, then the passphrase form that opens by itself while the first backup runs (D9, D10)
        open_view(dict(signed_in=False, running=False, on=False, account='', last_publish=0, state='off'))
        tab_to(button('Back up to Google Drive'))
        page.keyboard.press('Enter')
        assert last()[0] == '/api/cloud/connect'
        open_view(dict(last_publish=0, state='publishing', done=1204, total=5678, bytes_done=2_100_000_000, bytes_total=9_800_000_000, upload_since=NOW - 360_000), dict(configured=False))
        expect(panel.get_by_text('Choose a recovery passphrase', exact=True)).to_be_visible()
        expect(button('Save passphrase')).to_have_class(re.compile('pri'))
        assert audit('first setup')['pri'] == ['Save passphrase']
        count = len(calls)
        tab_to(button('Generate'))
        page.keyboard.press('Enter')
        generated = panel.locator('#bp-pass').input_value()
        assert re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{8}){3}', generated)
        assert calls_since(count) == [], 'Generating a passphrase must not change Drive'
        tab_to(panel.locator('#bp-pass'))                       # and typing one by hand, field to field
        page.keyboard.press('Control+A')
        page.keyboard.type('a long synthetic recovery phrase')
        tab_to(panel.locator('#bp-pass2'))
        page.keyboard.press('Control+A')
        page.keyboard.type('a long synthetic recovery phrase')
        tab_to(button('Save passphrase'))
        page.keyboard.press('Enter')
        assert last() == ('/api/cloud/recovery/enroll', {'password': 'a long synthetic recovery phrase', 'confirmation': 'a long synthetic recovery phrase'}), calls[-3:]
        # a short passphrase says why, and nothing is sent
        open_view(dict(), dict(configured=False))
        button('Create recovery passphrase').click()
        count = len(calls)
        panel.locator('#bp-pass').fill('short')
        button('Save passphrase').click()
        expect(panel.get_by_role('alert').filter(has_text='Use at least 12 characters.')).to_be_visible()
        panel.locator('#bp-pass').fill('a long synthetic recovery phrase')
        panel.locator('#bp-pass2').fill('another long synthetic phrase')
        button('Save passphrase').click()
        expect(panel.get_by_role('alert').filter(has_text='The two passphrases are different.')).to_be_visible()
        assert calls_since(count) == []
        page.wait_for_timeout(2300)         # ordinary status polling keeps what was typed
        expect(panel.locator('#bp-pass')).to_have_value('a long synthetic recovery phrase')
        panel.locator('#bp-pass2').fill('a long synthetic recovery phrase')
        audit('passphrase form')
        button('Save passphrase').click()
        assert last() == ('/api/cloud/recovery/enroll', {'password': 'a long synthetic recovery phrase', 'confirmation': 'a long synthetic recovery phrase'})

        # actions and what they send
        open_view(dict(), dict(REC_OK))
        count = len(calls)
        button('Pause backup').click()
        assert calls_since(count) == ['/api/cloud/pause']
        open_view(dict(on=False, running=False, paused_since=NOW - 3 * 24 * HOUR, state='off'), dict(REC_OK))
        expect(button('Resume backup')).to_have_class(re.compile('pri'))
        button('Resume backup').click()
        assert last()[0] == '/api/cloud/resume'
        open_view(dict(), dict(REC_OK))
        panel.get_by_role('group', name='Videos').get_by_role('button', name='All', exact=True).click()
        assert last() == ('/api/cloud/options', {'videos': 'all'})
        panel.get_by_role('group', name='Canvases').get_by_role('button', name='None', exact=True).click()
        assert last() == ('/api/cloud/options', {'canvases': False})
        # Switch account, Disconnect (what asking sends: nothing), Reset backup
        open_view(dict(), dict(REC_OK))
        count = len(calls)
        button('Switch account…').click()
        expect(panel.get_by_text('Switch to another Google account?', exact=False)).to_be_visible()
        assert audit('switch form')['pri'] == ['Switch account']
        button('Cancel').click()
        button('Disconnect Google Drive…').click()
        expect(button('Disconnect')).to_be_visible()
        assert calls_since(count) == [], 'Asking must not disconnect or delete'
        panel.get_by_role('switch', name='Also delete the backup from Google Drive').check()
        expect(button('Delete and disconnect')).to_be_visible()
        expect(panel.get_by_text('All Brainamon desktop backup data in', exact=False)).to_be_visible()
        panel.get_by_role('switch', name='Also delete the backup from Google Drive').uncheck()
        button('Disconnect').click()
        assert last() == ('/api/cloud/sign-out', {'delete_mirror': False})
        expect(panel.get_by_text('Google Drive disconnected. Backup is off.', exact=False)).to_be_visible()
        expect(button('Back up to Google Drive')).to_have_class(re.compile('pri'))
        open_view(dict(), dict(REC_OK))
        button('Disconnect Google Drive…').click()
        panel.get_by_role('switch', name='Also delete the backup from Google Drive').check()
        button('Delete and disconnect').click()
        assert last() == ('/api/cloud/sign-out', {'delete_mirror': True, 'delete_existing': True})
        open_view(dict(), dict(REC_OK))
        button('Switch account…').click()
        panel.get_by_role('switch', name='Delete the copy in sample@example.com once the new backup is complete').check()
        button('Switch account').click()
        assert last() == ('/api/cloud/switch', {'delete_old': True})
        open_view(dict(), dict(REC_OK))
        count = len(calls)
        button('Reset backup…').click()
        expect(panel.get_by_text('Reset the backup?', exact=True).first).to_be_visible()
        assert audit('reset form')['pri'] == []   # the form's danger key is its submit; Done steps back
        assert calls_since(count) == []
        button('Reset backup').click()
        assert last()[0] == '/api/cloud/reset'

        # recovery file: desktop saves and reads back (D11); a browser download is not confirmed
        open_view(dict(), dict(configured=True, enrolled=True, account='sample@example.com', setup_at=NOW // 1000))
        expect(panel.get_by_text('Recommended: also save a recovery file', exact=False)).to_be_visible()
        with page.expect_download():
            button('Save recovery file…').click()
        expect(panel.get_by_text('A browser download is not confirmed until you open the file.', exact=False)).to_be_visible()
        expect(panel.get_by_text('saved', exact=False).first).to_be_visible()
        with page.expect_file_chooser() as chooser:
            button('Check recovery file…').click()
        chooser.value.set_files({'name': 'kit.json', 'mimeType': 'application/json', 'buffer': b'{"synthetic":"kit"}'})
        expect(panel.get_by_text('Recovery file checked against your backup.', exact=True)).to_be_visible()
        assert last()[0] == '/api/cloud/recovery/verify'

        # phones: an older backend asks for an update, without a purchase/activation form
        open_view(dict(licensed=False), dict(REC_OK))
        expect(panel.get_by_text('Update this PC', exact=True)).to_be_visible()
        expect(panel.get_by_label('License key', exact=True)).to_have_count(0)
        open_view(dict(), dict(REC_OK))
        count = len(calls)
        button('Add a phone').click()
        expect(panel.get_by_role('img', name='Phone pairing QR code')).to_be_visible()
        assert last() == ('/api/cloud/pair', {'keys': ['anthropic', 'openai']})
        expect(panel.get_by_text('Code check: 4F2A.', exact=False)).to_be_visible()
        audit('pairing')
        button('Hide code').click()
        button('Remove all phones…').click()
        expect(panel.get_by_text('Remove all phones?', exact=True)).to_be_visible()
        assert audit('remove form')['pri'] == []
        n = len(calls)
        button('Remove all phones').click()
        expect(panel.get_by_role('alert').filter(has_text='Type your current recovery passphrase')).to_be_visible()
        assert calls_since(n) == []
        panel.get_by_role('button', name='Choose a new one', exact=True).click()
        panel.locator('#bp-pass').fill('a brand new synthetic phrase')
        panel.locator('#bp-pass2').fill('a brand new synthetic phrase')
        button('Remove all phones').click()
        assert last() == ('/api/cloud/unpair', {'recovery_passphrase': '', 'new_passphrase': 'a brand new synthetic phrase'})
        failing['/api/cloud/unpair'] = 'Synthetic: Drive is full.'
        open_view(dict(), dict(REC_OK))
        button('Remove all phones…').click()
        panel.locator('#bp-current').fill('a long synthetic recovery phrase')
        button('Remove all phones').click()
        expect(panel.get_by_role('alert').filter(has_text='Synthetic: Drive is full.')).to_be_visible()
        failing.clear()
        open_view(dict(), dict(configured=False))
        button('Remove all phones…').click()
        button('Remove all phones').click()
        assert last() == ('/api/cloud/unpair', {'recovery_passphrase': '', 'new_passphrase': ''})
        # the first backup after a restored library or a switch asks for the passphrase of THIS account (D10)
        open_view(dict(last_publish=0, state='publishing', done=3, total=50, bytes_done=5, bytes_total=500), dict(REC_OK, account='old@example.com'))
        expect(panel.get_by_text('Choose a recovery passphrase', exact=True)).to_be_visible()

        # take over a restored library: the passphrase from the recovery is reused when the PC has it sealed (D3)
        open_view(dict(), dict(restored=True, configured=True, enrolled=False, takeover_ready=True))
        button('Make this PC the backup PC…').click()
        expect(panel.get_by_text('The passphrase you just used keeps protecting it.', exact=False)).to_be_visible()
        expect(panel.locator('#bp-pass')).to_have_count(0)
        button('Make this PC the backup PC').click()
        assert last() == ('/api/cloud/recovery/take-over', {'password': '', 'confirmation': '', 'confirm': True})
        open_view(dict(), dict(restored=True, configured=True, enrolled=False, takeover_ready=False))
        button('Make this PC the backup PC…').click()
        expect(panel.locator('#bp-pass')).to_have_count(1)

        # Update this folder (S9): the confirm names this PC's later changes (T14c); Stop updating; Restart now prepares the switch
        open_view(dict(NOT_OWNER), dict(REC_OK, update=dict(UPDATE_OK, local_changes=3)))
        button('Update this folder…').click()
        expect(panel.get_by_text(f'Update this folder? Brainamon downloads 120 MB of changes from {ACCOUNT}, switches to the newer library at the restart', exact=False)).to_be_visible()
        expect(panel.get_by_role('alert').filter(has_text='This PC has 3 changes made after its last backup')).to_be_visible()
        expect(panel.get_by_role('alert').filter(has_text='Brainamon keeps this PC\'s library database as a dated copy beside the library')).to_be_visible()
        assert audit('t14c-confirm')['pri'] == ['Update this folder'], audit('t14c-confirm')
        capture('t14c-confirm')
        button('Update this folder').click()
        assert last() == ('/api/cloud/recovery/update-start', {'confirm': True}), calls[-3:]
        open_view(dict(NOT_OWNER), dict(REC_OK, update=UPDATE_OK))
        button('Keep working on this PC only').click()
        expect(panel.get_by_text('Not backed up: another PC is the backup PC.', exact=True)).to_be_visible()
        expect(button('Update this folder…')).to_be_visible()
        open_view(dict(NOT_OWNER), dict(REC_OK))
        assert ('/api/cloud/recovery/update-preview', {}) in calls, 'another PC took over: the page asks once whether this folder can update'
        open_view(dict(NOT_OWNER, task=updating('downloading', bytes_done=5, bytes_total=10)), dict(REC_OK, update=UPDATE_OK))
        capture('t14d-updating')
        button('Stop updating').click()
        assert last()[0] == '/api/cloud/recovery/update-cancel'
        failing['/api/cloud/recovery/update-activate'] = 'The other PC backed up again. Brainamon is fetching those changes first; restart when it says Downloaded.'
        open_view(dict(NOT_OWNER, task=updating('downloaded')), dict(REC_OK, update=UPDATE_OK))
        button('Restart now').click()
        assert last()[0] == '/api/cloud/recovery/update-activate'
        expect(panel.get_by_role('alert').filter(has_text='The other PC backed up again.')).to_be_visible()
        failing.clear()

        # A14: a task that failed while Settings was closed: the reopened page shows the classified reason and names the operation
        reason = "Can't reach Google Drive. Nothing changed. Brainamon retries when the connection is back."
        failed_removal = dict(id='r', kind='remove_phones', stage='prepared', title='Removing all phones', step=3, of=5, steps=[], done=0, total=0, bytes_done=0, bytes_total=0,
                              since=NOW, error=reason, code='offline', lock='')
        open_view(dict(rotation='pending', task=failed_removal, rotation_locked_at=NOW), dict(REC_OK))
        expect(panel.get_by_text('Removing all phones stopped.', exact=True)).to_be_visible()
        expect(panel.get_by_role('alert').filter(has_text=reason).first).to_be_visible()
        failed_enroll = dict(id='e', kind='enroll', stage='uploading', title='Saving the recovery passphrase', step=2, of=3, steps=[], done=0, total=0, bytes_done=0, bytes_total=0,
                             since=NOW, error='Google Drive sign-in for sample@example.com expired or was removed. Choose Sign in again and pick the same account. Your backup and settings stay as they are.',
                             code='auth_expired', lock='')
        open_view(dict(task=failed_enroll), dict(configured=False))
        expect(panel.get_by_text('Saving your passphrase · step 2 of 3', exact=False)).to_be_visible()
        expect(panel.get_by_role('alert').filter(has_text='Choose Sign in again and pick the same account.').first).to_be_visible()
        assert 'Change account' not in panel.inner_text() and 'did not finish' not in panel.inner_text()
        expect(button('Create recovery passphrase')).to_be_visible()      # no dead end: a save that stopped is retried by typing the passphrase again

        # the passphrase check that met an upload waits for a slot instead of refusing (S8)
        open_view(dict(rotation='pending', state='publishing', task=REMOVING), dict(REC_OK, enrolled=False, verified=False, rotation_pending=True))
        expect(button('Change passphrase…')).to_be_disabled()
        expect(button('Check recovery')).to_have_count(0)
        expect(panel.get_by_text('Passphrase created', exact=False)).to_be_visible()

        open_view(dict(), dict(configured=True, enrolled=False, account='sample@example.com'))
        expect(panel.get_by_text('Recovery setup not finished', exact=True)).to_be_visible()
        expect(panel.get_by_text('Passphrase created.', exact=False)).to_be_visible()
        button('Check recovery').click()
        assert last()[0] == '/api/cloud/recovery/preflight'

        # Saved reset: pause and failure take precedence over an apparently live progress bar.
        resetting = task('reset_backup', 'Resetting the backup', 2, 3)
        open_view(dict(task=resetting, on=False, running=False, state='off', paused_since=NOW), dict(REC_OK))
        expect(panel.get_by_text('Resetting the backup is paused too.', exact=False)).to_be_visible()
        expect(button('Resume backup')).to_be_visible()
        expect(button('Pause backup')).to_have_count(0)
        open_view(dict(task=dict(resetting, error='Synthetic reset failure.'), state='error'), dict(REC_OK))
        expect(panel.get_by_text('Resetting the backup stopped.', exact=True)).to_be_visible()
        expect(button('Try again')).to_be_visible()

        # No key has real exits; neither opening nor cancelling the confirmation mutates Drive.
        foreign = dict(state='error', error='Existing cloud backup', error_code='foreign_backup', last_publish=0)
        open_view(foreign, {})
        count = len(calls)
        button('Replace cloud backup with this PC’s library…').click()
        expect(panel.get_by_role('alert').filter(has_text='Replace the desktop backup')).to_be_visible()
        expect(button('Recover this backup…')).to_have_count(0)
        expect(panel.get_by_text('First backup running (progress above)', exact=True)).to_have_count(0)
        self.shot(page, f'desktop-{theme}-replace-backup-confirm')
        button('Cancel').click()
        expect(button('Recover this backup…')).to_be_visible()
        assert len(calls) == count
        button('Delete cloud backup and disconnect…').click()
        button('Delete and disconnect').click()
        assert last() == ('/api/cloud/sign-out', {'delete_mirror': True, 'delete_existing': True})

        open_view(foreign, {})
        button('Recover this backup…').click()
        recovery_window = page.get_by_role('dialog', name='Recover a library', exact=True)
        recovery_window.get_by_role('button', name='I don’t have a key', exact=True).click()
        recovery_window.get_by_role('button', name='Replace cloud backup with this PC’s library…', exact=True).click()
        count = len(calls)
        self.shot(page, f'desktop-{theme}-recover-without-key')
        recovery_window.get_by_role('button', name='Replace with this PC’s library', exact=True).click()
        expect(recovery_window).to_have_count(0)
        assert ('/api/cloud/reset', {'replace_existing': True}) in calls[count:]
        assert '/api/cloud/resume' not in calls_since(count)

        # narrow: no horizontal scroll in a busy state and a long one (A15 at 390 px)
        page.set_viewport_size({'width': 390, 'height': 844})
        for name, cloud_changes, recovery_changes, see, pri, absent in STATES:
            if name in ('t4-first-backup', 't16-removing-phones', 't3-foreign-backup', 't6-safe', 't11-expired'):
                open_view(cloud_changes, recovery_changes)
                audit(name + ' at 390 px')
                if name == 't16-removing-phones':
                    self.shot(page, f'desktop-{theme}-settings-backup-removing-narrow')
        page.set_viewport_size({'width': 1440, 'height': 1000})

        # the rail's Jobs module: a DRIVE row for the first backup, removing phones and a pause that waits for Resume (D14); nothing for a small upload
        rail_states = [
            ('idle', dict(), [], ['First backup', 'Removing phones', 'Backup paused'], None),
            ('uploading changes', dict(state='publishing', total=12, done=3), [], ['DRIVE'], None),
            ('first backup', dict(last_publish=0, state='publishing', done=1204, total=5678, bytes_done=2_100_000_000, bytes_total=9_800_000_000),
             ['First backup · 1,204/5,678', '21%'], [], 'Pause backup'),
            ('removing phones', dict(rotation='pending', state='publishing', task=REMOVING), ['Removing phones · step 3 of 5'], [], 'Pause backup'),
            ('paused', dict(on=False, running=False, state='off', paused_since=NOW - 3 * DAY), ['Backup paused · 3 days', 'Changes since 10:00 are only on this PC.'], [], 'Resume backup'),
            ('pausing', dict(state='stopping'), ['Pausing after the current upload request'], [], None),
            ('updating this folder', dict(NOT_OWNER, task=updating('downloading', bytes_done=30, bytes_total=120)), ['Updating this folder', '25%'], ['Removing phones'], 'Pause backup'),
            ('update downloaded', dict(NOT_OWNER, task=updating('downloaded')), [], ['Updating this folder'], None),
        ]
        for name, changes, see, absent, key in rail_states:
            reset(changes, dict(REC_OK))
            self.close_windows(page)
            page.reload()
            page.wait_for_selector('.cell[data-id]')
            self.settle(page)
            rail = page.locator('.rjobs')
            for text in see:
                expect(rail.get_by_text(text, exact=False).first, f'rail {name}: {text}').to_be_visible()
            for text in absent:
                expect(rail.get_by_text(text, exact=False), f'rail {name}: {text} is not shown').to_have_count(0)
            if key:
                count = len(calls)
                rail.get_by_role('button', name=key, exact=True).click()
                assert calls_since(count) == ['/api/cloud/' + ('resume' if key.startswith('Resume') else 'pause')], (name, calls_since(count))
            else:
                expect(rail.get_by_role('button', name='Pause backup', exact=True)).to_have_count(0)
                expect(rail.get_by_role('button', name='Resume backup', exact=True)).to_have_count(0)
        reset(dict(last_publish=0, state='publishing', done=5, total=100, bytes_done=1, bytes_total=100), dict(REC_OK))
        page.reload()
        page.wait_for_selector('.cell[data-id]')
        page.locator('.rjobs').get_by_role('button', name='Progress', exact=True).click()
        expect(page.locator('.set-heading h2')).to_have_text('Backup & phones')
        expect(page.locator('#set-s-sync-uploads')).to_be_focused()

        # the Recover a library window: pauses the backup while it runs, resumes it after, reads before it writes (W1 to W8)
        open_view(dict(), dict(REC_OK))
        count = len(calls)
        page.locator('.set-win .cw-foot').get_by_role('button', name='Recover a library…', exact=True).click()
        recover = page.locator('.cw').filter(has=page.get_by_label('Recover a library')).last
        expect(recover.get_by_text('Signed in as sample@example.com.', exact=False)).to_be_visible()
        assert calls_since(count) == ['/api/cloud/pause'], calls_since(count)
        expect(recover.get_by_role('button', name='Find backup', exact=True)).to_be_disabled()
        expect(recover.get_by_text('Type your passphrase first.', exact=True)).to_be_visible()
        recover.get_by_label('Recovery passphrase', exact=True).fill('a long synthetic recovery phrase')
        recover.get_by_role('button', name='Find backup', exact=True).click()
        assert last() == ('/api/cloud/recovery/preview', {'password': 'a long synthetic recovery phrase'}), calls[-4:]
        expect(recover.get_by_text('Found the backup from', exact=False)).to_be_visible()
        expect(recover.get_by_text('1,234 items, 5,678 files, 9.8 GB.', exact=False)).to_be_visible()
        expect(recover.get_by_text(SKIPPED, exact=True)).to_be_visible()      # the preview says what the backup left out (its omissions)
        expect(recover.get_by_text('Used the recovery setup from 12 Oct', exact=False)).to_be_visible()
        expect(recover.get_by_text('This folder matches it', exact=False)).to_be_visible()
        keep = recover.get_by_role('button', name='Keep this folder', exact=True)
        expect(keep).to_have_class(re.compile('pri'))
        recover.get_by_role('button', name='Copy into a new folder instead', exact=True).click()
        copy = recover.get_by_role('button', name='Copy into new folder', exact=True)
        expect(copy).to_be_disabled()
        expect(recover.get_by_text('Choose a new folder first.', exact=True)).to_be_visible()
        recover.get_by_label('New folder', exact=True).fill('C:/synthetic/new-library')
        copy.click()
        assert last() == ('/api/cloud/recovery/restore', {'destination': 'C:/synthetic/new-library'})
        expect(recover.get_by_text('Copying 2 of 5 files', exact=False)).to_be_visible()
        expect(recover.get_by_text('You can close this window.', exact=False)).to_be_visible()
        recover.get_by_role('button', name='Stop copying', exact=True).click()
        assert last()[0] == '/api/cloud/recovery/cancel'
        expect(recover.get_by_role('button', name='Retry copy', exact=True)).to_be_visible()
        recover.get_by_role('button', name='Use another method', exact=True).click()
        recover.get_by_role('button', name='Phone code', exact=True).click()
        recover.get_by_label('Phone code', exact=True).fill('synthetic-code')
        recover.get_by_role('button', name='Find backup', exact=True).click()
        assert last() == ('/api/cloud/recovery/preview', {'material': 'synthetic-code'})
        # Keep this folder: no passphrase asked when the one typed is known, one is asked for otherwise (D3)
        FOUND['password_known'] = False
        recovery['job'].update(state='preview')
        recover.get_by_role('button', name='Use another method', exact=True).click()
        recover.get_by_label('Phone code', exact=True).fill('synthetic-code')
        recover.get_by_role('button', name='Find backup', exact=True).click()
        expect(recover.get_by_label('Recovery passphrase', exact=True)).to_be_visible()
        recover.get_by_label('Recovery passphrase', exact=True).fill('short')
        recover.get_by_role('button', name='Keep this folder', exact=True).click()
        expect(recover.get_by_role('alert').filter(has_text='Use at least 12 characters.')).to_be_visible()
        recover.get_by_label('Recovery passphrase', exact=True).fill('a long synthetic recovery phrase')
        recover.get_by_label('Repeat it', exact=True).fill('a long synthetic recovery phrase')
        recover.get_by_role('button', name='Keep this folder', exact=True).click()
        assert last() == ('/api/cloud/recovery/reconnect', {'password': 'a long synthetic recovery phrase', 'confirmation': 'a long synthetic recovery phrase', 'confirm': True})
        expect(recover.get_by_text('This folder is unlocked again. Backup continues from where it stopped.', exact=True)).to_be_visible()
        count = len(calls)
        recover.get_by_role('button', name='Done', exact=True).click()
        page.wait_for_function("document.querySelectorAll('.cw').length === 1", timeout=3000)
        page.wait_for_timeout(500)
        assert '/api/cloud/resume' in calls_since(count), calls_since(count)      # the pause was the window's own: it undoes it
        # W4b: the backup found has this folder's key and another PC moved it on: Update this folder first, copying stays one click away
        update_answer[0] = UPDATE_OK
        open_view(dict(NOT_OWNER), dict(REC_OK, fingerprint='abc'))
        page.locator('.set-win .cw-foot').get_by_role('button', name='Recover a library…', exact=True).click()
        recover = page.locator('.cw').filter(has=page.get_by_label('Recover a library')).last
        FOUND.update(fingerprint='abc', reconnect={'ok': False, 'reason': 'has_key', 'message': ''})
        recover.get_by_label('Recovery passphrase', exact=True).fill('a long synthetic recovery phrase')
        recover.get_by_role('button', name='Find backup', exact=True).click()
        expect(recover.get_by_text("This folder already holds this backup's key: Update this folder downloads only what the other PC changed (120 MB) and makes this PC the backup PC again.", exact=True)).to_be_visible()
        assert ('/api/cloud/recovery/update-preview', {}) in calls[-3:], calls[-3:]
        update = recover.get_by_role('button', name='Update this folder', exact=True)
        expect(update).to_have_class(re.compile('pri'))
        expect(recover.get_by_label('New folder', exact=True)).to_have_count(0)
        self.shot(page, f'desktop-{theme}-recover-w4b-update')
        recover.get_by_role('button', name='Copy into a new folder instead', exact=True).click()
        expect(recover.get_by_label('New folder', exact=True)).to_be_visible()
        recover.get_by_role('button', name='Use another method', exact=True).click()
        recover.get_by_label('Recovery passphrase', exact=True).fill('a long synthetic recovery phrase')
        recover.get_by_role('button', name='Find backup', exact=True).click()
        count = len(calls)
        recover.get_by_role('button', name='Update this folder', exact=True).click()
        page.wait_for_function("document.querySelectorAll('.cw').length === 1", timeout=3000)      # it closes: the summary shows the progress
        page.wait_for_timeout(500)
        assert ('/api/cloud/recovery/update-start', {'confirm': True}) in calls[count:], calls[count:]
        update_answer[0] = None
        FOUND.pop('fingerprint')
        FOUND['reconnect'] = {'ok': True, 'reason': '', 'message': ''}
        # the window never touches a backup it did not pause, and shows the sign-in step while signed out
        open_view(dict(signed_in=False, running=False, on=False, account='', last_publish=0, state='off'))
        count = len(calls)
        page.locator('.set-win .cw-foot').get_by_role('button', name='Recover a library…', exact=True).click()
        recover = page.locator('.cw').filter(has=page.get_by_label('Recover a library')).last
        expect(recover.get_by_text('Get a Brainamon backup from Google Drive onto this PC.', exact=False)).to_be_visible()
        recover.get_by_role('button', name='Sign in with Google', exact=True).click()
        assert last()[0] == '/api/cloud/recovery/sign-in'
        expect(recover.get_by_text('Finish signing in in the browser window that opened.', exact=True)).to_be_visible()
        recover.get_by_role('button', name='Cancel sign-in', exact=True).click()
        assert last()[0] == '/api/cloud/cancel-sign-in'
        assert '/api/cloud/pause' not in calls_since(count) and '/api/cloud/resume' not in calls_since(count)
        self.close_windows(page)
        assert not errors, errors
        ctx.close()
        ctx = self.context(browser, theme)
        ctx.route('**/api/cloud**', cloud_route)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(self.url())
        page.wait_for_selector('.cell[data-id]')
        panel = page.locator('.set-win [role=tabpanel]')
        reset({}, dict(REC_OK))
        page.set_viewport_size({'width': 1440, 'height': 1000})
        saved_settings = self.api('GET', '/api/settings')
        key_calls = []
        fail_key = False
        def settings_route(route):
            if route.request.method == 'PUT':
                payload = route.request.post_data_json
                key_calls.append(payload)
                if fail_key:
                    route.fulfill(status=409, json={'detail': 'Synthetic key save failed. Retry.'})
                    return
                for provider in payload.get('keys', {}):
                    saved_settings['keys'][provider] = True
                for provider in payload.get('clear_keys', []):
                    saved_settings['keys'][provider] = False
                saved_settings['plain'].update(payload.get('plain', {}))
                for provider in saved_settings['models']['providers']:
                    provider['has_key'] = saved_settings['keys'].get(provider['id'], False)
            route.fulfill(json=saved_settings)
        ctx.route('**/api/settings', settings_route)
        assert self.palette(page, 'Set up Brainamon')
        page.keyboard.press('Control+Comma')
        go('ai')
        keys = page.locator('.set-win [role=tabpanel]')
        page.locator('#k-anthropic').fill('synthetic-anthropic')
        page.locator('#k-openai').fill('synthetic-openai')
        page.locator('#set-find').fill('ollama')
        page.locator('#set-find').press('Enter')
        expect(page.locator('#set-s-local')).to_be_focused()
        page.locator('#l-url').fill('http://localhost:12345/v1')
        go('ai')
        row = keys.locator('#k-anthropic').locator('..')
        row.get_by_role('button', name='Save Anthropic key', exact=True).focus()
        page.keyboard.press('Enter')
        expect(page.locator('#k-anthropic')).to_have_value('')
        expect(page.locator('#k-openai')).to_have_value('synthetic-openai')
        assert key_calls == [{'keys': {'anthropic': 'synthetic-anthropic'}}]
        expect(page.locator('#set-tai')).to_have_class(re.compile('dirty'))
        page.locator('#k-anthropic').fill('synthetic-replacement')
        writes_before = len(key_calls)
        row.get_by_role('button', name='Save Anthropic key', exact=True).evaluate('(e) => { e.click(); e.click() }')
        expect(page.locator('#k-anthropic')).to_have_value('')
        assert len(key_calls) == writes_before + 1
        assert key_calls[-1] == {'keys': {'anthropic': 'synthetic-replacement'}}
        expect(page.locator('#k-openai')).to_have_value('synthetic-openai')
        page.locator('.set-win .cw-foot').get_by_role('button', name='Back to Setup', exact=True).click()
        setup = page.get_by_role('dialog', name='Set up Brainamon', exact=True)
        expect(setup.locator('#setup-stage')).to_be_focused()
        checklist = setup.get_by_role('navigation', name='Setup checklist')
        checklist.get_by_role('button', name='Drive & recovery', exact=False).click()
        setup.get_by_role('button', name='Advanced cloud settings', exact=True).click()
        expect(page.locator('.set-heading h2')).to_have_text('Backup & phones')
        expect(page.locator('#set-s-sync-account')).to_be_focused()
        page.locator('.set-win .cw-foot').get_by_role('button', name='Back to Setup', exact=True).click()
        checklist.get_by_role('button', name='Connect your phone', exact=False).click()
        setup.get_by_role('button', name='Advanced phone settings', exact=True).click()
        expect(page.locator('.set-heading h2')).to_have_text('Backup & phones')
        expect(page.locator('#set-s-sync-pair')).to_be_focused()
        page.locator('.set-win .cw-foot').get_by_role('button', name='Back to Setup', exact=True).click()
        checklist.get_by_role('button', name='Wiskit AI', exact=False).click()
        setup.get_by_text('More AI options', exact=True).click()
        setup.get_by_role('button', name='Advanced AI settings', exact=True).click()
        expect(page.locator('.set-win')).to_have_count(1)
        expect(page.locator('#k-openai')).to_have_value('synthetic-openai')
        fail_key = True
        page.locator('#k-openai').locator('..').get_by_role('button', name='Save OpenAI key', exact=True).click()
        expect(keys.get_by_role('alert')).to_have_text('Synthetic key save failed. Retry.')
        expect(page.locator('#k-openai')).to_have_value('synthetic-openai')
        fail_key = False
        page.locator('#k-openai').locator('..').get_by_role('button', name='Save OpenAI key', exact=True).click()
        expect(page.locator('#k-openai')).to_have_value('')
        row.get_by_role('button', name='Remove key', exact=True).click()
        row.get_by_role('button', name='Confirm removal', exact=True).click()
        expect(row.get_by_role('button', name='Remove key', exact=True)).to_have_count(0)
        assert key_calls[-1] == {'clear_keys': ['anthropic']}
        expect(page.locator('#l-url')).to_have_value('http://localhost:12345/v1')
        page.locator('.set-win .cw-foot').get_by_role('button', name='Save', exact=True).click()
        expect(page.locator('#set-tai')).not_to_have_class(re.compile('dirty'))
        assert key_calls[-1]['plain']['local_base'] == 'http://localhost:12345/v1'
        go('ai')
        page.set_viewport_size({'width': 390, 'height': 844})
        assert keys.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
        self.shot(page, f'desktop-{theme}-settings-key-save-narrow')
        assert not errors, errors
        ctx.close()
        print(f'{theme}: Backup & phones states, forms, action payloads, the Recover window and 390px passed')


if __name__ == '__main__':
    args = SimpleNamespace(repo=str(ROOT), dist=str(ROOT / 'web/dist'), port=0,
                           out=tempfile.mkdtemp(prefix='brainamon-browser-shots-'), only=None,
                           root=None, themes='dark,light')
    Review(args).go()
