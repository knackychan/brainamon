"""Completed-file progress, parallel work and restart safety against memory-only vaults."""
import unittest

from tests.test_phone_js import TS_RESOLVE, _node_ok, node


FIXTURE = r"""
    import assert from 'node:assert/strict'
    const { vaultRound, PARALLEL } = await import('./web/src/mobile/vault/sync.ts')
    const { MirrorKey } = await import('./web/src/mobile/mirror/crypto.ts')
    const { blobName, blobLogical, encodeIndex, INDEX_LOGICAL, INDEX_PREFIX, NOMEDIA } = await import('./web/src/mobile/vault/merge.ts')
    const taking = "Taking the PC's changes", sending = 'Sending to Drive'
    const key = await MirrorKey.fromText(Buffer.from(Array.from({length:32}, (_,i) => i)).toString('base64url'))
    const text = s => new TextEncoder().encode(s)
    function deferred() { let resolve; const promise = new Promise(r => { resolve = r }); return {promise, resolve} }
    function barrier(n) {
      const ready = deferred(), releases = []
      return {ready:ready.promise, wait:() => new Promise(resolve => {
        releases.push(resolve); if (releases.length === n) ready.resolve()
      }), release:() => releases.forEach(resolve => resolve())}
    }
    async function bounded(promise) {
      let timer
      try { return await Promise.race([promise, new Promise((_,reject) => {
        timer = setTimeout(() => reject(Error('parallel workers did not reach the barrier')), 2000)
      })]) } finally { clearTimeout(timer) }
    }
    async function fixture(pcCount, phoneCount = 0) {
      const blobs = new Map(), mem = new Map(), files = {}, hooks = {}
      for (let i = 0; i < pcCount; i++) {
        const data = text(`PC file ${i}`), id = await key.contentId(data)
        files[`pc/${i}.md`] = id
        blobs.set(blobName(id), await key.seal(blobLogical(id), data))
      }
      const pcName = INDEX_PREFIX + await key.name('vault/index/pc')
      blobs.set(pcName, await key.seal(INDEX_LOGICAL, encodeIndex(files, 'pc')))
      for (let i = 0; i < phoneCount; i++) mem.set(`phone/${i}.md`, text(`Phone file ${i}`))
      const metrics = {gets:0, reads:0, writes:0, uploads:0, lists:0}, events = []
      let state, saves = 0
      const drive = {
        list:async () => [...blobs].map(([name,data]) => ({id:name,name,size:data.length})),
        get:async id => { if (id.startsWith('vb-')) metrics.gets++; return blobs.get(id) },
        remove:async id => { blobs.delete(id) },
        create:async (name,data) => {
          if (name.startsWith('vb-')) { await hooks.upload?.(name); metrics.uploads++ }
          blobs.set(name,data); return name
        },
      }
      const fs = {
        list:async () => { metrics.lists++; return [...mem].map(([path,data]) => ({path,size:data.length,mtime:1})) },
        read:async path => { metrics.reads++; return hooks.read?.(path) ?? mem.get(path) },
        write:async (path,data) => {
          if (path !== NOMEDIA) { await hooks.write?.(path); metrics.writes++ }
          mem.set(path,data)
        },
        remove:async path => { mem.delete(path) }, has:async path => mem.has(path),
      }
      const signal = {aborted:false}
      const env = {drive,key,fs,device:'test-phone',force:false,signal,
        load:async () => state, save:async next => { state = structuredClone(next); saves++ },
        progress:(step,done,total,overall,display,files) => {
          if (step === taking) assert.ok(done <= metrics.writes, 'pull progress must not lead completed writes')
          events.push({step,done,total,overall,files}); hooks.progress?.(step,done)
        },
      }
      return {env,hooks,metrics,events,mem,blobs,state:() => state,saves:() => saves,
        reset() { for (const k of Object.keys(metrics)) metrics[k] = 0; events.length = 0 }}
    }
"""


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class VaultProgressTest(unittest.TestCase):
    def test_repeated_budget_chunks_reconcile_counts_until_index_publication(self):
        node(TS_RESOLVE + FIXTURE + r"""
            const f = await fixture(13)
            const phoneIndex = INDEX_PREFIX + await key.name('vault/index/test-phone')
            let completed = 0
            for (let chunk = 0; chunk < 4; chunk++) {
              let writes = 0
              f.hooks.write = () => { if (++writes > 3) throw Error('synthetic budget exhausted') }
              await assert.rejects(vaultRound(f.env), /synthetic budget exhausted/)
              assert.equal(f.events.find(e => e.files).files.done, completed, 'new chunk rescans committed content')
              completed += f.metrics.writes
              assert.equal(completed, (chunk + 1) * 3)
              assert.equal(f.events.filter(e => e.files).at(-1).files.done, completed)
              assert.equal(f.blobs.has(phoneIndex), false, 'partial chunks never publish the phone index')
              assert.deepEqual(f.state()?.base ?? {}, {})
              f.reset()
            }
            delete f.hooks.write
            assert.equal((await vaultRound(f.env)).state, 'idle')
            assert.equal(f.events.find(e => e.files).files.done, 12)
            assert.equal(f.metrics.writes, 1, 'verified files are not rewritten by continuations')
            assert.equal(f.blobs.has(phoneIndex), true)
            assert.equal(f.events.filter(e => e.files).at(-1).files.done, 13)
        """, timeout=10)

    def test_verified_counts_reconcile_safe_writes_after_interruption(self):
        node(TS_RESOLVE + FIXTURE + r"""
            const f = await fixture(2 * PARALLEL + 1), writes = barrier(PARALLEL)
            f.hooks.write = () => writes.wait()
            const first = vaultRound(f.env)
            await bounded(writes.ready)
            assert.deepEqual(f.events.filter(e => e.files).at(-1).files, {done:0,total:2*PARALLEL+1})
            f.env.signal.aborted = true; writes.release()
            assert.equal((await first).state,'stopped')
            assert.equal(f.events.filter(e => e.files).at(-1).files.done,PARALLEL)
            f.reset(); delete f.hooks.write; f.env.signal.aborted=false
            await vaultRound(f.env)
            assert.deepEqual(f.events.find(e => e.files).files,{done:PARALLEL,total:2*PARALLEL+1})
            assert.deepEqual(f.events.filter(e => e.files).at(-1).files,{done:2*PARALLEL+1,total:2*PARALLEL+1})
        """, timeout=10)

    def test_presence_failed_writes_and_pending_index_are_not_completed_sync(self):
        node(TS_RESOLVE + FIXTURE + r"""
            const f = await fixture(1)
            f.mem.set('pc/0.md',text('Wrong existing content'))
            f.hooks.write = () => { throw Error('interrupted before commit') }
            await assert.rejects(vaultRound(f.env),/interrupted before commit/)
            assert.equal(f.events.find(e => e.files).files.done,0)
            assert.equal(f.events.filter(e => e.files).at(-1).files.done,0)
            delete f.hooks.write; f.reset()
            const create = f.env.drive.create, held = deferred(), reached = deferred()
            f.env.drive.create = async (name,data) => {
              if(name.startsWith(INDEX_PREFIX)){reached.resolve();await held.promise}
              return create(name,data)
            }
            let ended=false
            const run=vaultRound(f.env).then(result=>{ended=true;return result})
            await bounded(reached.promise)
            assert.equal(f.events.filter(e=>e.files).at(-1).files.done,1)
            assert.equal(ended,false,'all verified files still await publication')
            held.resolve(); assert.equal((await run).state,'idle')
        """, timeout=10)

    def test_interrupted_cold_pull_keeps_scan_hints_without_advancing_the_base(self):
        node(TS_RESOLVE + FIXTURE + r"""
            const f = await fixture(1, 3)
            f.hooks.write = () => { throw Error('synthetic interrupted pull') }
            await assert.rejects(vaultRound(f.env), /synthetic interrupted pull/)
            assert.deepEqual(f.state().base, {})
            assert.equal(f.state().cacheVersion, 1)
            assert.equal(Object.keys(f.state().cache).length, 3)
            delete f.hooks.write
            let phoneReads = 0
            f.hooks.read = path => { if (path.startsWith('phone/')) phoneReads++ }
            assert.equal((await vaultRound(f.env)).state, 'idle')
            assert.equal(phoneReads, 3, 'stable files are read only for upload, not rehashed after the interrupted pull')
        """, timeout=10)

    def test_parallel_pulls_and_uploads_report_completions_through_the_final_batch(self):
        node(TS_RESOLVE + FIXTURE + r"""
            const n = 2 * PARALLEL + 1, f = await fixture(n,n)
            const writes = barrier(PARALLEL), uploads = barrier(PARALLEL)
            let writeCalls = 0, uploadCalls = 0
            f.hooks.write = async () => { if (++writeCalls <= PARALLEL) await writes.wait() }
            f.hooks.upload = async () => { if (++uploadCalls <= PARALLEL) await uploads.wait() }
            const round = vaultRound(f.env)
            await bounded(writes.ready)
            assert.equal(writeCalls, PARALLEL)
            assert.equal(f.metrics.writes, 0)
            assert.deepEqual(f.events.filter(e => e.step === taking).map(e => e.done), [0])
            writes.release()
            await bounded(uploads.ready)
            assert.equal(uploadCalls, PARALLEL)
            assert.equal(f.metrics.uploads, 0)
            assert.deepEqual(f.events.filter(e => e.step === taking).map(e => e.done), Array.from({length:n+1}, (_,i) => i))
            assert.deepEqual(f.events.filter(e => e.step === sending).map(e => e.done), [0])
            uploads.release()
            const result = await round
            assert.equal(result.state, 'idle')
            assert.deepEqual(f.events.filter(e => e.step === sending).map(e => e.done), Array.from({length:n+1}, (_,i) => i))
            for (const [step,overall] of [[taking,.6],[sending,.97]]) {
              const last = f.events.filter(e => e.step === step).at(-1)
              assert.deepEqual([last.done,last.total,last.overall], [n,n,overall])
            }
            assert.deepEqual(f.events.map(e => e.overall), f.events.map(e => e.overall).sort((a,b) => a-b))
            assert.equal(f.metrics.writes, n); assert.equal(f.metrics.uploads, n)
            assert.equal(f.saves(), 2) // scan hints, then the completed round
        """, timeout=10)

    def test_stop_with_parallel_files_in_flight_resumes_without_downloads_then_uses_warm_cache(self):
        node(TS_RESOLVE + FIXTURE + r"""
            const n = 2 * PARALLEL + 1, f = await fixture(n), writes = barrier(PARALLEL)
            f.hooks.write = () => writes.wait()
            const round = vaultRound(f.env)
            await bounded(writes.ready)
            f.env.signal.aborted = true
            writes.release()
            assert.equal((await round).state, 'stopped')
            assert.equal(f.metrics.gets, PARALLEL); assert.equal(f.metrics.writes, PARALLEL)
            assert.deepEqual(f.events.filter(e => e.step === taking).map(e => e.done), Array.from({length:PARALLEL+1}, (_,i) => i))
            assert.equal(f.state(), undefined); assert.equal(f.saves(), 0)
            f.reset(); delete f.hooks.write; f.env.signal.aborted = false
            const resumed = await vaultRound(f.env)
            assert.equal(resumed.state, 'idle')
            assert.equal(f.metrics.gets, n-PARALLEL); assert.equal(f.metrics.writes, n-PARALLEL)
            assert.equal(f.mem.size, n+1) // includes the gallery marker
            assert.equal(Object.keys(f.state().cache).length, n)
            f.reset()
            const warm = await vaultRound(f.env)
            assert.equal(warm.summary, 'Already in step')
            assert.deepEqual(f.metrics, {gets:0,reads:0,writes:0,uploads:0,lists:2})
        """, timeout=10)

    def test_failed_operations_never_advance_the_completed_count(self):
        node(TS_RESOLVE + FIXTURE + r"""
            for (const step of [taking,sending]) {
              const f = await fixture(step === taking ? 3 : 0, step === sending ? 3 : 0)
              let calls = 0
              f.hooks[step === taking ? 'write' : 'upload'] = async () => {
                if (++calls === 1) throw Error('synthetic operation failure')
              }
              await assert.rejects(() => vaultRound(f.env), /synthetic operation failure/)
              const completed = step === taking ? f.metrics.writes : f.metrics.uploads
              assert.equal(f.events.filter(e => e.step === step).at(-1).done, completed)
              assert.ok(completed < 3); assert.equal(f.saves(), step === taking ? 0 : 1)
              if (f.state()) assert.deepEqual(f.state().base, {})
            }
        """, timeout=10)

    def test_file_edited_after_scan_does_not_publish_a_stale_index(self):
        node(TS_RESOLVE + FIXTURE + r"""
            const f = await fixture(0,1)
            let reads = 0
            f.hooks.read = path => {
              if (++reads === 2) f.mem.set(path,text('Edited after scanning this phone file'))
              return f.mem.get(path)
            }
            await assert.rejects(() => vaultRound(f.env), /file changed during sync/)
            assert.equal(f.metrics.uploads, 0)
            assert.equal([...f.blobs.keys()].filter(n => n.startsWith('vi-')).length, 1, 'only the PC index exists')
            delete f.hooks.read; f.reset()
            const next = await vaultRound(f.env)
            assert.equal(next.state, 'idle'); assert.equal(f.metrics.uploads, 1)
            assert.ok(next.summary.includes('1 sent'))
        """, timeout=10)

    def test_same_size_generated_updates_with_unchanged_metadata_do_not_repeat_pulls(self):
        node(TS_RESOLVE + FIXTURE + r"""
            const {decodeIndexFull} = await import('./web/src/mobile/vault/merge.ts')
            for (const mtime of [0,1000]) {
              const n = 31, f = await fixture(n)
              const list = f.env.fs.list
              f.env.fs.list = async () => (await list()).map(file => ({...file,mtime}))
              const pcName = INDEX_PREFIX + await key.name('vault/index/pc')
              const index = decodeIndexFull(await key.openText(INDEX_LOGICAL,f.blobs.get(pcName)))
              const publish = async () => f.blobs.set(pcName,await key.seal(INDEX_LOGICAL,
                encodeIndex(index.files,'pc',{vault:'same-vault',generated:Object.keys(index.files)})))
              await publish()
              assert.equal((await vaultRound(f.env)).state, 'idle')
              for (const path of Object.keys(index.files)) {
                const data = text(`PC edit ${path.split('/').at(-1).slice(0,-3)}`), id = await key.contentId(data)
                assert.equal(data.length, f.mem.get(path).length)
                index.files[path] = id
                f.blobs.set(blobName(id),await key.seal(blobLogical(id),data))
              }
              await publish(); f.reset()
              const update = await vaultRound(f.env)
              assert.equal(update.state,'idle'); assert.equal(f.metrics.gets,n)
              for (const [path,id] of Object.entries(index.files)) {
                assert.equal(await key.contentId(f.mem.get(path)), id)
                assert.equal(f.state().base[path],id)
                assert.equal(f.state().cache[path][2],id)
              }
              for (let round = 3; round <= 4; round++) {
                f.reset()
                const warm = await vaultRound(f.env)
                assert.equal(warm.summary,'Already in step')
                assert.deepEqual(f.metrics,{gets:0,reads:0,writes:0,uploads:0,lists:2})
                assert.equal([...f.mem.keys()].filter(p => p.includes('phone conflict')).length,0)
              }
            }
        """, timeout=10)

    def test_interrupted_same_size_update_invalidates_only_cache_and_resumes_remaining_files(self):
        node(TS_RESOLVE + FIXTURE + r"""
            const {decodeIndexFull} = await import('./web/src/mobile/vault/merge.ts')
            const n = 31, f = await fixture(n,1), list = f.env.fs.list
            f.env.fs.list = async () => (await list()).map(file => ({...file,mtime:0}))
            const pcName = INDEX_PREFIX + await key.name('vault/index/pc')
            const index = decodeIndexFull(await key.openText(INDEX_LOGICAL,f.blobs.get(pcName)))
            const publish = async () => f.blobs.set(pcName,await key.seal(INDEX_LOGICAL,
              encodeIndex(index.files,'pc',{vault:'same-vault',generated:Object.keys(index.files)})))
            await publish(); await vaultRound(f.env)
            const before = structuredClone(f.state())
            for (const path of Object.keys(index.files)) {
              const data = text(`PC edit ${path.split('/').at(-1).slice(0,-3)}`), id = await key.contentId(data)
              assert.equal(data.length,f.mem.get(path).length)
              index.files[path] = id
              f.blobs.set(blobName(id),await key.seal(blobLogical(id),data))
            }
            await publish(); f.reset()
            const savesBefore = f.saves()
            const writes = barrier(PARALLEL)
            f.hooks.write = () => writes.wait()
            const round = vaultRound(f.env)
            await bounded(writes.ready)
            assert.equal(f.metrics.writes,0)
            assert.equal(f.saves(),savesBefore+1) // one cache-only checkpoint before any replacement
            assert.deepEqual(f.state().base,before.base)
            for (const path of Object.keys(index.files)) assert.ok(!Object.hasOwn(f.state().cache,path))
            assert.deepEqual(f.state().cache['phone/0.md'],before.cache['phone/0.md'])
            f.env.signal.aborted = true; writes.release()
            assert.equal((await round).state,'stopped')
            assert.equal(f.metrics.writes,PARALLEL)
            assert.deepEqual(f.state().base,before.base)
            f.reset(); delete f.hooks.write; f.env.signal.aborted = false
            const resumed = await vaultRound(f.env)
            assert.equal(resumed.state,'idle')
            assert.equal(f.metrics.gets,n-PARALLEL); assert.equal(f.metrics.writes,n-PARALLEL)
            assert.equal([...f.mem.keys()].filter(p => p.includes('phone conflict')).length,0)
            assert.deepEqual(f.state().base,index.files)
            f.reset()
            assert.equal((await vaultRound(f.env)).summary,'Already in step')
            assert.deepEqual(f.metrics,{gets:0,reads:0,writes:0,uploads:0,lists:2})
        """, timeout=10)

    def test_legacy_stale_cache_is_rebuilt_without_pulls_or_conflicts(self):
        node(TS_RESOLVE + FIXTURE + r"""
            const f = await fixture(31)
            await vaultRound(f.env)
            const before = structuredClone(f.state().base)
            delete f.state().cacheVersion
            for (const path of Object.keys(before)) f.state().cache[path][2] = await key.contentId(text(`Old cached bytes: ${path}`))
            f.reset()
            const repaired = await vaultRound(f.env)
            assert.equal(repaired.summary,'Already in step')
            assert.equal(f.metrics.gets,0); assert.equal(f.metrics.writes,0); assert.equal(f.metrics.uploads,0)
            assert.equal(f.metrics.reads,31)
            assert.equal([...f.mem.keys()].filter(p => p.includes('phone conflict')).length,0)
            assert.deepEqual(f.state().base,before)
            assert.equal(f.state().cacheVersion,1)
            for (const [path,id] of Object.entries(before)) assert.equal(f.state().cache[path][2],id)
        """, timeout=10)

    def test_failed_cache_checkpoint_leaves_files_and_saved_state_untouched(self):
        node(TS_RESOLVE + FIXTURE + r"""
            const {decodeIndexFull} = await import('./web/src/mobile/vault/merge.ts')
            const f = await fixture(1)
            await vaultRound(f.env)
            const before = structuredClone(f.state()), oldBytes = f.mem.get('pc/0.md').slice()
            const pcName = INDEX_PREFIX + await key.name('vault/index/pc')
            const index = decodeIndexFull(await key.openText(INDEX_LOGICAL,f.blobs.get(pcName)))
            const data = text('PC edit 0'), id = await key.contentId(data)
            index.files['pc/0.md'] = id
            f.blobs.set(blobName(id),await key.seal(blobLogical(id),data))
            f.blobs.set(pcName,await key.seal(INDEX_LOGICAL,encodeIndex(index.files,'pc')))
            f.reset()
            f.env.save = async () => { throw Error('synthetic checkpoint storage failure') }
            await assert.rejects(() => vaultRound(f.env), /synthetic checkpoint storage failure/)
            assert.deepEqual(f.metrics,{gets:0,reads:0,writes:0,uploads:0,lists:1})
            assert.deepEqual(f.state(),before)
            assert.deepEqual(f.mem.get('pc/0.md'),oldBytes)
        """, timeout=10)


if __name__ == '__main__':
    unittest.main()
