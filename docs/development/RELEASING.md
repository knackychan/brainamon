# Releasing Brainamon source and official artifacts

Source publication, Windows artifact clearance and Android artifact clearance
are separate. A successful contributor build is development evidence, not an
official release. Keep existing releases, tags, asset IDs/URLs and website bytes.
Never import private history, retarget tags or replace old assets.

## Prepare the source

1. Reconcile public contributions through [EXPORT.md](EXPORT.md). Choose a clean
   committed implementation revision, review the exact manifest delta and close
   ownership/privacy/editable-input gates. Export into an independent public-only
   clone, preserving its website and deliberate README merge.
2. Choose an unused version, update core/version.py and CHANGELOG.md, and prepare
   source/license/support changes together. Do not claim new source matches old
   binaries. Old release terms remain unchanged.
3. Verify the complete manifest-only checkout with disposable data/config/profile
   paths and no owner credentials. Install exact declared dependencies, run
   frontend check/build, art/style regeneration checks, `scripts/security_tests.py
   --all`, explicit browser checks and contributor Windows/Android builds.
   Record failures/skips and their reasons. The excluded PHP-service and private
   Android-wrapper tests are not silently counted as passing public coverage.
4. Commit the reviewed public tree. Future official binaries must be built from
   this exact clean public commit. A source correction needs a new ordinary commit
   and rebuild, never a tag aimed at a different tree from the build input.

## Official artifacts

Official Windows builds use the protected release environment and existing update
key. Run `py packaging/build.py --release --installer` with its explicit official
OAuth/signing configuration. The gate requires the official channel marker,
trusted signed update manifest, extracted installer/expanded-file equivalence,
private-file scan and dependency report. Authenticode is separate and optional;
`--sign` requires its configured certificate. No keys belong in source or CI.

Preserve the stable updater's exact installer/sidecar names:
`Brainamon-Setup-X.Y.Z.exe`, `.exe.sha256`, `.exe.update.json`. The signed manifest
binds repository, version, name, size and SHA-256. Never sign a contributor build
as an official update. Contributor installers have their own identity and cannot
auto-install official updates.

Android official release tasks keep `app.brainamon.mobile` and existing upload/Play
signing trust. The protected `mobile-shell/scripts/release.py` remains the official
build entry point; own-key Gradle instructions are in
[mobile-shell/README.md](../../mobile-shell/README.md). Google artifact compatibility
and exact native payload/notices/source obligations must be cleared before GPL
Android binary distribution. A debug APK does not prove Play OAuth/signing or
physical-device behavior. Do not remove Drive/scanning or invent an SDK exception
to declare this gate passed.

CI compiles and scans the debug APK but uploads no APK by default. The repository
variable `ANDROID_BINARY_DISTRIBUTION_CLEARED` must remain unset/false while
Android distribution is held. Set it to `true` only after that exact binary's
licensing/source obligations and device gates are cleared; a source-only push
must not trigger binary distribution as a side effect.

Before distributing any binary, inventory its exact payload and license graph,
provide required corresponding source/notices and installation/rebuild materials,
and demonstrate LGPL library modification/replacement. Verify clean Windows
install/update/uninstall and the intended phone/PC/recovery/rotation matrix on
disposable profiles/devices. Record exact public source commit and artifact hashes.

## Publish only the prepared result

Prepare release notes, source archives, passed/open gates, public diff/commit and
the preservation comparison for the owner's publication authorization. Publication
is separate from local preparation. Do not push, create a remote tag/release or
upload assets before that authorization identifies the concrete result.

Then push only the ordinary public commits and new tag, and publish only the
cleared source/artifacts. Preserve historical downloads and Pages. Verify the
public tag equals the build commit, downloadable hashes/signatures, source
availability and website/tag/release preservation. Correct errors with a new
ordinary commit/version rather than rewriting old published history.

A source-only proposal must explicitly list held binaries. Do not accidentally
displace the stable installer update feed with a release that lacks its cleared
installer assets. Coordinate a phone-first rollout when a reader-incompatible
mirror format changes; v2 access is additive alongside legacy v1, not a mirror
reader-format change.
