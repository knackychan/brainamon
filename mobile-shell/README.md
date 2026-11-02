# Brainamon for Android (mobile-shell)

The phone page (`web/mobile.html`, `web/src/mobile/`) wrapped in a Capacitor 8 Android app.
Source setup and Windows contributor builds: [BUILDING.md](../docs/development/BUILDING.md).

**More > App info** shows the installed Android app's version and build number,
read directly from its package. It works offline; the browser page does not show
Android package information.

The app is the same page as the PWA. What it adds is native, in one plugin
(`android/app/src/main/java/app/brainamon/mobile/BrainamonPlugin.java`), used through
`web/src/mobile/native.ts`:

- **Secrets:** the pairing (mirror key, AI keys) and the Google token are encrypted with an
  Android Keystore key and kept in the app's private storage. The app's data is excluded from
  backups and device transfers.
- **Google Drive sign-in:** Google's Android authorization flow, scope `drive.appdata`. The app
  holds no client id: Google recognizes it by package name and signing key (below).
- **Pairing:** More > Scan reads the desktop's pairing QR with the Play services code scanner (no
  camera permission). Pasting the link works too.
- **Share sheet:** Brainamon appears in Android's share menu for text and links.
- **AI calls:** straight to Anthropic or OpenAI with the user's key. If the WebView's fetch is
  refused (CORS), the call is retried through native HTTP, which returns the whole answer instead
  of streaming it.

## Build

```sh
cd web && npm ci && npm run build          # the phone page
cd ../mobile-shell && npm ci && npm run sync   # copy it into android/ (scripts/www.mjs + cap sync)
cd android && ./gradlew assembleDebug      # needs JDK 21 and the Android SDK (or open android/ in Android Studio)
```

The APK lands in `android/app/build/outputs/apk/debug/`. Without an Android SDK, GitHub builds it:
the "Android app" workflow (`.github/workflows/android.yml`) runs on every push that touches the
phone page or the app and uploads `brainamon-debug-apk` as an artifact for 14 days.

`www/`, `android/app/src/main/assets/public/` and `node_modules/` are build output (gitignored).
The locked card files are copied from `design/card-designs/` byte for byte, never edited.
`py scripts/build_brand.py` (Windows, Edge) regenerates the launcher icons (legacy, round,
adaptive, monochrome) and splash screens from its embedded editable geometry, with the web icons.

## Signing and the Google sign-in client

Debug builds are named **Brainamon Contributor**, with application ID
`app.brainamon.mobile.contributor`. They use the SDK's locally generated debug
key. No shared repository keystore, official upload key or Google registration is
needed to compile. This is a separate installation, not an update over official
Play or historical debug installs; their local data stays in the old app.

Run `./gradlew signingReport` (Windows: `gradlew.bat signingReport`) to see the
actual debug key location and SHA-1/SHA-256. CI generates its own ephemeral key;
its certificate is not proof of official identity.

Optional Drive sign-in requires your own Google project, Drive API and Android
OAuth client registered for `app.brainamon.mobile.contributor` and your local key's
SHA-1. Use the same project for your desktop OAuth client: the hidden Drive folder
belongs to that project. Official Play keeps `app.brainamon.mobile` and its existing
Play signing/OAuth registration. No official signing trust is changed.

## Own-key release builds and official releases

For a local release build, create your own key outside the checkout using
`keytool -genkeypair` (it prompts for passwords). Set all six explicit variables
below in your build terminal, then run Gradle; do not use the official script to
create or locate the owner's key:

```powershell
$env:BRAINAMON_VERSION_NAME = '<your-version>'
$env:BRAINAMON_VERSION_CODE = '<positive-integer>'
$env:BRAINAMON_UPLOAD_KEYSTORE = 'C:\build-config\my-upload.jks'
$env:BRAINAMON_UPLOAD_KEY_ALIAS = '<your-alias>'
$env:BRAINAMON_UPLOAD_STORE_PASSWORD = '<your-password>'
$env:BRAINAMON_UPLOAD_KEY_PASSWORD = '<your-key-password>'
Push-Location mobile-shell/android
.\gradlew.bat bundleRelease assembleRelease --no-daemon
Pop-Location
```

These release tasks keep the official package ID. A build signed with your own
key cannot update an installed Play copy. Use the separate debug package for
side-by-side testing; own-key Drive sign-in needs registration of its own package
and certificate. Compiling does not establish binary-distribution clearance.

`py mobile-shell/scripts/release.py` remains the protected official build entry
point. Official releases are built in the release environment, with its existing
upload key kept outside source and CI.

The app is distributed only through Google Play. The script builds the phone page, signs
`dist/android/Brainamon-<version>.aab` (the Play upload) and a `.apk` (your own device tests only,
never given to users) with the upload key, runs the private-file gate and prints the certificate.
The version name is the desktop's (`core/version.py`); the version code is derived from it
(0.2.4 -> 2004), so every desktop version bump gives Play a higher number. Back up the key and its
passwords (Play can reset a lost upload key, slowly). Play re-signs its copy with the Play App
Signing key, so the test APK cannot install over a Play copy; Drive sign-in in the test APK needs
an optional Android OAuth client with the upload key's SHA-1. A debug APK cannot validate Play signing or release
OAuth; install a Play-delivered bundle on a device before publication.

When the PC changes the Drive copy in a way an older phone app would misread, raise `READER` in
both `library/mirror.py` and `web/src/mobile/source/mirror.ts` (a test keeps them equal) and ship
the phone app first: a phone whose app is older than the copy keeps its last copy and shows
"Update Brainamon on this phone".

## Try it without Google or AI keys

Debug builds allow plain http to the phone's own loopback, so the development stand-ins work over
USB:

```sh
py -m server.dev_drive --fake-ai --fake-dim 1536
adb reverse tcp:18765 tcp:18765 && adb reverse tcp:18766 tcp:18766
```

On the PC: Settings > Cloud > Upload to Google Drive, then Pair phone > Show pairing QR. In the
app: More > Scan. The stand-in Drive needs no sign-in.
