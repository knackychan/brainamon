export const messages = {
  "shared.analysis.interval": "Frame interval",
  "shared.analysis.seconds": "seconds · 0 = off (no frames)",
  "shared.analysis.transcription": "Transcription",
  "shared.analysis.extract": "Extract audio and transcribe",
  "shared.analysis.model": "Transcription model",
  "shared.analysis.openai": "GPT-Transcribe (OpenAI key)",
  "shared.analysis.provider": "AI provider",
  "shared.analysis.none": "none",
  "shared.analysis.budget": "Frames sent to AI",
  "shared.analysis.frames": "Extracted frames",
  "shared.analysis.after": "After analysis",
  "shared.analysis.deleteVideo": "Delete the downloaded video after analysis",
  "shared.analysis.deleteAudio": "Delete the extracted audio after analysis",
  "shared.analysis.disclosure": "With transcription on, extracted audio goes to OpenAI. An AI report sends text and selected frames to Anthropic (claude), OpenAI, or the configured FreeLLMAPI server and its upstream providers. Provider charges apply separately; recipient terms and retention apply. Choosing \"none\" disables the AI report only.",
  "shared.analysis.keepShow": "Keep & show in item canvas",
  "shared.analysis.keepDisk": "Keep on disk only (hidden from canvas)",
  "shared.analysis.deleteFrames": "Delete frames after analysis",
  "shared.analysis.auto": "Auto (scale with length)",
  "shared.analysis.off": "Off (transcript only)",
  "shared.analysis.upTo": "Up to {n}",
  "shared.native.google.replaced": "Replaced by a newer sign-in.",

  "shared.native.backup.pc-managed": "Manage the PC backup on your PC. Only standalone phone backups can be changed here.",
  "shared.native.backup.library-changed": "The phone library changed. This task cannot continue.",
  "shared.native.backup.account": "Connect the Google account selected for this backup, then retry.",
  "shared.native.backup.saved-task": "Finish the saved backup task first.",
  "shared.native.backup.select-backup": "Select a standalone phone backup first.",
  "shared.native.backup.task-changed": "The selected backup task changed.",
  "shared.native.backup.identity": "The phone key or Google sign-in changed. Connect the selected account and retry.",
  "shared.native.backup.paused": "Backup task paused. Resume when ready.",
  "shared.native.backup.replacement-missing": "The saved replacement is missing. The old backup has been kept. Disconnect backup and keep this phone’s local content.",
  "shared.native.backup.replacement-duplicate": "Drive has duplicate replacement files. The old backup has been kept. Disconnect backup and keep this phone’s local content.",
  "shared.native.backup.replacement-verification": "Replacement verification failed. The old backup has been kept. Retry or disconnect backup.",
  "shared.native.backup.replacement-retained": "The replacement could not be verified. Remaining old files have been kept. Retry or disconnect backup.",
  "shared.native.recovery.material": "Use the original recovery code, a pairing link or the text of an exported phone recovery file.",
  "shared.native.recovery.fingerprint": "Phone recovery key does not match its fingerprint.",
  "shared.native.recovery.unsupported": "Unsupported recovery file.",
  "shared.native.recovery.identity": "The phone library or Google account changed. Reconnect and retry recovery.",
  "shared.native.recovery.name": "The phone recovery file name does not match its contents.",
  "shared.native.recovery.missing-setup": "This recovery setup is missing from Google Drive. Keep the recovery file and connect the original account.",
  "shared.native.recovery.setup-mismatch": "The saved recovery file does not match the recovery setup in Drive.",
  "shared.native.recovery.verification": "Recovery verification failed. Keep your original recovery code.",
  "shared.native.recovery.select-file": "Select the recovery file saved for this setup.",
  "shared.native.recovery.other-backup": "This recovery file belongs to a different phone backup.",
  "shared.native.recovery.prepare-first": "Prepare recovery first.",
  "shared.native.recovery.changed-while-saving": "The phone library or its recovery changed while saving. Save the recovery file again.",

  "shared.native.google.timeout": "Google did not answer in 2 minutes (its sheet may have closed). Try again.",
  "shared.native.google.renewal-timeout": "Google did not answer the sign-in renewal in 20 seconds.",
  "shared.native.secure.write": "Sign-in could not be saved securely. Retry before leaving this page.",
  "shared.native.network.timeout": "Could not check the network.",
  "shared.native.recovery.kit-in-code": "This is a recovery file. Open it with File under Unlock with.",
  "shared.native.recovery.passphrase-mismatch": "The recovery passphrases do not match.",
  "shared.native.recovery.file-limit": "Recovery files must be smaller than 32 KiB.",
  "shared.native.network.network": "Could not check the network.",










  "shared.native.google.denied": "Google Drive was not connected.",
  "shared.native.google.consent": "Google Drive needs you to agree first.",
  "shared.native.google.failed": "{detail}",
  "shared.native.scanner.failed": "{detail}",
  "shared.native.google.detail": "{detail}",
  "shared.native.scanner.detail": "{detail}",
  "shared.native.secure.detail": "{detail}",
  "shared.native.network.detail": "{detail}",
  "shared.native.vault.detail": "{detail}",
  "shared.native.recovery.detail": "{detail}",
  "shared.native.backup.detail": "{detail}",
  "shared.native.openUri.detail": "{detail}",
} as const

export const budgets = {
  "shared.analysis.none": { limit: 20, params: {} },
  "shared.analysis.keepShow": { limit: 72, params: {} },
  "shared.analysis.keepDisk": { limit: 72, params: {} },
  "shared.analysis.deleteFrames": { limit: 72, params: {} },
  "shared.analysis.auto": { limit: 48, params: {} },
  "shared.analysis.off": { limit: 48, params: {} },
  "shared.analysis.upTo": { limit: 24, params: {"n":24} },
} as const

