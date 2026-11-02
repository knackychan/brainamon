# Brainamon on your phone: setup

Brainamon's phone app shows your library, notes and canvases, saves links you share to it, and lets
you ask Wiskit, all with your PC switched off. Your PC keeps an encrypted copy of the library in
your own Google Drive; the phone reads that copy. Nothing goes through a Brainamon server: there
is none.

## Use the phone on its own

No PC or license is needed for standalone use and encrypted Drive backup. In
**More > No PC?**, tap **Start**. Then in **More > Backup & phones**, tap
**Back up to Google Drive**, then **Set up recovery**: **Save passphrase**, then
**Save recovery file…** and keep the file outside the phone (the **Original recovery
code** works too). **Send now** uploads pending changes; wait for **All backed up**.
On a replacement phone, use **More > No PC? > Recover a library…** and the same
Google account. The backup includes the library journal, not AI keys or cached media.

A standalone phone has its own encryption key and backup files. It can use the same
Google account as a desktop without mixing the two libraries. To sync with a PC
instead, explicitly pair with a trusted PC using the steps below.

## Use the phone with a PC

For phone-PC sync, you need a current Brainamon build on your Windows PC, a Google
account, and an Android phone. No payment or receipt is required. The PC renews a
signed one-hour access grant while it runs; saved local content stays readable
when the PC is unavailable. Update older clients if they ask for activation.

## 1. On the PC: upload to Google Drive

1. Open Brainamon, then Settings > Backup & phones.
2. Click **Back up to Google Drive** and sign in with your Google account. Brainamon only gets its
   own hidden folder in your Drive; it cannot see your other files.
3. Wait for the first upload to finish (Backup & phones shows the progress). After that the PC
   refreshes the copy by itself while it runs.

## 2. On the phone: install Brainamon

Use the Android download channel identified by the release you choose at
https://github.com/knackychan/brainamon/releases. Follow that release's install
instructions. A source release alone does not include a cleared Android binary.
Independent developer builds use the separate **Brainamon Contributor** app.

## 3. Pair the phone

1. On the PC, in Settings > Backup & phones > Phones, click **Add a phone**. Under **Also send**, tick the AI keys the phone may use (for Wiskit,
   Smart search and Synthesize). The pairing QR appears on the page.
2. On the phone, open Brainamon, go to **More**, tap **Scan** and point the phone at the code.
3. Tap **Connect** next to Google Drive and pick the same Google account. Your library appears.

The code holds the key to your encrypted library. Show it only to your own phone and hide it
afterwards. The AI keys you ticked are not in the code: the PC leaves them in your Google Drive,
sealed with a one-time key the code carries, and the phone collects and deletes them once it is
connected (within 30 minutes; after that, pair again). The phone keeps the keys in its encrypted
storage; More > Wiskit on this phone > Forget removes them without unpairing.

Use the Brainamon app on the phone. The phone page in a browser works too, but a browser keeps
its storage less tightly than the app: treat it as a second choice for a phone that cannot
install the app.

## 4. Use it

- **Library:** browse, search, open an item's report and transcript. Items you open stay on the
  phone; **Save for offline** keeps one with its video for airplane mode.
- **Save links:** in Instagram, Facebook, Reddit or YouTube, tap Share, then Brainamon. The link
  is stored on the phone at once and reaches your PC's library the next time the PC runs.
- **Wiskit:** ask about your library. The phone calls the AI itself with your key and cites the
  cards it used. **Smart search** (search by meaning) needs your OpenAI key.
- **Notes:** read your Knowledge notes, write My Notes, **Synthesize** a note from up to 36
  sources (bigger ones are queued for the PC), or **Open in Obsidian**.
- **More:** what is on the phone, the cache limit, keeping canvases and videos automatically.

## Unpairing

- To lock out a lost phone: on the PC, Settings > Backup & phones > **Remove all phones…**. The PC makes a
  new key and uploads the copy again; old phones can no longer read it. (What a phone already
  downloaded stays on it until the app is removed.)
- To remove the copy from Google Drive: Settings > Backup & phones > **Disconnect Google Drive…**, with
  "Also delete the backup from Google Drive" ticked.
- On the phone, More > Backup & phones > **Unpair this phone** forgets the key (a phone used without a PC: **Remove from this phone**); uninstalling removes everything the app kept.
