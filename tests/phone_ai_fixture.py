"""The library the phone's AI ports are checked against (tests/test_phone_ai.py): items, reports,
notes and fake embeddings from tests/fixtures/phone_ai_library.json, in a real Database."""
import hashlib
import json
from pathlib import Path

import numpy as np

from core.db import Database

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'phone_ai_library.json'
DIM = 64


def fake_vec(text: str) -> list:
    """A stand-in embedding: words hashed into DIM buckets, so texts sharing words point the same way."""
    v = np.zeros(DIM, dtype=np.float32)
    for w in text.lower().split():
        h = hashlib.sha256(w.encode('utf-8')).digest()
        v[h[0] % DIM] += 1.0 + h[1] / 255
        v[h[2] % DIM] -= h[3] / 512
    return v.tolist()


def load() -> dict:
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def build(data_dir: Path, model: str = 'text-embedding-3-small') -> Database:
    fx = load()
    db = Database(Path(data_dir) / 'content_manager.db')
    for it in fx['items']:
        tmp = db.add_item({k: v for k, v in it.items() if k not in ('id', 'transcript', 'report')})
        db.conn.execute('UPDATE items SET id = ? WHERE id = ?', (it['id'], tmp))
        db.conn.commit()
        if it.get('transcript'):
            db.update_item(it['id'], {'transcript': it['transcript']})
        if it.get('report'):
            d = db.items_dir / str(it['id'])
            d.mkdir(parents=True, exist_ok=True)
            (d / 'report.md').write_text(it['report'], encoding='utf-8')
        text = ' '.join(it.get(k) or '' for k in ('description', 'ai_desc', 'tags', 'creator'))
        vec = np.asarray(fake_vec(text), dtype=np.float32)
        db.upsert_embedding(it['id'], model, DIM, 'h', vec.tobytes())
    db.notes_dir.mkdir(parents=True, exist_ok=True)
    for n in fx['notes']:
        (db.notes_dir / n['file']).write_text(n['text'], encoding='utf-8')
    db.reindex_notes()
    return db
