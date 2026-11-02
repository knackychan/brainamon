"""Build identity without importing runtime paths, settings or credentials."""
import json
from pathlib import Path

FILENAME = 'build-channel.json'
HOME_NAMES = {'official': 'Brainamon', 'source': 'Brainamon',
              'contributor': 'Brainamon-Contributor', 'unverified': 'Brainamon-Unverified'}
DISPLAY_NAMES = {'official': 'Brainamon', 'source': 'Brainamon',
                 'contributor': 'Brainamon Contributor', 'unverified': 'Brainamon Unverified'}


def read(bundle):
    try:
        value = json.loads((Path(bundle) / FILENAME).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return 'unverified'
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Invalid build-channel marker') from exc
    if not isinstance(value, dict) or set(value) != {'channel'} or value['channel'] not in ('official', 'contributor'):
        raise ValueError('Invalid build-channel marker')
    return value['channel']
