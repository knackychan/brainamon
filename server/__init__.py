"""CM-OS V6 backend: a FastAPI app over the existing Qt-free modules (db, search, ...).

Bound to 127.0.0.1 only (server/settings.py HOST). See projects/desktop-cmos/PLAN.md.
"""
import os

# numpy's OpenBLAS commits a buffer per thread, one thread per logical core: on a 32-thread CPU the
# first smart search took the server from 80 MB to 903 MB private. The vectors here are one query
# against a few thousand rows, so one thread is as fast. Must run before numpy is first imported.
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
