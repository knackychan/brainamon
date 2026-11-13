"""The owner vault: pages and names (library/owner_pages.py) and the manifest, ownership and recoverable
writes (library/owner_vault.py). Spec docs/superpowers/specs/2026-10-28-map-engine-owner-vault-design.md.

Run from the project root:  py -m unittest tests.test_owner_vault -v
Temp folders only; never the real data/.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.db import Database
from library import map_engine as M
from library import owner_pages as P
from library import owner_vault as V


class Lib:
    """A small library in a temp folder: the Database plus the vault folder next to it."""
    def __init__(self, case):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        case.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.data = self.root / 'data'
        self.vault = self.root / 'vault'
        self.db = Database(self.data / 'content_manager.db')
        case.addCleanup(self.db.close)

    def add(self, url, **fields):
        iid = self.db.add_item({'url': url, **{k: v for k, v in fields.items() if k in ('description', 'tags', 'creator', 'type')}})
        rest = {k: v for k, v in fields.items() if k not in ('description', 'tags', 'creator', 'type')}
        if rest:
            self.db.update_item(iid, rest)
        return iid


class PagesTest(unittest.TestCase):
    def test_item_title_rule(self):
        self.assertEqual(P.item_title({'url': 'https://x/1', 'description': 'https://x/1'}), '')
        self.assertEqual(P.item_title({'url': 'https://x/1', 'description': '  https://other.site/p?q=1 '}), '')
        self.assertEqual(P.item_title({'url': 'https://x/1', 'description': 'Scraped caption\nmore'}), 'Scraped caption')
        self.assertEqual(P.item_title({'url': 'https://x/1', 'description': 'caption', 'ai_desc': 'AI summary line\nrest'}), 'AI summary line')
        self.assertEqual(P.item_title({'url': 'https://x/1', 'description': 'caption', 'ai_desc': 'ai', 'short_desc': 'Page title'}), 'Page title')
        self.assertEqual(P.item_title({'url': 'https://x/1'}), '')

    def test_fold(self):
        self.assertEqual(P.fold('Martial Arts'), P.fold('martial-arts'))
        self.assertEqual(P.fold('martial_arts'), 'martial arts')
        self.assertNotEqual(P.fold('C++'), P.fold('C#'))

    def test_link_only_item_has_no_page_caption_gives_one(self):
        lib = Lib(self)
        bare = lib.add('https://x/bare', description='https://x/bare', tags='hips')
        cap = lib.add('https://x/cap', description='Hip airplane drill', tags='hips')
        man = V.new_manifest('lib1')
        payload = P.build_owner_payload(lib.db, V.Names(man), tag_map={'hips': 'hips'})   # no map: tags under 3 uses would be dropped
        by_id = {it['id']: it for it in payload['items']}
        self.assertEqual(by_id[bare]['name'], '')
        self.assertEqual(by_id[cap]['name'], f'hip-airplane-drill-{cap}')
        files = P.render(payload)
        self.assertIn(f'Brainamon/Items/hip-airplane-drill-{cap}.md', files)
        self.assertFalse(any(p.endswith(f'-{bare}.md') for p in files))
        hub = files['Brainamon/Tags/hips.md']['data'].decode('utf-8')
        self.assertIn(f'[[Brainamon/Items/hip-airplane-drill-{cap}|Hip airplane drill]]', hub)
        self.assertIn('- https://x/bare', hub)                 # listed as its URL, no link
        self.assertNotIn('[[Brainamon/Items/', hub.split('https://x/bare')[1])
        self.assertIn('source: brainamon', files['Brainamon/Items/hip-airplane-drill-' + str(cap) + '.md']['data'].decode())
        self.assertEqual(man['names']['item'][str(cap)], f'hip-airplane-drill-{cap}')

    def test_title_change_keeps_name_updates_aliases(self):
        lib = Lib(self)
        iid = lib.add('https://x/1', description='First caption of the post')
        man = V.new_manifest('lib1')
        first = P.render(P.build_owner_payload(lib.db, V.Names(man)))
        rel = f'Brainamon/Items/first-caption-of-the-post-{iid}.md'
        self.assertIn(rel, first)
        lib.db.update_item(iid, {'short_desc': 'Real page title'})
        second = P.render(P.build_owner_payload(lib.db, V.Names(man)))
        self.assertIn(rel, second)                                   # the file name is frozen
        page = second[rel]['data'].decode('utf-8')
        self.assertIn('aliases: [Real page title]', page)
        self.assertIn('# Real page title', page)
        self.assertEqual(len([p for p in second if p.startswith('Brainamon/Items/')]), 1)

    def test_pages_hubs_topics_and_map(self):
        lib = Lib(self)
        a = lib.add('https://x/a', description='Kettlebell swing basics', tags='kettlebell', category='SPORT')
        b = lib.add('https://x/b', description='Blender merge tip', tags='blender', category='3D')
        lib.db.update_item(a, {'analysis_done': 1, 'analysis_path': str(lib.data / 'items' / str(a) / 'report.md')})
        (lib.data / 'items' / str(a)).mkdir(parents=True)
        (lib.data / 'items' / str(a) / 'report.md').write_text('# report', encoding='utf-8')
        (lib.data / 'items' / str(a) / 'thumb.jpg').write_bytes(b'jpg')
        lib.db.notes_dir.mkdir(exist_ok=True)
        (lib.db.notes_dir / 'swings.md').write_text('---\ntopic: Swings\n---\nbody', encoding='utf-8')
        cache = M.empty('m')
        cache['clusters']['t-1'] = {'title': 'Strength', 'synthesis': 'All about swings.', 'member_ids': [a, b],
                                    'name': 'strength-t1', 'summary_basis': {}, 'stale': True}
        cache['clusters']['t-2'] = {'title': '', 'synthesis': '', 'member_ids': [b], 'name': '', 'summary_basis': None, 'stale': False}
        man = V.new_manifest('lib1')
        tag_map = {'kettlebell': 'kettlebell', 'blender': 'blender'}
        payload = P.build_owner_payload(lib.db, V.Names(man), tag_map=tag_map, cache=cache, include_pictures=True)
        files = P.render(payload)
        self.assertEqual(set(files), {
            f'Brainamon/Items/kettlebell-swing-basics-{a}.md', f'Brainamon/Items/blender-merge-tip-{b}.md',
            'Brainamon/Tags/kettlebell.md', 'Brainamon/Tags/blender.md',
            'Brainamon/Categories/sport.md', 'Brainamon/Categories/3d.md',
            'Brainamon/Topics/strength-t1.md',                      # t-2 waits for its summary: no page
            f'Brainamon/Reports/{a}.md', f'Brainamon/Attachments/{a}.jpg', 'Brainamon/Notes/swings.md',
            'Brainamon/Knowledge Map.md'})
        item = files[f'Brainamon/Items/kettlebell-swing-basics-{a}.md']['data'].decode('utf-8')
        self.assertIn(f'![[Brainamon/Attachments/{a}.jpg]]', item)
        self.assertIn('[[Brainamon/Topics/strength-t1|Strength]]', item)
        self.assertIn('[[Brainamon/Tags/kettlebell|kettlebell]]', item)
        self.assertIn('[[Brainamon/Categories/sport|SPORT]]', item)
        self.assertIn(f'[[Brainamon/Reports/{a}|Analysis report]]', item)
        self.assertEqual(files[f'Brainamon/Reports/{a}.md']['src'], str(lib.data / 'items' / str(a) / 'report.md'))
        topic = files['Brainamon/Topics/strength-t1.md']['data'].decode('utf-8')
        self.assertIn('stale: true', topic)
        self.assertIn('All about swings.', topic)
        m = files['Brainamon/Knowledge Map.md']['data'].decode('utf-8')
        self.assertIn('[[Brainamon/Topics/strength-t1|Strength]] (2 items, summary out of date)', m)
        self.assertEqual(files['Brainamon/Topics/strength-t1.md']['source'], 'topic')
        self.assertEqual(files['Brainamon/Topics/strength-t1.md']['key'], 't-1')
        without_pictures = P.render(P.build_owner_payload(lib.db, V.Names(man), tag_map=tag_map, cache=cache))
        self.assertNotIn(f'Brainamon/Attachments/{a}.jpg', without_pictures)
        self.assertNotIn('![[', without_pictures[f'Brainamon/Items/kettlebell-swing-basics-{a}.md']['data'].decode())
        # no map at all: the Knowledge Map says so
        no_map = P.render(P.build_owner_payload(lib.db, V.Names(man), tag_map=tag_map))
        self.assertIn('AI topics appear here after the first Refresh map', no_map['Brainamon/Knowledge Map.md']['data'].decode())


class NamesTest(unittest.TestCase):
    def test_colliding_slugs_get_distinct_pages(self):
        lib = Lib(self)
        a = lib.add('https://x/a', description='cpp post', tags='C++', category='Odds & ends')
        b = lib.add('https://x/b', description='csharp post', tags='C#', category='Odds   ends')
        man = V.new_manifest('lib1')
        tag_map = {'c++': 'C++', 'c#': 'C#'}
        files = P.render(P.build_owner_payload(lib.db, V.Names(man), tag_map=tag_map))
        self.assertIn('Brainamon/Tags/c.md', files)
        self.assertIn('Brainamon/Tags/c-2.md', files)
        self.assertIn('Brainamon/Categories/odds-ends.md', files)
        self.assertIn('Brainamon/Categories/odds-ends-2.md', files)
        n = man['names']                                   # which of the two got the suffix depends on item order
        self.assertEqual(sorted(n['tag'].values()), ['c', 'c-2'])
        self.assertEqual(sorted(n['category'].values()), ['odds-ends', 'odds-ends-2'])
        pa = files[f'Brainamon/Items/cpp-post-{a}.md']['data'].decode()
        pb = files[f'Brainamon/Items/csharp-post-{b}.md']['data'].decode()
        self.assertIn(f"[[Brainamon/Tags/{n['tag']['c++']}|C++]]", pa)
        self.assertIn(f"[[Brainamon/Tags/{n['tag']['c#']}|C#]]", pb)
        self.assertIn(f"[[Brainamon/Categories/{n['category']['odds & ends']}|Odds & ends]]", pa)
        self.assertIn(f"[[Brainamon/Categories/{n['category']['odds ends']}|Odds ends]]", pb)   # _link_text folds spaces
        self.assertNotEqual(n['tag']['c++'], n['tag']['c#'])

    def test_folded_names_share_one_hub(self):
        lib = Lib(self)
        a = lib.add('https://x/a', description='kick', tags='Martial Arts')
        b = lib.add('https://x/b', description='punch', tags='martial-arts')
        c = lib.add('https://x/c', description='throw', tags='martial_arts')
        files = P.render(P.build_owner_payload(lib.db, V.Names(V.new_manifest('l')), tag_map={'martial arts': 'Martial Arts', 'martial-arts': 'martial-arts', 'martial_arts': 'martial_arts'}))
        hubs = [p for p in files if p.startswith('Brainamon/Tags/')]
        self.assertEqual(hubs, ['Brainamon/Tags/martial-arts.md'])
        hub = files[hubs[0]]['data'].decode()
        for iid in (a, b, c):
            self.assertIn(f'-{iid}|', hub)

    def test_reserved_slug_gets_suffix(self):
        names = V.Names(V.new_manifest('l'))
        self.assertEqual(names.hub('tag', 'con', 'CON'), 'con-2')
        self.assertEqual(names.hub('tag', 'aux cable', 'aux'), 'aux-2')
        self.assertEqual(names.hub('category', 'lpt1', 'LPT1'), 'lpt1-2')
        self.assertEqual(names.hub('tag', 'con', 'CON'), 'con-2')          # stable

    def test_names_survive_restart(self):
        lib = Lib(self)
        iid = lib.add('https://x/a', description='Original caption', tags='C++', category='Odds')
        man = V.new_manifest('lib1')
        P.render(P.build_owner_payload(lib.db, V.Names(man), tag_map={'c++': 'C++'}))
        V.write_manifest(lib.vault, man)
        # a restart: the manifest is read back, the library changed meanwhile
        lib.db.update_item(iid, {'short_desc': 'New title'})
        lib.add('https://x/b', description='csharp', tags='C#')
        again = V.read_manifest(lib.vault)
        self.assertIsNotNone(again)
        files = P.render(P.build_owner_payload(lib.db, V.Names(again), tag_map={'c++': 'C++', 'c#': 'C#'}))
        self.assertIn(f'Brainamon/Items/original-caption-{iid}.md', files)
        self.assertIn('Brainamon/Tags/c.md', files)              # C++ keeps 'c'
        self.assertIn('Brainamon/Tags/c-2.md', files)            # C# gets the suffix, even on a later run
        self.assertEqual(again['names']['tag']['c++'], 'c')


class FolderTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)

    def test_location_check_both_directions(self):
        data, home = self.root / 'repo' / 'data', self.root / 'repo'
        data.mkdir(parents=True)
        (self.root / 'home2').mkdir()
        self.assertEqual(V.location_error(self.root / 'Documents' / 'Brainamon Vault', data, self.root / 'home2'), '')
        for bad in (data, data / 'Fredorama', data.parent, self.root, self.root / 'home2', self.root / 'home2' / 'v'):
            self.assertNotEqual(V.location_error(bad, data, self.root / 'home2'), '', bad)
        # from source the settings home is the repo, which contains data/: both rules fire for the repo
        self.assertIn('settings', V.location_error(self.root / 'repo' / 'x', data, home))

    def test_default_location_is_under_documents(self):
        p = V.default_location()
        self.assertEqual(p.name, 'Brainamon Vault')
        self.assertTrue(p.is_absolute())

    def test_owner_folder_rules(self):
        missing = self.root / 'new'
        self.assertEqual(V.folder_check(missing, 'lib1'), ('ok', '', 0))
        empty = self.root / 'empty'
        empty.mkdir()
        self.assertEqual(V.folder_check(empty, 'lib1'), ('ok', '', 0))
        obs = self.root / 'obs'
        (obs / '.obsidian').mkdir(parents=True)
        (obs / '.obsidian' / 'app.json').write_text('{}')
        self.assertEqual(V.folder_check(obs, 'lib1'), ('ok', '', 0))
        mine = self.root / 'mine'
        (mine / 'Brainamon').mkdir(parents=True)
        V.write_manifest(mine, V.new_manifest('lib1'))
        self.assertEqual(V.folder_check(mine, 'lib1'), ('ok', '', 0))
        theirs = self.root / 'theirs'
        theirs.mkdir()
        V.write_manifest(theirs, V.new_manifest('other'))
        self.assertEqual(V.folder_check(theirs, 'lib1'), ('takeover', V.TAKEOVER, 0))
        few = self.root / 'few'
        (few / '.obsidian').mkdir(parents=True)
        (few / 'Welcome.md').write_text('hi')
        (few / 'Daily').mkdir()
        state, msg, n = V.folder_check(few, 'lib1')
        self.assertEqual((state, n), ('confirm', 2))
        self.assertIn('2', msg)
        many = self.root / 'many'
        many.mkdir()
        for i in range(6):
            (many / f'n{i}.md').write_text('x')
        self.assertEqual(V.folder_check(many, 'lib1'), ('refused', V.TOO_MANY, 6))
        afile = self.root / 'afile'
        afile.write_text('x')
        self.assertEqual(V.folder_check(afile, 'lib1')[0], 'refused')

    def test_obsidian_vault_list_reads_only_the_known_shape(self):
        f = self.root / 'obsidian.json'
        self.assertEqual(V.obsidian_vaults(f), [])                      # missing
        f.write_text('{broken', encoding='utf-8')
        self.assertEqual(V.obsidian_vaults(f), [])                      # unreadable
        f.write_text(json.dumps({'vaults': {'24dd4224843cf085': {'path': 'D:\\V\\One', 'ts': 1780755098131, 'open': True},
                                            'bad': {'ts': 1}, 'x': 'nope'}, 'cli': True}), encoding='utf-8')
        self.assertEqual(V.obsidian_vaults(f), [{'path': 'D:\\V\\One', 'open': True, 'ts': 1780755098131}])
        f.write_text(json.dumps({'vaults': []}), encoding='utf-8')
        self.assertEqual(V.obsidian_vaults(f), [])


def files_of(**pages):
    """{rel: text} -> the render() shape."""
    return {rel: {'data': text.encode('utf-8'), 'source': 'item', 'key': rel} for rel, text in pages.items()}


class OwnershipTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.vault = Path(td.name) / 'vault'
        self.man = V.new_manifest('lib1')

    def read(self, rel):
        return (self.vault / rel).read_text(encoding='utf-8')

    def test_progress_counts_checks_writes_and_removals(self):
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/old.md': 'old'}))
        events = []
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/new.md': 'new'}),
                       progress=lambda *args: events.append(args))
        self.assertEqual(events, [('checking', 0, 2), ('checking', 1, 2), ('checking', 2, 2),
                                  ('saving', 0, 2), ('saving', 1, 2), ('saving', 2, 2)])
        events.clear()
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/new.md': 'new'}),
                       progress=lambda *args: events.append(args))
        self.assertEqual(events, [('checking', 0, 1), ('checking', 1, 1)])

    def test_unchanged_listed_file_is_updated(self):
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'v1'}))
        self.assertEqual(self.read('Brainamon/Items/a-1.md'), 'v1')
        r = V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'v2'}))
        self.assertEqual(self.read('Brainamon/Items/a-1.md'), 'v2')
        self.assertEqual((r['written'], r['adopted']), (1, []))
        self.assertEqual(V.read_manifest(self.vault)['files']['Brainamon/Items/a-1.md']['hash'], V.data_hash(b'v2'))
        same = V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'v2'}))
        self.assertEqual(same['written'], 0)                             # same bytes: not rewritten

    def test_edited_listed_file_is_adopted(self):
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'v1'}))
        (self.vault / 'Brainamon/Items/a-1.md').write_text('my edit', encoding='utf-8')
        r = V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'v2'}))
        self.assertEqual(self.read('Brainamon/Items/a-1.md'), 'my edit')
        self.assertEqual(r['adopted'], ['Brainamon/Items/a-1.md'])
        r = V.apply_render(self.vault, self.man, files_of())              # the item is gone: still never removed
        self.assertTrue((self.vault / 'Brainamon/Items/a-1.md').exists())
        self.assertEqual(r['adopted'], ['Brainamon/Items/a-1.md'])

    def test_unlisted_file_is_never_touched(self):
        (self.vault / 'Brainamon' / 'Items').mkdir(parents=True)
        (self.vault / 'Brainamon' / 'Items' / 'a-1.md').write_text('user file', encoding='utf-8')
        (self.vault / 'Mine.md').write_text('outside', encoding='utf-8')
        r = V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'generated', 'Brainamon/Items/b-2.md': 'new'}))
        self.assertEqual(self.read('Brainamon/Items/a-1.md'), 'user file')
        self.assertEqual(r['unlisted'], ['Brainamon/Items/a-1.md'])
        self.assertEqual(self.read('Brainamon/Items/b-2.md'), 'new')
        self.assertEqual(self.read('Mine.md'), 'outside')
        self.assertNotIn('Brainamon/Items/a-1.md', V.read_manifest(self.vault)['files'])

    def test_removed_only_if_unchanged(self):
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'a', 'Brainamon/Items/b-2.md': 'b'}))
        (self.vault / 'Brainamon/Items/b-2.md').write_text('kept by hand', encoding='utf-8')
        r = V.apply_render(self.vault, self.man, files_of())
        self.assertFalse((self.vault / 'Brainamon/Items/a-1.md').exists())
        self.assertEqual(self.read('Brainamon/Items/b-2.md'), 'kept by hand')
        self.assertEqual((r['removed'], r['adopted']), (1, ['Brainamon/Items/b-2.md']))

    def test_missing_listed_file_comes_back(self):
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'a'}))
        (self.vault / 'Brainamon/Items/a-1.md').unlink()
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'a'}))
        self.assertEqual(self.read('Brainamon/Items/a-1.md'), 'a')

    def test_lost_manifest_writes_only_new_files(self):
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'a', 'Brainamon/Items/b-2.md': 'b'}))
        (self.vault / V.MANIFEST).unlink()
        self.assertIsNone(V.read_manifest(self.vault))
        fresh = V.new_manifest('lib1')
        r = V.apply_render(self.vault, fresh, files_of(**{'Brainamon/Items/a-1.md': 'a2', 'Brainamon/Items/c-3.md': 'c'}))
        self.assertEqual(self.read('Brainamon/Items/a-1.md'), 'a')            # existing: untouched
        self.assertTrue((self.vault / 'Brainamon/Items/b-2.md').exists())       # not removed either
        self.assertEqual(self.read('Brainamon/Items/c-3.md'), 'c')            # new: written
        self.assertEqual(sorted(r['unlisted']), ['Brainamon/Items/a-1.md'])
        self.assertEqual(list(fresh['files']), ['Brainamon/Items/c-3.md'])

    def test_copies_are_written_and_hashed(self):
        src = self.vault.parent / 'report.md'
        src.write_text('# report', encoding='utf-8')
        files = {'Brainamon/Reports/7.md': {'src': str(src), 'source': 'report', 'key': '7'}}
        V.apply_render(self.vault, self.man, files)
        self.assertEqual(self.read('Brainamon/Reports/7.md'), '# report')
        self.assertEqual(self.man['files']['Brainamon/Reports/7.md']['hash'], V.file_hash(src))
        src.unlink()
        r = V.apply_render(self.vault, self.man, files)                        # source vanished: skipped, kept
        self.assertEqual(r['written'], 0)
        self.assertTrue((self.vault / 'Brainamon/Reports/7.md').exists())

    def test_interrupted_render_settles_pending(self):
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'a1', 'Brainamon/Items/d-4.md': 'd1'}))
        real = V.write_manifest
        calls = []

        def crash_on_second(vault, man):
            calls.append(1)
            if len(calls) == 2:
                raise OSError('power cut')
            real(vault, man)
        with mock.patch.object(V, 'write_manifest', crash_on_second):
            with self.assertRaises(OSError):
                V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'a2', 'Brainamon/Items/b-2.md': 'b1', 'Brainamon/Items/d-4.md': 'd2'}))
        # the pages were written, the manifest on disk still says pending
        self.assertEqual(self.read('Brainamon/Items/a-1.md'), 'a2')
        self.assertEqual(self.read('Brainamon/Items/b-2.md'), 'b1')
        on_disk = V.read_manifest(self.vault)
        self.assertEqual(len(on_disk['pending']), 3)
        (self.vault / 'Brainamon/Items/d-4.md').write_text('edited by hand after the crash', encoding='utf-8')
        # restart: the next pass settles
        r = V.apply_render(self.vault, on_disk, files_of(**{'Brainamon/Items/a-1.md': 'a2', 'Brainamon/Items/b-2.md': 'b1', 'Brainamon/Items/d-4.md': 'd2'}))
        self.assertEqual(r['adopted'], ['Brainamon/Items/d-4.md'])          # the real edit
        self.assertEqual(r['unlisted'], [])                                   # b-2 is listed, not unlisted
        self.assertEqual(r['written'], 0)                                     # a-1 recorded as written, not rewritten
        settled = V.read_manifest(self.vault)
        self.assertNotIn('pending', settled)
        self.assertEqual(settled['files']['Brainamon/Items/a-1.md']['hash'], V.data_hash(b'a2'))
        self.assertEqual(settled['files']['Brainamon/Items/b-2.md']['hash'], V.data_hash(b'b1'))
        self.assertEqual(settled['files']['Brainamon/Items/d-4.md']['hash'], V.data_hash(b'd1'))   # old entry kept: adopted


    def test_removed_records_only_while_vault_sync_is_on(self):
        """Spec 1b decision 2: a generated file the render removes leaves {path: the hash Brainamon last wrote};
        an adopted file never does; a path rendered again drops its record; with vault sync off (track_removed
        False, Fred 2026-10-28) the records are cleared."""
        files = files_of(**{'Brainamon/Items/a-1.md': 'a', 'Brainamon/Items/b-2.md': 'b', 'Brainamon/Items/c-3.md': 'c'})
        V.apply_render(self.vault, self.man, files, track_removed=True)
        self.assertNotIn('removed', self.man)
        (self.vault / 'Brainamon/Items/b-2.md').write_text('kept by hand', encoding='utf-8')
        (self.vault / 'Brainamon/Items/c-3.md').unlink()                       # deleted by hand on the PC: still a removal
        r = V.apply_render(self.vault, self.man, files_of(), track_removed=True)
        self.assertEqual(r['removed'], 2)
        self.assertEqual(self.man['removed'], {'Brainamon/Items/a-1.md': V.data_hash(b'a'), 'Brainamon/Items/c-3.md': V.data_hash(b'c')})
        self.assertEqual(V.read_manifest(self.vault)['removed'], self.man['removed'])
        # the item came back: the page is written again and its record goes
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'a2'}), track_removed=True)
        self.assertEqual(self.man['removed'], {'Brainamon/Items/c-3.md': V.data_hash(b'c')})
        # vault sync off: nothing to tell a phone, the records are cleared
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'a2'}))
        self.assertNotIn('removed', self.man)
        self.assertNotIn('removed', V.read_manifest(self.vault))

    def test_generated_paths_are_listed_and_unchanged(self):
        """Spec 1b decision 1: the generated set is the listed paths whose file still carries the recorded hash."""
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'a', 'Brainamon/Items/b-2.md': 'b',
                                                         'Brainamon/Items/c-3.md': 'c', 'Brainamon/Knowledge Map.md': 'map'}))
        (self.vault / 'Brainamon/Items/b-2.md').write_text('edited', encoding='utf-8')
        (self.vault / 'Brainamon/Items/c-3.md').unlink()
        (self.vault / 'Brainamon/Notes').mkdir(parents=True)
        (self.vault / 'Brainamon/Notes/mine.md').write_text('unlisted', encoding='utf-8')
        self.assertEqual(V.generated_paths(self.vault, self.man), {'Brainamon/Items/a-1.md', 'Brainamon/Knowledge Map.md'})
        self.assertEqual(V.generated_paths(self.vault, V.new_manifest('lib1')), set())

    def test_generated_check_reports_counts_and_can_stop_between_files(self):
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/a.md': 'a', 'Brainamon/b.md': 'b'}))
        events = []
        report = lambda *args: events.append(args)
        self.assertEqual(V.generated_paths(self.vault, self.man, progress=report), set(self.man['files']))
        self.assertEqual(events, [('Checking generated notes', n, 2) for n in range(3)])
        events.clear()
        with mock.patch.object(V, 'file_hash', wraps=V.file_hash) as hashed:
            with self.assertRaisesRegex(OSError, 'stopping'):
                V.generated_paths(self.vault, self.man, progress=report,
                                  should_stop=lambda: bool(events and events[-1][1] == 1))
            self.assertEqual(hashed.call_count, 1)

    def test_removal_records_survive_a_crash_before_final_manifest_save(self):
        rel = 'Brainamon/Items/a.md'
        for action in ('render', 'reset', 'leftovers'):
            with self.subTest(action):
                root = self.vault / action
                man = V.new_manifest('lib1')
                V.apply_render(root, man, files_of(**{rel: 'generated'}), track_removed=True)
                if action == 'leftovers':
                    man['released'], man['files'] = man['files'], {}
                    V.write_manifest(root, man)
                original = V.write_manifest
                calls = []

                def cut_before_commit(vault, value):
                    calls.append(1)
                    if len(calls) == 2:
                        raise OSError('power cut after unlink')
                    original(vault, value)

                with mock.patch.object(V, 'write_manifest', cut_before_commit):
                    with self.assertRaisesRegex(OSError, 'power cut'):
                        if action == 'render':
                            V.apply_render(root, man, {}, track_removed=True)
                        elif action == 'reset':
                            V.reset_page(root, man, rel, {})
                        else:
                            V.remove_leftovers(root, man)
                self.assertFalse((root / rel).exists())
                recovered = V.read_manifest(root)
                self.assertTrue(recovered['pending'])
                V.settle_pending(root, recovered)
                self.assertEqual(recovered['removed'], {rel: V.data_hash(b'generated')})
                self.assertNotIn(rel, recovered['files'])
                self.assertNotIn(rel, recovered.get('released') or {})
                V.write_manifest(root, recovered)
                V.apply_render(root, recovered, {}, track_removed=True)
                self.assertEqual(V.read_manifest(root)['removed'], {rel: V.data_hash(b'generated')})
                V.apply_render(root, recovered, {}, track_removed=False)
                self.assertNotIn('removed', V.read_manifest(root))

    def test_unfinished_removal_does_not_claim_a_deletion(self):
        rel = 'Brainamon/Items/a.md'
        V.apply_render(self.vault, self.man, files_of(**{rel: 'generated'}))
        old = V.data_hash(b'generated')
        for text in ('generated', 'user edit'):
            (self.vault / rel).write_text(text, encoding='utf-8')
            self.man['pending'] = [{'path': rel, 'old': old, 'new': None, 'record_removed': True}]
            V.settle_pending(self.vault, self.man)
            self.assertNotIn('removed', self.man)
            self.assertIn(rel, self.man['files'])
            self.assertEqual((self.vault / rel).read_text(encoding='utf-8'), text)

class ActionsTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.vault = Path(td.name) / 'vault'
        self.man = V.new_manifest('lib1')

    def test_reset_page(self):
        files = files_of(**{'Brainamon/Items/a-1.md': 'gen', 'Brainamon/Items/b-2.md': 'gen b'})
        V.apply_render(self.vault, self.man, files)
        (self.vault / 'Brainamon/Items/a-1.md').write_text('edited', encoding='utf-8')
        (self.vault / 'Brainamon/Items/b-2.md').write_text('edited b', encoding='utf-8')
        V.reset_page(self.vault, self.man, 'Brainamon/Items/a-1.md', files)
        self.assertEqual((self.vault / 'Brainamon/Items/a-1.md').read_text(encoding='utf-8'), 'gen')
        self.assertEqual(self.man['files']['Brainamon/Items/a-1.md']['hash'], V.data_hash(b'gen'))
        # the source is gone: Reset removes the page
        V.reset_page(self.vault, self.man, 'Brainamon/Items/b-2.md', files_of(**{'Brainamon/Items/a-1.md': 'gen'}))
        self.assertFalse((self.vault / 'Brainamon/Items/b-2.md').exists())
        self.assertNotIn('Brainamon/Items/b-2.md', self.man['files'])
        with self.assertRaises(V.VaultError):
            V.reset_page(self.vault, self.man, 'Mine.md', files)            # unlisted: never

    def test_reclaim_generated_pages(self):
        b = self.vault / 'Brainamon'
        (b / 'Items').mkdir(parents=True)
        (b / 'Items' / 'a-1.md').write_text('---\nid: 1\nsource: brainamon\n---\n# a', encoding='utf-8')
        (b / 'Items' / 'mine.md').write_text('# my own page', encoding='utf-8')
        (b / 'Items' / 'tricky.md').write_text('# no frontmatter\nsource: brainamon in the body', encoding='utf-8')
        (b / 'Reports').mkdir()
        (b / 'Reports' / '1.md').write_text('# report', encoding='utf-8')
        (b / 'Notes').mkdir()
        (b / 'Notes' / 'n.md').write_text('note', encoding='utf-8')
        (b / 'Notes' / 'mine.md').write_text('a note of mine saved here', encoding='utf-8')
        (self.vault / 'Outside.md').write_text('---\nsource: brainamon\n---\nx', encoding='utf-8')
        files = files_of(**{'Brainamon/Reports/1.md': 'r', 'Brainamon/Notes/n.md': 'n'})     # what the render produces
        n = V.reclaim(self.vault, self.man, files)
        self.assertEqual(n, 3)
        self.assertEqual(sorted(self.man['files']), ['Brainamon/Items/a-1.md', 'Brainamon/Notes/n.md', 'Brainamon/Reports/1.md'])
        self.assertEqual(V.reclaim(self.vault, self.man, files), 0)                       # mine.md stays the user's
        # a reclaimed page is now Brainamon's again: the next render updates it
        r = V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'regenerated'}))
        self.assertEqual((self.vault / 'Brainamon/Items/a-1.md').read_text(encoding='utf-8'), 'regenerated')
        self.assertEqual(r['adopted'], [])

    def test_take_over_refreshes_matches_and_keeps_leftovers(self):
        def page(iid, url, body='old'):
            return f'---\nid: {iid}\nurl: {P._yaml_value(url)}\n{P.SOURCE_LINE}\n---\n# {body}\n'
        old = V.new_manifest('other')
        V.apply_render(self.vault, old, files_of(**{
            'Brainamon/Items/swing-1.md': page(1, 'https://x/1'),       # same id and link here: the same item
            'Brainamon/Items/press-2.md': page(2, 'https://x/2'),       # id 2 is another item here
            'Brainamon/Items/gone-3.md': page(3, 'https://x/3'),        # not in this library
            'Brainamon/Items/edited-4.md': page(4, 'https://x/4'),
            'Brainamon/Knowledge Map.md': 'old map'}))
        old['names'] = {'item': {'1': 'swing-1', '2': 'press-2', '3': 'gone-3', '4': 'edited-4'},
                        'topic': {'t-1': 'old-topic-t1'}, 'tag': {'kb': 'kb'}}
        V.write_manifest(self.vault, old)
        (self.vault / 'Brainamon/Items/edited-4.md').write_text(page(4, 'https://x/4', 'my edit'), encoding='utf-8')
        for i in range(6):
            (self.vault / f'own{i}.md').write_text('mine', encoding='utf-8')
        # setup asks for take-over; the 5-file rule does not apply
        self.assertEqual(V.folder_check(self.vault, 'lib1'), ('takeover', V.TAKEOVER, 5))
        man = V.read_manifest(self.vault)
        V.settle_pending(self.vault, man)
        V.keep_names(self.vault, man, {'1': 'https://x/1', '2': 'https://x/other', '4': 'https://x/4'})
        self.assertEqual(man['names'], {'item': {'1': 'swing-1', '4': 'edited-4'}, 'tag': {'kb': 'kb'}})
        files = files_of(**{'Brainamon/Items/swing-1.md': 'new swing', 'Brainamon/Items/other-2.md': 'new other',
                            'Brainamon/Items/edited-4.md': 'gen 4', 'Brainamon/Knowledge Map.md': 'new map'})
        edited, matched, leftovers = V.takeover_split(self.vault, man, files)
        self.assertEqual(edited, ['Brainamon/Items/edited-4.md'])
        self.assertEqual(matched, ['Brainamon/Items/swing-1.md', 'Brainamon/Knowledge Map.md'])
        self.assertEqual(leftovers, ['Brainamon/Items/gone-3.md', 'Brainamon/Items/press-2.md'])
        self.assertIn('refreshes the 2 page(s) that match', V.takeover_message(1, 2, 2))
        self.assertIn('2 page(s) are about items or topics', V.takeover_message(1, 2, 2))
        self.assertNotIn('remove them', V.takeover_message(1, 2, 0))
        V.take_over(self.vault, man, 'lib1', files)
        man = V.read_manifest(self.vault)
        self.assertEqual((man['library_id'], man['vault_id']), ('lib1', old['vault_id']))     # the vault keeps its id
        self.assertEqual(sorted(man['released']), leftovers)
        r = V.apply_render(self.vault, man, files)
        read = lambda rel: (self.vault / rel).read_text(encoding='utf-8')
        self.assertEqual(r['removed'], 0)
        self.assertEqual(r['adopted'], ['Brainamon/Items/edited-4.md'])
        self.assertEqual((read('Brainamon/Items/swing-1.md'), read('Brainamon/Knowledge Map.md'), read('Brainamon/Items/other-2.md')),
                         ('new swing', 'new map', 'new other'))
        self.assertIn('# my edit', read('Brainamon/Items/edited-4.md'))
        self.assertIn('# old', read('Brainamon/Items/press-2.md'))                 # leftovers untouched
        self.assertIn('# old', read('Brainamon/Items/gone-3.md'))
        self.assertEqual(read('own0.md'), 'mine')
        # an item that comes back takes its leftover page back
        back = {**files, **files_of(**{'Brainamon/Items/gone-3.md': 'back'})}
        V.rejoin_released(self.vault, man, back)
        V.apply_render(self.vault, man, back)
        self.assertEqual(read('Brainamon/Items/gone-3.md'), 'back')
        # Remove leftovers: the unchanged leftover goes
        self.assertEqual(V.remove_leftovers(self.vault, man), 1)
        self.assertFalse((self.vault / 'Brainamon/Items/press-2.md').exists())
        self.assertEqual(V.read_manifest(self.vault)['released'], {})

    def test_take_over_and_remove(self):
        old = V.new_manifest('other')
        V.apply_render(self.vault, old, files_of(**{'Brainamon/Items/gone-3.md': 'old', 'Brainamon/Items/kept-5.md': 'old'}))
        (self.vault / 'Brainamon/Items/kept-5.md').write_text('my edit', encoding='utf-8')
        man = V.read_manifest(self.vault)
        files = files_of(**{'Brainamon/Knowledge Map.md': 'map'})
        V.take_over(self.vault, man, 'lib1', files, remove=True)
        r = V.apply_render(self.vault, man, files)
        self.assertFalse((self.vault / 'Brainamon/Items/gone-3.md').exists())
        self.assertEqual((self.vault / 'Brainamon/Items/kept-5.md').read_text(encoding='utf-8'), 'my edit')
        self.assertEqual(r['adopted'], ['Brainamon/Items/kept-5.md'])


    def test_reset_settles_a_previous_interrupted_removal(self):
        removed, target = 'Brainamon/Items/a.md', 'Brainamon/Items/b.md'
        V.apply_render(self.vault, self.man, files_of(**{removed: 'a', target: 'b'}), track_removed=True)
        self.man['pending'] = [{'path': removed, 'old': V.data_hash(b'a'), 'new': None, 'record_removed': True}]
        V.write_manifest(self.vault, self.man)
        (self.vault / removed).unlink()
        V.reset_page(self.vault, V.read_manifest(self.vault), target, files_of(**{target: 'new b'}))
        saved = V.read_manifest(self.vault)
        self.assertEqual(saved['removed'], {removed: V.data_hash(b'a')})
        self.assertNotIn(removed, saved['files'])
        self.assertEqual((self.vault / target).read_text(encoding='utf-8'), 'new b')

    def test_reset_and_remove_leftovers_record_removals(self):
        """Reset to generated on a page whose source is gone, and Remove leftovers, delete generated files too:
        both leave a deletion record (cleared by the next render when vault sync is off)."""
        V.apply_render(self.vault, self.man, files_of(**{'Brainamon/Items/a-1.md': 'gen'}), track_removed=True)
        (self.vault / 'Brainamon/Items/a-1.md').write_text('edited', encoding='utf-8')
        V.reset_page(self.vault, self.man, 'Brainamon/Items/a-1.md', files_of())
        self.assertEqual(self.man['removed'], {'Brainamon/Items/a-1.md': V.data_hash(b'gen')})   # the hash Brainamon wrote, not the edit
        old = V.new_manifest('other')
        V.apply_render(self.vault, old, files_of(**{'Brainamon/Items/gone-3.md': 'old', 'Brainamon/Items/kept-5.md': 'old'}))
        (self.vault / 'Brainamon/Items/kept-5.md').write_text('my edit', encoding='utf-8')
        man = V.read_manifest(self.vault)
        V.take_over(self.vault, man, 'lib1', files_of(**{'Brainamon/Knowledge Map.md': 'map'}))
        self.assertEqual(V.remove_leftovers(self.vault, man), 1)
        self.assertEqual(man['removed'], {'Brainamon/Items/gone-3.md': V.data_hash(b'old')})
        self.assertEqual(V.read_manifest(self.vault)['removed'], man['removed'])
        V.apply_render(self.vault, man, files_of(**{'Brainamon/Knowledge Map.md': 'map'}))
        self.assertNotIn('removed', man)

    def test_new_manifest_reuses_a_recorded_vault_id(self):
        self.assertEqual(V.new_manifest('lib1', 'abc123')['vault_id'], 'abc123')
        self.assertNotEqual(V.new_manifest('lib1')['vault_id'], V.new_manifest('lib1')['vault_id'])
        self.assertEqual(len(V.new_manifest('lib1', None)['vault_id']), 32)

class MoveTest(unittest.TestCase):
    def test_move_copies_everything_but_content_manager(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        old, new = root / 'Fredorama', root / 'Documents' / 'Brainamon Vault'
        (old / '.obsidian').mkdir(parents=True)
        (old / '.obsidian' / 'app.json').write_text('{}', encoding='utf-8')
        (old / '.trash').mkdir()
        (old / '.trash' / 'gone.md').write_text('trashed', encoding='utf-8')
        (old / 'Personal').mkdir()
        (old / 'Personal' / 'diary.md').write_text('mine', encoding='utf-8')
        (old / 'Content Manager' / 'items').mkdir(parents=True)
        (old / 'Content Manager' / 'items' / 'x.md').write_text('generated', encoding='utf-8')
        n = V.move(old, new)
        self.assertEqual(n, 3)
        self.assertEqual((new / '.obsidian' / 'app.json').read_text(encoding='utf-8'), '{}')
        self.assertEqual((new / '.trash' / 'gone.md').read_text(encoding='utf-8'), 'trashed')
        self.assertEqual((new / 'Personal' / 'diary.md').read_text(encoding='utf-8'), 'mine')
        self.assertFalse((new / 'Content Manager').exists())
        # the old vault is never deleted
        self.assertTrue((old / 'Personal' / 'diary.md').exists() and (old / 'Content Manager' / 'items' / 'x.md').exists())

    def test_move_stops_on_mismatch_and_on_cancel(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        old, new = root / 'old', root / 'new'
        old.mkdir()
        (old / 'a.md').write_text('a', encoding='utf-8')
        real = V.file_hash
        with mock.patch.object(V, 'file_hash', lambda p: 'bad' if Path(p).parent == new else real(p)):
            with self.assertRaises(V.VaultError) as cm:
                V.move(old, new)
        self.assertIn('does not match', str(cm.exception))
        self.assertTrue((new / 'a.md').exists())                     # the copy is left for inspection
        with self.assertRaises(V.VaultError):
            V.move(old, root / 'new2', should_stop=lambda: True)


class LibraryIdTest(unittest.TestCase):
    def test_library_id_is_created_once_and_kept(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        db = Database(Path(td.name) / 'content_manager.db')
        self.addCleanup(db.close)
        first = db.library_id()
        self.assertEqual(len(first), 32)
        self.assertEqual(db.library_id(), first)
        self.assertEqual(db.get_setting('library_id'), first)


if __name__ == '__main__':
    unittest.main()
