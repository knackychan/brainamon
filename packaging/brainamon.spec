# PyInstaller spec: one-folder build of Brainamon (V6 server + pywebview window).
# Build with packaging/build.py, not directly (it builds web/dist first and pins the versions).
# Entry: launch.pyw (windowless; logs to %LOCALAPPDATA%\Brainamon\error_log.txt when frozen).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from core.version import __version__
from core import build_channel

CHANNEL = build_channel.read(ROOT / 'build')
if CHANNEL not in ('official', 'contributor'):
    raise RuntimeError('Run packaging/build.py to select the build channel explicitly.')
APP_NAME = build_channel.DISPLAY_NAMES[CHANNEL]
OUTPUT_FOLDER = build_channel.HOME_NAMES[CHANNEL]

# The exe's version resource: Windows names the app in Settings > Taskbar > Other system tray icons (and
# Task Manager) from FileDescription, and an exe without one shows up under its file name only.
_v = (*map(int, __version__.split('.')), 0)
VERSION_FILE = ROOT / 'build' / 'version_info.txt'
VERSION_FILE.parent.mkdir(exist_ok=True)
VERSION_FILE.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={_v}, prodvers={_v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('InternalName', '{OUTPUT_FOLDER}'),
      StringStruct('OriginalFilename', '{OUTPUT_FOLDER}.exe'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ])
""", encoding='utf-8')

datas = [
    (str(ROOT / 'build' / 'google-oauth.json'), '.'),
    (str(ROOT / 'build' / build_channel.FILENAME), '.'),
    (str(ROOT / 'web' / 'dist'), 'web/dist'),
    (str(ROOT / 'knowledge' / 'prompts'), 'knowledge/prompts'),        # Ask Quick / Synthesize prompts (knowledge/prompt_files.py)
]
# The /cards runtime needs these four files, never design specimens or thumbnails.
datas += [(str(ROOT / 'design' / 'card-designs' / name), 'design/card-designs')
          for name in ('cards.css', 'engine.js')]
datas += [(str(ROOT / 'design' / 'card-designs' / 'full-art-v2' / name), 'design/card-designs/full-art-v2')
          for name in ('fa2.css', 'fa2.js')]
# Only versioned workers and JS assets: no scrape CSVs, browser state or optional runtime payload.
datas += [(str(p), 'scrapers') for p in sorted((ROOT / 'scrapers').glob('*.js'))]
datas += [(str(ROOT / 'scrapers' / name), 'scrapers') for name in
          ('fb_saved_playwright.py', 'ig_saved_playwright.py', 'reddit_saved_playwright.py')]
datas += [(str(ROOT / 'packaging' / 'requirements-scraper.txt'), 'packaging')]
datas += [(str(ROOT / 'LICENSE'), '.'), (str(ROOT / 'THIRD_PARTY_NOTICES.md'), '.')]
# IANA timezone data so ZoneInfo resolves named zones in the frozen build (no host zoneinfo).
datas += collect_data_files('tzdata')
# ffmpeg, ffprobe and yt-dlp are not bundled (the user installs them; Settings > Tools). Never a cookies file either.
hiddenimports = (collect_submodules('server') + collect_submodules('core') + collect_submodules('library') +
                 collect_submodules('knowledge') + collect_submodules('desktop') +
                 ['tzdata'] + collect_submodules('tzdata')) + ['webview.platforms.edgechromium', 'pystray._win32']
# The local MCP server for Wiskit's Claude Code mode: Brainamon.exe --mcp (launch.pyw) runs mcp_local over stdio.
hiddenimports += collect_submodules('mcp_local') + collect_submodules('mcp', filter=lambda m: not m.startswith('mcp.cli'))

# Retired or optional heavy modules stay out of the build (BRAINSTORM D1): local transcription,
# the Playwright scraper, the OpenCV frame fallback (ffmpeg is the default path), the old Qt app.
excludes = ['PyQt6', 'PyQt5', 'PySide6', 'whisper', 'torch', 'speech_recognition', 'playwright', 'cv2',
            'matplotlib', 'pytest']

a = Analysis(
    [str(ROOT / 'launch.pyw')],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=OUTPUT_FOLDER,
    console=False,
    upx=False,
    version=str(VERSION_FILE),
    icon=str(ROOT / 'packaging' / 'brainamon.ico'),   # projects/brainamon-logo/build.py
)
coll = COLLECT(exe, a.binaries, a.datas, name=OUTPUT_FOLDER, upx=False)
