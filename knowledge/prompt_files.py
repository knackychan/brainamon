"""The shared prompt files in knowledge/prompts/ (projects/mobile-app/PLAN.md Phase 5, step 1).

Ask Quick (ask_core.py) and Synthesize (synth.py) read their prompt texts and limits from JSON
files that the phone's TypeScript ports (web/src/mobile/ai/) import too, so both sides send the
same prompts. Placeholders are {name}; `fill` replaces the names it is given in one pass (a
value is never scanned again, so a question that contains "{topic}" stays as typed).
Installed builds ship the folder as data (packaging/brainamon.spec)."""
import json
import re
from functools import lru_cache

from core import app_paths

DIR = app_paths.BUNDLE / 'knowledge' / 'prompts'


@lru_cache(maxsize=None)
def load(name: str) -> dict:
    return json.loads((DIR / f'{name}.json').read_text(encoding='utf-8'))


def fill(template: str, **values) -> str:
    return re.sub(r'\{(\w+)\}', lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)


def phone_ai() -> dict:
    """The AI settings a phone with no PC uses (projects/mobile-app/plans/08-phone-solo.md): what the
    mirror's library/meta.json `ai` carries, with the default Synthesize choice. Bundled into the
    phone page as phone_ai.json so model ids still come from core/ai_client.py; tests check the file
    matches (rewrite it with `py -m knowledge.prompt_files`)."""
    from core import ai_client
    return ai_client.phone_settings(ai_client.ASK_PROVIDER_ANTHROPIC, ai_client.CLAUDE_MODEL)


if __name__ == '__main__':
    (DIR / 'phone_ai.json').write_text(json.dumps(phone_ai(), indent=2) + '\n', encoding='utf-8')
    print('wrote', DIR / 'phone_ai.json')
