"""English catalog lookups for source-pin tests: once a phone screen's words move into web/src/lib/i18n/en/<area>.ts the
screen's source no longer holds them, so a test pins the wiring in the source and the English words here."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def english(key: str) -> str:
    """The English text of a plain (string) catalog entry, exactly as the phone shows it without a language choice."""
    area = key.split('.', 1)[0]
    text = (ROOT / 'web/src/lib/i18n/en' / f'{area}.ts').read_text(encoding='utf-8')
    found = re.search(r'^\s*"' + re.escape(key) + r'": ("(?:[^"\\]|\\.)*")', text, re.M)
    if not found:
        raise AssertionError(f'the English catalog has no plain entry {key}')
    return json.loads(found.group(1))
