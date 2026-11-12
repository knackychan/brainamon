"""Section summaries use current local facts and preserve loading/error distinctions."""
import json
import unittest

from tests.test_phone_js import node, TS_RESOLVE


def lines(script):
    return json.loads(node(TS_RESOLVE + """
      const {videoLine, browserLine, vaultLine, mapStatusLine} = await import('./web/src/lib/settings-lines.ts')
      const tools = {tools_dir:'', all_found:true, tools:['ffmpeg','ffprobe','yt-dlp','deno'].map(name => ({name, state:'ready'})),
        youtube:{functional:true, deno:true, ejs:'detected'}}
      const install = {state:'idle', step:'', error:'', command:'', winget:true}
      const runtime = {state:'ready', version:'1.61.0', step:'', error:'', supported:true, workers:true, python:true, winget:true}
      const status = {state:'idle', pending:false, error:'', busy:'', waiting:false, last_maintenance:0, last_render:1,
        written:0, removed:0, adopted:[], unlisted:0, other_library:false, topics:5, stale:0, pending_summaries:0}
      const view = {vault:'synthetic', mode:'owner', exists:true, is_vault:true, legacy:false, default_location:'', earlier_vault:false,
        pictures:false, first_open:'', vault_sync_on:false, installed:true,
        map:{topics:20, stale:0, pending:0, model_changed:false, coverage:{indexed:1,total:1,low:false}}, status}
      const vf = {tools, install, checking:false, starting:false, error:''}
      const bf = {runtime, checking:false, doing:'', error:''}
      const of = {view, pending:false, error:''}
      const mf = {...of, job:null}
    """ + script))


class SettingsLinesTest(unittest.TestCase):
    def test_video(self):
        got = lines("""
          console.log(JSON.stringify([
            videoLine({...vf, checking:true, error:'old failure'}),
            videoLine({...vf, install:{...install,state:'running',step:'Installing Deno'}}),
            videoLine({...vf, starting:true, error:'old failure'}),
            videoLine({...vf, error:'Read failed'}),
            videoLine({...vf, install:{...install,state:'error',error:'Setup failed'}}),
            videoLine({...vf, tools:null}), videoLine(vf),
            videoLine({...vf, tools:{...tools, tools:tools.tools.filter(t=>t.name!=='deno'), youtube:{...tools.youtube,deno:false}}}),
          ]))
        """)
        self.assertEqual([x['kind'] for x in got], ['loading', 'working', 'working', 'failed', 'failed', 'loading', 'done', 'empty'])
        self.assertEqual(got[1]['text'], 'Installing Deno')
        self.assertEqual(got[1]['tone'], 'busy')
        self.assertEqual(got[3]['text'], 'Read failed')
        self.assertIn('Deno', got[7]['text'])
        self.assertEqual(got[7]['tone'], 'optional')

    def test_browser(self):
        got = lines("""
          console.log(JSON.stringify([
            browserLine({...bf,checking:true,error:'old failure'}), browserLine({...bf,doing:'remove'}),
            browserLine({...bf,runtime:{...runtime,state:'installing',step:'Downloading Chromium'}}),
            browserLine({...bf,error:'Read failed'}), browserLine({...bf,runtime:{...runtime,workers:false}}),
            browserLine({...bf,runtime:{...runtime,state:'failed',error:'Probe failed'}}), browserLine({...bf,runtime:null}),
            browserLine(bf), browserLine({...bf,runtime:{...runtime,state:'older'}}),
            browserLine({...bf,runtime:{...runtime,state:'missing'}}),
          ]))
        """)
        self.assertEqual([x['kind'] for x in got], ['loading', 'working', 'working', 'failed', 'failed', 'failed', 'loading', 'done', 'empty', 'empty'])
        self.assertEqual(got[2]['text'], 'Downloading Chromium')
        self.assertIn('incomplete', got[4]['text'])
        self.assertEqual(got[5]['text'], 'Probe failed')

    def test_vault(self):
        got = lines("""
          console.log(JSON.stringify([
            vaultLine({...of,pending:true,error:'old'}), vaultLine({...of,error:'Read failed'}), vaultLine({...of,view:null}),
            vaultLine({...of,view:{...view,exists:false,status:{...status,busy:'Rendering'}}}),
            vaultLine({...of,view:{...view,status:{...status,missing:true}}}),
            vaultLine({...of,view:{...view,status:{...status,other_library:true,busy:'Rendering'}}}),
            vaultLine({...of,view:{...view,status:{...status,error:'Failed',busy:'Rendering',waiting:true}}}),
            vaultLine({...of,view:{...view,status:{...status,busy:'Rendering',waiting:true}}}),
            vaultLine({...of,view:{...view,status:{...status,pending:true}}}),
            vaultLine({...of,view:{...view,mode:'',legacy:true}}), vaultLine({...of,view:{...view,mode:''}}),
            vaultLine({...of,view:{...view,status:{...status,last_render:0}}}), vaultLine(of),
          ]))
        """)
        self.assertEqual([x['kind'] for x in got], ['loading', 'failed', 'loading', 'failed', 'failed', 'failed', 'failed', 'working', 'working', 'empty', 'empty', 'empty', 'done'])
        self.assertEqual(got[1]['text'], 'Read failed')
        self.assertIn('Vault not found', got[3]['text'])
        self.assertIn('another Brainamon library', got[5]['text'])
        self.assertIn('Failed', got[6]['text'])
        self.assertEqual(got[7]['text'], 'Waiting for the vault to be free.')
        self.assertEqual(got[9]['tone'], 'optional')

    def test_map(self):
        got = lines("""
          const job = {kind:'refresh_map',state:'running',done:3,total:10}
          console.log(JSON.stringify([
            mapStatusLine({...mf,pending:true,error:'old'}), mapStatusLine({...mf,error:'Read failed'}), mapStatusLine({...mf,view:null}),
            mapStatusLine({...mf,job:{...job,state:'paused'}}), mapStatusLine({...mf,job}),
            mapStatusLine({...mf,view:{...view,status:{...status,error:'Map failed'}}}),
            mapStatusLine({...mf,view:{...view,status:{...status,topics:0}}}),
            mapStatusLine({...mf,view:{...view,status:{...status,stale:2,pending_summaries:1}}}),
            mapStatusLine({...mf,job:{...job,state:'finished'}}),
          ]))
        """)
        self.assertEqual([x['kind'] for x in got], ['loading', 'failed', 'loading', 'paused', 'working', 'failed', 'empty', 'empty', 'done'])
        self.assertIn('3 of 10', got[3]['text'])
        self.assertEqual(got[4]['tone'], 'busy')
        self.assertIn('2 out of date', got[7]['text'])
        self.assertIn('1 waiting for a summary', got[7]['text'])
        self.assertIn('5 topics', got[8]['text'])
        self.assertNotIn('20 topics', got[8]['text'])


if __name__ == '__main__':
    unittest.main()
