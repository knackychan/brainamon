"""Thumbnail tints: one colour per item for the Library map strip (GET /api/tints).

The average colour of each `data/items/<id>/thumb.jpg`, computed once by a daemon thread started
in the server lifespan and kept in memory only (no new data path). File reads only, no SQLite.
Items without a thumbnail are left out; the map draws them in their collection colour.
"""
import threading
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter()


class Tints:
    def __init__(self, items_dir: Path):
        self.items_dir = Path(items_dir)
        self.tints: dict[str, str] = {}
        self.ready = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name='cm-tints', daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            dirs = [d for d in self.items_dir.iterdir() if d.name.isdigit()] if self.items_dir.is_dir() else []
            for d in dirs:
                self.refresh(int(d.name))
        finally:
            self.ready = True

    def refresh(self, item_id: int) -> None:
        """(Re)compute one item's tint, e.g. after its thumbnail changed."""
        c = tint_of(self.items_dir / str(item_id) / 'thumb.jpg')
        if c:
            self.tints[str(item_id)] = c
        else:
            self.tints.pop(str(item_id), None)


def tint_of(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.draft('RGB', (32, 32))          # JPEG: decode at a small scale, much faster
            r, g, b = im.convert('RGB').resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    except Exception:
        return None
    return f'#{r:02x}{g:02x}{b:02x}'


@router.get('/api/tints')
def tints(request: Request):
    t: Tints = request.app.state.tints
    return {'ready': t.ready, 'tints': dict(t.tints)}
