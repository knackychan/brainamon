// node tests/check_phone_fetch_order.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from '../web/node_modules/typescript/lib/typescript.js'

const source = readFileSync('web/src/mobile/source/mirror.ts', 'utf8')
const methods = ['private names', 'async linkDetails', 'async fillPictures', 'private async fetchPictures'].map(name => {
  const start = source.indexOf(`  ${name}(`)
  assert.ok(start >= 0, name)
  return source.slice(start, source.indexOf('\n  }', start) + 4)
}).join('\n')
const queued = [], fetched = []
const context = { isApp: true, syncPaused: () => false,
  queueWork: (_lane, _kind, ids) => queued.push(Array.from(ids)), startWork() {}, endWork() {}, endLane() {},
  linkInfo: async url => { fetched.push(url); return null }, linkGet() {},
  picturePlan: () => ({ page: true }), cleanLink: url => url,
}
vm.createContext(context)
vm.runInContext(ts.transpileModule(`class Fixture { ${methods} }; globalThis.Fixture = Fixture`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText, context)
const fixture = new context.Fixture()
fixture.manifest = { files: Object.fromEntries([
  'library/part-000.json', 'library/part-002.json', 'library/part-001.json',
  'search/text-001.json.gz', 'search/text-000.json.gz', 'notes/a.md', 'notes/b.md',
].map(name => [name, {}])) }
assert.deepEqual(Array.from(fixture.names('library/part-')), ['library/part-002.json', 'library/part-001.json', 'library/part-000.json'])
assert.deepEqual(Array.from(fixture.names('search/text-')), ['search/text-001.json.gz', 'search/text-000.json.gz'])
assert.deepEqual(Array.from(fixture.names('notes/')), ['notes/a.md', 'notes/b.md'])
fixture.rowsNow = [
  { id: -1, uid: 'old', created: 10, url: 'old' },
  { id: -2, uid: 'new', created: 30, url: 'new' },
  { id: -3, uid: 'middle', created: 20, url: 'middle' },
  { id: 4, uid: 'pc', created: 40, url: 'pc' },
]
fixture.ready = async () => {}
fixture.changes = { list: [] }
fixture.triedLinks = new Set()
fixture.triedPics = new Set()
fixture.picHints = async () => ({})
await fixture.linkDetails()
assert.deepEqual(queued.pop(), [-2, -3, -1])
assert.deepEqual(fetched, ['new', 'middle', 'old'])
await fixture.fillPictures(() => {}, () => true)
assert.deepEqual(queued.pop(), [-2, -3, -1])
assert.deepEqual(fixture.rowsNow.map(r => r.id), [-1, -2, -3, 4], 'queue sorting must not mutate library storage')
fixture.triedLinks.clear()
await fixture.linkDetails([-1, -3])
assert.deepEqual(queued.pop(), [-3, -1])
console.log('Phone content and picture queues fetch newest first.')
