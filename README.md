# Brainamon

A private, local-first library for the posts, videos and links you want to keep. Brainamon runs on your Windows PC and helps you organize your saves, search notes, create canvases, and ask Wiskit questions about your library.

## Download for Windows

[Download the latest Brainamon installer](https://github.com/knackychan/brainamon/releases/latest) · [All releases](https://github.com/knackychan/brainamon/releases)

Run the installer and follow the setup prompts. Windows may show an unknown-publisher warning. Brainamon checks future updates with a signed release manifest and installs them when you choose.

## What it does

- Save and organize links, posts and videos in a library on your PC.
- Search your library, write notes, make canvases, and export to Obsidian.
- Use Wiskit to ask questions about your saved material. AI features require your own provider or supported account.
- Use the Android companion app with a paired PC or in standalone mode. Phone sync requires a license and Google Drive.

Save links or import supported lists and CSV files, then fetch available thumbnails and captions. Smart search combines words and meaning. Optional video analysis creates transcripts, key frames and reports. Wiskit can answer questions with citations back to your saved cards; Obsidian export writes linked Markdown files. A local MCP server lets Claude Code search the library and request supported jobs, with proposed changes awaiting your approval.

## Requirements and technical details

The installer requires an x64-compatible Windows PC and the Microsoft Edge WebView2 Runtime. Saving links and notes does not require an AI key. Optional video downloads and analysis may require separately installed tools such as yt-dlp and FFmpeg; AI providers may charge separately.

The desktop library uses a local SQLite database and files in your chosen data folder. The interface runs in WebView2 with a local server bound to `127.0.0.1`. Android uses a Capacitor app and Android Keystore; Windows app-managed secrets use current-user protected storage. Optional Drive sync encrypts a copy before upload to the app's hidden folder in your Google Drive. Keep a separate backup of your library and recovery information.

The 1.0.0 installer is a test release; clean-machine and upgrade validation remain in progress. The Android release is planned for Google Play, but store availability is not yet established. For support or privacy requests, contact [me@fredtomas.com](mailto:me@fredtomas.com).

Your library and settings stay under your control. Some features connect to services you choose, such as AI providers and Google Drive. See the [privacy policy](https://www.fredtomas.com/brainamon/privacy/).

The application source and support materials are maintained privately. This repository contains the public download page and release files.


