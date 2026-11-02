"""Settings > Obsidian copy (web/src/lib/obsidian.ts) under Node: the strings the spec fixes and the status line.

Run from the project root:  py -m unittest tests.test_obsidian_copy_js -v
"""
import json
import unittest

from tests.test_onboarding_js import _node_ok, node

MODULE = './web/src/lib/obsidian.ts'


def run(expr: str):
    return json.loads(node(f"import * as o from '{MODULE}'; console.log(JSON.stringify({expr}))"))


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class ObsidianCopyTest(unittest.TestCase):
    def test_setup_copy_and_states(self):
        c = run('o.COPY')
        self.assertEqual(c['existing'], 'Use existing vault')
        self.assertEqual(c['upcoming'], '(upcoming)')
        self.assertEqual(c['existingHint'], 'Connect your own notes vault: coming in a later update. Your vault stays untouched. Have an empty vault, or one Brainamon made before? Use the link under Create a new vault.')
        self.assertEqual(c['create'], 'Create a new vault')
        self.assertEqual(c['emptyLink'], 'Or use one you already created')
        self.assertEqual(c['willCreate'], 'Brainamon will create:')
        self.assertEqual((c['changeFolder'], c['createButton']), ('Change folder', 'Create'))
        self.assertEqual(c['ownerSync'], 'Phone: press Sync my Obsidian vault under Vault sync with phone, below. The pages Brainamon generates go one way, PC to phone; your own files, and anything you add inside the Brainamon folder, sync both ways.')
        self.assertEqual(c['syncOnHint'], 'Vault sync is on: the new vault reaches your phone too, as long as every phone runs the current Brainamon app. Vault sync pauses otherwise and names the phone to update.')
        self.assertNotIn('later update', c['ownerSync'])
        self.assertNotIn('Export', json.dumps(c))                     # the classic export is never offered here
        self.assertEqual(run("o.firstOpenText('D:\\\\V')"), 'In Obsidian, choose Open folder as vault and pick D:\\V. Ctrl+G shows the graph.')
        self.assertEqual(run('o.useAnyway(1)'), 'Use it anyway (1 other item stays untouched)')
        self.assertEqual(run('o.useAnyway(3)'), 'Use it anyway (3 other items stay untouched)')
        self.assertIn(run('o.COPY.openObsidian'), ('Open in Obsidian', 'Start Obsidian'))
        self.assertEqual(run('typeof o.OPEN_DIRECT'), 'boolean')

    def test_vault_in_picked_folder(self):
        self.assertEqual(run("o.vaultIn('C:\\\\Users\\\\x\\\\Documents')"), 'C:\\Users\\x\\Documents\\Brainamon Vault')
        self.assertEqual(run("o.vaultIn('C:\\\\Users\\\\x\\\\Documents\\\\')"), 'C:\\Users\\x\\Documents\\Brainamon Vault')
        self.assertEqual(run("o.vaultIn('D:\\\\Notes\\\\Brainamon Vault')"), 'D:\\Notes\\Brainamon Vault')
        self.assertEqual(run("o.vaultIn('C:\\\\')"), 'C:\\Brainamon Vault')
        self.assertNotIn('Export', run('o.COPY.folderHint'))

    def test_new_to_obsidian_text(self):
        line = run("o.newToObsidianText('D:\\\\V')")
        self.assertEqual(line, 'Obsidian is starting. It has not opened this folder yet: choose Open folder as vault and pick D:\\V. After that, Open in Obsidian goes straight to your map.')

    def test_status_line(self):
        st = {'pending': False, 'busy': '', 'waiting': False, 'error': '', 'last_render': 0, 'last_maintenance': 0,
              'adopted': [], 'unlisted': 0, 'other_library': False, 'stale': 0, 'topics': 0, 'pending_summaries': 0, 'written': 0, 'removed': 0, 'state': 'idle'}
        self.assertEqual(run(f'o.statusLine({json.dumps(st)})'), 'Not rendered yet.')
        self.assertEqual(run(f"o.statusLine({json.dumps({**st, 'pending': True})})"), 'Render pending: the vault is busy, Brainamon retries every minute.')
        self.assertEqual(run(f"o.statusLine({json.dumps({**st, 'busy': 'move', 'waiting': True})})"), 'Waiting for the vault to be free.')
        self.assertEqual(run(f"o.statusLine({json.dumps({**st, 'other_library': True})})"), 'This vault belongs to another Brainamon library.')
        line = run(f"o.statusLine({json.dumps({**st, 'last_render': 1, 'stale': 2, 'adopted': ['a', 'b', 'c']})})")
        self.assertTrue(line.startswith('Last refresh '))
        self.assertIn('2 topics out of date', line)
        self.assertIn('3 adopted pages', line)

    def test_reconnect_leftovers_missing(self):
        c = run('o.COPY')
        self.assertEqual((c['reconnect'], c['takeOverKeep'], c['takeOverRemove'], c['otherFolder']),
                         ('Reconnect this vault', 'Take over, keep them', 'Take over and remove them', 'Choose another folder'))
        self.assertEqual((c['removeLeftovers'], c['missingTitle'], c['locate']), ('Remove leftovers', 'Vault not found', 'Locate the folder'))
        self.assertEqual(c['viewHint'], 'The Brainamon folder is a view of your library: change items in Brainamon. Write your own notes anywhere else in the vault; Brainamon never touches them.')
        self.assertNotIn('Export', json.dumps(c))
        self.assertTrue(run('o.leftoversText(1)').startswith('1 page from an earlier library covers'))
        self.assertTrue(run('o.leftoversText(3)').startswith('3 pages from an earlier library cover'))
        self.assertEqual(run('o.removeText(2)'), 'Delete 2 leftover pages from the vault?')
        self.assertTrue(run('o.unlistedText(1)').startswith('1 file in the Brainamon folder is not in the manifest'))
        st = {'pending': False, 'busy': '', 'waiting': False, 'error': '', 'last_render': 1, 'last_maintenance': 0, 'missing': True,
              'adopted': [], 'unlisted': 0, 'other_library': False, 'stale': 0, 'topics': 0, 'pending_summaries': 0, 'written': 0, 'removed': 0, 'state': 'idle'}
        self.assertEqual(run(f'o.statusLine({json.dumps(st)})'), 'Vault not found. It was moved, renamed or deleted.')
