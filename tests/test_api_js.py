"""Concurrent setup panels share slow probes without caching readiness or blocking ordinary reads."""
import unittest

from tests.test_onboarding_js import _node_ok, node


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class ApiJsTest(unittest.TestCase):
    def test_tool_checks_share_only_pending_reads_and_invalidate_on_mutation(self):
        node(r"""
          import assert from 'node:assert/strict'
          import {registerHooks} from 'node:module'
          globalThis.__net={n:0}
          registerHooks({resolve(s,c,next){
            if(s==='./net.svelte')return {url:'data:text/javascript,export const net=globalThis.__net',shortCircuit:true}
            return next(s,c)
          }})
          const requests=[]
          globalThis.fetch=(url,init)=>new Promise((resolve,reject)=>requests.push({url,init,resolve,reject}))
          const {api}=await import('./web/src/lib/api.ts')
          const reply=(i,value={})=>requests[i].resolve(new Response(JSON.stringify(value)))
          const tools=api.get('/api/settings/tools')
          assert.equal(api.get('/api/settings/tools'),tools)
          const browser=api.get('/api/settings/scraper-runtime')
          assert.equal(api.get('/api/settings/scraper-runtime'),browser)
          const app=api.get('/api/app')
          assert.equal(requests.length,3)
          reply(2,{autostart:false});assert.deepEqual(await app,{autostart:false})
          reply(0);reply(1);await Promise.all([tools,browser])
          assert.equal(__net.n,0)
          const failed=api.get('/api/settings/tools')
          const error=assert.rejects(failed,/unavailable/)
          requests[3].reject(Error('unavailable'));await error
          const before=api.get('/api/settings/tools')
          const save=api.put('/api/settings/tools',{tools_dir:'synthetic'})
          const during=api.get('/api/settings/tools')
          assert.notEqual(during,before)
          reply(5);await save
          const after=api.get('/api/settings/tools')
          assert.notEqual(after,during)
          reply(4);reply(6);await Promise.all([before,during])
          assert.equal(api.get('/api/settings/tools'),after)
          reply(7,{ready:true});assert.deepEqual(await after,{ready:true})
          const recheck=api.get('/api/settings/tools')
          assert.equal(requests.length,9)
          reply(8);await recheck
          assert.equal(__net.n,0)
        """)


if __name__ == '__main__':
    unittest.main()
