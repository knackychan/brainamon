# Mobile Brainamon: sync in the background

Checked 2026-10-23 by reading the source. Not tested on a device.

## Answer

No. The Android app syncs only while it is open on screen. There is no background upload or sync.

## What exists

- Settings > Sync > **Wi-Fi only** applies to phone Drive uploads, reads, vault sync and downloads. It reuses the existing Wi-Fi preference (on by default; an earlier choice is preserved). A disallowed or unknown network pauses transfers, keeps edits queued, and shows the reason under the app bar. Reconnecting to Wi-Fi/Ethernet or allowing mobile data resumes sync while the app is open. Native Android detection follows the app's default network; a browser that cannot identify Wi-Fi stays paused until the user allows that connection. This setting covers sync and downloads; direct Wiskit requests still use the connection the user is on.

- No foreground service, WorkManager job or WakeLock in `mobile-shell/android/app/src/main/`.
- The only native threads are the AI-stream workers in `BrainamonPlugin.java`. They are shut down when the plugin is destroyed.
- All sync is page JavaScript:
  - Obsidian vault sync, `web/src/mobile/vault/auto.svelte.ts` (`startVault`): a round on app start, on every `visibilitychange` to visible, and every 2 minutes by `setInterval`. Automatic rounds are at least 60 s apart (`MIN_GAP_MS`). Android app paired to a PC only.
  - Google Drive read, `web/src/mobile/source/mirror.ts` (around line 1661): every 3 minutes and on `visibilitychange`.

## What happens when the app goes to the background

- Android freezes the WebView, so timers stop and an upload in flight can be cut off.
- Nothing resumes until the app is opened again. The visibility handler then starts a catch-up round.
- Phone changes (change files) queue locally and go out on the next foreground round.
- The PC side keeps its own schedule (vault rounds about every 30 seconds while "Sync my Obsidian vault" is on), so the PC only sees phone changes after the phone has had a foreground round.

## If real background sync is wanted

It needs a native piece in the Capacitor plugin: a WorkManager periodic job (15 minute minimum interval) or a foreground service with a notification. It would have to reach Drive and the Keystore-held keys from Java, or wake the WebView to run the existing JS round. Background sync is not implemented by the current source.
