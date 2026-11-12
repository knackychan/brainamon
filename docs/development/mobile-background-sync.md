# Mobile Brainamon: sync in the background

Updated 2026-11-11. Implementation and validation: [Android sync plan](../superpowers/plans/2026-11-11-android-sync.md).

## What now runs

On supported Android devices, Drive and Obsidian sync execute in a native WorkManager worker, independently
of the app page. Switching apps or locking the screen does not cancel that worker. Opening Brainamon shows
the saved local library first and joins or requests a catch-up round. Startup, reconnect, resume and refresh
share work instead of starting competing rounds.

There are two triggers:

- **Active work:** an immediate request for sync and durable pending uploads. Android 12+ uses expedited
  work when quota allows, with ordinary work as the fallback. This is still subject to system limits.
- **Periodic checks:** one WorkManager schedule with a 15-minute minimum interval. This is not a promise
  to run every 15 minutes. Power Saving, Doze, quotas, connectivity, app standby and manufacturer policies
  can delay checks substantially. Force-stopping the app prevents work until it is opened again.

Each attempt has an eight-minute budget. Interrupted work retains its checkpoints for a later attempt;
there is no continuous service or idle polling. No new notification permission or app notification is
required. Android's scheduler manages the job's execution resources.

## Existing controls and safety

Wi-Fi only includes Wi-Fi/Ethernet, not merely an unmetered cellular connection. Native transfers check
the actual default network before requests and while sending/receiving. Pause persists and cancels both
immediate and periodic sync. Resume requests fresh work. Stopping vault sync also turns its existing
switch off; already safe file writes can finish, and Drive sync remains available.

The confirmed Google account, pairing key, signed access/license controls and persisted vault permission
remain required. A token may renew silently; if Google needs interaction, Settings asks for reconnection.
A paired PC's access grant still expires after one hour without renewal. Local content and edits remain
available when access expires. Revoked vault access asks for the folder again.

The page keeps its existing edit journal. Before native upload, eligible changes are frozen and copied
as immutable encrypted envelopes to durable native storage. Staging is not delivery. An upload receipt
is recorded only after confirmed completion; the page acknowledges its journal afterwards. A lost
response is reconciled by name and exact encrypted bytes. PC-requested resends get a new transfer attempt
while retaining the existing delivery sequence. Edits interrupted before native handoff stay in the
page journal and are staged on reopening.

Uploads over 1 MiB use Drive resumable sessions with 1 MiB chunks. Downloads retain verified HTTP-range
chunks when the server supplies a strong ETag; otherwise they retry the file as a whole. Changed remote
versions discard partial downloads. Existing 50 MiB vault-file limits remain. Temporary failures back off.
Vault writes reuse recoverable replacement, deletion brakes and conflict copies; changed local content
is checked again before replacement/removal. A stale or incomplete vault index is never published.

Native and page vault writers do not overlap. Account changes and recovery operations wait for native
ownership to end. Only fully downloaded library snapshots become current. Unchanged library parts and
vault size/time/hash checkpoints are reused; SAF still requires a metadata walk to discover external
Obsidian edits. Old snapshot/content cache entries are reclaimed.

## Feedback and limits

The existing sync panel shows waiting for Wi-Fi, paused, syncing, up to date or needs attention. It does
not claim completion for an interrupted transfer. No extra interval setting or repetitive toast was added.

Android 8+ and a compatible Android System WebView/JavaScriptEngine provider are required for the native
runner. Android 7 and unsupported engines retain foreground sync after native work has been stopped.
The browser/PWA remains foreground-only. This change does not move Wiskit, picture/link enrichment,
offline media downloads or saved backup-management operations into background workers.

The S23 checks use synthetic data and a debug-only fixture, not a real Google account or the user's vault.
Power Saving was enabled during the initial checks and deferred new/restarted jobs; reopening resumed
saved work. See the plan for exact evidence and remaining device/release checks. Browser tests alone are
not evidence of Android background reliability.

Platform contracts: [WorkManager scheduling](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work),
[JavaScriptEngine](https://developer.android.com/develop/ui/views/layout/webapps/jsengine),
[Drive resumable uploads](https://developers.google.com/workspace/drive/api/guides/manage-uploads).
