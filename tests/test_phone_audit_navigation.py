"""Exercise the actual phone navigation callbacks with non-parent browser history."""
import json
import unittest
from pathlib import Path

from tests.test_phone_js import node, TS_RESOLVE

ROOT = Path(__file__).resolve().parents[1]


class BackupNavigation(unittest.TestCase):
    def test_shared_content_leaves_import_for_the_add_editor(self):
        result = json.loads(node(TS_RESOLVE + r"""
            import fs from 'node:fs'
            const src = fs.readFileSync('web/src/mobile/Mobile.svelte', 'utf8').replace(/\r\n/g, '\n')
            const callback = src.match(/const toAdd = (\(\) => \{[\s\S]*?\n  \})/)[1]
            const results = []
            for (const [route, hash] of [[{ tab: 'cap', imp: true }, '#/import'], [{ tab: 'cap' }, '#/cap'], [{ tab: 'lib' }, '#/lib']]) {
                const location = { hash }
                new Function('phone', 'location', 'isCompose', 'sharedToAdd', 'return (' + callback + ')')({ route }, location, r => r.tab === 'cap' && !r.imp, () => {})()
                results.push(location.hash)
            }
            console.log(JSON.stringify(results))
        """))
        self.assertEqual(result, ['#/cap', '#/cap', '#/cap'])

    def test_header_back_uses_the_backup_screen_parents(self):
        # the round Back of Settings, Backup & phones and Recover (PageKeys.svelte, projects/phone-settings spec 5.1):
        # one page back while the page behind is this app's, else the parent
        result = json.loads(node(TS_RESOLVE + r"""
            const { pageBack } = await import('./web/src/mobile/back.ts')
            const routes = [{ tab: 'more', backup: true }, { tab: 'more', recover: true }, { tab: 'more' }, { tab: 'more', group: 'look' }, { tab: 'more', backup: true, manage: true }]
            console.log(JSON.stringify([routes.map(r => pageBack(r, false)), routes.map(r => pageBack(r, true))]))
        """))
        self.assertEqual(result, [['#/more', '#/backup', '#/lib', '#/more', '#/backup'], ['', '', '', '', '']])
        keys = (ROOT / 'web/src/mobile/PageKeys.svelte').read_text(encoding='utf-8')
        self.assertIn('function leave() { const to = pageBack(r, inAppBehind()); if (to) go(to, true); else back() }', keys)

    def test_pairing_link_in_the_open_tab_restarts_the_startup_parser(self):
        result = json.loads(node(TS_RESOLVE + r"""
            import fs from 'node:fs'
            const src = fs.readFileSync('web/src/mobile/state.svelte.ts', 'utf8').replace(/\r\n/g, '\n')
            const callback = src.match(/window.addEventListener\('hashchange', (\(\) => \{[\s\S]*?\})\)/)[1]
            const calls = [], phone = { route: { tab: 'more', backup: true } }
            const location = { hash: '#pair=synthetic-code', reload: () => calls.push('reload') }
            new Function('phone', 'location', 'parseRoute', 'return (' + callback + ')')(
              phone, location, () => { calls.push('ignored pairing'); return { tab: 'lib' } })()
            console.log(JSON.stringify(calls))
        """))
        self.assertEqual(result, ['reload'])
