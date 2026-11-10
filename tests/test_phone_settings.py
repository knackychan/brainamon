"""projects/phone-settings (spec docs/superpowers/specs/2026-11-07-phone-settings-design.md): the state lines of
Settings and Backup & phones (web/src/mobile/settings-lines.ts, run by Node), and the page pieces read as text: the
top keys on each page, the group rows, one orange key, the link into a group. No browser, no network."""
import json
import re
import unittest
from pathlib import Path

from tests import test_phone_js
from tests.phone_catalog import english

ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / 'web/src/mobile'


def source(rel):
    return (MOBILE / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


LINES = """
import * as L from './web/src/mobile/settings-lines.ts'
const st = (id, tone, action = null) => ({ id, tone, action: action ? { id: action } : null })
const out = {
  sync: [L.syncLine({ signedIn: false, lamp: 'idle', wifiOnly: true }), L.syncLine({ signedIn: true, lamp: 'idle', wifiOnly: true }),
         L.syncLine({ signedIn: true, lamp: 'idle', wifiOnly: false }), L.syncLine({ signedIn: true, lamp: '1 running · 1 queued', wifiOnly: true })],
  phone: [L.phoneLine(true, 'ab12'), L.phoneLine(false, 'ab12')],
  ai: [L.aiLine('OpenAI', true), L.aiLine('', true), L.aiLine('', false)],
  vault: [L.vaultLine({ name: 'Notes', syncing: true, lamp: 'in step' }), L.vaultLine({ name: '', syncing: false, lamp: 'off' }), L.vaultLine({ name: 'Notes', syncing: false, lamp: 'off' })],
  vaultTone: ['queued', 'in step', 'off', 'error'].map(l => L.vaultTone(l, true)).concat([L.vaultTone('error', false) ?? null]),
  storage: [L.storageLine('86 MB', false, 'off'), L.storageLine('1.2 GB', true, 'all')],
  look: L.lookLine('Auto', true), about: [L.aboutLine({ desktop: true, version: '1.0.9' }), L.aboutLine({ desktop: false, version: '1.0.9' }), L.aboutLine({ desktop: false, version: '' })],
  google: [L.googleLine({ signedIn: false, account: '', driveOk: false, lamp: 'off', solo: true }),
           L.googleLine({ signedIn: true, account: 'a@example.com', driveOk: true, lamp: 'connected', solo: false }),
           L.googleLine({ signedIn: true, account: 'a@example.com', driveOk: false, lamp: 'access removed', solo: false })],
  googleTone: [L.googleTone(st('removed', 'next'), { signedIn: true, driveOk: false, busy: false }), L.googleTone(null, { signedIn: true, driveOk: true, busy: false }),
               L.googleTone(null, { signedIn: false, driveOk: false, busy: false })],
  thisPhone: [L.thisPhoneLine({ solo: false, name: 'Pixel 8', unsent: 0 }), L.thisPhoneLine({ solo: false, name: '', unsent: 3 }), L.thisPhoneLine({ solo: true, name: '', unsent: 0 })],
  recovery: ['none', 'prepared', 'saved', 'checked'].map(f => L.recoveryLine(true, f)).concat([L.recoveryLine(false, '')]),
  recoveryTone: [L.recoveryTone(st('solo-recovery', 'next', 'set-up-recovery'), true, 'none'), L.recoveryTone(null, true, 'checked'), L.recoveryTone(null, false, '')],
  tones: [L.settingsTones(st('wifi', 'todo'), { running: false, driveOk: true, ai: true }), L.settingsTones(st('removed', 'next'), { running: false, driveOk: false, ai: false }),
          L.settingsTones(null, { running: true, driveOk: true, ai: true })],
  every: [],
}
// every fixed line (no name the person chose) fits 33 characters, one line at 320 px
for (const keep of ['off', 'fav', 'all']) for (const c of [false, true]) out.every.push(L.storageLine('999.9 MB', c, keep))
for (const f of ['none', 'prepared', 'saved', 'checked']) out.every.push(L.recoveryLine(true, f))
for (const lamp of ['idle', 'paused', 'needs Drive', '1 running · 1 queued']) out.every.push(L.syncLine({ signedIn: true, lamp, wifiOnly: false }))
out.every.push(L.phoneLine(true, ''), L.phoneLine(false, 'abcdef12'), L.aiLine('Anthropic', false), L.aiLine('', false), L.aboutLine({ desktop: true, version: '1.10.10' }),
  L.lookLine('Cover', false), L.thisPhoneLine({ solo: true, name: '', unsent: 999 }), L.syncLine({ signedIn: false, lamp: '', wifiOnly: true }))
out.every = out.every.filter(s => s.length > 33)
console.log(JSON.stringify(out))
"""


class SettingsLinesTest(unittest.TestCase):
    def test_the_state_lines(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + LINES))
        self.assertEqual(out['sync'], ['Google Drive not connected', 'Wi-Fi only · runs on its own', 'Any network · runs on its own', '1 running · 1 queued'])
        self.assertEqual(out['phone'], ['Saving here · a PC is optional', 'Paired · key ab12'])
        self.assertEqual(out['ai'], ['OpenAI on your key', 'No AI key yet', 'No AI key · pair again'])
        self.assertEqual(out['vault'], ['Notes · in step', 'Vault name not set', 'Notes'])
        self.assertEqual(out['vaultTone'], ['busy', 'done', 'todo', 'next', None])        # queued is teal (spec decision)
        self.assertEqual(out['storage'], ['86 MB · keeps favourites', '1.2 GB · favs, canvases, videos'])
        self.assertEqual(out['look'], 'Auto cards · night on')
        self.assertEqual(out['about'], ['Windows app · v1.0.9 · licenses', 'Version 1.0.9 · licenses', 'licenses'])
        self.assertEqual(out['google'], ['Sign in', 'a@example.com', 'Access removed'])     # the lamp, never the sentence again
        self.assertEqual(out['googleTone'], ['next', 'done', 'todo'])
        self.assertEqual(out['thisPhone'], ['Pixel 8 · all sent', 'This phone · 3 not sent', 'All backed up · no PC paired'])
        self.assertEqual(out['recovery'], ['Not set up', 'Passphrase set', 'File saved, not checked', 'Passphrase set · file checked', 'Managed on your PC'])
        self.assertEqual(out['recoveryTone'], ['next', 'done', 'todo'])
        self.assertEqual(out['tones'], [{'sync': 'todo', 'phone': 'done', 'ai': 'done'}, {'sync': 'todo', 'phone': 'next', 'ai': 'todo'},
                                        {'sync': 'busy', 'phone': 'done', 'ai': 'done'}])
        self.assertEqual(out['every'], [])


class SettingsPagesTest(unittest.TestCase):
    def test_each_page_draws_its_own_keys_before_its_content(self):
        for rel, info in (('screens/More.svelte', None), ('screens/Backup.svelte', ('Google Drive sync', 'Google Drive backup')),
                          ('screens/Recover.svelte', ('How recovery works',))):
            src = source(rel)
            self.assertIn("import PageKeys from '../PageKeys.svelte'", src, rel)
            for at in [m.start() for m in re.finditer(r'<PageKeys', src)]:
                self.assertLess(at, src.index('<div class="m-pad m-calm m-page">', at), rel)
            for title in info or ():
                key = {'Google Drive sync': 'backup.group.sync', 'Google Drive backup': 'backup.group.drive', 'How recovery works': 'recovery.help.title'}[title]
                self.assertIn(f"<PageKeys infoTitle={{t('{key}')}}>", src, rel)
                self.assertEqual(english(key), title)
        keys = source('PageKeys.svelte')
        self.assertEqual(keys.count("aria-label={t('common.back')}"), 1)
        self.assertEqual(english('common.back'), 'Back')
        self.assertIn("import './settings.css'", keys)
        self.assertIn('<div class="m-sheet-keys m-page-keys">', keys)
        mobile = source('Mobile.svelte')
        self.assertIn("{:else if !r.item && !compose && r.tab !== 'more'}", mobile)   # the app bar is the canvas detail's only
        self.assertIn("const title = $derived(r.item ? t('shell.route.item') : r.imp ? t('shell.route.import') : r.save ? t('shell.route.save') : tabName(r.tab))", mobile)
        self.assertEqual([english('shell.route.item'), english('shell.route.import'), english('shell.route.save')], ['Item', 'Import', 'Save'])

    def test_the_rows_are_groups_and_the_links_open_them(self):
        more, backup, recovery, vault = source('screens/More.svelte'), source('screens/Backup.svelte'), source('PhoneRecovery.svelte'), source('Vault.svelte')
        self.assertIn('setGroups()', more)
        self.assertIn('setGroups()', backup)
        for title in ('Sync', 'Wiskit on this phone', 'Storage', 'Look', 'About', 'Use without a PC', 'Recover a library…', 'Your PC', 'Your phone'):
            key = {'Sync': 'shell.sync.title', 'Wiskit on this phone': 'settings.group.ai', 'Storage': 'settings.group.storage', 'Look': 'settings.group.look', 'About': 'settings.group.about', 'Use without a PC': 'settings.group.solo', 'Recover a library…': 'recovery.action.recoverEllipsis', 'Your PC': 'settings.group.pc', 'Your phone': 'settings.group.phone'}[title]
            self.assertIn(f"<MGroup title={{t('{key}')}}", more)
            self.assertEqual(english(key), title)
        self.assertIn('<MGroup title="Obsidian"', vault)
        for title in ('Google account', 'This phone', 'Recovery'):
            key = {'Google account': 'backup.group.account', 'This phone': 'backup.group.thisPhone', 'Recovery': 'recovery.group.title'}[title]
            self.assertIn(f"<MGroup title={{t('{key}')}}", backup)
            self.assertEqual(english(key), title)
        self.assertIn('<MGroup title={t(\'recovery.group.title\')} id="m-recovery"', recovery)
        self.assertNotIn('text="Not set up"', recovery)                         # the row says it; the open group does not again
        self.assertNotIn('id="m-phone"', more)                                   # only the page it opens carries the id
        self.assertEqual(more.count('<MGroup title={t(\'settings.group.pc\')} href="#/backup"'), 1)
        group = source('ui/MGroup.svelte')
        self.assertIn('<h3><button type="button" class="m-group-row"', group)
        self.assertIn('aria-expanded={open} aria-controls={panelId}', group)
        self.assertIn('hidden={!open}', group)
        self.assertIn("export const OPEN_GROUP = 'm-group-open'", source('ui/groups.svelte.ts'))
        onboard = source('onboard.svelte.ts')
        self.assertIn("group.dispatchEvent(new Event('m-group-open'))", onboard)
        self.assertNotIn("from './ui/groups.svelte'", onboard)                             # the box openers' Node test stubs svelte
        for rel in ('screens/More.svelte', 'screens/Backup.svelte', 'PhoneRecovery.svelte', 'Vault.svelte'):
            self.assertIn("variant={lead ? 'pri' : 'default'}", source(rel), rel)   # one orange key per screen
        self.assertEqual(english('settings.storage.clearCopy'), "Clear the phone's copy")
        self.assertIn("{confirmClear ? t('settings.storage.confirmClear') : t('settings.storage.clear')}", more)
        self.assertEqual([english('settings.storage.confirmClear'), english('settings.storage.clear')], ['Sure? Clear', 'Clear'])
        self.assertFalse((MOBILE / 'SetupList.svelte').exists())

    def test_the_pill_and_the_hero(self):
        button, status = source('ui/MButton.svelte'), source('ui/MStatus.svelte')
        self.assertIn("shape?: 'rect' | 'pill'", button)
        self.assertIn("look?: 'line' | 'hero'", status)
        css = source('settings.css')
        self.assertIn('.m-btn.pill.pri{border-color:color-mix(in srgb,var(--accent) 78%,#000)', css)
        self.assertNotRegex(css, r'#(?!000\b|fff\b)[0-9a-fA-F]{3,6}\b(?![-\w])')     # tokens, plus the spec's #000 and #fff
        self.assertIn('<MButton shape="pill"', source('StatusCard.svelte'))
        self.assertEqual(source('screens/Recover.svelte').count('<MButton shape="pill"'), 5)


if __name__ == '__main__':
    unittest.main()
