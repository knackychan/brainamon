"""
canvas.py — Data layer for canvases (moodboards).
Each canvas is a JSON file in data/canvases/.
Complete canvas files are authoritative; legacy index.json is ignored.
"""

import json, os, tempfile, time, uuid
from pathlib import Path


def canvas_entries(canvas_dir: Path) -> list:
    """Read-only listing shared by the store, model tools and name validation."""
    entries = []
    for path in Path(canvas_dir).glob('*.json'):
        if path.name == 'index.json':
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get('id') != path.stem:
            continue
        entries.append({k: data.get(k, 0 if k in ('created', 'modified') else '')
                        for k in ('id', 'name', 'created', 'modified')})
        entries[-1]['item_count'] = len(data.get('items', []))
    return sorted(entries, key=lambda c: c['modified'], reverse=True)


class CanvasStore:
    """Manages all canvases stored as JSON files."""

    def __init__(self, data_dir: Path):
        self.canvas_dir = Path(data_dir) / 'canvases'
        self.canvas_dir.mkdir(parents=True, exist_ok=True)
        # Folder for images uploaded directly to a canvas (source = file)
        self.uploads_dir = self.canvas_dir / 'uploads'
        self.uploads_dir.mkdir(exist_ok=True)

    def list_canvases(self) -> list:
        """Derive metadata from published snapshots, never from a second commit."""
        return canvas_entries(self.canvas_dir)

    # ── CRUD ─────────────────────────────────────────────────────────────
    def create_canvas(self, name: str) -> str:
        canvas_id = uuid.uuid4().hex[:12]
        now = int(time.time() * 1000)
        data = {
            'id': canvas_id,
            'name': name or 'Untitled Canvas',
            'created': now,
            'modified': now,
            'items': [],
        }
        self.save_canvas(data)
        return canvas_id

    def load_canvas(self, canvas_id: str) -> dict:
        path = self.canvas_dir / f'{canvas_id}.json'
        if not path.exists():
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def save_canvas(self, data: dict):
        """Publish a complete canvas snapshot; listings derive its metadata."""
        canvas_id = data['id']
        data['modified'] = int(time.time() * 1000)
        self._write_canvas(canvas_id, data)

    def _write_canvas(self, canvas_id: str, data: dict):
        # The sole commit point is replacement of a complete, closed staging file.
        raw = json.dumps(data, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=self.canvas_dir, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.canvas_dir / f'{canvas_id}.json')
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)  # Only an unpublished staging file, never a canvas.

    def rename_canvas(self, canvas_id: str, new_name: str):
        data = self.load_canvas(canvas_id)
        if data:
            data['name'] = new_name
            self.save_canvas(data)

    def delete_canvas(self, canvas_id: str):
        path = self.canvas_dir / f'{canvas_id}.json'
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass

    # ── Uploaded images ──────────────────────────────────────────────────
    def save_uploaded_image(self, src_path: str) -> str:
        """Copy an uploaded image into the uploads folder. Returns relative filename."""
        from PIL import Image
        src = Path(src_path)
        if not src.exists():
            return ''
        fname = f'{uuid.uuid4().hex[:12]}.jpg'
        dest = self.uploads_dir / fname
        try:
            img = Image.open(str(src)).convert('RGB')
            # Cap very large uploads
            img.thumbnail((1200, 1200))
            img.save(str(dest), 'JPEG', quality=85)
            return fname
        except Exception:
            dest.unlink(missing_ok=True)
            return ''

    def upload_path(self, filename: str) -> Path:
        return self.uploads_dir / filename
