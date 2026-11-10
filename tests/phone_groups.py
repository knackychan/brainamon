"""The group rows of the phone's Settings and Backup & phones (web/src/mobile/ui/MGroup.svelte, projects/phone-settings)
for the browser checks: a check opens the group that holds what it clicks or reads, then works inside it as before."""
import re

from playwright.sync_api import expect


def group(page, title):
    """The group whose row is called `title` on the current page (its box: .m-box.m-group, id and all)."""
    name = page.locator('.m-group-words > b', has_text=re.compile('^' + re.escape(title) + '$'))
    return page.locator('.m-group').filter(has=name)


def open_group(page, title):
    """Open the group `title` (one tap on its row; nothing when it is open already) and return its box."""
    box = group(page, title)
    row = box.locator('button.m-group-row')
    expect(row).to_have_count(1)
    if row.get_attribute('aria-expanded') != 'true':
        row.click()
    expect(row).to_have_attribute('aria-expanded', 'true')
    return box


def row_line(page, title):
    """The state line of the row `title` (its small text)."""
    return group(page, title).locator('.m-group-words > small')
