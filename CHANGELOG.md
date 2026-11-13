# Changelog

Every release bumps `core/version.py` and adds a section here in the same commit. Newest first.

## Android 137.1.11 - 2026-11-13

- Recognizes Facebook's current More button when removing newly collected saved posts.

## 1.1.12 - 2026-11-13

- Recognizes Facebook's current More button during automatic saved-post removal.

## 1.1.11 - 2026-11-13

- Makes automatic Facebook removal more reliable when the saved list redraws.

## 1.1.9 - 2026-11-13

- Explains when another job blocks saved-post scanning and links to its progress.

## Android 137.1.09 - 2026-11-13

- Removes the unreliable mobile unsave option; scans collect posts without removing saves.

## 1.1.8 - 2026-11-13

- Refreshes the desktop installer with current import, link-preview, processing feedback and backup fixes.

## Android 137.1.08 - 2026-11-13

- Refreshes the signed Android app with current sync, progress and background-work fixes.

## 1.1.7 - 2026-11-12

- Desktop: clearer saved-post imports and automatic link previews after importing.
- Phone: pull-to-refresh retries sync immediately, with clearer sync progress and controls.
- Phone: background sync prioritizes pending uploads and resumes interrupted work.

## Android 137.1.07 - 2026-11-12

- Immediate pull-to-refresh sync retries and clearer progress and controls.
- Background sync prioritizes pending uploads and resumes interrupted work.

## 1.1.6 - 2026-11-12

- Refreshes the desktop installer and bundled phone interface with the latest fixes.
- Phone: smoother gallery navigation and pull-to-refresh, with clearer sync and processing progress.
- Phone: updated processing controls and narrow-screen layouts.

## Android 137.1.06 - 2026-11-12

- Reduced Android code size with release optimization, obfuscation and resource shrinking.
- Improved gallery, pull-to-refresh, processing controls and sync progress.

## 1.1.5 - 2026-11-12

- Includes the Settings, backup, background sync and import improvements prepared for 1.1.4.
- Phone: clearer saved-post import controls and feedback when a site cannot confirm removal.
- Phone: improved Facebook saved-list reading and more reliable targeted removal.
- Phone: sync, link previews and pictures fetch newer library content first.

## Android 137.1.05 - 2026-11-12

- Background Drive and Obsidian sync with saved checkpoints and resumable transfers.
- Clearer saved-post imports, safer targeted removal and improved Facebook reading.
- Newer library content, previews and pictures load first.
- Updated Settings, backup and recovery controls.

## 1.1.4 - 2026-11-12

- Desktop: redesigned Settings, backup status and recovery progress.
- Phone: redesigned Settings, backup and recovery screens with clearer status and controls.
- Desktop: Threads saved-post import, clearer scraper setup and safer Facebook CSV checkpoints before unsaving.
- Desktop: Obsidian copy progress reports checking and saving files.
- Phone: Drive and Obsidian sync continue through Android background work, with saved checkpoints, resumable transfers and clearer progress.
- Phone: safer saved-post removal and improved Facebook and Instagram saved-list reading.

## Android 137.1.04 - 2026-11-12

- Redesigned Settings, backup and recovery screens with clearer status and controls.
- Background Drive and Obsidian sync with saved checkpoints, resumable transfers and clearer progress.
- Safer saved-post removal and improved Facebook and Instagram saved-list reading.

## 1.1.3 - 2026-11-10

- Phone and desktop: phone languages foundation (English, French, Taiwan Traditional Chinese preview) across Add, import and Voice.
- Phone: dock shell, Add sheet, Notes manager, Settings, Wiskit chat, canvas composer and Tools panel rework.
- Desktop and phone: file transcription uses gpt-transcribe.
- Desktop: Remove all phones shows progress at once (the button turns into "Removing all phones…" with a bar) and cannot be pressed twice while the request runs.
- Desktop: checking the new copy after Remove all phones reads eight files at a time (at most two files over 64 MiB, to keep memory low) without waiting for the slowest of a group, so large libraries finish sooner.
- Desktop: Removing all phones stays on "Checking the new copy" while your Obsidian vault is uploaded and read back, instead of falling back to "Re-encrypting: 0 of 0 files".

## Android 137.1.03 - 2026-11-10

- Phone: same changes as desktop 1.1.3 (languages preview, dock shell, Add sheet, Notes manager, Wiskit chat, canvas composer, Tools panel).

## Android 137.1.02 - 2026-11-04

- Phone: every settings row keeps its button, switch or choice on the right, beside its words, on every screen width.
- Phone: one Obsidian card holds the vault folder, its sync with the PC and the vault name Open in Obsidian uses.
- Phone: Open in Obsidian uses the synced vault folder's name unless you typed another; choosing a folder saves its name.
- Phone: the Obsidian row in Sync shows Stop while a round runs and Sync now otherwise.
- Phone: Wiskit shows a single provider as text, and each AI key field has its Save button beside it.
- Phone: help moves into info overlays; searchable category and collection pickers; mobile versioning is independent of the desktop app.

## 1.1.2 - 2026-11-03

- Phone: long Obsidian and Drive sync messages stay within the screen without horizontal viewport scrolling.
- Phone: narrow settings screens place action buttons below their descriptions, keeping Google Drive and recovery text readable.
- Desktop and phone: show an estimated deletion count separately from confirmed progress.
- Desktop and phone: delete selected old backup files with up to four concurrent batches of 100 requests with progress after each confirmed batch, retaining individual failure handling and protection of independent backups.
- Desktop and phone: backup checklists show checked steps and an animated current step, with item/file counts and upload progress. Completed replacement counts remain visible during old-copy cleanup.
- Desktop: resetting a backup shows live upload file and byte counts, a numeric percentage, and clear active and waiting steps. The status explains why Google Drive temporarily holds both copies.
- Desktop: deleting the old backup reports file progress, retries count only remaining files, and completion clears the progress display immediately.

## 1.1.1 - 2026-11-02

- Desktop: recovery help offers confirmed replacement or deletion of an inaccessible Drive backup, while keeping local content and independent phone backups.
- Desktop: disconnect and deletion stop conflicting backup work automatically; saved tasks retain pause, retry and restart state.
- Phone: manage a selected standalone backup without its old key, with verified replacement uploads and deletion limited to confirmed files.
- Phone: disconnect preserves local content, manual sync pause persists, and interrupted backup management waits for Resume or Retry.
- Desktop and phone: save each AI provider's key independently, with clearer backup and recovery navigation.

## 1.1.0 - 2026-11-02

- Application-owned source is GPL-3.0-only, with editable artwork, independent build instructions and isolated tests. Historical releases keep their original terms.
- All current features, including phone pairing and vault sync, are available without payment or activation. Support is optional; legacy receipts remain usable with older phone apps.
- Current phones use an authenticated one-hour access grant from their trusted paired PC, without a payment receipt. Invalid or disabled grants still refuse access; phones that verified the new protocol cannot fall back after its deletion.
- Contributor Windows and Android builds use separate installation identities and local settings. Contributor Windows builds cannot install official automatic updates.
- Existing signed-update trust and explicit sync, pairing, recovery and unpairing controls are preserved.

This source transition does not declare historical binaries to match this source.
Future Windows and Android binaries require their own payload, licensing and
device checks before distribution.

## 1.0.9 - 2026-11-02

- Desktop (rebuilt installer): Install and restart waits for all Brainamon windows and background processes to exit before starting setup, preventing shutdown-related rollback.
- Desktop: one Backup & phones page in Settings for Google Drive backup, phones and recovery, with clearer sign-in, wrong-account and Google permission messages.
- Desktop: Recover a library window, and Update this folder to bring a library up to date from a temporary PC session.
- Desktop: long backup tasks (removing phones, saving the recovery passphrase, switching account, resetting the backup) are saved and resume after a restart.
- Desktop: backup skips files that recovery would refuse (a video over 512 MiB, any other file over 64 MiB) and shows how many. A video over the limit that an older version uploaded leaves Google Drive at the first backup; the original stays on this PC.
- Desktop: the vault sync reports files over 50 MiB that it leaves out instead of saying everything is up to date.
- Phone: new Backup & phones and Recover screens with one status model, edits made while the phone was locked out arrive once after pairing again, and the phone shows its name and last sync time on the PC.
- Phone: safer queued edits and undo journals while pairing, retry of failed record downloads, and clearer access messages in the sync row.
- Update every PC before any recovery handover; older versions must stay off.

## 1.0.8 - 2026-10-30

- Desktop: the About window has a link to support Brainamon on Ko-fi.
- Buy and license links keep pointing to the Gumroad product page; the Android app link points to Google Play.

## 1.0.7 - 2026-10-29

- Phone: a phone that lost its backup key can keep its content and reconnect to its Drive backup (Recovery > Restore from Drive > Find backup > Reconnect this phone). Restoring onto an empty phone still works.
- Phone: a calmer More screen, with the Setup summary first, one framed box per intent, long explanations folded away and quiet buttons for removing or forgetting things.
- Desktop: a calmer Settings, and a way to keep an existing library folder when the Drive key was lost.

## 1.0.6 - 2026-10-29

- Restore from Drive no longer fails with "Unsafe Windows filename" on libraries that use Wiskit Deep.
- Clearer restore: passphrase, recovery file or pairing code, each with its own button.
- Backup & recovery shows its page while the Drive status loads.
- Restart button after choosing another library folder or a restored library.
- Setup counts content already in a chosen library folder.

## 1.0.5 - 2026-10-29

- Adds guided first-run setup with inline AI, Drive recovery and phone pairing controls.
- Improves Settings navigation and preserves unsaved settings while switching sections.
- Clarifies phone connection, Google authorization and recovery setup progress.
- Hardens recovery enrollment and protected local settings handling.

## 1.0.4 - 2026-10-28

- Adds the maintained knowledge map and Brainamon-owned Obsidian vault, with safer phone vault sync.
- Activates permanent phone-sync licenses from Gumroad receipt keys.
- Updates privacy disclosures for the one-time license activation request.

## 1.0.3 - 2026-10-27

- Adds phone backup recovery with a passphrase, saved key kit, or original recovery code.

## 1.0.2 - 2026-10-27

- Removes the extra native App menu row above the desktop interface; automatic startup recovery remains available.
- Adds Obsidian and Claude Code sections to the website source.

## 1.0.1 - 2026-10-27

- Configures the permanent license verifier for desktop and Android, enabling activation for phone pairing and sync.
- Preserves existing libraries and the signed automatic update path from 1.0.0.

## 1.0.0 - 2026-10-27

- Adds Drive recovery and restore options for moving to a new PC.
- Improves phone sync reliability, backup handling, and desktop startup.
- Updates release guidance and the Brainamon website.

## 0.2.5 - 2026-10-27

- Wiskit's Claude Code mode now works in the installed app: the Brainamon tool server is bundled (Brainamon.exe --mcp). Settings > Claude Code finds the program, links to its installer and opens its sign-in. Claude Code itself is a separate install with a Claude plan.

## 0.2.4 - 2026-10-27

- Install browser tools now works on Windows 10 (version 2004 or later) as well as Windows 11; the browser check still has to pass before use.
- Installed builds hide the developer-only Google sign-in setup hints in Settings > Cloud.

## 0.2.3 - 2026-10-27

- Automatic updates use free Brainamon release signatures, verified with a pinned public key at download, recovery and installation.
- Older Windows-certificate-based versions require one manual upgrade to this version. Windows publisher warnings may remain.

## 0.2.2 - 2026-10-27

- Rebuild current desktop changes for the public update-feed trial from installed 0.2.1.
- This unsigned test build supports discovery/download testing; automatic installation requires valid matching publisher signatures.

## 0.2.1 - 2026-10-27

- Marketplace licensing setup, safer automatic updates, and a guided browser scraping walkthrough.

## 0.2.0 - 2026-10-27

- Version bump and unsigned Windows installer rebuild; retains the optional local-data uninstall cleanup.

## 0.1.9 - 2026-10-27

- Windows uninstall offers to permanently remove local libraries, settings, saved credentials,
  caches and app-managed tools. Keeping data is the default; deletion requires a second
  confirmation listing the folders. Silent uninstall keeps saved data.

## 0.1.6 - unreleased

- Update installation now requires the downloaded checksum, a matching release version and a valid
  Windows signature from the installed app's publisher; installer logs are kept in the updates folder.
- Item CSV export restores short descriptions and item notes; invalid JSON rows are rejected before
  changes are written. The interface now distinguishes item export from full backup.
- First-run Help leads with saving a link or note, an empty Library offers Add to Brainamp, and
  destructive confirmations focus Cancel.
- Release builds reinstall locked frontend dependencies, check WebView2 at Windows setup, and require
  explicit Android signing and version inputs for release bundles.

## 0.1.5 - 2026-10-12

- Vault sync: a two-way Obsidian vault between the PC and the Android app (Settings > Cloud, option `cloud_vault`).
  Off by default. The phone side has a Storage Access Framework folder picker and a Vault panel with the round status.

## 0.1.4 - 2026-10-12

- `build-installer.bat`: one double-click runs `packaging/build.py --installer`.
- Installed app: the one-click scrapers (Facebook, Instagram, YouTube) are now part of the installer.
- FFmpeg, ffprobe and yt-dlp are no longer in the installer. Settings > Tools shows which of them
  Brainamp finds, the `winget` command that installs them with a Run button, and a folder picker for a
  folder that holds them (put first on PATH at every start). Without them downloads and Analyze video
  say which tool is missing and point to Settings > Tools. No cookies file ships: each user sets their
  own in Settings > Downloads (the Help checklist points there), and the build refuses to package any.
- Analyze video: checks for FFmpeg, local transcription and the OpenAI key before it starts, and says
  in plain words what to install or change. Transcription defaults to whisper-api (OpenAI) where local
  Whisper is not installed; a skipped transcript now says why in the report.
- Release builds can be code-signed with a certificate file (.pfx) as well as a certificate store
  thumbprint; `py packaging/build.py --sign` refuses to build unsigned.
- Licence, changelog and third-party notices.
- Help window with a getting-started checklist, opened on first start; Settings > App can point the
  installed app at another data folder.
- Security: Jarvis chat names are checked before they become file names; a video attached to an item
  is limited to 4 GB.
- `requirements.txt` pins exact versions.
- Settings > App > Export diagnostics: a zip with the error log, version and a redacted settings
  summary, saved on this PC for you to send if you choose.

## 0.1.3 - 2026-10-11

- Tray and sleep mode, the drop panel, attachments, Jarvis fixes.
- Upload to Google Drive (encrypted phone mirror), the phone page and the Android app.

## 0.1.2 - 2026-10-10

- First version in the repo as Brainamp: per-user installer, Start with Windows, update check
  against GitHub releases (SHA-256 verified), database backup before the first start of a new
  version, the desktop widget and drop panel. (Earlier builds were not recorded here.)
