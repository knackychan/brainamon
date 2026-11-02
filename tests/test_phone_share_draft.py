"""The share target makes a DRAFT, never an item or a note (projects/note-organic-ui/plans/09-add-to-brainamon.md).
web/public/sw.js runs under Node's vm with a small stand-in for IndexedDB: what is shared lands in
kv 'drafts' in the shape src/lib/capture.ts newDraft() makes, earlier drafts are kept, the outbox (the
Library's queue) stays empty, and a failing IndexedDB falls back to handing the text to the page.
Skips without Node 22.6+."""
import json
import unittest

from tests.test_phone_js import TS_RESOLVE, _node_ok, node

HARNESS = TS_RESOLVE + """
import fs from 'node:fs'
import vm from 'node:vm'
const { newDraft } = await import('./web/src/lib/capture.ts')

function fakeIndexedDB(fail = false) {
  const stores = { kv: new Map(), outbox: new Map(), items: new Map(), files: new Map(), changes: new Map() }
  let seq = 0
  const db = {
    objectStoreNames: { contains: n => n in stores }, createObjectStore() {}, close() {},
    transaction(name) {
      const st = stores[name]
      const t = { oncomplete: null, onerror: null, onabort: null, error: null }
      t.objectStore = () => ({
        get(k) { const r = {}; queueMicrotask(() => { r.result = st.get(k); r.onsuccess && r.onsuccess() }); return r },
        put(v, k) { st.set(k ?? ++seq, v) },
        add(v) { st.set(++seq, v) },
      })
      setTimeout(() => t.oncomplete && t.oncomplete(), 5)
      return t
    },
  }
  return { stores, indexedDB: { open() {
    const rq = { result: db, error: new Error('no storage') }
    setTimeout(() => { if (fail) return rq.onerror && rq.onerror(); rq.onupgradeneeded && rq.onupgradeneeded(); rq.onsuccess && rq.onsuccess() }, 0)
    return rq
  } } }
}

function load(fail = false) {
  const fake = fakeIndexedDB(fail)
  const ctx = {
    self: { addEventListener() {} }, location: { origin: 'x' }, indexedDB: fake.indexedDB, setTimeout, queueMicrotask,
    Response: { redirect: (url, status) => ({ url, status }) },
  }
  vm.createContext(ctx)
  vm.runInContext(fs.readFileSync('web/public/sw.js', 'utf8'), ctx)
  const req = fields => ({ formData: async () => new Map(Object.entries(fields)) })
  return { fake, ctx, share: f => ctx.share(req(f)) }
}
"""


def run(body: str):
    return json.loads(node(HARNESS + body))


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class ShareMakesADraftTest(unittest.TestCase):
    def test_a_shared_link_waits_as_a_draft_and_nothing_is_queued(self):
        out = run("""
            const { fake, share } = load()
            const r = await share({ share_url: 'https://www.instagram.com/reel/abc/?igsh=zzz&utm_source=x' })
            console.log(JSON.stringify({ r, drafts: fake.stores.kv.get('drafts'), outbox: fake.stores.outbox.size, items: fake.stores.items.size, changes: fake.stores.changes.size }))
        """)
        self.assertEqual(out['r'], {'url': '/mobile.html?shared=1#/cap', 'status': 303})
        self.assertEqual(len(out['drafts']), 1)
        d = out['drafts'][0]
        self.assertEqual((d['origin'], d['text'], d['pic'], d['dest']), ('share', 'https://www.instagram.com/reel/abc/', None, ''))
        self.assertEqual((out['outbox'], out['items'], out['changes']), (0, 0, 0), 'nothing is created before Save')

    def test_share_text_around_a_link_is_kept_as_shared(self):
        out = run("""
            const { fake, share } = load()
            await share({ share_text: 'Look at this https://example.com/a?igsh=1', share_title: 'A title' })
            console.log(JSON.stringify(fake.stores.kv.get('drafts')))
        """)
        self.assertEqual(out[0]['text'], 'Look at this https://example.com/a?igsh=1\nA title')

    def test_a_link_with_only_its_page_title_is_a_lone_link_named_by_the_title(self):
        out = run("""
            const { fake, share } = load()
            await share({ share_url: 'https://www.youtube.com/watch?v=abc&si=zz', share_title: 'Knife skills' })
            console.log(JSON.stringify(fake.stores.kv.get('drafts')[0]))
        """)
        self.assertEqual((out['text'], out['title']), ('https://www.youtube.com/watch?v=abc', 'Knife skills'))

    def test_the_service_worker_splits_a_share_like_the_page(self):
        cases = ['https://a.com/x?igsh=1', 'https://a.com/x\nTitle', 'Title\nhttps://a.com/x', 'Look https://a.com/x',
                 'https://a.com/x\nhttps://b.com/y', 'one\ntwo\nhttps://a.com/x', 'plain words', '']
        out = run(f"""
            const {{ ctx }} = load()
            const {{ shareParts }} = await import('./web/src/lib/capture.ts')
            console.log(JSON.stringify({json.dumps(cases)}.map(t => [shareParts(t), ctx.shareParts(t)])))
        """)
        for text, (page, sw) in zip(cases, out):
            self.assertEqual(page, sw, text)

    def test_a_second_share_keeps_the_first_draft(self):
        out = run("""
            const { fake, share } = load()
            await share({ share_text: 'first' })
            await share({ share_text: 'second' })
            console.log(JSON.stringify(fake.stores.kv.get('drafts').map(d => d.text)))
        """)
        self.assertEqual(out, ['first', 'second'])

    def test_a_shared_file_is_a_draft_with_its_blob(self):
        out = run("""
            const { fake, share } = load()
            const file = new File(['png bytes'], 'screen.png', { type: 'image/png' })
            const r = await share({ share_file: file, share_title: 'Screenshot' })
            const d = fake.stores.kv.get('drafts')[0]
            console.log(JSON.stringify({ r, origin: d.origin, text: d.text, name: d.pic.name, type: d.pic.type, isBlob: d.pic.blob instanceof Blob, size: d.pic.blob.size }))
        """)
        self.assertEqual(out['r']['url'], '/mobile.html?shared=1#/cap')
        self.assertEqual((out['origin'], out['text'], out['name'], out['type'], out['isBlob'], out['size']),
                         ('file', 'Screenshot', 'screen.png', 'image/png', True, 9))

    def test_an_empty_share_opens_add_without_a_draft(self):
        out = run("""
            const { fake, share } = load()
            const r = await share({})
            console.log(JSON.stringify({ r, kv: fake.stores.kv.size }))
        """)
        self.assertEqual(out['r']['url'], '/mobile.html?share_text=#/cap')
        self.assertEqual(out['kv'], 0)

    def test_without_storage_the_text_goes_to_the_page(self):
        out = run("""
            const { share } = load(true)
            console.log(JSON.stringify(await share({ share_text: 'keep me & more' })))
        """)
        self.assertEqual(out['url'], '/mobile.html?share_text=keep%20me%20%26%20more#/cap')

    def test_the_service_worker_draft_has_the_shape_the_page_makes(self):
        out = run("""
            const { fake, share } = load()
            await share({ share_text: 'x' })
            console.log(JSON.stringify([Object.keys(fake.stores.kv.get('drafts')[0]).sort(), Object.keys(newDraft('share', 'x')).sort()]))
        """)
        self.assertEqual(out[0], out[1])


if __name__ == '__main__':
    unittest.main()
