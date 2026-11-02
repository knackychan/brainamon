"""Why the phone found no library in Google Drive (web/src/mobile/mirror/diagnose.ts): each cause gets its own
words and the right next action, instead of one guess for all. Runs the TypeScript under Node (skips without
Node 22.6+)."""
import json
import unittest

from tests.test_phone_js import _node_ok, node

H32 = 'a' * 32


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class DiagnoseTest(unittest.TestCase):
    def run_cases(self, cases):
        base = {'listed': [], 'ours': False, 'signedAs': 'fred@example.com', 'pcAccount': 'fred@example.com', 'pcProject': '', 'phoneProject': ''}
        out = json.loads(node(f"""
            import {{ diagnoseNoLibrary, projectOf }} from './web/src/mobile/mirror/diagnose.ts'
            const base = {json.dumps(base)}
            const cases = {json.dumps(cases)}
            console.log(JSON.stringify(cases.map(c => {{ const w = diagnoseNoLibrary({{ ...base, ...c }}); return [w.cause, w.changeAccount, w.pairAgain, w.message] }})))
        """))
        return out

    def test_each_cause_has_its_own_answer(self):
        out = self.run_cases([
            {'listed': None, 'problem': 'out of reach'},                                   # could not list
            {'listed': [H32], 'ours': True},                                               # first upload still running
            {'listed': [H32, 'chg-1']},                                                    # library files, none for this key
            {'listed': ['vb-' + H32, 'vi-' + H32]},                                        # only the vault is there
            {'listed': [], 'pcProject': '111111111', 'phoneProject': '222222222'},         # another Cloud project
            {'listed': ['chg-1'], 'pcAccount': ''},                                        # empty, PC did not say its account
            {'listed': [], 'pcProject': '111111111', 'phoneProject': '111111111'},         # empty, same project, same account
            {'listed': [], 'pcProject': '', 'phoneProject': ''},                           # empty, project unknown
        ])
        causes = [o[0] for o in out]
        self.assertEqual(causes, ['unknown', 'uploading', 'key', 'mirror-off', 'project', 'account', 'empty', 'empty'])
        # next actions: Change account only where the account is in doubt, Pair again where the key is
        self.assertEqual([(o[1], o[2]) for o in out],
                         [(True, True), (False, False), (False, True), (False, False), (False, False), (True, True), (False, False), (False, False)])
        # the words name the thing to do, and no cause shares another's text
        self.assertIn('Pair again', out[2][3])
        self.assertIn('Add a phone', out[2][3])
        self.assertIn('Turn on backup', out[3][3])
        self.assertIn('111111111', out[4][3])
        self.assertIn('222222222', out[4][3])
        self.assertEqual(len({o[3] for o in out[:7]}), 7)       # the last case is 'empty' again, with the project unknown
        for o in out:
            self.assertNotIn(chr(0x2014), o[3])                                              # no em-dash in text

    def test_the_project_is_the_number_before_the_dash(self):
        out = json.loads(node("""
            import { projectOf } from './web/src/mobile/mirror/diagnose.ts'
            console.log(JSON.stringify(['123456789012-abcdef.apps.googleusercontent.com', ' 55555555-x ', 'web-123.apps.googleusercontent.com', ''].map(projectOf)))
        """))
        self.assertEqual(out, ['123456789012', '55555555', '', ''])

    def test_a_pairing_without_p_falls_back_to_the_web_client(self):
        # pairings made before the PC sent `p` (source/mirror.ts noLibrary): the project comes from `c`
        out = json.loads(node("""
            import { diagnoseNoLibrary, projectOf } from './web/src/mobile/mirror/diagnose.ts'
            const pair = { c: '111111111-web.apps.googleusercontent.com', e: 'fred@example.com' }
            const pcProject = pair.p || projectOf(pair.c || '')
            const w = diagnoseNoLibrary({ listed: [], ours: false, signedAs: 'fred@example.com', pcAccount: pair.e, pcProject, phoneProject: '222222222' })
            console.log(JSON.stringify([pcProject, w.cause]))
        """))
        self.assertEqual(out, ['111111111', 'project'])
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1] / 'web/src/mobile/source/mirror.ts').read_text(encoding='utf-8')
        self.assertIn("const pcProject = this.pair.p || projectOf(this.pair.c || '')", src)
        self.assertIn('empty && pcProject ? await tokenProject()', src)


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class WaitTest(unittest.TestCase):
    """Change account / Connect: Google's sheet answers through native.ts googleToken, bounded by wait.ts
    (2 minutes; 20 s silent). An answer that never comes ends in words, not a button working for ever."""

    def test_the_wait_ends(self):
        out = json.loads(node("""
            import { withTimeout } from './web/src/mobile/wait.ts'
            const unhandled = []
            process.on('unhandledRejection', e => unhandled.push(String(e)))
            const never = new Promise(() => {})
            const slowFail = new Promise((_, reject) => setTimeout(() => reject(new Error('cancelled')), 60))
            const r = []
            r.push(await withTimeout(Promise.resolve('token'), 50, 'late'))
            try { await withTimeout(never, 20, 'Google did not answer in 2 minutes') } catch (e) { r.push(e.message) }
            try { await withTimeout(Promise.reject(new Error('cancelled')), 50, 'late') } catch (e) { r.push(e.message) }
            try { await withTimeout(slowFail, 10, 'late') } catch (e) { r.push(e.message) }
            await new Promise(ok => setTimeout(ok, 100))      // slowFail fails after the wait ended: nobody listens
            r.push(unhandled.length)
            console.log(JSON.stringify(r))
        """))
        self.assertEqual(out, ['token', 'Google did not answer in 2 minutes', 'cancelled', 'late', 0])

    def test_google_token_uses_the_bounded_wait(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1] / 'web/src/mobile/native.ts').read_text(encoding='utf-8')
        body = src.split('export function googleToken', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('withTimeout(B.googleToken(', body)
        self.assertIn('120_000', body)
        self.assertIn('20_000', body)


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class PairedFolderTest(unittest.TestCase):
    """MirrorSource.noLibrary (web/src/mobile/source/mirror.ts) on a paired phone. The phone gets there only with a valid
    access record in Drive (mirror/drive.ts authorize), so that record is no library content, and the PC's recovery
    records (vi-recovery-, vi-phone-recovery-) are no vault content: no backup yet, or only the vault, says so."""

    def causes(self, listings):
        return json.loads(node(r"""
            import fs from 'node:fs'
            import { stripTypeScriptTypes } from 'node:module'
            import * as D from './web/src/mobile/mirror/diagnose.ts'
            const src = fs.readFileSync('web/src/mobile/source/mirror.ts', 'utf8').replace(/\r\n/g, '\n')   // a CRLF checkout too
            const method = src.match(/  private async noLibrary\(key: MirrorKey\)[\s\S]*?\n  }\n/)[0].replace('private ', '')
            const logical = fs.readFileSync('web/src/mobile/mirror/license.ts', 'utf8').match(/export const LICENSE_LOGICAL = '([^']+)'/)[1]
            class NoMirror extends Error { constructor(message, why) { super(message); this.why = why } }
            const Source = new Function('NeedsSignIn', 'SyncPaused', 'syncPaused', 'isLibraryName', 'projectOf', 'diagnoseNoLibrary',
              'tokenProject', 'NoMirror', 'CONTROL_LOGICALS', stripTypeScriptTypes('class Source {\n' + method + '\n}') + ';return Source')(
              class {}, class {}, () => false, D.isLibraryName, D.projectOf, D.diagnoseNoLibrary, async () => '111111111', NoMirror, [logical, 'control/access-v2.json'])
            // this pairing's key: its access record and its library's meta file, by their hashed names
            const key = { name: async n => n === logical ? 'c'.repeat(32) : n === 'control/access-v2.json' ? 'f'.repeat(32) : n === 'library/meta.json' ? 'd'.repeat(32) : 'e'.repeat(32) }
            const out = []
            for (const names of LISTINGS) {
              const s = new Source()
              s.pair = { g: 'a@example.com', e: 'a@example.com', p: '111111111', c: '' }
              s.drive = { list: async () => names.map(name => ({ id: name, name })) }
              out.push((await s.noLibrary(key)).why.cause)
            }
            console.log(JSON.stringify(out))
        """.replace('LISTINGS', json.dumps(listings))))

    def test_the_phones_own_access_record_and_the_recovery_records_are_no_library(self):
        access, recovery = 'c' * 32, f"vi-recovery-{'1' * 32}-{'2' * 32}.json"
        phone_recovery = f"vi-phone-recovery-{'3' * 32}-{'4' * 32}.json"
        self.assertEqual(self.causes([
            [access],                                       # the PC confirmed the phone; nothing backed up yet
            [access, 'f' * 32],                             # both signed access protocols, no library yet
            [access, recovery, phone_recovery],             # and its recovery set up
            [access, recovery, 'vb-' + H32, 'vi-' + H32],   # only the vault (and the recovery records)
            [access, recovery, 'd' * 32],                   # the PC's first backup is running
            [access, H32],                                  # a library under another key
        ]), ['empty', 'empty', 'empty', 'mirror-off', 'uploading', 'key'])


if __name__ == '__main__':
    unittest.main()
