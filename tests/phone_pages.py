"""Settings hub/page navigation shared by synthetic browser checks."""
import re
import json
from pathlib import Path

from playwright.sync_api import expect


def group(page, title):
    """Find a hub row, or the titled card on Backup & phones."""
    heading = page.locator('.m-card-head h3', has_text=re.compile('^' + re.escape(title) + '$'))
    card = page.locator('.m-card-section').filter(has=heading)
    if card.count():
        return card
    name = page.locator('.m-group-words > b', has_text=re.compile('^' + re.escape(title) + '$'))
    return page.locator('.m-group').filter(has=name)


def open_page(page, title):
    expect(page.locator('#m-startup')).to_have_count(0)
    routes = {'Obsidian': 'more/obsidian'}
    keys = {'shell.sync.title':'more/sync', 'settings.group.ai':'more/wiskit',
            'settings.group.storage':'more/storage', 'settings.group.look':'more/look',
            'settings.group.about':'more/about', 'backup.group.title':'backup',
            'settings.group.phone':'backup', 'settings.group.pc':'backup',
            'backup.group.account':'backup', 'backup.group.thisPhone':'backup', 'recovery.group.title':'backup'}
    for language in ('en', 'fr', 'zh-Hant'):
        for key, route in keys.items():
            catalog = Path(__file__).resolve().parents[1] / 'web/src/lib/i18n' / language / (key.split('.')[0] + '.ts')
            text = catalog.read_text(encoding='utf-8')
            value = re.search(r'^\s*"' + re.escape(key) + r'": ("(?:[^"\\]|\\.)*")', text, re.M)
            routes[json.loads(value.group(1))] = route
    route = '#/' + routes[title]
    if page.url.split('#')[-1] != route[1:]:
        link = page.locator(f'a[href="{route}"]')
        if link.count() and link.first.is_visible():
            link.first.click()
        else:
            page.evaluate('(hash) => location.hash = hash', route)
    expect(page).to_have_url(re.compile(re.escape(route) + '$'))
    if route.startswith('#/more/'):
        expect(page.locator('.m-page:visible h1')).to_have_text(title)
    else:
        expect(page.locator('#m-backup-status')).to_be_visible()
    box = group(page, title) if route == '#/backup' and title in routes else page.locator('.m-page:visible')
    if not box.count():
        box = page.locator('.m-page:visible')
    expect(box).to_be_visible()
    box.locator('details.m-more-foot').evaluate_all('(nodes) => nodes.forEach(node => node.open = true)')
    return box


# Existing checks keep their concise calls; opening a group now means opening its page/card.
open_group = open_page


def row_line(page, title):
    box = group(page, title)
    return box.locator('.m-card-line') if box.locator('.m-card-line').count() else box.locator('.m-group-words > small')
