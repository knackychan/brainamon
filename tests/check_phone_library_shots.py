"""Rule 9: every phone Library screenshot exists on both sides and has identical pixels."""
from pathlib import Path
import sys
from PIL import Image, ImageChops

before, after = (Path(p) for p in sys.argv[1:])
old = {p.name: p for p in before.glob('phone-*-library*.png')}
new = {p.name: p for p in after.glob('phone-*-library*.png')}
assert old and old.keys() == new.keys(), (sorted(old), sorted(new))
for name in sorted(old):
    with Image.open(old[name]) as a, Image.open(new[name]) as b:
        assert a.size == b.size, name
        assert ImageChops.difference(a.convert('RGB'), b.convert('RGB')).getbbox() is None, name
print(f'{len(old)} phone Library screenshots, all identical')
