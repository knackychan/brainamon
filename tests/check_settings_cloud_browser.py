"""Backup & phones Settings page and the Recover a library window against mocked Drive responses; never signs into Google.

Run after building web/: py tests/check_settings_cloud_browser.py   (--remove-only: just Remove all phones in flight and its steps)
Uses the existing screenshot harness and its throwaway library (its own cloud folder). The rules of the approved mockup
(projects/backup-phones-mockup/check.py) are asserted on every state: one primary key in the window, a reason next to every
disabled control, no dead end, no link off the page, no horizontal overflow, in light and dark at 1440 and 390 px.
"""
import importlib.util
import argparse
import copy as copies
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
CONNECTED = dict(signed_in=True, configured=True, licensed=True, pair_ready=True, account=ACCOUNT, on=True, running=True, state='idle', last_publish=NOW - 2 * HOUR,
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
REMOVING.update(stage='publishing', done=2345, total=5678, bytes_done=4_100_000_000, bytes_total=9_800_000_000,
                steps=[dict(label=label, state='done' if i < 2 else 'active' if i == 2 else 'waiting') for i, label in
                       enumerate(['New key ready', 'Phones locked out', 'Re-encrypting', 'Checking the new copy', 'Deleting the old copy'])])
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
     ['Backing up for the first time: 1,204 of 5,678 files (2.0 of 9.1 GB).', 'You can create your recovery passphrase while it runs',
      'First backup · 1,204 of 5,678 files', 'Pause backup'], ['Done'], ['Choose a recovery passphrase']),
    ('t4b-first-backup-recovered', dict(last_publish=0, state='publishing', done=10, total=5678, bytes_done=1_000_000, bytes_total=9_800_000_000), dict(REC_OK),
     ['Backing up for the first time: 10 of 5,678 files'], ['Done'], ['Choose a recovery passphrase']),
    ('reset-preparing', dict(task=RESETTING, state='publishing', upload_step='Preparing the encrypted library for upload…'), dict(REC_OK),
     ['Preparing the encrypted library for upload… · in progress', 'Deleting the old backup · waiting', 'Drive temporarily holds both copies.'], ['Done'], ['0%']),
    ('reset-uploading', dict(task=dict(RESETTING, done=250, total=1000, bytes_done=25 * 1048576, bytes_total=100 * 1048576), state='publishing'), dict(REC_OK),
     ['Backing up again: 250 of 1,000 files (25 MB of 100 MB)', 'Deleting the old backup · waiting'], ['Done'], []),
    ('reset-small-progress', dict(task=dict(RESETTING, done=10, total=1000, bytes_done=1048576, bytes_total=1000 * 1048576), state='publishing'), dict(REC_OK),
     ['Backing up again: 10 of 1,000 files (1 MB of 1000 MB)'], ['Done'], []),
    ('reset-deleting', dict(task=dict(RESETTING, stage='cleanup', step=3, done=4, total=10, steps=[dict(label=x['label'], state='active' if n == 2 else 'done') for n, x in enumerate(RESETTING['steps'])])), dict(REC_OK),
     ['Deleting the old backup: 4 of 10 files confirmed. · in progress', 'Backing up again · done'], ['Done'], ['Uploading replacement backup:']),
    ('t5-no-recovery', dict(), dict(configured=False),
     ['Backed up at 10:00, but if this PC is lost nothing can unlock the backup.', 'A recovery passphrase unlocks it on another PC.',
      'If this PC is lost, your passphrase or a recovery file unlocks the backup on another PC.'], ['Create recovery passphrase'], ['Choose a recovery passphrase']),
    ('t6-safe', dict(), dict(REC_OK),
     [SAFE, 'Up to date · 10:00', 'Changes back up about a minute after you make them.', 'Passphrase set', 'recovery file checked', 'Keep the file outside this PC.',
      'No phone sync report received yet', 'Pause backup', 'Reset backup…', 'Included'], ['Done'], ['too big to recover', 'Next: 6 Oct.']),
    ('t6b-phones-named', dict(phones=[dict(device='a', name='Pixel 8', seen=NOW - 120_000), dict(device='b', name='Galaxy A54', seen=NOW - 3 * HOUR)]), dict(REC_OK),
     ['2 phones', 'Pixel 8 · last reported sync 2 min ago', 'Galaxy A54 · last reported sync 3.0 h ago', '2 phones have reported a sync.'], ['Done'], ['This PC cannot tell which phones are paired.']),
    ('t6c-left-out', dict(skipped=2, skipped_note=SKIPPED), dict(REC_OK), [SKIPPED], ['Done'], []),
    ('t7-changes', dict(state='publishing', total=12, done=3), dict(REC_OK), ['Backing up 12 changes. Last complete backup 10:00.'], ['Done'], []),
    ('t8-paused', dict(on=False, running=False, state='off', paused_since=NOW - 3 * DAY), dict(REC_OK),
     ['Backup paused. Changes since 10:00 are only on this PC.', 'Paused'], ['Resume backup'], ['Pause backup']),
    ('t9-pausing', dict(state='stopping'), dict(REC_OK), ['Pausing after the current upload request (up to a minute).', 'Resume is available when the current requests finish.'], ['Done'], ['Keep backing up']),
    ('t10-offline', dict(state='error', error="Can't reach Google Drive.", error_code='offline', error_action='none'), dict(REC_OK),
     ["Can't reach Google Drive. Changes stay on this PC and back up when the connection returns.", 'Phones keep syncing for up to an hour; after that their edits wait on the phone.',
      'Waiting for the connection'], ['Done'], []),
    ('t11-expired', dict(token_expired=True, state='error', error_code='auth_expired', error='x', error_action='sign_in_again'), dict(REC_OK),
     [f"Google stopped accepting this PC's sign-in for {ACCOUNT}. Nothing was deleted.", 'Backup waits, and phones pause within an hour, until you sign in again.',
      f'Sign-in expired · {ACCOUNT}', 'Waiting: sign-in expired'], ['Sign in again'], ["Google asks again every 7 days while Brainamon's Google sign-in is in testing."]),
    ('t12-wrong-account', dict(token_expired=True, state='error', error_code='wrong_account', error_action='sign_in_again', error_account='b@example.com',
                               error=f'You signed in as b@example.com, but this library backs up to {ACCOUNT}. Nothing changed.'), dict(REC_OK),
     [f'You signed in as b@example.com, but this library backs up to {ACCOUNT}. Nothing changed.', 'Switch this library to b@example.com…'], ['Sign in again'], []),
    ('t13-drive-full', dict(state='error', error='x', error_code='drive_full', error_action='free_space'), dict(REC_OK),
     ['Google Drive is full. Recent changes are not backed up yet.', 'Waiting: Google Drive is full'], ['Try again'], []),
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
     ['Downloaded. Restart Brainamon to switch to the newer library; this PC then backs up again.', 'Stop updating'], ['Restart now'], []),
    ('t14e-update-failed', dict(NOT_OWNER, task=updating('downloading', error="Can't reach Google Drive. Nothing changed. Brainamon retries when the connection is back.")),
     dict(REC_OK, update=UPDATE_OK), ['Updating this folder stopped.', "Can't reach Google Drive. Nothing changed.", 'Stop updating'], ['Try again'], []),
    ('t14e-updated', dict(), dict(REC_OK, updated=dict(at=NOW - HOUR, published=NOW - DAY, kept=3, folder='C:/synthetic/data/before-update-2026-10-05')),
     ['This PC is the backup PC again.', "Kept this PC's 3 earlier changes in a copy of its library database (before update,", 'Hide'], ['Done'], [SAFE]),
    ('t15-two-copies', dict(state='error', error=TWO_COPIES, error_code='other_copy', error_action='none'), dict(REC_OK), [TWO_COPIES], ['Done'], ['Restore from', 'Reconnect']),
    ('t16-removing-phones', dict(rotation='pending', rotation_locked_at=NOW, state='publishing', done=2345, total=5678, bytes_done=4_100_000_000, bytes_total=9_800_000_000,
                                 task=REMOVING), dict(REC_OK),
     ['Removing all phones · step 3 of 5.', 'New key ready · done', 'Phones locked out at 12:00', 'Re-encrypting: 2,345 of 5,678 files (3.8 GB of 9.1 GB)', 'Deleting the old copy · waiting',
      'You can close Settings. Quitting Brainamon pauses this; it continues at the next start.', 'Re-encrypting with the new key', 'Locked out at 12:00',
      'Phones you keep: add them again now. They load the library when re-encrypting finishes.', 'Lost or stolen? Also sign that phone out of your Google account.',
      'How to sign a phone out', 'Pause backup', 'Add a phone'], ['Done'], ['Remove all phones…', 'Reset backup…']),
    ('t16a-removing-starting', dict(rotation='pending', rotation_locked_at=NOW, state='publishing', task=dict(REMOVING, step=3, done=0, total=0, bytes_done=0, bytes_total=0)), dict(REC_OK),
     ['Removing all phones · step 3 of 5.', 'Re-encrypting the backup…', 'Starts after the current upload request (up to a minute).'], ['Done'], ['Re-encrypting: 0 of 0 files']),
    ('t16a-removing-checking-vault', dict(rotation='pending', rotation_locked_at=NOW, state='publishing', upload_step='Uploading and verifying the vault with the replacement key…',
                                          task=dict(REMOVING, step=4, done=0, total=0, bytes_done=0, bytes_total=0,
                                                    steps=[dict(label=s['label'], state='done' if i < 3 else 'active' if i == 3 else 'waiting') for i, s in enumerate(REMOVING['steps'])])), dict(REC_OK),
     ['Removing all phones · step 4 of 5.', 'Checking the new copy, including your Obsidian vault if you sync one…', 'Re-encrypting · done'], ['Done'],
     ['Re-encrypting: 0 of 0 files', 'Starts after the current upload request']),
    ('t16b-removing-needs-the-new-file', dict(rotation='pending', rotation_locked_at=NOW, state='publishing', task=REMOVING), dict(REC_OK, file_outdated=True, replaced_at=NOW // 1000),
     ['Removing all phones · step 3 of 5.', 'Save new recovery file…'], ['Done'], []),
    ('t16c-passphrase-created-during-rotation', dict(rotation='pending', state='publishing', task=REMOVING), dict(REC_OK, enrolled=False, verified=False, rotation_pending=True),
     ['Passphrase created', 'Recovery checks and passphrase changes are available after upload, verification and cleanup finish.',
      'Available after the backup update finishes. Progress is shown above.'], ['Done'], ['Recovery setup not finished', 'Check recovery']),
    ('t16d-first-backup-rotation-without-recovery', dict(rotation='pending', state='publishing', last_publish=0, task=REMOVING), {},
     ['Recovery setup waits for the backup update', 'Available after the backup update finishes. Progress is shown above.'], ['Done'], ['Choose a recovery passphrase']),
    ('t18-phones-removed', dict(rotation='complete', rotation_locked_at=NOW - HOUR), dict(REC_OK),
     ['All phones removed at 11:00.', 'Add each phone you keep again: its unsent edits arrive then.', 'Hide'], ['Add a phone'], []),
    ('t19-old-file', dict(), dict(REC_OK, file_outdated=True, replaced_at=NOW // 1000),
     ['Your library is safe: backed up at 10:00, unlocked by your passphrase.', 'Saving a replacement is optional', 'Passphrase set · old recovery file outdated',
      'Removing phones made a new key. The old recovery file no longer opens your backup; your passphrase still does.'], ['Done'], []),
    ('t20-restart', dict(), dict(restored=True, restart_required=True, configured=True),
     ['The restored library is ready. Restart Brainamon to open it.', 'Your current library stays in its folder.'], ['Restart now'], []),
    ('t21-restored', dict(), dict(restored=True, configured=True),
     ['This restored library is not backed up yet.', 'Make this PC the backup PC once the old PC is off or closed.'], ['Make this PC the backup PC…'], []),
    ('t22-disconnected', dict(SIGNED_OUT), dict(REC_OK), ['Google Drive disconnected. Backup is off. The copy in sample@example.com from', 'stays in Drive.', 'Disconnected · the copy in sample@example.com stays'],
     ['Back up to Google Drive'], []),
    ('key-missing', dict(key_missing=True), dict(configured=False),
     [f"{ACCOUNT} already holds this library's backup", 'but this PC no longer has the key that opens it.', 'Unlock backup…', 'Reset backup instead…'], ['Unlock backup…'], []),
    ('backup-off', dict(on=False, running=False, state='off'), dict(REC_OK), ['Backup is off. Last backup:'], ['Turn on backup'], []),
    ('switching-account', dict(state='publishing', last_publish=0, done=5, total=100, task=task('switch_account', 'Switching Google account', 2, 3)), dict(REC_OK),
     ['Switching Google account · step 2 of 3.'], ['Done'], []),
    ('saving-the-passphrase', dict(task=task('enroll', 'Saving the recovery passphrase', 1, 3)), dict(configured=False),
     ['Backed up at 10:00. Saving your recovery passphrase…', 'Saving your passphrase · step 1 of 3', 'Backup pauses for these few seconds, then continues.',
      'Waiting for the current upload request: about 2 s, up to a minute on a slow connection.'], ['Done'], ['Create recovery passphrase']),
    ('recovery-file-saved-not-checked', dict(), dict(REC_OK, verified=False, verified_at=0),
     ['Recovery file saved', 'not checked', 'Open it once so you know it unlocks your backup.', 'Check recovery file…', 'Save another copy…'], ['Done'], []),
    ('passphrase-only', dict(), dict(REC_OK, verified=False, verified_at=0, saved_at=0),
     ['Optional: also save a recovery file, in case you forget the passphrase.', 'Save recovery file…', 'Change passphrase…'], ['Done'], []),
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
        hold, held = set(), []      # paths whose request waits for the test to answer it: a request in flight
        update_answer = [None]      # what update-preview answers (W4b)
        manual_pause = [False]     # a later explicit Pause takes ownership from Recover

        def reset(cloud_changes, recovery_changes):
            view.clear()
            view.update(base)
            view.update(CONNECTED)
            view.update(cloud_changes)
            recovery.clear()
            recovery.update(idle_recovery)
            recovery.update(recovery_changes)
            manual_pause[0] = False

        def cloud_route(route):
            path = urlparse(route.request.url).path
            method = route.request.method
            if path == '/api/cloud/sizes':
                route.fulfill(json=sizes)
                return
            if path == '/api/cloud/recovery':
                if path in hold:
                    held.append(route)
                    return
                if path in failing:
                    route.fulfill(status=409, json={'detail': failing[path]})
                    return
                route.fulfill(json=recovery)
                return
            if method == 'GET':
                route.fulfill(json=view)
                return
            body = route.request.post_data_json if route.request.post_data else {}
            calls.append((path, body))
            if path in hold:
                held.append(route)
                return
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
                if body.get('source') != 'recovery':
                    manual_pause[0] = True
                view.update(running=False, on=False, state='off', paused_since=NOW)
                route.fulfill(json={**view, **({'pause_token': 'a' * 32} if body.get('source') == 'recovery' else {})})
                return
            elif path == '/api/cloud/resume' or path == '/api/cloud/connect':
                if path == '/api/cloud/resume' and body.get('pause_token') and manual_pause[0]:
                    route.fulfill(json=view)  # stale recovery token is a successful no-op
                    return
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
        page.on('pageerror', lambda error: errors.append(error.stack))
        page.goto(self.url())
        page.wait_for_selector('.cell[data-id]')
        panel = page.locator('.set-win [role=tabpanel]')

        def open_view(cloud_changes=None, recovery_changes=None, settle=True):
            reset(cloud_changes or {}, recovery_changes or {})
            self.close_windows(page)
            page.keyboard.press('Control+Comma')
            try:
                page.wait_for_selector('.cw.set-win')
            except Exception:
                print('Settings page errors:', errors, flush=True)
                raise
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

        def show(name):
            opener = button('Show ' + name)
            if opener.count():
                opener.click()

        def more(name):
            summary = panel.get_by_text(name, exact=True)
            if summary.count() and summary.is_visible() and summary.locator('..').get_attribute('open') is None:
                summary.click()

        def open_recover():
            show = button('Show Recovery')
            if show.is_visible():
                show.click()
            panel.locator('#bp-group-recovery').get_by_role('button', name='Recover a library…', exact=True).click()

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

        def check_recover_and_keys():
            nonlocal ctx, page, errors, panel
            # the Recover a library window: pauses the backup while it runs, resumes it after, reads before it writes (W1 to W8)
            open_view(dict(), dict(REC_OK))
            count = len(calls)
            open_recover()
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
            open_recover()
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
            open_recover()
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
            page.on('pageerror', lambda error: errors.append(error.stack))
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
            row = keys.locator('#k-anthropic-st').locator('..')
            row.get_by_role('button', name='Save Anthropic key', exact=True).focus()
            page.keyboard.press('Enter')
            expect(page.locator('#k-anthropic')).to_have_count(0)
            expect(page.locator('#k-openai')).to_have_value('synthetic-openai')
            assert key_calls == [{'keys': {'anthropic': 'synthetic-anthropic'}}]
            expect(page.locator('#set-tai')).to_have_class(re.compile('dirty'))
            row.get_by_role('button', name='Replace…', exact=True).click()
            page.locator('#k-anthropic').fill('synthetic-replacement')
            writes_before = len(key_calls)
            row.get_by_role('button', name='Save Anthropic key', exact=True).evaluate('(e) => { e.click(); e.click() }')
            expect(page.locator('#k-anthropic')).to_have_count(0)
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
            expect(page.locator('#k-openai')).to_have_count(0)
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
            if '--recover-walk-only' in sys.argv:
                print(f'{theme}: Recover, Setup return and key actions passed')
            else:
                print(f'{theme}: Backup & phones states, forms, action payloads, the Recover window and 390px passed')

        if '--recover-walk-only' in sys.argv:
            check_recover_and_keys()
            return

        def check_rail():
            # the rail's Jobs module: a DRIVE row for the first backup, removing phones and a pause that waits for Resume (D14); nothing for a small upload
            rail_states = [
                ('idle', dict(), [], ['First backup', 'Removing phones', 'Backup paused'], None),
                ('uploading changes', dict(state='publishing', total=12, done=3), [], ['DRIVE'], None),
                ('first backup', dict(last_publish=0, state='publishing', done=1204, total=5678, bytes_done=2_100_000_000, bytes_total=9_800_000_000),
                 ['Backing up for the first time: 1,204 of 5,678 files (2.0 of 9.1 GB).', '21%'], [], 'Pause backup'),
                ('removing phones', dict(rotation='pending', state='publishing', task=REMOVING), ['Removing all phones · step 3 of 5', '42%', 'Re-encrypting: 2,345 of 5,678 files'], [], 'Pause backup'),
                ('paused', dict(on=False, running=False, state='off', paused_since=NOW - 3 * DAY), ['Backup paused. Changes since 10:00 are only on this PC.'], [], 'Resume backup'),
                ('pausing', dict(state='stopping'), ['Pausing after the current upload request'], [], None),
                ('updating this folder', dict(NOT_OWNER, task=updating('downloading', bytes_done=30, bytes_total=120)), ['Updating this folder', '25%'], ['Removing phones'], 'Pause backup'),
                ('update downloaded', dict(NOT_OWNER, task=updating('downloaded')), ['Updating this folder · step 2 of 3'], [], None),
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


        def check_review_regressions():
            for kind in ('replace', 'delete'):
                open_view(dict(state='error', error_code='foreign_backup', last_publish=0), {})
                button('Recover this backup…').click()
                recover = page.get_by_role('dialog', name='Recover a library', exact=True)
                recover.get_by_role('button', name='I don’t have a key', exact=True).click()
                label = 'Replace cloud backup with this PC’s library…' if kind == 'replace' else 'Delete cloud backup and disconnect…'
                submit = 'Replace with this PC’s library' if kind == 'replace' else 'Delete and disconnect'
                recover.get_by_role('button', name=label, exact=True).click()
                before = len(calls)
                view.update(seq=view['seq'] + 1, account='other@example.com')
                page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
                expect(recover.get_by_role('button', name=submit, exact=True)).to_have_count(0)
                expect(recover.get_by_role('alert').filter(has_text='The Google account changed.')).to_be_visible()
                assert not calls_since(before)
                recover.get_by_role('button', name=label, exact=True).click()
                recover.get_by_role('button', name=submit, exact=True).click()
                assert last()[1]['expected_account'] == 'other@example.com'

            restarts = []
            ctx.route('**/api/app/restart', lambda route: (restarts.append('restart'), route.fulfill(json={'ok': True})))
            completed = dict(REC_OK, job=dict(state='complete', done=5, total=5, error='', destination='C:/synthetic/restored'))
            open_view(dict(running=False, on=False, state='off', paused_since=NOW), completed)
            failing['/api/cloud/recovery/activate'] = 'Synthetic activation refusal.'
            button('Restart now').click()
            expect(panel.get_by_role('alert').filter(has_text='Synthetic activation refusal.')).to_be_visible()
            assert not restarts
            failing.clear()
            hold.add('/api/cloud/recovery/activate')
            before = len(calls)
            button('Restart now').click()
            expect(button('Restart now')).to_be_disabled()
            button('Restart now').evaluate('el => el.click()')
            assert calls_since(before) == ['/api/cloud/recovery/activate']
            recovery.update(restart_required=True, job=dict(completed['job'], state='activated'))
            hold.clear()
            held.pop().fulfill(json={'restart': True})
            page.wait_for_timeout(200)
            assert restarts == ['restart']
            assert last() == ('/api/cloud/recovery/activate', {'confirm': True})
            ctx.unroute('**/api/app/restart')

        if '--review-regressions-only' in sys.argv:
            check_review_regressions()
            assert not errors, errors
            ctx.close()
            print(f'{theme}: account-bound confirmations and completed-copy activation passed', flush=True)
            return

        if '--rail-only' in sys.argv:
            check_rail()
            assert not errors, errors
            ctx.close()
            print(f'{theme}: Rail progress and actions', flush=True)
            return

        if '--recover-choice-only' in sys.argv:
            for kind in ('replace', 'delete', 'rejected', 'lost', 'lost-delete', 'server-error', 'server-error-delete', 'lost-then-rejected'):
                foreign = dict(state='error', error='Existing cloud backup', error_code='foreign_backup', last_publish=0)
                open_view(foreign, {})
                button('Recover this backup…').click()
                recover = page.get_by_role('dialog', name='Recover a library', exact=True)
                recover.get_by_role('button', name='I don’t have a key', exact=True).click()
                if kind in ('delete', 'lost-delete', 'server-error-delete'):
                    path = '/api/cloud/sign-out'
                    recover.get_by_role('button', name='Delete cloud backup and disconnect…', exact=True).click()
                    submit = recover.get_by_role('button', name='Delete and disconnect', exact=True)
                else:
                    path = '/api/cloud/reset'
                    recover.get_by_role('button', name='Replace cloud backup with this PC’s library…', exact=True).click()
                    submit = recover.get_by_role('button', name='Replace with this PC’s library', exact=True)
                before = len(calls)
                hold.add(path)
                submit.click()
                assert held
                if kind != 'lost-then-rejected':
                    page.keyboard.press('Escape')
                    expect(recover).to_have_count(0)
                    assert not any(p == '/api/cloud/resume' for p, _ in calls[before:])
                hold.clear()
                if kind == 'rejected':
                    held.pop().fulfill(status=409, json={'detail': 'Synthetic choice refusal.'})
                elif kind in ('lost', 'lost-delete', 'lost-then-rejected'):
                    held.pop().abort()
                elif kind in ('server-error', 'server-error-delete'):
                    held.pop().fulfill(status=503, json={'detail': 'Synthetic uncertain result.'})
                else:
                    held.pop().fulfill(json=view)
                if kind == 'lost-then-rejected':
                    expect(submit).to_be_enabled()
                    hold.add(path)
                    submit.click()
                    assert held
                    page.keyboard.press('Escape')
                    expect(recover).to_have_count(0)
                    hold.clear()
                    held.pop().fulfill(status=409, json={'detail': 'Synthetic retry refusal.'})
                page.wait_for_timeout(600)
                resumes = [(p, body) for p, body in calls[before:] if p == '/api/cloud/resume']
                assert resumes == ([('/api/cloud/resume', {'pause_token': 'a' * 32})] if kind == 'rejected' else []), resumes
            assert not errors, errors
            ctx.close()
            print(f'{theme}: closing during replacement/disconnect waits for its result', flush=True)
            return

        if '--form-safety-only' in sys.argv:
            open_view({}, dict(configured=False))
            button('Create recovery passphrase').click()
            panel.locator('#bp-pass').fill('a long synthetic recovery phrase')
            panel.locator('#bp-pass2').fill('a long synthetic recovery phrase')
            hold.add('/api/cloud/recovery/enroll')
            button('Save passphrase').click()
            expect(button('Cancel')).to_be_disabled()
            expect(button('Show Backup')).to_be_disabled()
            page.keyboard.press('Escape')
            expect(panel.locator('#bp-pass')).to_have_value('a long synthetic recovery phrase')
            hold.clear()
            held.pop().fulfill(status=409, json={'detail': 'Synthetic passphrase refusal.'})
            expect(panel.get_by_role('alert').filter(has_text='Synthetic passphrase refusal.')).to_be_visible()
            button('Cancel').click()
            expect(panel.locator('#set-s-sync-recovery')).to_be_focused()
            open_view({}, dict(REC_OK))
            show('Google account')
            more('More: switch account, disconnect')
            button('Switch account…').click()
            toggle = panel.get_by_role('switch', name='Delete the copy in sample@example.com once the new backup is complete')
            toggle.check()
            hold.add('/api/cloud/switch')
            button('Switch account').click()
            expect(button('Cancel')).to_be_disabled()
            expect(button('Cancel')).to_have_attribute('aria-describedby', 'bp-confirming')
            expect(panel.get_by_text('Waiting for this action to finish.', exact=True)).to_be_visible()
            assert held
            hold.clear()
            held.pop().fulfill(status=409, json={'detail': 'Synthetic switch refusal.'})
            expect(panel.get_by_role('alert').filter(has_text='Synthetic switch refusal.').first).to_be_visible()
            expect(toggle).to_be_checked()
            expect(button('Cancel')).to_be_enabled()
            failing.clear()
            button('Switch account').click()
            assert last() == ('/api/cloud/switch', {'delete_old': True, 'expected_account': ACCOUNT})

            open_view({}, dict(REC_OK))
            show('Backup')
            more('More: reset the backup')
            button('Reset backup…').click()
            failing['/api/cloud/reset'] = 'Synthetic reset refusal.'
            button('Reset backup').click()
            expect(panel.get_by_role('alert').filter(has_text='Synthetic reset refusal.').first).to_be_visible()
            expect(panel.get_by_text('Reset the backup?', exact=True)).to_be_visible()
            expect(button('Cancel')).to_be_visible()
            failing.clear()
            button('Reset backup').click()
            assert last() == ('/api/cloud/reset', {'replace_existing': True, 'expected_account': ACCOUNT})

            open_view({}, dict(REC_OK))
            show('Google account')
            more('More: switch account, disconnect')
            button('Switch account…').click()
            panel.get_by_role('switch', name='Delete the copy in sample@example.com once the new backup is complete').check()
            before = len(calls)
            view.update(seq=view['seq'] + 1, account='other@example.com')
            page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
            expect(panel.get_by_text('Switch to another Google account?', exact=False)).to_have_count(0)
            expect(panel.get_by_role('region', name='Is my library safe').get_by_text('The Google account changed. Review the action again before continuing.', exact=True)).to_be_visible()
            assert not calls_since(before)

            open_view({}, dict(REC_OK))
            show('Backup')
            more('More: reset the backup')
            button('Reset backup…').click()
            view.update(seq=view['seq'] + 1, key_missing=True)
            page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
            expect(panel.get_by_text('Reset the backup?', exact=True)).to_be_visible()
            expect(button('Cancel')).to_be_visible()
            button('Cancel').click()
            open_view({}, dict(REC_OK))
            show('Phones')
            more('More: remove all phones, phone page address')
            button('Remove all phones…').click()
            expect(button('Hide Phones')).to_be_disabled()
            expect(button('Show Backup')).to_be_disabled()
            view.update(seq=view['seq'] + 1, licensed=False)
            page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
            expect(panel.get_by_text('Remove all phones?', exact=True)).to_be_visible()
            expect(button('Cancel')).to_be_visible()
            button('Cancel').click()

            open_view({}, dict(configured=True, enrolled=False, account=ACCOUNT))
            show('Recovery')
            failing['/api/cloud/recovery/preflight'] = 'Synthetic preflight refusal.'
            panel.get_by_role('region', name='Is my library safe').get_by_role('button', name='Check recovery', exact=True).click()
            expect(panel.get_by_role('alert').filter(has_text='Synthetic preflight refusal.')).to_be_visible()
            failing.clear()
            panel.get_by_role('region', name='Is my library safe').get_by_role('button', name='Check recovery', exact=True).click()
            assert last()[0] == '/api/cloud/recovery/preflight'
            assert not errors, errors
            ctx.close()
            print(f'{theme}: failed forms, account changes, eligibility and preflight retry passed', flush=True)
            return

        if '--board-only' in sys.argv:
            cleanup = dict(REMOVING, stage='cleanup', step=5, done=200, total=1000, bytes_done=0, bytes_total=0,
                           steps=[dict(label=s['label'], state='done' if i < 4 else 'active') for i, s in enumerate(REMOVING['steps'])])
            queue = [dict(id=cleanup['id'], kind=cleanup['kind'], title=cleanup['title'], stage=cleanup['stage'], error='', code=''),
                     dict(id='queued', kind='enroll', title='Saving recovery', stage='queued', error='', code='')]
            open_view(dict(rotation='pending', task=cleanup, tasks=queue), dict(REC_OK))
            go('overview')
            overview_task = panel.get_by_role('region', name='Task')
            expect(overview_task.get_by_text('Deleting the old copy: 200 of 1,000 files confirmed.', exact=False)).to_be_visible()
            expect(overview_task.get_by_role('progressbar', name='Removing all phones')).to_have_attribute('aria-valuenow', '20')
            expect(overview_task.get_by_text('Saving recovery · queued', exact=False)).to_be_visible()
            assert len(audit('overview task')['pri']) <= 1
            view.update(seq=view['seq'] + 1, task=dict(cleanup, done=250))
            page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
            expect(overview_task.get_by_role('progressbar', name='Removing all phones')).to_have_attribute('aria-valuenow', '25')
            go('backup')
            backup_task = panel.get_by_role('region', name='Task')
            expect(backup_task.get_by_role('progressbar', name='Removing all phones')).to_have_attribute('aria-valuenow', '25')
            expect(backup_task.get_by_text('Saving recovery · queued', exact=False)).to_be_visible()
            go('overview')
            overview_task.get_by_role('button', name='Pause backup', exact=True).focus()
            view.update(seq=view['seq'] + 1, task=None, tasks=[], rotation='complete')
            page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
            expect(page.locator('.set-heading h2')).to_be_focused()
            open_view(dict(rotation='pending', task=cleanup, tasks=queue), dict(REC_OK))
            go('overview')
            page.locator('#set-find').focus()
            view.update(seq=view['seq'] + 1, task=None, tasks=[], rotation='complete')
            page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
            expect(page.locator('#set-find')).to_be_focused()
            paused = dict(cleanup, paused_snapshot=True)
            open_view(dict(rotation='pending', task=paused, tasks=queue, on=False, running=True, state='stopping', paused_since=NOW), dict(REC_OK))
            draining = panel.get_by_role('region', name='Task')
            expect(draining.get_by_text('Resume is available when the current requests finish.', exact=True)).to_be_visible()
            expect(draining.get_by_role('progressbar', name='Removing all phones')).to_have_attribute('aria-valuenow', '20')
            expect(draining.locator('.prog .lead')).to_have_count(0)
            expect(button('Resume backup')).to_have_count(0)
            view.update(seq=view['seq'] + 1, running=False, state='off')
            page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
            expect(button('Resume backup')).to_be_visible()
            open_view(dict(rotation='pending', task=paused, tasks=queue, on=False, running=False, state='off', paused_since=NOW), dict(REC_OK))
            go('overview')
            overview_task = panel.get_by_role('region', name='Task')
            expect(overview_task.get_by_text('Last reported when Pause was requested.', exact=True)).to_be_visible()
            assert audit('paused overview')['pri'] == ['Resume backup']
            count = len(calls)
            overview_task.get_by_role('button', name='Resume backup', exact=True).click()
            assert calls_since(count) == ['/api/cloud/resume']
            expect(page.locator('.set-heading h2')).to_have_text('Backup & phones')
            activity = dict(action='reconnect', state='running', step='Checking this library', started=NOW)
            open_view(dict(recovery_gate_active=True, recovery_activity=activity), dict(REC_OK))
            go('obsidian')
            vault = panel.get_by_role('region', name='Vault sync with phone')
            start = vault.get_by_role('button', name='Sync my Obsidian vault', exact=True)
            expect(start).to_be_disabled()
            expect(start).to_have_attribute('aria-describedby', 'set-vault-gate')
            expect(vault.get_by_text('Checking this library Wait for it to finish.', exact=True)).to_be_visible()
            view.update(seq=view['seq'] + 1, vault_running=True, vault_state='idle')
            page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
            expect(vault.get_by_role('button', name='Turn off vault sync', exact=True)).to_be_enabled()
            open_view({}, dict(REC_OK))
            button('Show Phones').click()
            panel.get_by_text('More: remove all phones, phone page address', exact=True).click()
            button('Remove all phones…').click()
            panel.locator('#bp-current').fill('synthetic draft passphrase')
            page.locator('#set-tgeneral').click()
            expect(page.locator('.set-heading h2')).to_have_text('Backup & phones')
            expect(panel.locator('#bp-current')).to_have_value('synthetic draft passphrase')
            expect(page.get_by_text('Finish or cancel the open backup form before changing sections.', exact=True)).to_be_visible()
            page.keyboard.press('Escape')
            expect(panel.get_by_text('Remove all phones?', exact=True)).to_have_count(0)
            go('general')
            assert not errors, errors
            ctx.close()
            print(f'{theme}: Overview/Backup task counts, queue and real action parity passed', flush=True)
            return

        if '--recovery-file-feedback-only' in sys.argv:
            old_file = dict(REC_OK, file_outdated=True, replaced_at=NOW // 1000)
            open_view({}, old_file)
            expect(panel.get_by_text('Saving a replacement is optional', exact=False)).to_be_visible()
            assert audit('optional recovery file')['pri'] == ['Done']
            page.evaluate('''() => {
                window.__picks = [];
                window.pywebview = {api: {pick: kind => {
                    window.__picks.push(kind);
                    return new Promise(resolve => window.__chooseRecovery = resolve);
                }}};
            }''')
            before = len(calls)
            button('Save new recovery file…').click()
            expect(button('Choose where to save…')).to_be_disabled()
            expect(panel.get_by_text('Choose a filename and location', exact=False)).to_be_visible()
            page.evaluate('window.__chooseRecovery(null)')
            expect(button('Save new recovery file…')).to_be_enabled()
            assert len(calls) == before
            assert page.evaluate('window.__picks') == ['recovery-save']

            hold.add('/api/cloud/recovery/save-kit')
            button('Save new recovery file…').click()
            page.evaluate("window.__chooseRecovery(['C:/synthetic/Recovery copy.json'])")
            expect(button('Saving and checking…')).to_be_disabled()
            expect(button('Saving and checking…')).to_have_attribute('aria-busy', 'true')
            expect(panel.get_by_role('progressbar', name='Saving and checking recovery file')).to_be_visible()
            expect(panel.get_by_text('This can take a minute.', exact=False)).to_be_visible()
            audit('saving recovery file')
            capture('recovery-file-saving')
            assert last() == ('/api/cloud/recovery/save-kit', {'path': 'C:/synthetic/Recovery copy.json'})
            held.pop().fulfill(status=409, json={'detail': 'Synthetic save failed. Choose another filename.'})
            expect(panel.get_by_role('alert').filter(has_text='Synthetic save failed')).to_be_visible()
            expect(button('Save new recovery file…')).to_be_enabled()
            expect(panel.get_by_role('progressbar', name='Saving and checking recovery file')).to_have_count(0)

            button('Save new recovery file…').click()
            page.evaluate("window.__chooseRecovery(['C:/synthetic/Recovery copy.json'])")
            expect(button('Saving and checking…')).to_be_disabled()
            last()
            recovery.update(file_outdated=False, saved_at=NOW // 1000, verified_at=NOW // 1000)
            held.pop().fulfill(json={'path': 'C:/synthetic/Recovery copy.json', 'saved': True, 'verified': True})
            hold.clear()
            expect(panel.get_by_text('Recovery file saved and checked against your backup.', exact=False)).to_be_visible()
            expect(panel.get_by_text('Saved to C:/synthetic/Recovery copy.json', exact=False)).to_be_visible()
            expect(panel.get_by_role('progressbar', name='Saving and checking recovery file')).to_have_count(0)
            capture('recovery-file-saved')

            open_view({}, old_file)
            page.evaluate('delete window.pywebview')
            hold.add('/api/cloud/recovery/kit')
            button('Save new recovery file…').click()
            expect(button('Preparing download…')).to_be_disabled()
            expect(panel.get_by_role('progressbar', name='Preparing recovery file download')).to_be_visible()
            last()
            with page.expect_download():
                held.pop().fulfill(json={'synthetic': 'kit'})
            hold.clear()
            expect(panel.get_by_text('Download requested. A browser download is not confirmed until you open the file.', exact=True)).to_be_visible()
            expect(button('Save new recovery file…')).to_be_enabled()
            assert recovery['file_outdated']

            for age in [59 * 60_000, 61 * 60_000, 3 * DAY]:
                open_view({'phones': [{'device': 'a', 'name': 'My phone', 'seen': NOW - age}]}, dict(REC_OK))
                expect(panel.get_by_text('1 phone has reported a sync. These are periodic reports, not a live connection status.', exact=True)).to_be_visible()
                button('Show Phones').click()
                expect(panel.get_by_text('My phone · last reported sync', exact=False)).to_be_visible()
                expect(panel.get_by_text('An older report does not mean a phone is disconnected.', exact=False).last).to_be_visible()
                assert 'in sync' not in panel.inner_text()
            for width in [1440, 390]:
                page.set_viewport_size({'width': width, 'height': 900})
                audit(f'phone report {width}')
                capture(f'phone-report-{width}')
                panel.locator('#bp-group-phones').scroll_into_view_if_needed()
                self.shot(page, f'desktop-{theme}-phone-report-detail-{width}')
            open_view({'phones': None, 'running': False, 'on': False, 'state': 'off', 'paused_since': NOW - HOUR}, dict(REC_OK))
            button('Show Phones').click()
            expect(panel.get_by_text('This PC will read newer reports when it resumes syncing.', exact=False).last).to_be_visible()
            assert not errors, errors
            ctx.close()
            print(f'{theme}: optional file, Save picker, cancel, busy, failure, success and phone reports passed')
            return

        if '--recover-pause-only' in sys.argv:
            open_view({}, dict(REC_OK))
            hold.add('/api/cloud/recovery')
            before = len(calls)
            open_recover()
            recover = page.get_by_role('dialog', name='Recover a library', exact=True)
            expect(recover).to_be_visible()
            page.wait_for_timeout(300)
            assert held
            page.keyboard.press('Escape')
            expect(recover).to_have_count(0)
            hold.clear()
            while held:
                held.pop().fulfill(json=recovery)
            page.wait_for_timeout(500)
            assert not any(path in ('/api/cloud/pause', '/api/cloud/resume') for path, _ in calls[before:]), calls[before:]
            open_view(dict(task=REMOVING), dict(REC_OK))
            hold.add('/api/cloud/pause')
            before = len(calls)
            open_recover()
            recover = page.get_by_role('dialog', name='Recover a library', exact=True)
            expect(recover).to_be_visible()
            page.wait_for_timeout(300)
            assert calls[before:] == [('/api/cloud/pause', {'source': 'recovery'})], calls[before:]
            assert held
            page.keyboard.press('Escape')
            expect(recover).to_have_count(0)
            assert not any(path == '/api/cloud/resume' for path, _ in calls[before:])
            hold.clear()
            held.pop().fulfill(json={**view, 'pause_token': 'a' * 32})
            page.wait_for_timeout(500)
            assert ('/api/cloud/resume', {'pause_token': 'a' * 32}) in calls[before:], calls[before:]
            # Another client explicitly pauses after Recover acquired its own token.
            # The server accepts Recover's later conditional Resume as a no-op.
            open_view({}, dict(REC_OK))
            before = len(calls)
            open_recover()
            recover = page.get_by_role('dialog', name='Recover a library', exact=True)
            expect(recover.get_by_label('Recovery passphrase', exact=True)).to_be_visible()
            page.wait_for_timeout(300)
            assert ('/api/cloud/pause', {'source': 'recovery'}) in calls[before:]
            page.evaluate("fetch('/api/cloud/pause', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})")
            assert manual_pause[0] and not view['running'] and not view['on']
            page.keyboard.press('Escape')
            expect(recover).to_have_count(0)
            page.wait_for_timeout(500)
            assert [body for path, body in calls[before:] if path == '/api/cloud/resume'] == [{'pause_token': 'a' * 32}]
            assert manual_pause[0] and not view['running'] and not view['on'] and view['paused_since']
            for existing in (dict(restored=True), dict(restart_required=True)):
                open_view({}, dict(REC_OK, **existing))
                before = len(calls)
                open_recover()
                recover = page.get_by_role('dialog', name='Recover a library', exact=True)
                expect(recover).to_be_visible()
                page.wait_for_timeout(400)
                assert ('/api/cloud/pause', {'source': 'recovery'}) in calls[before:], calls[before:]
                page.keyboard.press('Escape')
                expect(recover).to_have_count(0)
                page.wait_for_timeout(500)
                assert not any(path == '/api/cloud/resume' for path, _ in calls[before:]), (existing, calls[before:])
            for outcome in ('accepted', 'rejected', 'rejected-active', 'rejected-unknown', 'ambiguous'):
                open_view({}, dict(REC_OK))
                before = len(calls)
                open_recover()
                recover = page.get_by_role('dialog', name='Recover a library', exact=True)
                expect(recover.get_by_label('Recovery passphrase', exact=True)).to_be_visible()
                recover.get_by_label('Recovery passphrase', exact=True).fill('a long synthetic recovery phrase')
                recover.get_by_role('button', name='Find backup', exact=True).click()
                recover.get_by_role('button', name='Copy into a new folder instead', exact=True).click()
                recover.get_by_label('New folder', exact=True).fill('C:/synthetic/new-library')
                if outcome == 'accepted':
                    recovery['job'].update(state='cancelled')
                    expect(recover.get_by_role('button', name='Retry copy', exact=True)).to_be_visible(timeout=5000)
                    stale = copies.deepcopy(recovery)
                    hold.add('/api/cloud/recovery')
                    page.wait_for_timeout(2200)
                    assert any(r.request.method == 'GET' for r in held), 'Expected an old recovery poll to be in flight.'
                hold.add('/api/cloud/recovery/restore')
                recover.get_by_role('button', name='Retry copy' if outcome == 'accepted' else 'Copy into new folder', exact=True).click()
                assert any(r.request.method == 'POST' for r in held)
                page.keyboard.press('Escape')
                expect(recover).to_have_count(0)
                assert not any(path == '/api/cloud/resume' for path, _ in calls[before:])
                hold.clear()
                reads = [r for r in held if r.request.method == 'GET']
                for route in reads:
                    held.remove(route)
                    route.fulfill(json=stale)
                if outcome == 'accepted':
                    recovery['job'].update(state='restoring', done=0, total=5, destination='C:/synthetic/new-library')
                    held.pop().fulfill(json=recovery)
                elif outcome.startswith('rejected'):
                    if outcome == 'rejected-active':
                        recovery['job'].update(state='restoring', done=0, total=5, destination='C:/synthetic/new-library')
                    elif outcome == 'rejected-unknown':
                        failing['/api/cloud/recovery'] = 'Synthetic recovery status failure.'
                    held.pop().fulfill(status=409, json={'detail': 'Synthetic copy start failure.'})
                else:
                    held.pop().abort('failed')
                page.wait_for_timeout(600)
                failing.clear()
                resumes = [(path, body) for path, body in calls[before:] if path == '/api/cloud/resume']
                assert resumes == ([('/api/cloud/resume', {'pause_token': 'a' * 32})] if outcome == 'rejected' else []), resumes
            assert not errors, errors
            ctx.close()
            print(f'{theme}: close during recovery pause releases only its token', flush=True)
            return

        if '--switch-events-only' in sys.argv:
            open_view(dict(signed_in=False, on=False, running=False, state='signing-in', last_publish=0), dict(REC_OK))
            expect(panel.get_by_text('Finish signing in in the browser window that opened.', exact=True)).to_be_visible()
            expect(button('Cancel sign-in')).to_be_visible()
            view.update(seq=view['seq'] + 1, signed_in=True, on=True, running=True, state='publishing', done=10, total=100)
            page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
            expect(panel.get_by_text('Backing up for the first time: 10 of 100 files', exact=False)).to_be_visible()
            expect(button('Pause backup').first).to_be_visible()
            expect(button('Turn on backup')).to_have_count(0)
            view.update(seq=view['seq'] + 1, on=False, running=False, state='off', paused_since=NOW)
            page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
            expect(panel.get_by_role('region', name='Is my library safe').get_by_text('Backup paused. The first backup is not finished.', exact=True)).to_be_visible()
            expect(button('Resume backup').first).to_be_visible()
            assert 'pri' in (button('Resume backup').first.get_attribute('class') or '')
            stale = dict(view, seq=view['seq'] - 1, on=True, running=True, state='publishing', paused_since=0)
            page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", stale)
            expect(panel.get_by_role('region', name='Is my library safe').get_by_text('Backup paused. The first backup is not finished.', exact=True)).to_be_visible()
            assert not errors, errors
            ctx.close()
            print(f'{theme}: sign-in, external pause and stale event passed', flush=True)
            return

        if '--recovery-read-only' in sys.argv:
            hold.add('/api/cloud/recovery')
            open_view({}, dict(REC_OK), settle=False)
            button('Show Recovery').click()
            recovery_group = panel.locator('#bp-group-recovery')
            hero = panel.get_by_role('region', name='Is my library safe')
            expect(recovery_group.get_by_text('Checking recovery status…', exact=True).first).to_be_visible()
            expect(recovery_group.get_by_text('Passphrase set', exact=False)).to_have_count(0)
            assert held
            hold.clear()
            while held:
                held.pop().fulfill(status=409, json={'detail': 'Synthetic recovery read failure.'})
            expect(hero.get_by_text('Could not check recovery: Synthetic recovery read failure.', exact=True)).to_be_visible()
            expect(hero.get_by_role('button', name='Check again', exact=True)).to_be_visible()
            assert 'pri' in (hero.get_by_role('button', name='Check again', exact=True).get_attribute('class') or '')
            expect(hero.get_by_text(SAFE, exact=True)).to_have_count(0)
            hero.get_by_role('button', name='Check again', exact=True).click()
            expect(hero.get_by_text(SAFE, exact=True)).to_be_visible()
            recovery_group.get_by_text('More: change passphrase, another copy, forgot it', exact=True).click()
            expect(recovery_group.get_by_role('button', name='Save another copy…', exact=True)).to_be_visible()
            failing['/api/cloud/recovery'] = 'Synthetic recovery read failure.'
            recovery_group.get_by_role('button', name='Save another copy…', exact=True).click()
            expect(hero.get_by_text('Could not check recovery: Synthetic recovery read failure.', exact=True)).to_be_visible()
            expect(hero.get_by_text(SAFE, exact=True)).to_have_count(0)
            expect(recovery_group.get_by_role('button', name='Save another copy…', exact=True)).to_have_count(0)
            failing.clear()
            hero.get_by_role('button', name='Check again', exact=True).click()
            expect(hero.get_by_text(SAFE, exact=True)).to_be_visible()
            assert not errors, errors
            ctx.close()
            print(f'{theme}: recovery pending, failed read, retry and stale success passed', flush=True)
            return

        if '--progress-only' in sys.argv:
            for width in (1440, 390):
                page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
                uploading = dict(RESETTING, done=250, total=1000, bytes_done=25 * 1048576, bytes_total=100 * 1048576, items_done=750, items_total=3000)
                open_view(dict(task=uploading, state='publishing'), dict(REC_OK))
                task_panel = panel.get_by_role('region', name='Task').last
                steps = task_panel.get_by_role('list', name='Backup steps')
                expect(steps.get_by_role('listitem')).to_have_count(3)
                expect(steps.locator('.cycle')).to_have_count(1)
                expect(steps.locator('li').first.locator('path')).to_have_count(1)
                expect(task_panel.get_by_text('750 / 3,000 item records backed up.', exact=False)).to_be_visible()
                button('Show Backup').click()
                expect(panel.get_by_text('Library · 3,000 items', exact=False)).to_be_visible()
                expect(panel.get_by_text('5,678 files in the backup.', exact=False)).to_be_visible()
                expect(task_panel.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '25')
                audit(f'progress-{width}')
                capture(f'progress-{width}')
                view.update(seq=view['seq'] + 1, task=dict(uploading, done=500, bytes_done=50 * 1048576, items_done=1500))
                page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
                expect(task_panel.get_by_text('1,500 / 3,000 item records backed up.', exact=False)).to_be_visible()
                expect(task_panel.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '50')
                cleanup = dict(RESETTING, stage='cleanup', step=3, done=100, total=1000, uploaded_items=3000, uploaded_items_total=3000, uploaded_files=4000,
                               steps=[dict(label=s['label'], state='done' if i < 2 else 'active') for i, s in enumerate(RESETTING['steps'])])
                open_view(dict(task=cleanup), dict(REC_OK))
                expect(task_panel.get_by_role('list', name='Backup steps')).to_contain_text('3,000 / 3,000 item records · 4,000 / 4,000 files')
                expect(task_panel.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '10')
                expect(task_panel.get_by_text('100 of 1,000 files confirmed.', exact=False)).to_be_visible()
                view.update(seq=view['seq'] + 1, task=dict(cleanup, done=120))
                page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
                expect(task_panel.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '12')
                expect(task_panel.get_by_text('120 of 1,000 files confirmed.', exact=False)).to_be_visible()
                expect(task_panel.locator('.task-steps li:nth-child(2) path')).to_have_count(1)
                page.emulate_media(reduced_motion='no-preference')
                page.evaluate("document.documentElement.classList.remove('motion-off')")
                expect(task_panel.locator('.deletion-estimate')).to_be_visible()
                page.wait_for_function("() => Number(document.querySelector('.deletion-estimate').textContent.match(/: ([0-9,]+)/)[1].replaceAll(',',''))>120")
                expect(task_panel.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '12')

                page.emulate_media(reduced_motion='reduce')
                assert task_panel.locator('.task-steps .cycle').evaluate("e => getComputedStyle(e).animationName") == 'none'
                expect(task_panel.locator('.deletion-estimate')).to_be_hidden()
                page.emulate_media(reduced_motion='no-preference')
                audit(f'cleanup-{width}')
                capture(f'cleanup-{width}')
            assert not errors, errors
            ctx.close()
            print(f'{theme}: live upload/item counts, checklist, cleanup, layouts and reduced motion passed', flush=True)
            return

        if '--remove-only' in sys.argv:
            for width in (1440, 390):
                page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
                # Remove all phones while its request is in flight (Drive can take a while): the key says so, a bar shows, nothing is pressed twice
                open_view(dict(), dict(REC_OK))
                button('Show Phones').click()
                panel.get_by_text('More: remove all phones, phone page address', exact=True).click()
                button('Remove all phones…').click()
                panel.locator('#bp-current').fill('a long synthetic recovery phrase')
                hold.add('/api/cloud/unpair')
                n = len(calls)
                button('Remove all phones').click()
                removing = panel.get_by_role('button', name='Removing all phones…', exact=True)
                expect(removing).to_be_disabled()
                expect(removing).to_have_attribute('aria-busy', 'true')
                expect(panel.get_by_role('progressbar', name='Removing all phones')).to_be_visible()
                expect(panel.get_by_text('Locking phones out and making a new key.', exact=False)).to_be_visible()
                expect(button('Cancel')).to_be_disabled()
                audit(f'remove-in-flight-{width}')
                removing.scroll_into_view_if_needed()          # the Phones box is below the fold: the shot shows the form itself
                self.shot(page, f'desktop-{theme}-settings-backup-remove-in-flight-{width}')
                removing.click(force=True)
                assert calls_since(n) == ['/api/cloud/unpair'], calls_since(n)      # a second press reaches nothing
                hold.clear()
                view.update(rotation='pending', task=dict(REMOVING, stage='requested', step=3, done=0, total=0, bytes_done=0, bytes_total=0))
                held.pop().fulfill(json=view)
                expect(panel.get_by_text('Remove all phones?', exact=True)).to_have_count(0)
                expect(panel.get_by_text('Removing all phones · step 3 of 5.', exact=False)).to_be_visible()
                expect(panel.get_by_role('region', name='Task').last.get_by_text('Re-encrypting the backup…', exact=False)).to_be_visible()
                # step 4 while the Obsidian vault is uploaded and read back: no fall back to "Re-encrypting: 0 of 0 files"
                checking = dict(REMOVING, step=4, done=0, total=0, bytes_done=0, bytes_total=0,
                                steps=[dict(label=s['label'], state='done' if i < 3 else 'active' if i == 3 else 'waiting') for i, s in enumerate(REMOVING['steps'])])
                open_view(dict(rotation='pending', rotation_locked_at=NOW, state='publishing', task=checking,
                               upload_step='Uploading and verifying the vault with the replacement key…'), dict(REC_OK))
                expect(panel.get_by_text('Removing all phones · step 4 of 5.', exact=False)).to_be_visible()
                expect(panel.get_by_role('region', name='Task').last.get_by_text('Checking the new copy, including your Obsidian vault if you sync one…', exact=False)).to_be_visible()
                expect(panel.get_by_text('Re-encrypting: 0 of 0 files', exact=False)).to_have_count(0)
                expect(panel.get_by_text('Starts after the current upload request', exact=False)).to_have_count(0)
                audit(f'removal-checking-{width}')
                capture(f'removal-checking-{width}')
                task_panel = panel.get_by_role('region', name='Task').last
                bar = task_panel.get_by_role('progressbar', name='Removing all phones')
                expect(bar).to_have_count(0)  # unknown counts use named steps without inventing a percentage
                for done in (25, 50):
                    view.update(seq=view['seq'] + 1, task=dict(checking, done=done, total=100), upload_step='Verifying the uploaded Obsidian vault…')
                    page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
                    expect(task_panel.get_by_text(f'Checking the new copy: {done} of 100 files.', exact=False)).to_be_visible()
                    expect(task_panel.get_by_text('Verifying the uploaded Obsidian vault…', exact=False)).to_be_visible()
                    expect(bar).to_have_attribute('aria-valuenow', str(done))
                for done in (100, 200):
                    view.update(seq=view['seq'] + 1, task=dict(REMOVING, step=5, stage='cleanup', done=done, total=1000,
                                steps=[dict(label=s['label'], state='done' if i < 4 else 'active') for i, s in enumerate(REMOVING['steps'])]),
                                upload_step='Removing the old encrypted copies to finish unpairing…')
                    page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
                    expect(task_panel.get_by_text(f'Deleting the old copy: {done} of 1,000 files confirmed.', exact=False)).to_be_visible()
                    expect(bar).to_have_attribute('aria-valuenow', str(done // 10))
                audit(f'removal-cleanup-live-{width}')
                capture(f'removal-cleanup-live-{width}')
            assert not errors, errors
            ctx.close()
            print(f'{theme}: Remove all phones in flight, its steps and the vault check passed', flush=True)
            return

        # ── A15: every state keeps the rules; each says its words and offers its one primary (README: T, G, B, R, P) ──
        open_view({}, REC_OK)
        show('Recovery')
        more('More: change passphrase, another copy, forgot it')
        card = panel.get_by_role('region', name='Recovery', exact=True)
        guide = card.get_by_text('Forgot passphrase?', exact=True).locator('..')
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
        show('Recovery')
        more('More: change passphrase, another copy, forgot it')
        card = panel.get_by_role('region', name='Recovery', exact=True)
        card.get_by_text('Forgot passphrase?', exact=True).click()
        card.get_by_text('I can still open my library', exact=True).click()
        expect(card.get_by_text('Forgot passphrase?', exact=True).locator('..').get_by_role('button', name='Change passphrase…', exact=True)).to_be_disabled()
        expect(card.get_by_text('Passphrase changes wait until', exact=False).first).to_be_visible()

        if '--guide-only' in sys.argv:
            assert not errors, errors
            ctx.close()
            print(f'{theme}: forgot-passphrase navigation, cancellation, rotation and layouts passed')
            return

        state_filter = next((arg.partition('=')[2] for arg in sys.argv if arg.startswith('--state=')), '')
        diagnose = '--diagnose-matrix' in sys.argv
        mismatches = []
        for name, cloud_changes, recovery_changes, see, pri, absent in STATES:
            if '--actions-only' in sys.argv or (state_filter and name != state_filter):
                continue
            open_view(cloud_changes, recovery_changes)
            window = page.locator('.set-win')
            for text in see:
                visible = window.get_by_text(text, exact=False).locator('visible=true')
                if not visible.count():
                    candidate = panel.get_by_text(text, exact=False).first
                    if candidate.count():
                        candidate.evaluate("el => { for (let p = el.parentElement; p; p = p.parentElement) if (p instanceof HTMLDetailsElement) p.open = true }")
                    for group, group_id in (('Google account', 'account'), ('Backup', 'backup'), ('Recovery', 'recovery'), ('Phones', 'phones')):
                        element = panel.locator('#bp-group-' + group_id).get_by_text(text, exact=False).first
                        if element.count():
                            show(group)
                            element.evaluate("el => { for (let p = el.parentElement; p; p = p.parentElement) if (p instanceof HTMLDetailsElement) p.open = true }")
                            break
                if diagnose:
                    if not window.get_by_text(text, exact=False).locator('visible=true').count(): mismatches.append((name, 'missing', text))
                else:
                    expect(window.get_by_text(text, exact=False).locator('visible=true').first, f'{name}: {text}').to_be_visible()
            for text in absent:
                if diagnose:
                    if window.get_by_text(text, exact=False).locator('visible=true').count(): mismatches.append((name, 'unexpected', text))
                else:
                    expect(window.get_by_text(text, exact=False).locator('visible=true'), f'{name}: {text} is not shown').to_have_count(0)
            got = audit(name)['pri']
            if diagnose:
                if got != pri: mismatches.append((name, 'primary', got, pri))
                continue
            assert got == pri, f'{name}: primary keys {got}, expected {pri}'
            if name in ('t6-safe', 't4-first-backup', 't16-removing-phones', 't1-not-connected') or name.startswith('reset-'):
                capture(name)
            if name == 'reset-preparing':
                expect(window.get_by_role('progressbar', name='Resetting the backup')).to_have_count(0)
            elif name == 'reset-uploading':
                expect(window.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '25')
            elif name == 'reset-small-progress':
                pct = float(window.get_by_role('progressbar', name='Resetting the backup').get_attribute('aria-valuenow'))
                assert 0 < pct < 1, pct
            if name.startswith('reset-'):
                page.set_viewport_size({'width': 390, 'height': 844})
                audit(name + '-390')
                capture(name + '-390')
                page.set_viewport_size({'width': 1440, 'height': 1000})
            if name == 'reset-uploading':
                view.update(seq=view['seq'] + 1, task=dict(RESETTING, done=500, total=1000, bytes_done=50 * 1048576, bytes_total=100 * 1048576))
                page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
                expect(panel.get_by_role('region', name='Task').get_by_text('Backing up again: 500 of 1,000 files (50 MB of 100 MB)', exact=False)).to_be_visible()
                expect(window.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '50')
        assert not errors, errors
        if diagnose:
            ctx.close()
            print(f'{theme} matrix discrepancies: {mismatches}', flush=True)
            assert not mismatches, mismatches
            return
        if state_filter:
            ctx.close()
            print(f'{theme}: {state_filter} passed', flush=True)
            return

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

        # First setup, keyboard only: optional passphrase setup is opened explicitly during the first backup.
        open_view(dict(signed_in=False, running=False, on=False, account='', last_publish=0, state='off'))
        tab_to(button('Back up to Google Drive'))
        page.keyboard.press('Enter')
        assert last()[0] == '/api/cloud/connect'
        open_view(dict(last_publish=0, state='publishing', done=1204, total=5678, bytes_done=2_100_000_000, bytes_total=9_800_000_000, upload_since=NOW - 360_000), dict(configured=False))
        expect(panel.get_by_text('Choose a recovery passphrase', exact=True)).to_have_count(0)
        tab_to(button('Show Recovery'))
        page.keyboard.press('Enter')
        tab_to(button('Create recovery passphrase'))
        page.keyboard.press('Enter')
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
        show('Backup')
        count = len(calls)
        button('Pause backup').click()
        assert calls_since(count) == ['/api/cloud/pause']
        open_view(dict(on=False, running=False, paused_since=NOW - 3 * 24 * HOUR, state='off'), dict(REC_OK))
        expect(button('Resume backup')).to_have_class(re.compile('pri'))
        button('Resume backup').click()
        assert last()[0] == '/api/cloud/resume'
        open_view(dict(), dict(REC_OK))
        show('Backup')
        panel.get_by_role('group', name='Videos').get_by_role('button', name='All', exact=True).click()
        assert last() == ('/api/cloud/options', {'videos': 'all'})
        panel.get_by_role('group', name='Canvases').get_by_role('button', name='None', exact=True).click()
        assert last() == ('/api/cloud/options', {'canvases': False})
        # Switch account, Disconnect (what asking sends: nothing), Reset backup
        open_view(dict(), dict(REC_OK))
        show('Google account')
        more('More: switch account, disconnect')
        count = len(calls)
        button('Switch account…').click()
        expect(panel.get_by_text('Switch to another Google account?', exact=False)).to_be_visible()
        assert audit('switch form')['pri'] == ['Switch account']
        button('Cancel').click()
        more('More: switch account, disconnect')
        button('Disconnect Google Drive…').click()
        expect(button('Disconnect')).to_be_visible()
        assert calls_since(count) == [], 'Asking must not disconnect or delete'
        panel.get_by_role('switch', name='Also delete the backup from Google Drive').check()
        expect(button('Delete and disconnect')).to_be_visible()
        expect(panel.get_by_text('All Brainamon desktop backup data in', exact=False)).to_be_visible()
        panel.get_by_role('switch', name='Also delete the backup from Google Drive').uncheck()
        button('Disconnect').click()
        assert last() == ('/api/cloud/sign-out', {'delete_mirror': False, 'expected_account': ACCOUNT})
        expect(panel.get_by_text('Google Drive disconnected. Backup is off.', exact=False)).to_be_visible()
        expect(button('Back up to Google Drive')).to_have_class(re.compile('pri'))
        open_view(dict(), dict(REC_OK))
        show('Google account')
        more('More: switch account, disconnect')
        button('Disconnect Google Drive…').click()
        panel.get_by_role('switch', name='Also delete the backup from Google Drive').check()
        button('Delete and disconnect').click()
        assert last() == ('/api/cloud/sign-out', {'delete_mirror': True, 'delete_existing': True, 'expected_account': ACCOUNT})
        open_view(dict(), dict(REC_OK))
        show('Google account')
        more('More: switch account, disconnect')
        button('Switch account…').click()
        panel.get_by_role('switch', name='Delete the copy in sample@example.com once the new backup is complete').check()
        button('Switch account').click()
        assert last() == ('/api/cloud/switch', {'delete_old': True, 'expected_account': ACCOUNT})
        open_view(dict(), dict(REC_OK))
        show('Backup')
        more('More: reset the backup')
        count = len(calls)
        button('Reset backup…').click()
        expect(panel.get_by_text('Reset the backup?', exact=True).first).to_be_visible()
        assert audit('reset form')['pri'] == []   # the form's danger key is its submit; Done steps back
        assert calls_since(count) == []
        button('Reset backup').click()
        assert last()[0] == '/api/cloud/reset'

        # recovery file: desktop saves and reads back (D11); a browser download is not confirmed
        open_view(dict(), dict(configured=True, enrolled=True, account='sample@example.com', setup_at=NOW // 1000))
        show('Recovery')
        expect(panel.get_by_text('Optional: also save a recovery file', exact=False)).to_be_visible()
        with page.expect_download():
            button('Save recovery file…').click()
        expect(panel.get_by_text('A browser download is not confirmed until you open the file.', exact=False)).to_be_visible()
        expect(panel.get_by_text('Recovery file saved', exact=False)).to_have_count(0)
        recovery.update(saved_at=NOW // 1000)
        view.update(seq=view['seq'] + 1, last_publish=view['last_publish'] + 1)
        page.evaluate("data => window.__cloudStreams.forEach(stream => stream.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", view)
        with page.expect_file_chooser() as chooser:
            button('Check recovery file…').click()
        chooser.value.set_files({'name': 'kit.json', 'mimeType': 'application/json', 'buffer': b'{"synthetic":"kit"}'})
        expect(panel.get_by_text('Recovery file checked against your backup.', exact=True)).to_be_visible()
        assert last()[0] == '/api/cloud/recovery/verify'

        # phones: an older backend asks for an update, without a purchase/activation form
        open_view(dict(licensed=False), dict(REC_OK))
        show('Phones')
        expect(panel.get_by_text('Update this PC', exact=True)).to_be_visible()
        expect(panel.get_by_label('License key', exact=True)).to_have_count(0)
        open_view(dict(), dict(REC_OK))
        show('Phones')
        count = len(calls)
        button('Add a phone').click()
        expect(panel.get_by_role('img', name='Phone pairing QR code')).to_be_visible()
        assert last() == ('/api/cloud/pair', {'keys': ['anthropic', 'openai']})
        expect(panel.get_by_text('Code check: 4F2A.', exact=False)).to_be_visible()
        audit('pairing')
        button('Hide code').click()
        more('More: remove all phones, phone page address')
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
        assert last() == ('/api/cloud/unpair', {'recovery_passphrase': '', 'new_passphrase': 'a brand new synthetic phrase', 'expected_account': ACCOUNT})
        failing['/api/cloud/unpair'] = 'Synthetic: Drive is full.'
        open_view(dict(), dict(REC_OK))
        show('Phones')
        more('More: remove all phones, phone page address')
        button('Remove all phones…').click()
        panel.locator('#bp-current').fill('a long synthetic recovery phrase')
        button('Remove all phones').click()
        expect(panel.get_by_role('alert').filter(has_text='Synthetic: Drive is full.')).to_be_visible()
        failing.clear()
        open_view(dict(), dict(configured=False))
        show('Phones')
        more('More: remove all phones, phone page address')
        button('Remove all phones…').click()
        button('Remove all phones').click()
        assert last() == ('/api/cloud/unpair', {'recovery_passphrase': '', 'new_passphrase': '', 'expected_account': ACCOUNT})
        # The first backup after a switch offers a passphrase for this account, only when requested.
        open_view(dict(last_publish=0, state='publishing', done=3, total=50, bytes_done=5, bytes_total=500), dict(REC_OK, account='old@example.com'))
        show('Recovery')
        button('Create recovery passphrase').click()
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
        expect(panel.get_by_role('region', name='Is my library safe').get_by_text('Not backed up: another PC is the backup PC.', exact=True)).to_be_visible()
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
        show('Recovery')
        expect(panel.get_by_text('Saving your passphrase · step 2 of 3', exact=False)).to_be_visible()
        expect(panel.get_by_role('alert').filter(has_text='Choose Sign in again and pick the same account.').first).to_be_visible()
        assert 'Change account' not in panel.inner_text() and 'did not finish' not in panel.inner_text()
        expect(button('Create recovery passphrase')).to_be_visible()      # no dead end: a save that stopped is retried by typing the passphrase again

        # the passphrase check that met an upload waits for a slot instead of refusing (S8)
        open_view(dict(rotation='pending', state='publishing', task=REMOVING), dict(REC_OK, enrolled=False, verified=False, rotation_pending=True))
        show('Recovery')
        expect(button('Change passphrase…')).to_be_disabled()
        expect(button('Check recovery')).to_have_count(0)
        expect(panel.get_by_text('Passphrase created', exact=False)).to_be_visible()

        open_view(dict(), dict(configured=True, enrolled=False, account='sample@example.com'))
        show('Recovery')
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
        more('No passphrase, recovery file or phone code?')
        count = len(calls)
        button('Replace cloud backup with this PC’s library…').click()
        expect(panel.get_by_role('alert').filter(has_text='Replace the desktop backup')).to_be_visible()
        expect(button('Recover this backup…')).to_have_count(0)
        expect(panel.get_by_text('First backup running (progress above)', exact=True)).to_have_count(0)
        self.shot(page, f'desktop-{theme}-replace-backup-confirm')
        button('Cancel').click()
        expect(button('Recover this backup…')).to_be_visible()
        assert len(calls) == count
        more('No passphrase, recovery file or phone code?')
        button('Delete cloud backup and disconnect…').click()
        button('Delete and disconnect').click()
        assert last() == ('/api/cloud/sign-out', {'delete_mirror': True, 'delete_existing': True, 'expected_account': ACCOUNT})

        open_view(foreign, {})
        button('Recover this backup…').click()
        recovery_window = page.get_by_role('dialog', name='Recover a library', exact=True)
        recovery_window.get_by_role('button', name='I don’t have a key', exact=True).click()
        recovery_window.get_by_role('button', name='Replace cloud backup with this PC’s library…', exact=True).click()
        count = len(calls)
        self.shot(page, f'desktop-{theme}-recover-without-key')
        recovery_window.get_by_role('button', name='Replace with this PC’s library', exact=True).click()
        expect(recovery_window).to_have_count(0)
        assert ('/api/cloud/reset', {'replace_existing': True, 'expected_account': ACCOUNT}) in calls[count:]
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

        check_rail()

        check_review_regressions()
        check_recover_and_keys()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', default=str(ROOT / 'web/dist'))
    parser.add_argument('--out', default=None)
    options, _ = parser.parse_known_args()
    args = SimpleNamespace(repo=str(ROOT), dist=options.dist, port=0,
                           out=options.out or tempfile.mkdtemp(prefix='brainamon-browser-shots-'), only=None,
                           root=None, themes='dark,light')
    Review(args).go()
