"""`py -m server`: run the V6 backend on 127.0.0.1 (no window). The window launcher is
server/desktop.py (plan 13)."""
import uvicorn

from core import config
from server import settings
from server.app import create_app


def main():
    config.load_env()
    uvicorn.run(create_app(), host=settings.HOST, port=settings.PORT, log_level='warning')


if __name__ == '__main__':
    main()
