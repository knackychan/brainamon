# Build Brainamon from source

The GPL source release is in preparation. These commands describe the implemented
source and contributor build modes. Release publication and native/device
clearance are separate steps.

Prerequisites: Python 3.14, Node 22 satisfying web/package.json's engine range,
and Microsoft Edge WebView2 for the Windows desktop window. Use your own API
credentials only when enabling optional integrations. An empty configuration
can run the local library without cloud credentials.

In PowerShell from a prepared checkout:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix web ci
npm --prefix web run check
npm --prefix web run build
$taskHome = Join-Path $env:TEMP ([guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $taskHome | Out-Null
$env:BRAINAMON_HOME = $taskHome
$env:CM_DATA_DIR = Join-Path $taskHome 'data'
.\.venv\Scripts\python.exe -m server.desktop
```

The disposable paths keep this run separate from an installed app and existing
library. Run `-m server` instead for the backend, or `-m mcp_local` for the stdio
MCP server. On a non-Windows host use a local Python virtual environment and
requirements-remote.txt for backend/tests; native desktop features require
Windows. Do not copy another checkout's local directory, environment, browser
profiles, build products or signing keys.

Editable art and style regeneration commands are in
[assets-source/README.md](../../assets-source/README.md). They do not require the
private design documents. Wiskit and style checks can run without changing output:

```powershell
node web/scripts/export_wiskit.mjs --check
.\.venv\Scripts\python.exe web/scripts/extract_v6_css.py --check
```

For isolated synthetic regressions:

```powershell
.\.venv\Scripts\python.exe scripts/security_tests.py tests.test_export_public tests.test_public_test_inputs tests.test_sync tests.test_vault_sync_pc tests.test_cloud_isolation
```

Browser checks additionally require test-only Playwright with Chromium:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe tests/check_settings_cloud_browser.py
```

They create synthetic libraries, profiles and screenshot output in temporary
folders. The script prints its screenshot folder. Use web/dist from this checkout.
The PHP activation service's internal tests and private Windows Android wrapper
tests are deliberately excluded from the public manifest. Synthetic activation
client tests remain; actual npm/Gradle builds must verify Android independently.

## Windows contributor build

Install Inno Setup 6 to build an installer, then run:

```powershell
.\.venv\Scripts\python.exe packaging/build.py --contributor --installer
```

The output is `dist/Brainamon-Contributor/Brainamon-Contributor.exe` and
`dist/installer/Brainamon-Contributor-Setup-<version>.exe`. The installer has a
separate AppId, install directory, shortcuts, autostart value and executable. Its
default data/settings home is `%LOCALAPPDATA%\Brainamon-Contributor`, with local
port 18767. It does not discover official/legacy data homes or install official
updates. An unmarked frozen build uses an unverified identity and is also denied
official updates. Explicit BRAINAMON_HOME/CM_DATA_DIR/CM_PORT overrides still let
you choose disposable test locations; do not select an official app's live data.

Contributor mode ignores ambient application credentials, project .env and
official signers. It builds without an OAuth registration by default. Optional
`--contributor-oauth C:\build-config\google-oauth.json` accepts only your own
explicit app-registration object, outside the checkout:

```json
{
  "BRAINAMON_GOOGLE_CLIENT_ID": "your-desktop-client-id",
  "BRAINAMON_GOOGLE_CLIENT_SECRET": "your-desktop-client-secret",
  "BRAINAMON_GOOGLE_WEB_CLIENT_ID": "your-web-client-id-or-empty"
}
```

This registration enables optional Google integration; it contains no library
keys or personal Google tokens. It is embedded in your build. Without it the
local library works and Drive requires your own setup. The build emits a channel
marker and payload/checksum evidence, never an official signed .update.json.
`--contributor` cannot be combined with `--release` or `--sign`. Official release
builds retain their existing OAuth/key checks and require an official marker at
the final release gate.

## Android contributor build

Android prerequisites are JDK 21 and SDK 36 (minimum device API 24). After building
web/dist:

```powershell
npm --prefix mobile-shell ci
npm --prefix mobile-shell run sync
Push-Location mobile-shell/android
.\gradlew.bat assembleDebug --no-daemon
.\gradlew.bat signingReport
Pop-Location
```

Debug installs as **Brainamon Contributor**, package
`app.brainamon.mobile.contributor`, with the SDK's own local debug key. No
repository keystore or release key is needed. It cannot update official Play or
historical debug installations. For optional Drive integration, register that
package and the signingReport SHA-1 in your own Google project, shared with your
desktop registration. [mobile-shell/README.md](../../mobile-shell/README.md) covers
own-key Gradle release commands; the official release script remains protected.

The Gradle 8.14.3 distribution checksum is pinned, the wrapper JAR was matched to
Gradle's published checksum, and CI uses pinned action commits with wrapper
validation and the final APK payload guard. See
[Gradle wrapper verification](https://docs.gradle.org/current/userguide/gradle_wrapper.html#sec:verification).
Source-only, Windows binary and Android binary clearance remain separate release
gates. A local native build does not establish Play signing, device compatibility
or GPL Android binary-distribution clearance.
CI artifact upload is disabled by default while that distribution gate is open;
local compilation does not enable it.
