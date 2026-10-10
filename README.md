# Brainamp

Releases of Brainamp, a local-first desktop library for the posts you save (Facebook Reels,
Instagram, Reddit, YouTube): thumbnails and captions, AI descriptions and video analysis, search by
meaning, notes, canvases, and Jarvis, an assistant that answers from everything you saved.

This repository only holds the Windows installers. The source code is kept elsewhere.

## Install

Download `Brainamp-Setup-<version>.exe` from the latest release and run it. It installs for your
Windows user only, with no admin rights, to `%LOCALAPPDATA%\Programs\Brainamp`.

Windows SmartScreen may say the publisher is unknown, because the installer is not code-signed.
Check the file before running it: its SHA-256 must match the `.sha256` file published with it.

```powershell
Get-FileHash .\Brainamp-Setup-<version>.exe -Algorithm SHA256
```

## Updates

Brainamp checks this repository's latest release once per start and in Settings > App. An update
is only downloaded and installed when you click, and only after its SHA-256 matches. Your library
lives outside the install folder, so updates and uninstalling never touch it.
