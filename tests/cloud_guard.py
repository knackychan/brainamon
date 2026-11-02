"""No test may reach the user's cloud folder (`local/cloud/`: the Google token, the mirror key, a pending removal).

`server.settings.CLOUD_DIR` is the default of `create_app(cloud_dir=None)`. For the whole test run it points at a throwaway
folder, so a test app (or any helper) built without an explicit `cloud_dir` works in an empty one. Imported by
`tests/__init__.py`, which every `tests.*` import runs first, and by the modules that build apps or services themselves.
"""
import atexit
import shutil
import tempfile
from pathlib import Path

from server import settings

REAL = Path(settings.CLOUD_DIR)         # what the user's app uses; never written by a test
FOLDER = Path(tempfile.mkdtemp(prefix='cm-test-cloud-'))
settings.CLOUD_DIR = FOLDER
atexit.register(shutil.rmtree, FOLDER, True)
