"""Temporary fake Drive and Brainamon server for check_phone_canvas_pair_browser: a synthetic license, the phone page
built with the development transport and that license's issuer only (tests/test_sync_loop_browser.py builds it the same
way), and the per-run credential below the check's temporary folder (its BRAINAMON_HOME)."""
import json
import os
import subprocess
import unittest
from pathlib import Path

import uvicorn

from core import app_paths, config, license
from library import drive_client
from server.app import create_app
from server.dev_drive import serve
from tests.license_fixture import activate


data = Path(os.environ['CM_DATA_DIR'])
local = data.parent
assert app_paths.LOCAL.is_relative_to(local), app_paths.LOCAL
cloud = local / 'cloud'
cloud.mkdir(parents=True, exist_ok=True)
activate(unittest.TestCase(), local)
script = """import {build} from 'vite'
  await build({configFile: 'vite.config.ts', logLevel: 'error',
    define: {'import.meta.env.DEV': 'true', __LICENSE_PUBLIC_KEYS__: process.argv[2]},
    build: {outDir: process.argv[1], emptyOutDir: true}})"""
subprocess.run(['node', '--input-type=module', '-e', script, str(local / 'web'), json.dumps(license.PUBLIC_KEYS)],
               cwd=Path(__file__).resolve().parents[1] / 'web', check=True, timeout=300)
serve(local / 'drive', port=18797)
base = 'http://127.0.0.1:18797'
drive_client.API = base + '/drive/v3'
drive_client.UPLOAD = base + '/upload/drive/v3'
drive_client.save_token(cloud / 'google_token.json', {'access_token': 'dev', 'refresh_token': 'dev', 'expires_at': 4e9})
config.google_client = lambda: ('dev', 'dev')
config.google_web_client = lambda: 'dev'
app = create_app(data_dir=data, cloud_dir=cloud, port=18799, web_dist=local / 'web')
uvicorn.run(app, host='127.0.0.1', port=18799, log_level='warning')
