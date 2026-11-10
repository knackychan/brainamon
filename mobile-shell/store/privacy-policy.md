# Brainamon privacy policy

Last updated: 2026-10-28

Seller and privacy contact: Frederic TOMAS, an individual, at me@fredtomas.com.
Public copy of this policy: https://www.fredtomas.com/brainamon/privacy/

Brainamon stores a library on your devices. Windows desktop, standalone phone, Google Drive mirror
and direct-PC modes have different connections, described below. Saving links and notes needs no
AI key. External AI processing and Google Drive sync are optional. Reading the bundled policy,
software license and notices does not require a provider connection.

## Local data and credentials

- On Windows, the selected data folder holds saved links, metadata, thumbnails/media, notes,
  transcripts, reports, canvases, chats and settings. Settings > App shows the data folder.
  The selected settings home is normally `%LOCALAPPDATA%\Brainamon`, a reused populated
  `%LOCALAPPDATA%\Content Manager`, or the explicit `BRAINAMON_HOME`. Source runs normally use
  the repository's `data/` and `local/`; configured locations can differ.
- API keys, Google authorization, mirror keys and explicitly imported site sessions are kept in
  the settings home, outside normal library/Drive exports. Windows protects app-managed secret
  files with current-user DPAPI and access restrictions. Library files themselves are not all
  encrypted by Brainamon. Protection does not prevent access by someone using your unlocked
  account or by malware with the same access.
- Social-site cookies and remembered scraper logins are credentials for the site you choose to
  access. Import, remembering a login, and copying it for downloads are explicit choices. Forget
  saved access stops app use and removes app-managed secrets; it does not revoke the site's
  sessions or delete your original exports, browser profiles or backups.
- The phone holds library rows, downloaded/opened files, saved offline copies, drafts and pending
  changes in local browser/app storage. Decrypted library content can remain on the device.
  The Android app stores pairing/AI keys and Google tokens using Android Keystore-backed
  encrypted storage and excludes its app data from Android backup. This protection does not
  describe ordinary browser storage or make downloaded library content encrypted at rest.
- The desktop error log and in-app diagnostics are local. They may contain file paths, errors,
  operation details and content from requests/responses. The app does not automatically upload
  crash reports or analytics to the developer. Review/redact logs or support bundles before
  choosing to send them; do not include keys, pairing codes or cookie exports.

## Optional AI processing

AI requests go from the device running the operation to the selected provider or configured
OpenAI-compatible/local/proxy endpoint. A proxy may forward them to another provider; a server
labelled Local is only local if its configured address actually is. Direct-PC phone mode sends
requests to the running PC, which performs the external processing. Standalone/mirror phone
own-key features use the providers supported by the phone.

Depending on the operation, inputs can include questions, chat history, library titles, URLs,
descriptions, captions, notes, transcript/report excerpts, retrieved context, supplied images,
PDF documents or selected video frames. Own-key phone PDF reading uploads the complete PDF;
direct-PC/desktop PDF reading extracts text on the PC. Adding a PDF on the phone starts reading
immediately. Search indexing and some Deep research send library text for embeddings; semantic queries send
query text. Video analysis can upload extracted audio to OpenAI for transcription and frames/text
to the selected analysis provider. Voice notes upload recorded audio to OpenAI for transcription.
Picture-reading features send the chosen image to the configured vision provider. Desktop voice-note
temporary audio is scheduled for cleanup after processing. Phone recordings can stay queued locally
until transcription and saving succeed, and upload automatically when connectivity returns.
Video-analysis extracted audio, frames and
downloaded media can remain according to the operation's retention options; transcripts/reports
remain in the library until deleted. Choosing Claude Code mode in a source installation also
uses your separately configured Claude Code service and permissions.

API credentials authenticate these requests. Provider/API charges are separate from the app's
optional support for Brainamon. Provider/proxy terms govern their handling of inputs, outputs, retention and
any training use; Brainamon does not promise that a provider deletes immediately, never trains,
or keeps data in a particular country. Review your endpoint and provider's current terms before
sending sensitive content. Removing a local key stops future use by that copy of the app; it does
not revoke the key with its issuer or erase requests already processed externally.

## Requested network access and other apps

Fetching previews, captions, pages or media contacts the requested sites and their content
hosts, transmitting the requested URL and normal connection information such as your IP address
and request headers. Chosen site credentials are used only through the relevant access flow.
Some previews are requested after a link is pasted/shared. Source sites control their own logs,
availability and terms. Browser scraping and video download/analysis run on the PC; a Drive mirror
is file sync and does not provide a live PC jobs connection.

Installed Windows builds check GitHub daily and download updates automatically by
default; Settings > App can turn this off. Manual checks/downloads remain available.
Checks include the app version; downloads contact GitHub release hosts. Installation
always waits for an explicit Install and restart action. Optional tool installation contacts the relevant package/tool/browser
download services. These services receive normal connection/download information. The app's
local library is not part of an update-check request.

Sharing a link creates a local draft; Save commits it. Phone edits can queue locally, then travel
encrypted through Drive for PC intake when paired with a trusted PC. Current apps
use an encrypted access-v2 record containing the mirror fingerprint, issue/expiry
times and an enabled flag, signed by the PC key from pairing. No receipt or holder
information is needed. The PC also renews legacy license-v1 records for older phone
apps when an existing valid receipt is stored; those records contain the signed
receipt (holder, optional email, ID and issue date). Neither record is sent to a
licensing server or included in the QR. The PC renews access while running and
signed in. Removing all phones propagates through Drive or the last grant expires
within one hour offline. Removing a legacy receipt does not revoke current pairing
or sync; an old phone app needs an upgrade when its legacy proof is no longer renewed.
Local phone content and queued edits remain available when access is refused.
Standalone phone users can optionally back up their library journal encrypted in
Google Drive without a PC or license. This backup uses its own key and separate
files, even when the account also holds a desktop library. Restoring it requires
the same Google account and the phone recovery code; AI keys are not included. Exports and Open in Obsidian hand the selected content to the destination you choose;
those exported copies have their own retention. Android QR scanning uses Google Play services'
code scanner; Brainamon receives the scanned text and does not request camera permission itself.
Android includes Google's code-scanner/ML Kit components. Google's ML Kit terms state that its
input processing happens on-device, while the SDK can contact Google for fixes/model and
compatibility updates and sends API performance/utilization metrics to Google. See
https://developers.google.com/ml-kit/terms and Google's privacy policy at
https://policies.google.com/privacy. Exact shipped SDK/device behavior still requires release
verification; this app does not promise that every Android dependency makes no external request.

## Optional Google Drive sync

Google authorization uses `drive.appdata`, access to Brainamon's hidden app-data area rather than
your ordinary Drive files. Drive is off until you connect/enable it. The PC encrypts the mirror
contents with AES-256-GCM before upload; paired devices hold the key needed to decrypt them.
Standalone phone mode can also store encrypted changes there. Optional Obsidian vault sync sends
its configured content through the app's encrypted Drive flow. Google receives your account and
connection information and can observe file counts, sizes and change times. Encryption of these
contents does not hide that metadata or prevent access by a device/person holding the key.

Pairing/recovery codes carry library key material. Anyone with the code and the Google account
may be able to read the corresponding library. AI-key transfer is separately selected on the PC:
selected keys are sealed with a one-time transfer key, expire for collection after 30 minutes and
are deleted after successful collection. Failed/offline cleanup can leave expired ciphertext
until a later authorized cleanup; expiry is not a promise that every remote byte vanished then.
The library key itself does not expire with that transfer. Keep codes and clipboard copies secret.

A paired phone also keeps one small record in the same hidden area, sealed with the library key:
its device name (the Android device name, else its maker and model; "Phone browser" in a browser)
and when it last synced, so the PC can list it in Settings > Backup & phones. The phone replaces
the record in place after it reads the library, at most every 30 minutes (at once when its name or
pairing changes). Unpair on the phone tries to delete it (a failed attempt leaves it in Drive);
Remove all phones on the PC deletes the records sealed with the old key in the key rotation's
cleanup. A phone used without a PC writes none.

Optional Recovery setup uploads passphrase-protected and independent kit-secret-protected
envelopes of the library master key to the same hidden Drive area. Scrypt derives the
passphrase wrapping key; AES-256-GCM encrypts each envelope. Recovery metadata includes
format/version, account, library identity, fingerprint, generation and setup time. The
plaintext passphrase and kit secret are not sent to Google or the seller. A recovery kit or
explicit phone recovery export contains sensitive key material that you choose where to save.
Google sign-in alone cannot decrypt the mirror, and losing every recovery secret/device can
make it unrecoverable. New-PC restore downloads the latest available mirror into a separate
local library; it is not retained version history or a full machine/credential backup.

Google's service terms and retention apply to Google-held data. Disconnecting is different from
deleting the mirror or revoking another phone's Google authorization.

Brainamon uses the Google Drive app-data access only to store, read and delete its own encrypted
mirror, change, transfer and recovery files for your devices. It does not read your other Drive
files and does not send Google user data to the seller. Library content read from the mirror goes
to another party only when you direct it, such as a question you send to your own AI provider.
Brainamon does not use Google user data for advertising and does not use it to train AI models. Brainamon's use and transfer of information
received from Google APIs adheres to the Google API Services User Data Policy
(https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use
requirements.

## Optional support and legacy purchase information

Current Brainamon features require no purchase or activation. Optional support links open an external service, which applies its own privacy policy and payment terms. Historical purchases and explicit legacy receipt exchange can still use Gumroad. The app has no Brainamon customer account, store or
card-entry system. Gumroad handles checkout, payment, sales tax, receipts, download delivery and
refund requests under its own terms and privacy policy (https://gumroad.com/privacy); payment
card details go to Gumroad and its payment processors, never to the seller or the app.

Through Gumroad the seller receives the order details Gumroad shares with sellers, such as your
email address, name, country, the product bought, the price paid and refund status. Only when you explicitly save a legacy receipt, the app sends the license key from your Gumroad receipt once to the seller's activation
service at fredtomas.com, which asks Gumroad whether the purchase is valid and not refunded and
returns a legacy Brainamon license key; that key carries the name and email of the purchase and is
stored in the app on your PC. The activation service keeps no record of the request beyond the
hosting provider's standard access logs. The seller also receives what you choose to send for
support: emails, attachments or diagnostics. These are used only to deliver the purchase and
license, answer support and privacy requests, handle refunds or disputes and keep required
accounting records. They are not sold, not used for advertising and not used for unrelated
marketing. Order records stay in Gumroad and are not copied to another service, except license
details the seller needs to reissue a key and support emails kept in the seller's mailbox. They
are kept as long as needed for these purposes and for legally required accounting periods.

The developer cannot inspect your local library remotely through a privacy request and does
not automatically receive it from normal app use.

Gumroad, AI providers and Google can process information outside your country under their own
policies and transfer safeguards.

## Retention and deleting your data

Local library/settings data remains until you delete it; caches may be trimmed while saved
offline copies and pending changes remain. Backups and exports are separate copies. For a full
backup or deletion walkthrough, see `docs/BACKUP-RESTORE.md` supplied with the project documentation.

1. Review pending phone edits/drafts and keep or send anything you need before removing a copy.
   Deleting an item/note uses the existing library controls; in mirror mode a PC deletion queued
   from the phone takes effect on the PC only after intake.
2. If you want the PC's owned mirrored library files removed from Drive, while still authorized
   use Settings > Backup & phones > Disconnect Google Drive... and select Also delete the backup from Google
   Drive, then confirm Delete and disconnect. Wait for successful completion.
   This targets files identified by the current mirror manifest, not every Drive object, solo
   journal, vault export, unknown/old file or provider backup. A failed/offline attempt is not
   completed deletion. Review other retained app data through Google's available controls.
3. On each phone, Settings > Backup & phones > Unpair this phone (or Remove from this phone in
   standalone mode) removes that connection. Saved offline files and some pending/local records
   may remain. To remove all app storage after reviewing unsent work, use Android's app-storage
   clearing control or uninstall; in a browser clear the Brainamon site's storage. Remove
   separately exported files yourself.
   Settings > Storage > Clear the phone's copy only clears a cache: saved offline files and unsent changes stay,
   and an immediate refresh can download the library again.
4. On Windows, note the selected data folder in Settings > App and the actual settings home,
   then Quit fully, including the background/tray process. Interactive uninstall offers to
   permanently delete local saved data; keeping data is the default, and silent uninstall keeps
   it. Choosing deletion lists the settings/library folders for a second confirmation, including
   any discovered custom library outside the settings home. Confirm only after checking every
   path and any needed backups: everything inside the listed folders is deleted. Cleanup stops
   on unsafe/unrecognized paths or failures. Review unlisted custom/old folders separately.
5. Review separate backups, Downloads cookie exports, legacy profiles, logs, other-device copies
   and exported/Obsidian content. Remove or revoke credentials with their issuers if desired.

Remove all phones on the PC queues a key rotation; it finishes only after authorized publication,
verification and owned old-file cleanup. It cannot erase cached plaintext on another device or
revoke that device's independent Google sign-in. No control promises secure/forensic erasure or
automatic deletion from AI providers, marketplaces, their backups or records legally retained.

## Privacy rights and contact

Seller: Frederic TOMAS, an individual.
Support, privacy requests and complaints: me@fredtomas.com.
Public privacy-policy URL: https://www.fredtomas.com/brainamon/privacy/

For seller-held purchase/support records, applicable rights can include access/inquiry, a copy,
correction, deletion, stopping/restricting processing, objection, portability or withdrawing
consent where relevant. Email me@fredtomas.com, identifying the request
and enough order/contact information to locate it. Mandatory retention or another lawful
exception may limit deletion; applicable rights are not waived by this policy. Requests about
provider-held data should also be addressed to that provider. You may complain to the competent
data-protection authority, such as the CNIL where applicable in France; the applicable authority,
seller obligations and response process must be confirmed for the actual business before launch.

Brainamon is not directed at children under 13. The intended audience and applicable age rules
must be reviewed before targeting children. Changes to this policy should identify the revision
date and be made available with the app and at the final public URL.
