# Back up and restore Brainamon on Windows

## Words of Settings > Backup & phones (2026-10-31)

The Backup and Phone sync tabs are one page, **Settings > Backup & phones**: a summary that says whether your
library is safe, then Google account, Backup, Recovery and Phones. Getting a library back is a separate window,
**Recover a library…** (the page's footer, the app menu, and the summary when it is the next step). What this
document used to call: Connect Google Drive and Turn on uploads is **Back up to Google Drive** (one key: it signs in and
starts); Turn off uploads is **Pause backup** (it stays paused until **Resume backup**, and the main window's Jobs
shows the pause); Change account is **Sign in again** (the same account, nothing cleared) or **Switch account…**
(another account); recovery kit is **recovery file**; Set up recovery is **Create recovery passphrase**; Verify saved
kit is **Check recovery file…**; Show pairing QR is **Add a phone**; Unpair all phones is **Remove all phones…**;
Restore from Drive is **Recover a library…** with **Passphrase**, **Recovery file** or **Phone code**; Restore into
new folder is **Copy into new folder**; Reconnect this library is **Keep this folder**; Take over uploads is **Make
this PC the backup PC**. The recovery check no longer refuses while an upload runs: it waits for the gap between two
upload requests and backup carries on.

## Recover the latest Drive mirror (guided flow, 2026-10-29)

This workflow is implemented in source and is awaiting live Google, clean Windows
installation and Android device validation. It is not a historical backup service.
Keep the complete local backup below for excluded data and machine settings.

Recovery is optional. Connect Google Drive and turn on library uploads immediately;
Brainamon generates the encryption key automatically. Add recovery before or after
uploading, including while sync is on. Setup pauses active cloud work and resumes
the previously enabled publishers afterward, preserving the same encryption key.
Saving and verifying a kit is recommended, but does not gate normal uploads.
Without recovery, retain the original key on a surviving device or in a secure
export: Google sign-in alone cannot unlock an encrypted library after key loss.

To add recovery before losing a device:

1. Update every desktop that uses the account. Open Settings > Backup & phones.
2. Choose **Back up to Google Drive** if necessary. In Recovery, choose **Create recovery passphrase**
   (it also opens by itself while the first backup runs), enter/confirm
   a passphrase of at least 12 characters, then **Save passphrase**. Brainamon preserves the existing master
   and phone pairings, uploads two independently encrypted key envelopes and
   verifies their download/unlock round trips and uploader ownership. It is a saved task
   that takes the next gap between two upload requests (up to a minute on a slow connection), so
   backup carries on. No plaintext passphrase is saved.
   An interrupted candidate stays unconfirmed (**Recovery setup not finished**, with **Check recovery**);
   recovery-file checking is a separate fact.
3. Optionally **Save recovery file…**, put a copy outside both PC and phone, then
   **Check recovery file…** by reopening that exact file. The recovery file provides an independent
   alternative to the passphrase; uploads can continue without saving one. A
   browser download request does not prove that the file was saved. Reopen the
   saved file to check it. Saving a recovery file
   on the desktop reads it back against Drive in the same step. Removing phones needs
   no kit before the key switches; the replacement recovery file comes after it, and
   the old file is reported as out of date until the new one is saved and read back (**Save new recovery file…**).
4. Keep the passphrase separately. The kit contains an independent secret and an
   offline key envelope, not the library, Google authorization, API keys or license.
   An already paired phone also offers Settings > Backup & phones > Recovery > Export recovery file,
   using Android's folder picker or a browser download. Treat every kit/phone file
   and original pairing/recovery code as a secret.

After replacing or formatting a PC:

1. Install the compatible release and connect the same Google account.
   Desktop backup and recovery need no phone-sync license or paired phone.
   Open **Recover a library…** in Settings > Backup & phones (it pauses this PC's backup while it runs and
   resumes it afterwards).
2. Find the uploaded recovery setup and enter its passphrase, or open the saved kit
   or paired-phone recovery file. Original pairing codes/raw master codes can open
   legacy desktop mirrors. A solo phone journal without a desktop mirror is not
   a desktop restore source; its existing solo recovery path is unchanged.
   If the original PC is still available, stop its uploads before previewing. An
   unfinished in-place publication must finish on that PC before recovery; v1
   cannot repair overwritten objects or reconstruct a historical snapshot.
3. Preview the latest uploaded library and its omissions. Choose a new folder name
   inside an existing parent directory, outside the active library/settings home.
   The folder must not already exist. Allow roughly three times the uploaded size
   in free space. Recovery v1 limits a video to 512 MiB, another object to 64 MiB,
   a library to 100,000 files/100 GiB and a manifest to 16 MiB. Backup keeps the two
   per-file limits itself: it never uploads a video over 512 MiB or another file over
   64 MiB. It counts them, and the Backup card and this preview say how many files are
   not in the backup (they stay on the original PC). The copy of such a file that this
   PC uploaded earlier (an older version had no limit) is removed from Google Drive by
   the first backup after the update. Backup does not check the other limits (100,000
   files, 100 GiB, a 16 MiB manifest): a library past one is still uploaded and recovery
   stops safely without restoring anything.
4. Restore into that folder. Every referenced object is authenticated; missing,
   changed, damaged or unsupported files fail without modifying Drive or the active
   library. Cancellation keeps app-owned staging for retry in the same session;
   after restarting, make a fresh preview. Interrupted staging is not auto-deleted.
   Closing the window does not cancel the copy: use **Stop copying**. Open **Recover a library…**
   again to see a copy that is running.
5. **Restart now** (it switches to the restored library), then quit fully and restart. The original folder and
   protected pre-activation key/settings remain available. A protected activation
   journal finishes an interrupted key/pointer switch at startup. If it repairs
   the pointer after paths were already loaded, reopen once more as instructed;
   the app refuses to mix old file paths with the restored database. The installed
   app follows `location.json`; source launches must set `CM_DATA_DIR` to the restored
   folder after activation. Remove an existing conflicting `CM_DATA_DIR` launch
   override before activation. Uploads and vault sync remain off.
6. Review restored content. If this PC should publish, stop and update all other
   desktop copies, then choose **Make this PC the backup PC** (it reuses the passphrase you used to find the backup). Save and
   check a recovery file if you want an independent recovery method. Other upgraded
   desktop writers pause. Old binaries do not implement this ownership protocol and must stay off.
   If the original PC changed the mirror since preview, restore a fresh copy first.
   Phones may need re-pairing to the replacement PC's pairing-control signer.

Coverage: item IDs/UIDs, links/text/notes/tags/categories, favourite and processing
flags, uploaded reports/transcripts/thumbnails, Knowledge/personal note files,
chats, enabled canvases/images and selected videos; FTS text indexes are rebuilt.
Phone acknowledgement/alias state is preserved when present, and readable pending
changes use existing intake in staging without remote deletion. Older mirrors can
omit newer recovery metadata. Original unuploaded media, original-resolution
thumbnails, analysis intermediates, derived semantic/resource/topic indexes, machine
settings, credentials, Obsidian vault files and files over the per-file size limits
(step 3) are excluded. Vault recovery is not implemented by turning on bidirectional
sync against an empty folder.

Changing the passphrase deletes the setup it replaces once the new one is in Drive
and read back; a kit saved from the old setup still opens the same master. When
phones are removed, every setup of the old key is deleted after the new copy is
checked. For a stolen phone or compromised recovery secret, use **Remove all
phones…** with the current recovery passphrase, or choose a new passphrase if the
current one is forgotten: the phones are locked out at once, the replacement
recovery records are sealed on this PC and go up before the key switches, and the
new passphrase also opens the old key until its copy is deleted, so a restore
path exists throughout. The removal is a saved task on the sync thread
(`cloud/intents.json`): closing Settings or quitting Brainamon only pauses it, and
it runs with backup off without turning backup on.
Old devices cannot decrypt the newly published mirror, but their cached plaintext,
Google authorization and independent copies cannot be erased. Losing all recovery
secrets/devices makes an encrypted mirror unrecoverable; setup cannot reconstruct
a master that was already lost. The kit also cannot replace access to the content
in Google Drive. Deleted/overwritten library history is not retained in v1.

## Keep this library after the Drive key was lost (reconnect)

Use this when the library folder survived but this PC lost its Drive key, for example after the app home
was recreated. Instead of restoring a copy into a new folder, **Keep this folder** puts the
recovered key back and keeps this folder, its database, its local changes and its upload history.

1. Make a complete local backup first (below). Reconnect checks publication history, not every local file.
2. Quit Brainamon on every other PC and update it. Reconnect makes this PC the only uploader; other
   updated PCs pause, older versions are not stopped.
3. Open **Recover a library…**. It pauses library uploads and vault sync while it runs and resumes them when you are done.
4. Use your passphrase, recovery file, a surviving phone's recovery
   file or an original pairing code with **Find backup**. The review shows **Keep this folder**.
5. When it says the folder matches the latest backup, choose **Keep this folder**; with a passphrase typed to find the
   backup nothing more is asked, otherwise set a recovery passphrase. It protects the recovered key; earlier passphrases and kits keep working. Saving
   and verifying a kit afterwards is optional.
6. Backup continues from where it stopped (**Resume backup** if it shows paused). Only what changed since the last upload is sent, including local additions,
   edits and deletions. Licensed phone changes waiting in Drive go through the normal intake; phones may
   need to pair again. Vault sync is not part of reconnect: keep it off until you review it separately.

Reconnect is offered only when the folder's record of its last upload (key fingerprint, manifest ID and
manifest signature) matches the current Drive mirror. It is refused, and restoring into a new folder stays
available, when the folder is older or another PC uploaded since, when it was uploaded with another key,
when a key rotation, adoption, activation or restored-library takeover is pending, when either sync switch
is on, or when Drive's uploader or recovery records are damaged or ambiguous. **Disconnect and delete the
copy**, and signing in to a different Google account, clear the folder's upload record, so reconnect is refused
after either. Signing in again to the same account keeps it.

Reconnect writes only a protected backup of this PC's previous key and recovery settings
(`recovery-before-reconnect-*.json` in the protected cloud folder), a new recovery setup in Drive, the
uploader record, the recovered key and the recovery settings. It deletes nothing in Drive or on this PC and
does not move the data folder. If it is interrupted after it started writing, Drive may already hold an
extra recovery setup or a changed uploader record; uploads stay off. Keep the backups, find your library
again and retry. Never edit the epoch, the upload record or the uploader record to force a match.

## Back from a temporary PC: Update this folder (2026-10-31)

Use this when another PC restored this library's backup with the same key, became the backup PC and backed up
there (a temporary PC), and this PC still has its library folder, its key and its recovery setup. Instead of a
full copy into a new folder, **Update this folder** downloads only the files whose version differs, switches to
the newer library at one restart and makes this PC the backup PC again. The key does not change: phones, the
passphrase and the recovery file keep working.

1. Settings > Backup & phones says another PC became the backup PC and offers **Update this folder…** with the
   amount to download. The Recover a library window offers it first too when the backup it finds has this
   folder's key; **Copy into a new folder instead** stays one click away.
2. The confirm names this PC's own changes made after its last backup. They are not in the newer version and
   are not merged: they stay only in the dated folder `before-update-<YYYY-MM-DD>` inside the library, which holds
   this PC's previous `content_manager.db` and every file the switch replaced or removed. Nothing is deleted.
3. The download goes to a staging folder beside the library (`.brainamon-update-<hex>`). Drive is only read.
   Pause or quit keeps what was downloaded; **Stop updating** removes the staging folder and changes nothing.
   If the other PC backs up again meanwhile, its new changes are fetched first (up to three rounds; then quit
   Brainamon there and try again).
4. **Restart now** checks the newer backup once more, then the switch runs at the start, before anything opens
   the database. A crash in the middle resumes at the next start; a switch that fails before anything moved
   leaves this library as it was. Uploads stay off until this PC is the backup PC again.
5. After the restart this PC writes the uploader record (the other PC stops at its next upload), and its next
   upload sends almost nothing: what the other PC sent is recorded as sent. When the other PC changed nothing,
   step 3 and the restart are skipped and this PC's own later changes go up as usual.

Not offered (Copy into a new folder… only): when the backup there uses another key (phones were removed or the
backup was reset there), another library or Google account, a restored library that never became the backup PC,
a pending key change or activation, or a PC without a recovery setup. Known limits: edits to note files during
the download can survive the switch (database edits go to the dated copy); thumbnail packs, a video renamed by
the restore and the search vectors are downloaded or sent again once.

## Missing the original cloud key

The local library remains usable. A new passphrase cannot unlock a cloud copy
whose original key is missing. Restore with surviving material, keep working
locally, or connect a different Google account that passes the readiness check.
**Switch account…** preserves the local library and existing cloud copies, and
leaves both uploads and vault sync off. Turn uploads on explicitly after review.

If you must reuse the same account without any recovery material, open the
missing-key help step and review its scope first. Removing this app's hidden data
can also remove standalone phone backups, vault copies and other app records.
Do not proceed if those copies are needed. The UI requires acknowledgement before
showing the manual procedure and requires sync to be paused.

The reported working procedure is: disconnect the app from Google Drive, then
confirm removal of hidden app data. Google documents app management under
[Settings > Manage apps](https://support.google.com/drive/answer/2500820).
The exact confirmation wording still needs validation on a disposable account.
If that confirmation is not offered, stop and consult Google's help. This is
separate from Brainamon's limited **Disconnect and delete the copy** action;
there is no automatic keyless reset. Reconnect afterward and retry the readiness
check with uploads off. Remaining or ambiguous app data keeps setup blocked.

## Google stopped accepting this PC's sign-in

While Brainamon's Google sign-in app is in testing, Google asks again every 7 days (`docs/RELEASING.md` A5); a
password change or a removed access does the same. Uploads wait, phones pause within an hour (the access record is no
longer renewed) and Settings says so. Choose **Sign in again** and pick the same account: only the sign-in is replaced.
Nothing is deleted, `sync_state` and the key stay, and the next upload sends only what changed. If you pick another
account, the new sign-in is revoked and dropped and nothing changes. **Change account** is for really using another account.

## Setup and phone connection

App menu > Setup and first start use the same six steps: local library,
tools/environment, first content, Wiskit, Drive/recovery and phone. Back,
Continue, Skip and the final summary keep unfinished tasks available. Capability
checks determine readiness; skipping never marks a task ready. The last step and
skipped step IDs persist with existing onboarding preferences;
after restart, actual saved capabilities determine readiness. All six count in
desktop progress, including optional unfinished steps. Existing welcome/hide preferences stay.
Links, notes and supported imports need no optional tools, AI, Google or license.

Each API-key field has **Save key** (or **Confirm removal**). It saves only that
provider; other key, model, URL and download drafts remain pending for global
**Save**. **Saved on this PC** means stored, not tested with the provider. Returning
to Setup keeps a Settings window with unsaved drafts open.

After scanning the PC's pairing code, the phone shows its expected Google account,
Google connection, signed PC access check and library load together at the top of
More. Native sign-in returns there; browser OAuth returns to the same screen.
The phone needs its own Google consent, and inherits sync access from the PC.
It does not need a second license. Matching saved connections are retained only
with matching key, account and OAuth client/project context and a usable token.
Missing, expired or unauthenticated grants remain denied with different retry
messages. A missing grant alone does not establish why the PC is unavailable.
Google connection stays visible if later library loading fails or the first
upload is unfinished. Secure-storage failures surface before reporting completion.

The reported Android 1.0.4 chooser failure has not been reproduced on a physical
phone. Synthetic browser/native tests do not close that device gate. See the
implementation ledger (private development record).

## Standalone phone backup

A phone used without a PC can back up its library journal to Google Drive without
pairing or a license. In **Settings > Use without a PC**, choose **Start**. Then in
**Settings > Backup & phones**, choose **Back up to Google Drive**, and under **Recovery**
choose **Set up recovery**, enter or generate a passphrase, then **Save passphrase**,
**Save recovery file…** and **Check recovery file…**. Keep the recovery file outside
the phone and the passphrase separately. The **Original recovery code** remains
available and existing saved codes still work. Use **Send now** to send pending changes;
confirm they show **All backed up** before relying on the copy.

The phone generates its own encryption key. Its backup files use a separate,
key-derived `solo-` namespace in Brainamon's hidden Drive app data storage, so
using the desktop's Google account does not merge, replace or sync either library.
This is a separate collection of encrypted files, not a folder in My Drive.
The backup contains the library journal (saved links, edits, notes, chats and
approved canvas changes), not a full copy of app storage, AI keys or cached media.

On an empty replacement phone, use **Settings > Recover a library…** (a phone
already used without a PC: **Settings > Backup & phones > Recovery > Recover a library…**).
Under **Unlock with**, choose **Passphrase** to find an uploaded setup, **File** to open
the saved recovery file, or **Code** for the original 43-character key. A passphrase or
a file needs Google Drive first: **Start** beside **Use without a PC** in Settings, then
**Back up to Google Drive** with the account that holds the backup. The code option
works before connecting; connect the same account afterward. The code field also takes
a pairing link or the text of an exported phone recovery file. **Find backup** unlocks
the key without restoring anything, then the
review **Keep this phone's content** says whether this phone's latest backup lives in
Drive under that key (its recorded batch is there, opens with the key, and matches its
time, count and digest). When it does, **Reconnect this phone** keeps everything on the
phone and its queued changes, puts the key back, keeps a backup of the previous pairing
in the phone's protected storage, and sends again at the next sync whatever went up under
the wrong key. It writes nothing to Drive and deletes nothing; a new recovery passphrase
is ordinary Set up recovery afterwards. Otherwise, or when the phone never backed up,
**Restore on an empty phone** stays available and still refuses a phone that already
contains local content.
Desktop kits/passphrases belong to desktop libraries and must be restored on a PC.
Older standalone `chg-` backup files
remain readable with their original key. Explicit pairing with a trusted paired PC
requeues the phone journal under the PC's key; its independent backup stays in Drive.
Without a recovery passphrase, recovery file, original code or a surviving phone holding
the key, the encrypted phone backup cannot be opened. Disconnecting or removing
the phone does not delete it. Phone envelopes use `vi-phone-recovery-` names and
the same fixed scrypt/AES-GCM settings as desktop recovery, but a distinct
authenticated format. Setup preserves the key, so earlier recovery secrets remain
valid. The kit is a key, not a backup; content must have finished uploading.

## Make a complete local backup

1. In Settings > App, record the **Data folder** path. Choose **Quit** from Settings or the tray menu. Closing the window may only hide Brainamon in the tray.
2. Copy the entire data folder, including `content_manager.db`, `items/`, `notes/`, chats, canvases and other files.
3. Copy the entire selected settings home as well: normally `%LOCALAPPDATA%\Brainamon`, or the populated legacy `%LOCALAPPDATA%\Content Manager` home, or the explicit `BRAINAMON_HOME`. Include `location.json`, all `private/`, `cloud/` and `site-sessions/` subdirectories, and pending rotation/previous files. Source runs normally use the repository and its `local/`; `BRAINAMON_HOME` redirects those runtime paths too. If the data folder is inside that home, one complete copy covers both steps.
4. Copy the Obsidian vault folder shown in Settings > Obsidian (default `Documents\Brainamon Vault`; a vault moved off the legacy `data\Fredorama` lives outside the data folder). It holds Brainamon's rendered pages, their ownership manifest and deletion records (`.brainamon\manifest.json`) and anything you wrote in that vault yourself. A classic-export vault inside `data\Fredorama` is covered by step 2. The settings home's `cloud\vault_base.json` (step 3) holds vault sync's merge bases, remembered devices and the vault identity it last synced; without it the next round after a restore is a non-destructive first sync.
5. Keep the copies somewhere access-controlled. The settings copy contains credentials and the data copy can contain personal content. Check that the copies contain the expected files before relying on them.

**Item CSV export is only item metadata.** It omits thumbnails and other media, Knowledge notes, chats, canvases, credentials and cloud pairing material. The automatic `data/backups/` copies are database-only and do not replace the steps above.

## Restore under the same Windows account

1. Quit Brainamon fully before copying files. Restore the entire data folder and selected settings home from the same backup, using the same or a newer compatible app version.
2. If the data folder is at a different path, edit only `data_dir` in `%LOCALAPPDATA%\Brainamon\location.json` to the new absolute folder path before starting Brainamon. Alternatively, use Settings > App to select the restored folder after starting, then restart the app.
3. Start Brainamon. Check several links, item notes, Knowledge notes and local media. If protected storage cannot unlock, preserve the complete backup and stop cloud publication. Do not remove the mirror-key sentinel or generate a replacement key as a repair.

Windows DPAPI copies are **not a portable credential backup**. Another account or PC may not unlock API keys, Google authorization, site sessions or the mirror master. Before a planned move, securely retain the explicit pairing QR/code from Settings > Backup & phones > Add a phone, with **Also send** turned off so no AI keys are included. It contains the portable master key; possession together with the Google account permits decrypting the mirror. Treat the QR, clipboard and any written copy as secrets. The key does not expire with an AI transfer.

On a new PC, the local library can be restored independently. Re-enter API keys and reconnect site/Google accounts as needed. The recovery workflow above can import the original master and restore the latest available mirror. A retained QR also works with a compatible phone app; it does not make the DPAPI settings copy portable. Keep uploads off until recovery/enrollment and explicit handover are verified.

Restore a backup with the same or a newer Brainamon version than the version that last opened it. Do not run an older version against a newer database without a tested restore procedure.

## If a phone is lost

Restore the PC backup first. Choose Remove all phones… in Settings > Backup & phones. The click locks every phone out: this PC deletes the old key's current and legacy phone-access records, which a phone reads on every Drive call, and stops renewing it. If this PC cannot reach Drive at the click, the lock is retried at the next contact and Settings names the latest time, at most one hour after the last renewal (the access record's lifetime, `core/sync_license.py`). Changes a removed phone sends after the click are not applied: they stay in Drive and Settings counts them. Also sign that phone out of your Google account ([how](https://support.google.com/accounts/answer/3067630)); until then it can still delete Brainamon's files in your Drive and download the old encrypted copy. The re-encrypting that follows waits for Drive while offline and resumes as a queued task without turning regular uploads on. New pairings use the replacement key while removal finishes. Retry uses the same candidate key and protected rotation record. Do not delete pending rotation files: they retain the old key for explicitly authorized recovery of old pending phone edits, which are preserved and never silently replayed after rotation. Unknown cloud objects survive cleanup. Rotation cannot erase cached plaintext or revoke the phone's independent Google authorization. Google Drive sync is optional and does not replace the local backup.

## Delete your copies and disconnect

Deletion is a separate choice from backup, uninstall or disconnect. Use the steps below only for
copies you intentionally want removed; retain a complete backup first if you may need recovery.

1. **Review work on every phone first.** In More, inspect Changes from this phone and unsent
   drafts/edits. Send and let the PC apply what you want to keep; a sent change can still be
   waiting for PC intake. Keep needed saved-offline files or exports separately. Solo mode's
   journal is its library, so removing unsent records can lose the only copy.
2. **Choose the cloud scope while authorization is available.** To remove the PC's mirrored
   library files, open Settings > Backup & phones > Disconnect Google Drive…, tick Also delete the
   backup from Google Drive, then confirm Delete and disconnect. Wait for
   successful completion before removing credentials/settings. An error/offline attempt is
   not successful deletion; the existing flow retains authorization on deletion failure so
   you can retry. The control removes files identified by the current mirror manifest. It
   does not erase every hidden-app-data object, solo journal, vault copy, old/unknown object,
   separately exported Drive file or provider backup. Review those separately with the
   provider's available app-data/file controls. Disconnect without the checkbox stops sync
   and removes the PC authorization; it keeps the cloud copy. Turning off sync keeps both
   the sign-in and cloud copy.
3. **Remove each phone's local copy deliberately.** Settings > Backup & phones > Unpair this phone
   (paired mode) or Remove from this phone (solo mode) removes that phone connection and its
   pairing/token material.
   Saved-offline content and some queued/local records can remain. For complete app-storage
   removal after step 1, use Android's app-storage clearing control or uninstall. In a browser,
   clear the Brainamon site's storage, including service-worker/cache data. Remove files exported
   to other folders/apps yourself. Clear the phone's copy is a cache control: saved-offline files
   and unsent changes stay, and its immediate refresh can download the library again.
4. **Identify the actual Windows folders, then quit.** Record Settings > App > Data folder and
   the selected settings home: normally `%LOCALAPPDATA%\Brainamon`, a reused populated
   `%LOCALAPPDATA%\Content Manager`, or the explicit `BRAINAMON_HOME`. Check `CM_DATA_DIR` and the
   selected home's `location.json` if configured. Source runs normally use repository `data/`
   and `local/`. A custom library can be outside the settings home. Quit from Settings or the
   tray and ensure the background app has stopped; closing its window is insufficient.
5. **Choose whether to remove local saved data during Windows uninstall.** The interactive
   uninstaller asks whether to delete local data; **No (keep data)** is the default. Yes lists
   the exact folders and asks for a second confirmation to permanently delete everything inside
   them, including database backups, notes/media/chats/canvases, protected keys, cloud/session
   material, browser cache, app-managed tools and diagnostics. Check every path and back up anything
   you need first. Both standard homes, default libraries, configured `location.json` libraries,
   and `BRAINAMON_HOME`/`CM_DATA_DIR` overrides visible to the uninstaller are reviewed. Silent
   uninstall keeps data. Cleanup stops on unsafe/unrecognized paths, links/junctions, a running app
   or a deletion failure; a failure can leave partially removed data. Custom folders configured
   only in a separate launcher's environment, old libraries no longer referenced, and other
   unlisted copies require manual review. For manual cleanup, verify each absolute path and its
   contents before removing it; do not delete a parent folder shared with other files.
6. **Review independent copies and records.** Backups on other drives/cloud services, original
   cookie exports in Downloads, old persistent browser profiles, historical plaintext settings,
   copied pairing/recovery codes, logs and exported/Obsidian files can remain. Revoke site
   sessions/API keys through their issuers if desired. AI providers and marketplaces govern
   their own records; removing a local key does not erase earlier requests. Contact the seller
   Frederic TOMAS at me@fredtomas.com about seller-held purchase/support records, subject to
   applicable retention/rights.

Remove all phones… on the PC is key rotation, not complete deletion. It requires authorized
publication/verification and owned old-file cleanup to finish, and cannot erase another device's
cached plaintext or revoke its independent Google authorization. Never delete rotation or
mirror-key files to work around a failed unlock or incomplete rotation. These instructions make
no secure/forensic-erasure guarantee. Flow validation uses synthetic files/services only; actual
installer/device and production gates stay open in the security plan.

## Repair a failed update

Quit Brainamon from the tray. Use a newer signed repair release from the trusted channel; keep the data and settings folders untouched. The silent updater verifies the downloaded hash again, requires the exact current production certificate identity and rejects same/older versions. It writes an Inno Setup log to the selected settings home's `updates/Brainamon-Setup-<version>.log`. Review that log and diagnostics before retrying. Do not downgrade protected settings or a database already opened by a newer version; any manual rollback requires a matching complete backup and a tested procedure.

## Saved site access (2026-10-24)

App-managed cookies and remembered scraper logins live under the PC settings
folder's `site-sessions/`, outside the library and Drive payload. They are encrypted
at rest with current-user Windows DPAPI and may be unusable after moving to another
Windows account or PC. Re-import the site's cookies or sign in again if Settings
says Cannot unlock on this PC. Drive authorization is separate from social-site
access. Optional browser tools in `tools/scraper/` can be installed again.

A full manual copy of the local settings folder may also contain **old plaintext
cookie exports or persistent browser profiles**. Those were not silently migrated,
encrypted or deleted by this feature. Protect that backup accordingly. Brainamon
leaves user-owned exports in Downloads until you remove them. Forget saved access
clears app-managed secrets and blocks legacy fallback; it does not promise remote
session revocation or forensic erasure of temporary bytes, exports or backups.
Drive recovery v1 is described above; live account/device release checks remain open.

## Protected-storage migration (2026-10-25)

Windows API keys live in `LOCAL/private/api-keys.dpapi`; Google tokens, mirror keys, rotation records and transfer ownership records live under `LOCAL/cloud/private/`. Existing accessor paths remain logical names. Directories, temporary and final secret files use current-user-only DACLs and current-user DPAPI. Migration verifies protected bytes and read-back before retiring active plaintext. The exact mirror master is preserved; `mirror.key` becomes a nonsecret downgrade sentinel. A successful retry retires plaintext left by an interrupted commit. A verified `.previous` ciphertext can recover an interrupted replacement; conflicting legacy/protected values or an undecryptable last copy fail closed. Never delete these files to bypass an error.

Active legacy database API-key rows are removed only after protected config reads successfully. Historical SQLite/WAL files, backups and user-owned exports can still contain plaintext; no forensic erasure is promised. Linux secret files use 0600 permissions in 0700 directories, with no DPAPI claim. Same-user malware can read app memory and use the account's DPAPI access.

Local tests use synthetic files/accounts and mocked services. Actual patched artifacts, production signatures, installer equivalence, another-account denial, Console and physical-device interruption checks remain release gates in the security plan (private development record).

### Removal cutoff limits (2026-10-30)

Recovery preparation is local, so an enrolled PC can record Remove while offline. The replacement recovery
records are uploaded and checked before switching keys; saving the replacement recovery file follows the switch.
Once removal is recorded, old-key vault rounds stop at their cancellation checkpoints. A request already in
flight can finish. New-key vault publication remains available to finish removal.

The offline phone-change cutoff uses Drive `modifiedTime`, which a client holding the token can set.
It constrains the real app, not a hostile token holder. The online snapshot of file IDs also does not prove
that a token holder has not rewritten an existing file. Key rotation protects future new-key content;
sign the lost phone out of Google separately. Already downloaded content cannot be revoked.
