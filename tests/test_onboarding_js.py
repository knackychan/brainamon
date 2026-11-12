"""First-run rules (web/src/lib/onboarding.ts) under Node (type stripping, no build), and the welcome's
answers agreeing with server/routes/onboarding.py. Skips without Node 22.6+.

Run from the project root:  py -m unittest tests.test_onboarding_js -v
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from server.routes import onboarding

ROOT = Path(__file__).resolve().parent.parent
MODULE = './web/src/lib/onboarding.ts'


def node(script: str) -> str:
    r = subprocess.run(['node', '--experimental-strip-types', '--no-warnings', '--input-type=module', '-e', script],
                       cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode:
        raise AssertionError(r.stderr[-2000:])
    return r.stdout


def run(expr: str):
    return json.loads(node(f"import * as o from '{MODULE}'; console.log(JSON.stringify({expr}))"))


def _node_ok() -> bool:
    # the same probe as tests/test_note_format.py: Node strips the types of a module that already exists
    if not shutil.which('node'):
        return False
    try:
        node("import { plain } from './web/src/lib/note-format.ts'; console.log(plain('x'))")
        return True
    except Exception:
        return False


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class OnboardingJsTest(unittest.TestCase):
    def test_answers_match_the_server(self):
        self.assertEqual(tuple(run('o.ANSWERS.map(a => a.id)')) + ('skip',), onboarding.ANSWERS)

    def test_the_start_action_by_answer(self):
        got = run("['instagram', 'facebook', 'reddit', 'youtube', 'links', 'skip', ''].map(a => o.startFor(a))")
        self.assertEqual([g['site'] for g in got], ['instagram', 'facebook', 'reddit', 'youtube', None, None, None])
        self.assertEqual((got[0]['task'], got[0]['key']), ('Bring in your Instagram saves', 'Bring in Instagram saves'))
        self.assertEqual((got[3]['task'], got[3]['key']), ('Bring in a YouTube playlist', 'Bring in a YouTube playlist'))
        self.assertEqual((got[4]['task'], got[4]['key']), ('Save your first link or note', 'Add a link or note'))
        self.assertTrue(all(g['line'].endswith('you can sort and search.') for g in got))
        self.assertEqual(got[0]['line'], got[2]['line'])                     # every social site: the saved-posts line
        self.assertIn('saved posts', got[0]['line'])
        self.assertIn('playlist', got[3]['line'])
        self.assertIn('Paste a link', got[4]['line'])
        self.assertEqual(run("['reddit', 'links', 'constructor', '__proto__'].map(a => o.isSite(a))"), [True, False, False, False])
        self.assertEqual(run("o.startFor('constructor').site"), None)          # no prototype keys

    def test_desktop_tasks(self):
        none = run("o.desktopTasks('reddit', { items: 0, notes: 0, wiskit: false })")
        self.assertEqual([(t['id'], t['done']) for t in none], [('install', True), ('tools', False), ('saves', False), ('wiskit', False), ('drive', False), ('phone', False)])
        self.assertEqual([t['label'] for t in none], ['Your library', 'Tools & environment', 'Bring in your Reddit saves', 'Wiskit AI (optional)', 'Drive & recovery (optional)', 'Connect your phone (optional)'])
        self.assertEqual([t['done'] for t in run("o.desktopTasks('links', { items: 0, notes: 1, wiskit: true, tools: true, drive: true, recovery: true, phone: true })")], [True] * 6)
        self.assertEqual(run("o.progressOf(o.desktopTasks('', { items: 2, notes: 0, wiskit: false }), true)"), {'done': 2, 'total': 6, 'all': False})
        self.assertEqual(run('o.SETUP_STEPS'), ['library', 'tools', 'content', 'ai', 'drive', 'phone'])
        self.assertEqual(run("o.startFor('files').key"), 'Choose a file')
        self.assertFalse(run("o.desktopTasks('', {items:0,notes:0,wiskit:false,drive:true}).find(t=>t.id==='drive').done"))

    def test_navigation_writes_serialize_and_stale_reads_cannot_move_the_step(self):
        node(r"""
          import assert from 'node:assert/strict'
          import fs from 'node:fs'
          import {registerHooks,stripTypeScriptTypes} from 'node:module'
          globalThis.$state=x=>x
          const gets=[], puts=[]
          globalThis.__api={get:()=>new Promise(resolve=>gets.push(resolve)),put:(path,body)=>new Promise((resolve,reject)=>puts.push({body,resolve,reject}))}
          const stubs={
            './api':'export const api=globalThis.__api',
            './edit-commands':'export const openAdd=()=>{}',
            './events.svelte':'export const on=()=>()=>{}',
            './io-commands.svelte':'export const openImport=()=>{};export const openScrapersFor=()=>{}',
            './windows.svelte':'export const openWin=()=>{}',
            '../windows/WelcomeWin.svelte':'export default null',
            '../windows/WiskitKeyWin.svelte':'export default null',
          }
          registerHooks({resolve(s,c,next){
            if(c.parentURL?.endsWith('/lib/onboarding.svelte.ts')&&stubs[s])return {url:'data:text/javascript,'+encodeURIComponent(stubs[s]),shortCircuit:true}
            try{return next(s,c)}catch(e){if(s.startsWith('.')&&!/\.\w+$/.test(s))return next(s+'.ts',c);throw e}
          },load(url,c,next){
            if(url.endsWith('/lib/onboarding.svelte.ts'))return {format:'module',shortCircuit:true,source:stripTypeScriptTypes(fs.readFileSync(new URL(url),'utf8'))}
            return next(url,c)
          }})
          const O=await import('./web/src/lib/onboarding.svelte.ts')
          const view={answer:'links',hidden:false,welcome:false,items:0,notes:0,wiskit:false,step:'library',skipped:[]}
          const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve()}
          const old=O.loadOnboarding()
          const first=O.saveOnboarding({step:'tools'})
          const during=O.loadOnboarding()
          const second=O.saveOnboarding({step:'ai',skipped:['tools']})
          await flush()
          assert.equal(puts.length,1)
          puts[0].resolve({...view,step:'tools'});await first;await flush()
          assert.equal(O.onb.step,'ai')
          assert.equal(puts.length,2)
          puts[1].resolve({...view,step:'ai',skipped:['tools']});await second
          gets.forEach(resolve=>resolve(view));await Promise.all([old,during])
          assert.equal(O.onb.step,'ai')
          assert.deepEqual(O.onb.skipped,['tools'])
          assert.equal(O.onb.saving,false)
          const failed=assert.rejects(O.saveOnboarding({step:'phone'}),/synthetic failure/)
          await flush();puts[2].reject(Error('synthetic failure'));await failed
          assert.equal(O.onb.saving,false)
          const retry=O.saveOnboarding({step:'phone'})
          await flush();puts[3].resolve({...view,step:'phone',skipped:['tools']});await retry
          assert.equal(O.onb.step,'phone')
          assert.deepEqual(puts[1].body,{step:'ai',skipped:['tools']})
          const stale=O.loadOnboarding()
          const facebook=O.saveOnboarding({answer:'facebook'})
          const youtube=O.saveOnboarding({answer:'youtube'})
          const content=O.saveOnboarding({step:'content'})
          assert.equal(O.onb.answer,'youtube')
          assert.equal(O.onb.step,'content')
          await flush()
          puts[4].resolve({...view,answer:'facebook',step:'phone'});await facebook;await flush()
          assert.equal(O.onb.answer,'youtube')
          puts[5].resolve({...view,answer:'youtube',step:'phone'});await youtube;await flush()
          assert.equal(O.onb.step,'content')
          puts[6].resolve({...view,answer:'youtube',step:'content'});await content
          gets.at(-1)(view);await stale
          assert.equal(O.onb.answer,'youtube')
          assert.equal(O.onb.step,'content')
          assert.equal(O.onb.saving,false)
          gets.length=0
          const checks=O.loadInstallChecks()
          assert.equal(O.loadInstallChecks(),checks)
          assert.equal(gets.length,4)
          gets[0]({tools:[],all_found:false});gets[1]({state:'missing'})
          gets[2]({signed_in:false});gets[3]({enrolled:false})
          assert.equal(await checks,true)
          const recheck=O.loadInstallChecks()
          assert.equal(gets.length,8)
          gets.slice(4).forEach(resolve=>resolve({tools:[],state:'missing'}))
          assert.equal(await recheck,true)
        """)

    def test_phone_tasks(self):
        pc = run("o.phoneTasks('pc', { pc: false, items: 3, ai: false })")
        self.assertEqual([(t['id'], t['label'], t['done']) for t in pc],
                         [('install', 'Install Brainamon', True), ('pc', 'Connect your PC', False), ('wiskit', 'Turn on Wiskit', False)])
        solo = run("o.phoneTasks('phone', { pc: false, items: 1, ai: true })")
        self.assertEqual([(t['id'], t['done']) for t in solo], [('install', True), ('saves', True), ('wiskit', True)])
        self.assertEqual(solo[1]['label'], 'Save your first link')
        self.assertTrue(run("o.progressOf(o.phoneTasks('skip', { pc: false, items: 1, ai: true })).all"))

    def test_desktop_counts_optional_steps_without_requiring_them_for_local_use(self):
        self.assertEqual(run("o.progressOf(o.desktopTasks('links', {items: 1, notes: 0, wiskit: true, tools: false, drive: false}), true)"),
                         {'done': 3, 'total': 6, 'all': False})

    def test_tool_probe_states_and_installer_progress(self):
        self.assertEqual(run("['ready','older','missing','failed'].map(state => o.toolState({name:'deno',state}, {state:'running',step:'DenoLand.Deno'}))"),
                         ['Installing', 'Installing', 'Installing', 'Installing'])
        self.assertEqual(run("o.toolState({name:'ffprobe',state:'failed'}, {state:'running',step:'yt-dlp.FFmpeg'})"), 'Installing')
        self.assertEqual(run("o.toolState({name:'ffmpeg',state:'missing'}, {state:'running',step:'DenoLand.Deno'})"), 'Missing')
        self.assertTrue(run("o.toolsReady({tools:Array(4).fill({state:'ready'}),youtube:{deno:true,ejs:'detected',functional:true}})"))
        for field in ("deno:false,ejs:'detected',functional:true", "deno:true,ejs:'unknown',functional:true", "deno:true,ejs:'detected',functional:false"):
            self.assertFalse(run("o.toolsReady({tools:Array(4).fill({state:'ready'}),youtube:{" + field + "}})"))

    def test_drive_states_do_not_display_server_errors_or_credentials(self):
        states = run("['off','signed-out','idle','publishing','error','signing-in','starting','stopping','disconnecting'].map(state => o.driveStep({seq:1,state,signed_in:true,running:state !== 'off',configured:true,error:'secret',token:'secret',key:'secret'}))")
        self.assertEqual([s['ready'] for s in states], [False, False, True, True, False, False, False, False, False])
        self.assertEqual(states[0]['line'], 'Google Drive uploads are off.')
        self.assertEqual(states[2]['line'], 'Google Drive uploads are on.')
        self.assertIn('Uploading', states[3]['line'])
        self.assertIn('Settings > Backup & phones', states[4]['line'])
        self.assertNotIn('secret', json.dumps(states))
        self.assertEqual(run("o.driveStep({seq:0,state:'off',signed_in:false,running:false,configured:false}).line"), 'Signed out of Google Drive. Uploads are off.')

    def test_phone_empty_library(self):
        self.assertEqual(run("o.phoneEmpty('pc', false)"), {'pc': True, 'line': 'Connect your PC and its library shows up here.', 'key': 'Connect your PC'})
        self.assertEqual(run("o.phoneEmpty('pc', true).key"), 'Add your first save')
        self.assertEqual(run("o.phoneEmpty('phone', false)"), {'pc': False, 'line': 'Share a post to Brainamon from any app, or add one here.', 'key': 'Add your first save'})

    def test_the_scrapers_guide(self):
        for site, name in (('instagram', 'Instagram'), ('facebook', 'Facebook'), ('reddit', 'Reddit'), ('youtube', 'YouTube'), ('threads', 'Threads')):
            manual = run(f"o.scrapeGuide('{site}', false)")
            self.assertEqual(len(manual['steps']), 3, site)
            self.assertEqual(manual['key'], f'Copy script and open {name}')
            self.assertIn('F12', manual['steps'][1])
            self.assertIn(name, manual['steps'][0])
        self.assertIn('Saved, then All posts', run("o.scrapeGuide('instagram', false)")['steps'][1])
        for site in ('facebook', 'reddit', 'threads'):
            self.assertIn('Saved page that opens', run(f"o.scrapeGuide('{site}', false)")['steps'][1])
        self.assertIn('playlist', run("o.scrapeGuide('youtube', false)")['steps'][1])
        for site, name in (('instagram', 'Instagram'), ('facebook', 'Facebook'), ('reddit', 'Reddit'), ('threads', 'Threads')):
            helper = run(f"o.scrapeGuide('{site}', true)")
            self.assertEqual(helper['key'], f'Start the {name} helper')
            self.assertIn(name, helper['steps'][1])
        auto = run("o.scrapeGuide('instagram', true)")
        self.assertEqual((auto['title'], auto['key']), ('Bring in your Instagram saves', 'Start the Instagram helper'))
        self.assertIn('never sees your password', auto['steps'][1])
        self.assertIn('Keep this window open', auto['steps'][2])        # closing Scrapers stops the helper
        self.assertEqual(run("o.scrapeGuide('youtube', true).key"), 'Copy script and open YouTube')    # no helper for YouTube


if __name__ == '__main__':
    unittest.main()
