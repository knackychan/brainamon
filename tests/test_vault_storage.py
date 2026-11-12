"""Vault checkpoints require a committed IndexedDB write before replacing files."""
import unittest

from tests.test_phone_js import _node_ok, node


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class VaultStorageTest(unittest.TestCase):
    def test_required_writes_wait_for_commit_and_reject_storage_failures(self):
        node(r"""
            import assert from 'node:assert/strict'
            const tick = () => new Promise(resolve => setImmediate(resolve))
            let serial = 0
            async function fixture(mode = '') {
              const transactions = [], requests = [], writes = []
              const quota = new DOMException('synthetic quota exhausted', 'QuotaExceededError')
              const db = { transaction(name, access) {
                assert.equal(name,'kv'); assert.equal(access,'readwrite')
                if (mode === 'throw-transaction') throw quota
                const t = { error:null, objectStore(store) {
                  assert.equal(store,'kv')
                  return { put(value,key) {
                    if (mode === 'throw-put') throw quota
                    writes.push([key,structuredClone(value)])
                    const r = {}; requests.push(r); return r
                  } }
                } }
                transactions.push(t); return t
              } }
              globalThis.indexedDB = { open() {
                if (mode === 'throw-open') throw Error('synthetic unavailable storage')
                const r = {result:db}
                queueMicrotask(() => mode === 'unavailable' ? r.onerror() : r.onsuccess())
                return r
              } }
              const {kv} = await import(`./web/src/mobile/store.ts?vault-storage=${++serial}`)
              return {kv,transactions,requests,writes,quota}
            }
            const value = {base:{'note.md':'old'},cache:{}}
            const f = await fixture()
            let completed = false
            const pending = f.kv.setRequired('vault-state',value).then(() => { completed = true })
            await tick()
            assert.deepEqual(f.writes,[['vault-state',value]])
            f.requests[0].onsuccess?.()
            await tick()
            assert.equal(completed,false,'request success is not a committed checkpoint')
            f.transactions[0].oncomplete()
            await pending
            assert.equal(completed,true)

            for (const event of ['onerror','onabort']) {
              const f = await fixture()
              const writing = f.kv.setRequired('vault-state',value)
              const rejected = assert.rejects(writing,/Phone storage could not save vault sync progress/)
              await tick()
              f.requests[0].onsuccess?.()
              f.transactions[0][event]()
              await rejected
            }
            const q = await fixture()
            const writing = q.kv.setRequired('vault-state',value)
            const rejected = assert.rejects(writing,e => e === q.quota)
            await tick(); q.transactions[0].error = q.quota; q.transactions[0].onabort()
            await rejected
            for (const mode of ['unavailable','throw-open','throw-transaction','throw-put']) {
              const f = await fixture(mode)
              await assert.rejects(() => f.kv.setRequired('vault-state',value),
                mode.startsWith('throw-') && mode !== 'throw-open' ? /synthetic quota/ : /Phone storage could not save vault sync progress/)
            }
        """, timeout=10)

    def test_sync_vault_propagates_required_checkpoint_failure(self):
        node(r"""
            import assert from 'node:assert/strict'
            import { readFileSync } from 'node:fs'
            import { stripTypeScriptTypes } from 'node:module'
            const text = readFileSync('web/src/mobile/source/mirror.ts','utf8')
            const start = text.indexOf('  async syncVault(')
            const end = text.indexOf('\n  // the PC\'s last vault round',start)
            assert.ok(start > 0 && end > start)
            let fail = false, saves = 0
            const state = {base:{'note.md':'old'},cache:{}}
            const kv = {
              get:async key => { assert.equal(key,'vault'); return {on:true,uri:'content://synthetic-vault'} },
              set:async () => { throw Error('vault checkpoint used the optional write helper') },
              setRequired:async (key,value) => {
                assert.equal(key,'vault-state'); assert.deepEqual(value,state); saves++
                if (fail) throw Error('synthetic checkpoint quota failure')
              },
            }
            const vaultRound = async env => { await env.save(state); return {state:'idle',reason:'',summary:'fixture'} }
            const Source = new Function('kv','vaultFs','vaultRound','deviceId',
              stripTypeScriptTypes('class Source {\n'+text.slice(start,end)+'\n}')+'; return Source')(
                kv, () => ({}), vaultRound, () => 'test-phone')
            const source = new Source()
            source.nativeReady = async () => false
            source.drive = {authorize:async () => {}}
            source.key = Promise.resolve({})
            assert.equal((await source.syncVault()).state,'idle')
            fail = true
            await assert.rejects(() => source.syncVault(),/synthetic checkpoint quota failure/)
            assert.equal(saves,2)
        """, timeout=10)
