# Software license, phone access and older receipts

Brainamon's application-owned source and assets are copyright 2026 Frederic TOMAS,
licensed under **GPL-3.0-only**. The full unmodified license is at [LICENSE](../../LICENSE).
Contributions use the same license; third-party components keep the terms and
notices in [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
Historical releases retain their original terms. New source does not establish
an exact match for historical binaries.

## Current features

No purchase, activation or receipt is required for current desktop or phone
features. Your selected AI provider can charge for requests made with your keys.
Google integration, optional tools, trusted pairing and an available PC remain
separate setup requirements. Installing source does not supply provider accounts.

## A paired phone's access

The library mirror is encrypted under its own key. Explicit trusted pairing
gives the phone that key and the PC's P-256 public verifier. The private control
signer stays in protected local PC storage and is never application source.

The PC publishes an encrypted `control/access-v2.json`. Its signed JSON body has
exactly v=2, fp, issued, expires and enabled. The lifetime is at most one hour;
the running, signed-in PC normally renews it every five minutes. Each paired
Drive content request and retry verifies the current record against the key from
pairing. No verifier supplied by a Drive record can authorize itself.

Invalid signatures, wrong fingerprints, disabled/expired/malformed/duplicate
records and incomplete listings refuse access. A valid v2 confirmation must be
recorded durably in the phone's protected pairing before access is returned.
After that, deleting v2 cannot downgrade the pairing to v1. Scanning the same QR
again retains this bound for the same library key and signer.

Remove all phones rotates the mirror key and removes both old control records.
An already offline phone can retain its last grant until its expiry, at most one
hour after renewal. Saved local content and queued edits stay on that phone.
Google/account, recovery ownership/epoch, unpair/rotation, local request tokens,
Writer serialization and stopped-worker checks remain in force. Financial support
does not change these controls or turn a saved sync switch on.

## Legacy receipts and older phones

The PC also publishes the unchanged `control/license-v1.json` for older phone
apps. It embeds a real issuer-signed `BRAINAMON1` receipt when a valid one is saved.
No synthetic paid receipt is issued. New phones accept v1 only when a complete,
authenticated Drive lookup establishes v2 is absent and that pairing has never
successfully adopted v2. Bad v2 never falls back.

An old phone app with a valid legacy receipt can keep using v1. A PC with no
receipt cannot make an old phone app payment-independent; update the phone.
Old PC software may likewise need updating. Current apps require no receipt.

Settings > General > Support contains an optional **Legacy receipt for an older
phone app** disclosure. Saving a Gumroad receipt key explicitly calls the legacy
activation service once, then stores a verified Brainamon key locally, outside
the library. It does not perform checkout. Status and removal stay local. No
receipt exchange runs at startup. Removing it does not stop current sync, rotate
keys, unpair phones, discard queued edits or change backup/vault switches. Old
phones still relying on v1 need an upgrade when its receipt is no longer renewed.

The bounded, locally authenticated legacy API remains `GET /api/license`,
`PUT /api/license` with a key, and `DELETE /api/license`. An invalid replacement
preserves the existing receipt; responses never return the full key.

## Distinct keys

- The paired-PC P-256 key authenticates short-lived phone access for one library.
- Legacy issuer Ed25519 keys verify old receipts, not current feature availability.
- The official update Ed25519 verifier authenticates official Windows installers.
- Android upload/Play and optional Windows publisher certificates are separate.

Contributor builds need none of the owner's private keys. They use their own
debug/optional signing credentials and a separate installation identity, with
official updates disabled. See [BUILDING.md](BUILDING.md),
[UPDATES.md](UPDATES.md) and [legacy format testing](LICENSE-GENERATION.md).
