# Testing the legacy receipt format

Current Brainamon features do not require a generated license. This document is
for maintaining compatibility with older phone apps and testing the receipt
parser. See [LICENSING.md](LICENSING.md) for current phone access.

Legacy keys have the form `BRAINAMON1.<base64url JSON>.<Ed25519 signature>`. The
bounded JSON contains the legacy cloud edition, ID, holder, optional email, issue
date and no expiry. It is signed, not encrypted, so never put secrets in it.
Only issuer public verifiers are part of the application.

The owner's existing issuer/private hosted activation service stays outside the
public source and contributor build. Do not generate a replacement official
issuer, replace the pinned verifier or include a private key to make a build pass.
Contributor builds do not need an issuer, customer receipt or activation service.

The public synthetic tests generate disposable test issuers and patch their
verifiers only inside temporary fixtures:

```powershell
py scripts/security_tests.py tests.test_license tests.test_license_activation tests.test_server_license tests.test_access_v2 tests.test_licensed_sync
```

They test tampering, unknown issuers, bounded parsing, atomic replacement, explicit
mock-service exchange, legacy v1 signatures and payment-independent v2 access.
They do not contact Gumroad or the owner's service, read production keys or modify
real libraries. PHP service internals are intentionally absent from the public
test set; the activation client retains its synthetic protocol coverage.
