# Brainamon updates

Step-by-step release routine (desktop and Play Store): [RELEASING.md](RELEASING.md).

Brainamon uses free Ed25519 release signatures. No Microsoft subscription or
paid Windows certificate is required. Windows can still show Unknown publisher
or SmartScreen warnings: these signatures protect Brainamon's updater, not
Windows publisher reputation.

## First setup on the release PC

Run `py packaging/update_keys.py init` once. It creates a separate update key at
`%LOCALAPPDATA%/Brainamon-Updates/private/release.key.dpapi`, protected by Windows
current-user DPAPI and ACLs, and pins only its public key in
`core/update_signing.py`. Repeated setup reuses the key. A different configured
key or missing private key is an error; setup never silently replaces trust.
The phone/license issuer is unrelated and is never used for updates.

Keep the protected key and Windows profile recovery material backed up securely.
DPAPI protection is tied to this Windows user/PC; copying this file to another
computer alone is not a portable signing backup. Losing access requires a
deliberately distributed new bootstrap. Do not delete the key or change the
public verifier to work around signing failures.

`BRAINAMON_UPDATE_KEY` can select an existing logical private-key path outside
the source checkout. Never bundle or upload any private key, plaintext or
protected. Only the public verifier belongs in source and installed builds.

## Build and publish

1. Bump `core/version.py` and add the changelog entry.
2. Run `py packaging/build.py --installer`. Configured installer builds check
   key access before building, then sign the final installer automatically.
3. Inspect the actual extracted installer, compare its files with the expanded
   bundle, scan for private files, and run an isolated frozen startup/upgrade.
   `--release` also invokes the existing final-artifact checker (requires its
   extraction tooling). Authenticode remains optional through `--sign`.
4. Upload exactly `Brainamon-Setup-X.Y.Z.exe`, its `.exe.sha256` and
   `.exe.update.json` to stable tag `vX.Y.Z` in the public source-and-release
   `knackychan/brainamon` repository. Only reviewed source exported without private history belongs there; future artifacts must match their exact public source commit.

To sign an already built installer, run
`py packaging/update_keys.py sign dist/installer/Brainamon-Setup-X.Y.Z.exe`.
Its name must match the current checkout version. Do not modify installer bytes
after signing; regenerate all sidecars if a final installer changes.

The signed manifest binds schema, repository, version, filename, size and SHA-256
using a domain-specific message. The app trusts only its bundled public key,
checks the checksum/GitHub digest, and rechecks signature and bytes before
installation and offline recovery. Missing/invalid signatures never become ready.
Installation still requires the explicit Install and restart action and waits
for active work. The installed-only automatic worker checks/downloads daily.

The rebuilt 1.0.9 updater hands setup to a hidden Windows PowerShell helper, which
waits up to 120 seconds for every process from the installed executable to exit.
It rechecks the verified installer hash after waiting, then starts setup. A timeout
leaves the app processes alone and does not install. Handoff failures are recorded
beside the download in `Brainamon-Setup-X.Y.Z.handoff.log`; setup keeps its `.log`.
Copies installed from the original 1.0.9 installer need a manual reinstall of the
rebuilt installer: the automatic updater does not offer the same version again.

If an older build rolls back with `Some applications could not be shut down` in
the setup log, quit Brainamon completely (including its tray/keeper), allow the
windows to close, then run the already verified downloaded installer manually.
There is no need to uninstall or remove saved data.

## Test-feed migration to the public repository

Older installed copies still check `knackychan/brainamon-update-test`. To migrate them,
put the same 1.0.0 installer on both repositories, with a separately signed manifest
binding each repository name. The 1.0.0 app checks `knackychan/brainamon` for later
updates. Never reuse a manifest signed for one repository on the other.

## One-time migration

Installed 0.2.1 and other old Authenticode-only versions cannot accept this trust
change through their updater. Manually install the verified 0.2.3 bootstrap once;
then future releases signed by the same update key can use the normal updater.
The installer retains the existing AppId and application data locations.
Do not uninstall or select local-data deletion to perform this upgrade.

Full-folder backup instructions: [BACKUP-RESTORE.md](BACKUP-RESTORE.md).
