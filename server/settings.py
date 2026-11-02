"""Paths and network constants for the V6 backend.

HOST is fixed to 127.0.0.1; local token/origin checks remain required. Never bind
0.0.0.0, '' or a LAN address, and never read HOST from the environment or a setting.
"""
import os

from core import app_paths

REPO = app_paths.BUNDLE          # read-only assets: the repo from source, sys._MEIPASS installed
HOME = app_paths.HOME            # writable app files (error_log.txt): the repo, or %LOCALAPPDATA%\Brainamon
HOST = '127.0.0.1'
PORT = int(os.environ.get('CM_PORT', app_paths.DEFAULT_PORT))
DATA_DIR = app_paths.data_dir()
DB_NAME = 'content_manager.db'
WEB_DIST = REPO / 'web' / 'dist'
CARDS_DIR = REPO / 'design' / 'card-designs'
CLOUD_DIR = app_paths.LOCAL / 'cloud'     # Upload to Google Drive: the sign-in token and the mirror key (server/sync.py)
