"""Sub-plan 06 of docs/superpowers/plans/2026-10-31-phone-backup-phones.md: every hint names a real place, on the phone
and on the PC. No text sends the user to a place that 04 and 05 moved or removed (the phone's More > Scan, More >
Recovery, More > Unpair, More > Without a PC; the PC's Pair phone, Unpair, Upload now, Phone sync), the phone says
recovery file where its screens do, its access refusals speak the status model's words, and no text promises that
phones keep working where they must scan once (P4). Reads the sources as text: no Node, browser or network."""
import re
import unittest
from collections import Counter
from pathlib import Path
from tests.phone_catalog import english

ROOT = Path(__file__).resolve().parents[1]
# the plan's inventory search over the plan's places (what rg finds there, without rg)
INVENTORY = re.compile(r'More (&gt;|>) (Scan|Recovery|Unpair)|Pair phone|Unpair on the PC|Upload now|Settings > Phone sync'
                       r'|turn on Upload to Google Drive|Phones keep working')
PLACES = ['web/src', 'library', 'mobile-shell/store', 'docs/development/BACKUP-RESTORE.md']
# Also review private design references when present; public runtime checks do
# not require those documents or the preview application.
PLACES += [p for p in ('docs/BACKUP-RESTORE.md', 'projects/backup-phones-mockup/README.md', 'CLAUDE.md') if (ROOT / p).is_file()]
# the matches that stay, each for its reason
ALLOWED = Counter({
    ('web/src/previews/backup/ui.svelte.ts', 'Upload now'): 1,              # the preview's old and new label of one key
    ('web/src/previews/settings/SettingsPreview.svelte', 'Upload now'): 1,  # a sample button of the Settings preview
    ('projects/backup-phones-mockup/README.md', 'Upload now'): 1,           # D12: today's key, kept as the choice it was
})
SKIP = {'node_modules', '__pycache__', 'dist'}
CODE_COMMENT = re.compile(r'^\s*(//|/\*|\*)')
PY_COMMENT = re.compile(r'^\s*#')
# the words that tell the user which phone needs which code (P4)
P4 = "Phones paired with this PC keep working; phones paired with another PC scan this PC's code once (Add a phone)."
PAIR = 'Settings > Pair with your PC > Scan (a phone already set up: Settings > Backup & phones > This phone)'
CODE = 'On a paired phone: Settings > Backup & phones > Recovery code > Show.'
# the phone's own sources: a "Settings > X" there is a phone place unless its sentence is about the PC
PHONE = ('web/src/mobile/', 'web/src/components/ForgotPassphrase.svelte', 'tests/fixtures/phone_states.json')
PC_WORDS = re.compile(r'\b(PC|PC\'s|desktop|Android)\b')
# sentences whose "it" is the PC named in the sentence before (mirror/phone-state.ts, the replaced PC)
PC_SAID = ('Scan the new code on it: ', 'Open the new pairing link from it: ')


def files():
    for place in PLACES:
        top = ROOT / place
        for f in ([top] if top.is_file() else sorted(top.rglob('*'))):
            rel = f.relative_to(ROOT)
            if f.is_file() and not SKIP & set(rel.parts):
                data = f.read_bytes()
                if b'\0' not in data:
                    yield rel.as_posix(), data.decode('utf-8', 'replace').replace('\r\n', '\n')


def plain(text):
    return text.replace('&gt;', '>').replace('&amp;', '&')


def visible(path, text, raw=False):
    """The lines a reader sees: comments of code are left out, documents are read whole."""
    if not path.endswith('.md'):
        text = re.sub(r'<!--.*?-->', lambda m: re.sub(r'[^\n]', ' ', m.group()), text, flags=re.S)
    comment = None if path.endswith('.md') else PY_COMMENT if path.endswith('.py') else CODE_COMMENT
    for n, line in enumerate(text.split('\n'), 1):
        if not (comment and comment.match(line)):
            yield n, line if raw else plain(line)


def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def names(rel):
    """Box titles, row titles, keys and quoted words of one phone screen: the places a path can name."""
    src = read(rel)
    out = set(re.findall(r'<h3>([^<{]+)', src)) | set(re.findall(r'(?:title|kicker)="([^"{]+)"', src))
    out |= set(re.findall(r'>([^<>{}\n]+)</M(?:Button|TextButton)>', src)) | set(re.findall(r"'([A-Z][^'\n]{2,40})'", src))
    # Catalog moves retain the same navigation labels and their actual component wiring.
    keys = re.findall(r"(?:title|kicker)=\{t\('([^']+)'\)\}", src)
    keys += re.findall(r">\{t\('([^']+)'\)\}</M(?:Button|TextButton)>", src)
    for body in re.findall(r'>([^<]*)</M(?:Button|TextButton)>', src):
        keys += re.findall(r"t\('([^']+)'\)", body)
    out.update(english(key) for key in keys)
    return {plain(n).strip() for n in out}


class CopyPlacesTest(unittest.TestCase):
    def test_the_inventory_search_finds_only_the_allowed_matches(self):
        found = Counter((path, m.group()) for path, text in files() for m in INVENTORY.finditer(text))
        self.assertEqual(found, Counter({key: n for key, n in ALLOWED.items() if (ROOT / key[0]).is_file()}))

    def test_a_pc_place_named_on_the_phone_or_in_a_guide_is_a_real_label(self):
        block = read('web/src/lib/backup.ts').split('export const W = {', 1)[1].split('\n}', 1)[0]
        labels = [v.rstrip('…') for v in re.findall(r"\w+: '([^']+)'", block)] + ['Recovery']   # Recovery: the page's own group title
        # the phone's Settings > Backup & phones names its own groups and rows (projects/phone-settings)
        labels += names('web/src/mobile/screens/Backup.svelte') | names('web/src/mobile/PhoneRecovery.svelte')
        wrong = []
        for path, text in files():
            for n, line in enumerate(plain(text).split('\n'), 1):
                for m in re.finditer(r'Settings > Backup & phones > ', line):
                    rest = line[m.end():].lstrip('*')
                    if not any(rest.startswith(label) for label in labels):
                        wrong.append(f'{path}:{n}: {rest[:60]}')
        self.assertEqual(wrong, [])

    def test_phone_backup_off_help_names_both_pc_actions(self):
        block = read('web/src/lib/backup.ts').split('export const W = {', 1)[1].split('\n}', 1)[0]
        for action in ('Turn on backup', 'Resume backup'):
            self.assertIn("'" + action + "'", block)
        for language in ('en', 'fr', 'zh-Hant'):
            text = read(f'web/src/lib/i18n/{language}/backup.ts')
            help_line = next(line for line in text.splitlines() if '"backup.state.backupOffHelp"' in line)
            for label in ('Settings > Backup & phones', 'Turn on backup', 'Resume backup'):
                self.assertIn(label, help_line)

    def test_a_phone_place_named_anywhere_exists_on_the_phone(self):
        # the phone's Settings (#/more) was called More until projects/phone-settings: no visible line says More > any more
        more = names('web/src/mobile/screens/More.svelte') | names('web/src/mobile/Vault.svelte') | {'Backup & phones'}
        for path in (ROOT / 'web/src/mobile/screens/settings').glob('*.svelte'):
            more |= names(path.relative_to(ROOT).as_posix())
        backup = names('web/src/mobile/screens/Backup.svelte') | names('web/src/mobile/PhoneRecovery.svelte')
        wrong = [f'{path}:{n}: {line.strip()[:60]}' for path, text in files() for n, line in visible(path, text) if 'More > ' in line]
        for path, text in files():
            if not path.startswith(PHONE):
                continue
            for n, line in visible(path, text):
                for m in re.finditer(r'Settings > ', line):
                    said = re.split(r"\. |['\"`]", line[:m.start()])[-1]
                    if PC_WORDS.search(said) or said.endswith(PC_SAID):
                        continue                                  # a PC place, checked by the test above
                    rest = line[m.end():].lstrip('*')
                    if not any(rest.startswith(p) for p in more):
                        wrong.append(f'{path}:{n}: Settings > {rest[:50]}')
                    elif rest.startswith('Backup & phones > '):
                        sub = rest[len('Backup & phones > '):].lstrip('*')
                        if not any(sub.startswith(p) for p in backup):
                            wrong.append(f'{path}:{n}: Settings > Backup & phones > {sub[:40]}')
        self.assertEqual(wrong, [])
        # the places the PC and the guides name on the phone, word for word
        self.assertIn("Open it in the phone app: Settings > Recover a library…, then File.", read('library/recovery.py'))
        for name in ('Sync', 'Wiskit on this phone', 'Obsidian', "Clear the phone's copy", 'Pair with your PC', 'Use without a PC', 'Recover a library…'):
            self.assertIn(name, more)

    def test_the_phone_says_recovery_file_where_its_screens_do(self):
        # the format names and the saved file's name stay (brainamon-phone-backup-kit, Brainamon-phone-recovery-kit-N.json)
        kit = re.compile(r'(?i)(?<![-\w])kits?\b(?!-)')
        wrong = []
        for path, text in files():
            if not path.startswith('web/src/mobile/'):
                continue
            for n, line in visible(path, text, raw=True):
                # what a screen can say: a quoted sentence, a template literal without its ${...} parts, markup text
                said = re.findall(r"'([A-Z][^'\n]* [^'\n]*)'", line) + re.findall(r'>([^<>{}\n]+)<', line)
                said += [re.sub(r'\$\{[^}]*\}', '', t) for t in re.findall(r'`([^`\n]* [^`\n]*)`', line)]
                wrong += [f'{path}:{n}: {t}'[:120] for t in said if kit.search(t)]
        self.assertEqual(wrong, [])

    def test_no_text_promises_that_phones_keep_working_without_a_scan(self):
        promise = re.compile(r'(?i)\bphones (keep working|never notice|carry on)|same key, same phones|Unpairing deletes them')
        wrong = [f'{path}:{n}' for path, text in files() for n, line in visible(path, text) if promise.search(line)]
        self.assertEqual(wrong, [])
        for rel, n in (('web/src/windows/BackupPhonesPage.svelte', 2), ('web/src/lib/backup-state.ts', 1),
                       ('web/src/previews/backup/BackupPage.svelte', 3), ('projects/backup-phones-mockup/README.md', 2)):
            if not (ROOT / rel).is_file():
                continue
            self.assertEqual(plain(read(rel)).count(P4), n, rel)

    def test_the_pc_and_its_previews_say_where_the_phone_scans_and_shows_its_code(self):
        for rel in ('web/src/windows/BackupPhonesPage.svelte', 'web/src/windows/SetupHub.svelte', 'web/src/previews/backup/BackupPage.svelte', 'projects/backup-phones-mockup/README.md'):
            if not (ROOT / rel).is_file():
                continue
            self.assertIn(PAIR, plain(read(rel)), rel)
        for rel in ('web/src/windows/RecoverWin.svelte', 'web/src/previews/backup/RecoverWin.svelte', 'projects/backup-phones-mockup/README.md'):
            if not (ROOT / rel).is_file():
                continue
            self.assertIn(CODE, plain(read(rel)), rel)

    @unittest.skipUnless((ROOT / 'projects/backup-phones-mockup/README.md').is_file(), 'private design reference excluded')
    def test_the_mockup_phone_pane_follows_p6_p10_and_names_ph12(self):
        pane = {line.split('|')[1].strip().split(' ')[0]: line for line in read('projects/backup-phones-mockup/README.md').split('\n') if line.startswith('| PH')}
        self.assertIn('Your PC is still backing up. The library appears when it finishes.', pane['PH3'])     # P6: no numbers
        self.assertIn("3 edits haven't reached your PC yet. If you unpair now, they never will.", pane['PH10'])   # P10
        self.assertIn('Restored or reinstalled it? Scan its new code.', pane['PH6'])                       # P4
        self.assertIn('Your PC changed (restored or reinstalled).', pane['PH12'])                          # P4, advisory
        # the reinstall scenario of the preview: the phone scans this PC's new code before its edit arrives (P4)
        reinstall = read('web/src/previews/backup/scenarios.ts').split("id: 'reinstall'", 1)[1].split('] },', 1)[0]
        self.assertLess(reinstall.index("click: '@addPhone'"), reinstall.index("event: 'scan', arg: 'A'"))
        self.assertLess(reinstall.index("event: 'scan', arg: 'A'"), reinstall.index("wait: 'synced:A'"))

    def test_access_refusals_use_the_status_model_words(self):
        src, model = read('web/src/mobile/mirror/license.ts'), read('web/src/mobile/mirror/phone-state.ts')
        text = dict(re.findall(r"""export const (\w+) = ['"](.+)['"]\n""", src))
        # each starts with its state's sentence; the expired one names no time (its state says when the PC last renewed)
        for name, start in (('LICENSE_REQUIRED', 'Waiting for your PC to confirm this phone'), ('ACCESS_EXPIRED', "This phone's sync access expired"),
                            ('ACCESS_INVALID', 'This phone could not check its access'), ('ACCESS_INACTIVE', 'Your PC needs an update.'),
                            ('PC_REPLACED', 'Your PC changed (restored or reinstalled)')):
            self.assertTrue(text[name].startswith(start), name)
        for sentence in ('Waiting for your PC to confirm this phone.', 'This phone could not check its access.', 'Your PC needs an update.',
                         'Your PC changed (restored or reinstalled).'):
            self.assertIn(sentence, model)                          # the model says the same sentence
        self.assertIn('older phone access', text['ACCESS_INACTIVE'])
        self.assertIn('expired', text['ACCESS_EXPIRED'])
        self.assertEqual(len(set(text.values())), len(text))        # KINDS tells them apart by their words
        lib = read('web/src/mobile/screens/Library.svelte')
        self.assertIn('ACCESS_STATES.includes(status.id) ? status.text : phone.error', lib)    # the error box says the model's sentence

    def test_the_privacy_policy_says_what_the_phone_record_holds(self):
        policy = re.sub(r'\s+', ' ', read('mobile-shell/store/privacy-policy.md'))
        for words in ('sealed with the library key', 'its device name', 'when it last synced', 'Unpair on the phone tries to delete it',
                      'Remove all phones on the PC deletes the records sealed with the old key', 'A phone used without a PC writes none.'):
            self.assertIn(words, policy)


if __name__ == '__main__':
    unittest.main()
