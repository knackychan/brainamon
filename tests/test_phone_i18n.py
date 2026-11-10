"""Phone language core in Node without browser storage or real user data."""
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from tests.test_phone_js import TS_RESOLVE, _node_ok, node


def policy_date(text):
    values = re.findall(r'^(?:#{1,6} )?(?:Last updated|Dernière mise à jour|最後更新)\s*[:：]\s*(.*?)\s*$', text, re.M)
    if len(values) != 1 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', values[0]):
        raise ValueError('Expected exactly one labelled policy date')
    from datetime import date
    return date.fromisoformat(values[0]).isoformat()


def listing_description(text, heading):
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line == '## ' + heading]
    if len(starts) != 1:
        raise ValueError('Expected exactly one designated description heading')
    start = starts[0] + 1
    end = next((i for i in range(start, len(lines)) if re.match(r'^#{1,6} ', lines[i])), len(lines))
    body = lines[start:end]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    if not body:
        raise ValueError('Empty description')
    return '\n'.join(body)


class PhoneLegalDraftsTest(unittest.TestCase):
    def test_policy_date_parser_rejects_missing_duplicate_and_invalid_dates(self):
        for label in ('Last updated:', 'Dernière mise à jour :', '最後更新：'):
            with self.subTest(label=label):
                self.assertEqual(policy_date(label + ' 2026-10-28\n'), '2026-10-28')
                for text in ('2026-10-28', label + ' 2026-10-28\n' + label + ' 2026-10-28',
                             label + ' 2026-02-30', label + ' 2026-1-2', label + ' unknown'):
                    with self.assertRaises(ValueError):
                        policy_date(text)
        with self.assertRaises(ValueError):
            policy_date('Last updated: 2026-10-28\n最後更新：2026-10-28')

    def test_listing_parser_boundaries_spaces_newlines_and_supplementary_characters(self):
        text = '# Draft\nPreparation excluded\n\n## Short\n\n A😀 B \n\n## Full\n\nFirst\n𠮷 second\n\nThird\n\n## Gates\nNo publication\n'
        short = listing_description(text, 'Short')
        full = listing_description(text, 'Full')
        self.assertEqual(short, ' A😀 B ')
        self.assertEqual(len(short), 6)
        self.assertEqual(full, 'First\n𠮷 second\n\nThird')
        self.assertEqual(len(full), 21)
        self.assertEqual(listing_description('## Full\n\nLast 😀\n', 'Full'), 'Last 😀')
        self.assertEqual(listing_description('## Full\nBody\n### Other\nExcluded', 'Full'), 'Body')
        for bad in ('# Full\nwrong level', '## Full\n\n## Gates\nempty', '## Full\nA\n## Full\nB'):
            with self.assertRaises(ValueError):
                listing_description(bad, 'Full')

    def test_policies_match_authoritative_date_links_paths_and_current_clauses(self):
        from collections import Counter
        root = Path(__file__).resolve().parents[1]
        english = (root / 'mobile-shell/store/privacy-policy.md').read_text(encoding='utf-8')
        urls = lambda text: Counter(u.rstrip('.') for u in re.findall(r'https://[A-Za-z0-9:/._-]+', text))
        for suffix, notice, draft in [('fr', 'la version anglaise fait foi.', 'Brouillon de traduction non relu'),
                                      ('zh-Hant', '以英文版本為準。', '未經審閱的翻譯草稿')]:
            with self.subTest(language=suffix):
                text = (root / f'mobile-shell/store/privacy-policy.{suffix}.md').read_text(encoding='utf-8')
                self.assertIn(notice, text.split('\n\n')[0])
                self.assertIn(draft, text)
                self.assertEqual(policy_date(text), policy_date(english))
                self.assertEqual(urls(text), urls(english))
                self.assertEqual(len(re.findall(r'^## ', text, re.M)), 7)
                for token in ('%LOCALAPPDATA%\\Brainamon', '%LOCALAPPDATA%\\Content Manager', 'BRAINAMON_HOME',
                              'data/', 'local/', 'drive.appdata', 'AES-256-GCM', 'Scrypt', 'docs/BACKUP-RESTORE.md',
                              'access-v2', 'license-v1', 'Phone browser', 'Frederic TOMAS', 'me@fredtomas.com',
                              'Settings > Backup & phones > Disconnect Google Drive...',
                              'Also delete the backup from Google Drive', 'Delete and disconnect',
                              'Settings > Backup & phones > Unpair this phone', "Settings > Storage > Clear the phone's copy"):
                    self.assertIn(token, text)

    def test_translated_listing_description_lengths_and_distribution_holds(self):
        root = Path(__file__).resolve().parents[1]
        for code, short_heading, full_heading, hold in [
                ('fr-FR', 'Description courte pour téléphone (80 caractères max)', 'Description complète pour téléphone', 'reste suspendue'),
                ('zh-TW', '手機簡短說明（最多 80 個字元）', '手機完整說明', '仍暫緩')]:
            with self.subTest(language=code):
                text = (root / f'mobile-shell/store/play-listing.{code}.md').read_text(encoding='utf-8')
                short = listing_description(text, short_heading)
                full = listing_description(text, full_heading)
                self.assertLessEqual(len(short), 80)
                self.assertLessEqual(len(full), 4000)
                self.assertIn('2026-11-02', text)
                self.assertIn(hold, text)
                for token in ('GPL-3.0-only', 'app.brainamon.mobile.contributor', 'me@fredtomas.com',
                              'https://ko-fi.com/fredtomas', 'https://github.com/knackychan/brainamon/releases',
                              'scripts/build_brand.py', 'assets-source/README.md'):
                    self.assertIn(token, text)
                print(f'Plan 08 {code}: short={len(short)}, full={len(full)} Unicode code points')


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneLanguageCoreTest(unittest.TestCase):
    def test_plan06_tasks_keep_ids_facts_shapes_and_default_english(self):
        node(r"""
          import assert from 'node:assert/strict'
          import fs from 'node:fs'
          import {stripTypeScriptTypes} from 'node:module'
          import {phoneTasks,progressOf,ANSWERS,SETUP_STEPS,desktopTasks} from './web/src/lib/onboarding.ts'
          import {setup,t} from './web/src/lib/i18n/index.ts'
          import {messages as fr} from './web/src/lib/i18n/fr/index.ts'
          import {messages as zh} from './web/src/lib/i18n/zh-Hant/index.ts'
          const fixed=JSON.stringify({ANSWERS,SETUP_STEPS,desktop:desktopTasks('links',{items:0,notes:0,wiskit:false})})
          for(const answer of ['pc','phone','skip','unknown'])for(const pc of [false,true])for(const items of [0,1,3000])for(const ai of [false,true]){
            const facts={pc,items,ai}, copy=JSON.stringify(facts)
            const expected=[{id:'install',label:'Install Brainamon',done:true},answer==='pc'?{id:'pc',label:'Connect your PC',done:pc}:{id:'saves',label:'Save your first link',done:items>0},{id:'wiskit',label:'Turn on Wiskit',done:ai}]
            setup({fr,'zh-Hant':zh},'en',[])
            assert.deepEqual(phoneTasks(answer,facts),expected)
            assert.deepEqual(phoneTasks(answer,facts,t),expected)
            for(const language of ['fr','zh-Hant']){
              setup({fr,'zh-Hant':zh},language,[])
              const displayed=phoneTasks(answer,facts,t)
              assert.deepEqual(displayed.map(({label,...rest})=>rest),expected.map(({label,...rest})=>rest))
              assert.deepEqual(progressOf(displayed),progressOf(expected))
              assert.ok(displayed.every((task,i)=>task.label!==expected[i].label))
              assert.deepEqual(phoneTasks(answer,facts),expected)
            }
            assert.equal(JSON.stringify(facts),copy)
          }
          assert.equal(JSON.stringify({ANSWERS,SETUP_STEPS,desktop:desktopTasks('links',{items:0,notes:0,wiskit:false})}),fixed)
          assert.equal(SETUP_STEPS.length,6)
          const src=fs.readFileSync('web/src/windows/AnalyzeOptionsForm.svelte','utf8')
          const module=src.match(/<script[^>]*module[^>]*>([\s\S]*?)<\/script>/)[1]
          const {FRAME_CHOICES,BUDGETS}=await import('data:text/javascript,'+encodeURIComponent(stripTypeScriptTypes(module)))
          assert.deepEqual(FRAME_CHOICES,[['Keep & show in item canvas',true,true],['Keep on disk only (hidden from canvas)',true,false],['Delete frames after analysis',false,false]])
          assert.deepEqual(BUDGETS,[['Auto (scale with length)','auto'],['Off (transcript only)','0'],['Up to 8','8'],['Up to 15','15'],['Up to 24','24']])
          assert.ok(!/^import /m.test(fs.readFileSync('web/src/lib/onboarding.ts','utf8')))
          assert.ok(!fs.existsSync('web/src/mobile/SetupList.svelte'))
          const processing=fs.readFileSync('web/src/mobile/Processing.svelte','utf8')
          assert.ok(processing.includes("import type { AO } from '../windows/AnalyzeOptionsForm.svelte'"))
          assert.ok(!processing.includes('<AnalyzeOptionsForm'))
        """)

    def test_plan05_recovery_task_and_vault_helpers_preserve_default_english(self):
        from tests.test_phone_reconnect import PRELUDE as RECONNECT
        from tests.test_mobile_recovery_remediation import PRELUDE as BACKUP
        from tests.test_vault_progress import FIXTURE as VAULT
        node(RECONNECT + r"""
          import assert from 'node:assert/strict'
          import {phoneWords} from './web/src/mobile/settings-words.ts'
          for(const [reason,message] of Object.entries({...R.REFUSALS,eligible:R.ELIGIBLE})){
            const check={ok:reason==='eligible',reason,message}
            assert.equal(R.eligibilityText(check),message)
            assert.equal(R.eligibilityText(check,phoneWords),message)
          }
        """)
        for kind in ('delete', 'replace'):
            output = []
            for formatter in ('undefined', 'phoneWords'):
                output.append(json.loads(node(BACKUP + r"""
                  import {phoneWords} from './web/src/mobile/settings-words.ts'
                  const steps=[]
                  await B.beginBackupTask(KIND,prefix)
                  await B.runBackupTask(new Changes(),(text,deleted)=>steps.push({text,deleted}),FORMATTER)
                  console.log(JSON.stringify(steps))
                """.replace('KIND', json.dumps(kind)).replace('FORMATTER', formatter))))
            self.assertEqual(output[0], output[1], kind)
            self.assertTrue(any('Removing selected backup files' in s['text'] for s in output[0]))
        node(TS_RESOLVE + VAULT + r"""
          import {phoneWords} from './web/src/mobile/settings-words.ts'
          const plain=await fixture(3,2),formatted=await fixture(3,2)
          formatted.env.words=phoneWords
          assert.deepEqual(await vaultRound(formatted.env),await vaultRound(plain.env))
          assert.deepEqual(formatted.events,plain.events)
          const {mergeVault}=await import('./web/src/mobile/vault/merge.ts')
          const {readFileSync}=await import('node:fs')
          const cases=JSON.parse(readFileSync('tests/fixtures/vault_cases.json','utf8'))
          for(const c of cases){
            const args=[c.base,c.mine,c.theirs,c.role,new Date(2026,9,12,9,30),{generated:c.generated?new Set(c.generated):null,removed:c.removed,mineHash:c.mine_hash,fresh:c.fresh,kept:c.kept}]
            assert.deepEqual(mergeVault(...args,phoneWords),mergeVault(...args))
          }
        """)

    def test_plan05_successful_pairing_keeps_raw_control_until_secure_save_and_invalid_input(self):
        from tests.test_phone_resend import PAIRING, keys, run
        result = run(PAIRING + r"""
          import assert from 'node:assert/strict'
          import fs from 'node:fs'
          import {stripTypeScriptTypes} from 'node:module'
          import {setup,t} from './web/src/lib/i18n/index.ts'
          import {messages as fr} from './web/src/lib/i18n/fr/index.ts'
          import {messages as zh} from './web/src/lib/i18n/zh-Hant/index.ts'
          import {phoneWords,nativeError} from './web/src/mobile/settings-words.ts'
          const source=fs.readFileSync('web/src/mobile/state.svelte.ts','utf8')
          const region=source.slice(source.indexOf('export async function pairFrom('),source.indexOf('// use the phone without a PC:'))
          const phone={note:''},events=[],raw=[];let finish
          const location={pathname:'/mobile.html',replace:path=>events.push(path),reload:()=>events.push('reload')}
          globalThis.__pairDeps={phone,location,backup:{},t,phoneWords,nativeError,RECONNECT_BUSY:'busy',reconnecting:()=>false,beginLanguageWork:()=>()=>{},pairing:P.pairing,
            acceptLink:async(...args)=>{const note=await P.acceptLink(...args);raw.push(note);return note},secretsSaved:()=>new Promise(resolve=>finish=resolve)}
          const mod=await import('data:text/javascript,'+encodeURIComponent(stripTypeScriptTypes('const {phone,location,backup,t,phoneWords,nativeError,RECONNECT_BUSY,reconnecting,beginLanguageWork,pairing,acceptLink,secretsSaved}=globalThis.__pairDeps;'+region)))
          for(const language of ['fr','zh-Hant']){
            setup({fr,'zh-Hant':zh},language,[]);await P.startSolo(K[1].k);events.length=0;finish=null
            const scan={v:2,k:K[0].k,f:K[0].f,l:A,c:'client',e:'synthetic@example.test'}
            const running=mod.pairFrom(link(scan))
            while(!finish)await new Promise(resolve=>setTimeout(resolve,0))
            assert.equal(raw.at(-1),'Paired with your PC.');assert.notEqual(phone.note,raw.at(-1));assert.equal(events.length,0)
            assert.equal(JSON.parse(secrets.get('bp-pair')).k,K[0].k)
            finish();await running;assert.deepEqual(events,['/mobile.html#/backup','reload'])
            assert.equal(session.get('bp-note'),phone.note)
            events.length=0;const stored=secrets.get('bp-pair')
            await mod.pairFrom('#pair=invalid')
            assert.equal(raw.at(-1),'That pairing code could not be read. Show the QR on the PC again.')
            assert.notEqual(phone.note,raw.at(-1));assert.equal(secrets.get('bp-pair'),stored);assert.equal(events.length,0)
          }
          console.log(JSON.stringify({languages:2,successAndInvalid:true,secureReload:true}))
        """, KEYS=keys())
        self.assertEqual(result, dict(languages=2, successAndInvalid=True, secureReload=True))

    def test_plan05_all_fixture_decisions_and_defaults_are_unchanged(self):
        node(TS_RESOLVE + r"""
          import assert from 'node:assert/strict'
          import fs from 'node:fs'
          import {setup, t} from './web/src/lib/i18n/index.ts'
          import {messages as fr} from './web/src/lib/i18n/fr/index.ts'
          import {messages as zh} from './web/src/lib/i18n/zh-Hant/index.ts'
          import {phoneState, clock, day} from './web/src/mobile/mirror/phone-state.ts'
          import {phoneWords, nativeError} from './web/src/mobile/settings-words.ts'
          import * as L from './web/src/mobile/settings-lines.ts'
          import {diagnoseNoLibrary} from './web/src/mobile/mirror/diagnose.ts'
          import {unpairWarning} from './web/src/mobile/mirror/phone-facts.ts'
          import {progress} from './web/src/lib/progress.ts'
          import {amount,num} from './web/src/lib/backup.ts'
          const fx=JSON.parse(fs.readFileSync('tests/fixtures/phone_states.json','utf8'))
          const signature=s=>[s.id,s.tone,s.action?.id,s.action?.primary,s.strip,Object.keys(s).sort()]
          for(const language of ['en','fr','zh-Hant']){
            setup({fr,'zh-Hant':zh},language,[])
            for(const c of fx.cases){
              const f={...fx.base,...c.facts}, raw=phoneState(f), shown=phoneState(f,phoneWords)
              assert.deepEqual(raw,c.expect, c.name+' fixture')
              assert.deepEqual(signature(shown),signature(raw),language+' '+c.name)
              assert.equal(Object.keys(shown).length,7)
              assert.ok(!JSON.stringify(shown).includes('backup.state.'))
              if(language==='en')assert.deepEqual(shown,raw,c.name+' English formatter')
            }
            for(const n of [0,1,2,3000])for(const mode of ['pc','solo']){
              const f={...fx.base,mode,unsent:n,waiting:n,resending:0}
              assert.deepEqual(signature(phoneState(f,phoneWords)),signature(phoneState(f)))
            }
          }
          setup({fr,'zh-Hant':zh},'en',[])
          const calls=[['syncLine',{signedIn:false,lamp:'idle',wifiOnly:true}],['syncLine',{signedIn:true,lamp:'idle',wifiOnly:false}],
            ['phoneLine',true,'abcdef'],['phoneLine',false,'abcdef'],['aiLine','OpenAI',true],['aiLine','',false],
            ['vaultLine',{name:'Original',syncing:true,lamp:'in step'}],['vaultLine',{name:'',syncing:false,lamp:'off'}],
            ['storageLine','86 MB',false,'off'],['storageLine','1.2 GB',true,'all'],['lookLine','Cover',true],
            ['aboutLine',{desktop:true,version:'1.0.9'}],['aboutLine',{desktop:false,version:'1.0.9'}],
            ['googleLine',{signedIn:false,account:'',driveOk:false,lamp:'off',solo:true}],
            ['thisPhoneLine',{solo:false,name:'Original',unsent:3}],['thisPhoneLine',{solo:true,name:'',unsent:0}],
            ...['none','prepared','saved','checked'].map(f=>['recoveryLine',true,f]),['recoveryLine',false,'']]
          const expected=['Google Drive not connected','Any network · runs on its own','Saving here · a PC is optional','Paired · key abcdef','OpenAI on your key','No AI key · pair again',
            'Original · in step','Vault name not set','86 MB · keeps favourites','1.2 GB · favs, canvases, videos','Cover cards · night on','Windows app · v1.0.9 · licenses','Version 1.0.9 · licenses',
            'Sign in','Original · 3 not sent','All backed up · no PC paired','Not set up','Passphrase set','File saved, not checked','Passphrase set · file checked','Managed on your PC']
          calls.forEach(([name,...args],i)=>{assert.equal(L[name](...args),expected[i]);assert.equal(L[name](...args,phoneWords),expected[i])})
          assert.deepEqual([0,1,2].map(unpairWarning),['',"1 edit hasn't reached your PC yet. If you unpair now, it never will.","2 edits haven't reached your PC yet. If you unpair now, they never will."])
          for(const n of [0,1,2,3000])assert.equal(unpairWarning(n,phoneWords),unpairWarning(n))
          const base={listed:[],ours:false,signedAs:'original@example.test',pcAccount:'pc@example.test',pcProject:'111111',phoneProject:'111111'}
          for(const over of [{listed:null,problem:'<img>'},{ours:true},{listed:['a'.repeat(32)]},{listed:['vi-vault']},{phoneProject:'222222'},{pcAccount:''},{}]){
            const f={...base,...over};assert.deepEqual(diagnoseNoLibrary(f,phoneWords),diagnoseNoLibrary(f))
            const raw=diagnoseNoLibrary(f);setup({fr,'zh-Hant':zh},'fr',[])
            const shown=diagnoseNoLibrary(f,phoneWords)
            assert.deepEqual([shown.cause,shown.changeAccount,shown.pairAgain],[raw.cause,raw.changeAccount,raw.pairAgain])
            assert.ok(!shown.message.includes('backup.diagnose.'));setup({fr,'zh-Hant':zh},'en',[])
          }
          for(const [done,total,since,now,want] of [[10,2827,1000,213000,''],[30,2827,1000,5000,''],[30,60,1000,61000,'about 1 min left'],[60,60,1000,121000,''],[30,31,1000,11000,'under a minute left'],[30,3630,1000,61000,'about 2 h left'],[30,3660,1000,61000,'about 2 h 1 min left']]){
            assert.equal(progress(done,total,since,now).left,want)
            assert.deepEqual(progress(done,total,since,now,phoneWords),progress(done,total,since,now))
          }
          for(const bytes of [0,1,1048575,1048576,1073741823,1073741824,1610612736,...[1.05,1.15,1.95,2.55].map(n=>n*1073741824)])assert.equal(amount(bytes,phoneWords),amount(bytes))
          assert.equal(num(3000.4),'3,000');assert.equal(amount(1610612736),'1.5 GB')
          process.env.TZ='UTC';const now=Date.UTC(2026,10,8,15,5)
          assert.equal(clock(now,now),'15:05');assert.equal(clock(now-864e5,now),'7 Nov 15:05');assert.equal(clock(0,now),'');assert.equal(day(now),'8 Nov')
          for(const operation of ['google','scanner','secure','network','vault','recovery','backup','openUri'])
            for(const error of [new Error('<img src=x onerror=alert(1)>'),{code:'failed',message:'Original provider detail'},null,{message:42}])
              assert.equal(nativeError(operation,error),String(error?.message??error))
        """)

    def test_plan05_native_codes_timeouts_cancellation_and_late_results(self):
        node(TS_RESOLVE + r"""
          import assert from 'node:assert/strict'
          import {registerHooks} from 'node:module'
          import {setup} from './web/src/lib/i18n/index.ts'
          import {messages as fr} from './web/src/lib/i18n/fr/index.ts'
          import {messages as zh} from './web/src/lib/i18n/zh-Hant/index.ts'
          import {nativeError} from './web/src/mobile/settings-words.ts'
          import {withTimeout} from './web/src/mobile/wait.ts'
          let qr, pick, google, writes=0, failWrite=false
          globalThis.__plugin={scanQr:()=>qr(),vaultPick:()=>pick(),googleToken:()=>google(),secretSet:async()=>{writes++;if(failWrite)throw Error('synthetic')}}
          registerHooks({resolve(s,c,next){
            if(s==='@capacitor/core')return {url:'data:text/javascript,export const Capacitor={isNativePlatform:()=>true};export const registerPlugin=()=>globalThis.__plugin;export const CapacitorHttp={}',shortCircuit:true}
            if(s==='@capacitor/app')return {url:'data:text/javascript,export const App={}',shortCircuit:true}
            return next(s,c)
          }})
          const native=await import('./web/src/mobile/native.ts')
          for(const language of ['fr','zh-Hant']){
            setup({fr,'zh-Hant':zh},language,[])
            qr=async()=>{throw Object.assign(Error('No code was scanned.'),{code:'cancelled'})}
            assert.equal(await native.scanQr(),'')
            pick=async()=>{throw Error('cancelled')}
            await assert.rejects(native.vaultPick(),e=>e.message==='cancelled')
            qr=async()=>{throw Object.assign(Error('<img> original scanner'),{code:'failed'})}
            try{await native.scanQr();assert.fail()}catch(e){assert.ok(nativeError('scanner',e).includes('<img> original scanner'));assert.equal(e.message,'<img> original scanner')}
            for(const code of ['denied','consent','failed']){
              google=async()=>{throw Object.assign(Error('Original Google detail'),{code})}
              await assert.rejects(native.googleToken(false),e=>e.code===code&&nativeError('google',e)!=='Original Google detail')
            }
            let late
            google=()=>new Promise(resolve=>late=resolve)
            const timer=setTimeout;globalThis.setTimeout=(fn,ms,...args)=>timer(fn,ms===120000?1:ms,...args)
            await assert.rejects(native.googleToken(false),e=>e.code==='timeout'&&e.message==='Google did not answer in 2 minutes (its sheet may have closed). Try again.'&&nativeError('google',e)!==e.message)
            late({token:'synthetic',expiresIn:3600});globalThis.setTimeout=timer
            assert.equal(native.secrets.get('bp-gtoken'),null)
            failWrite=true;native.secrets.set('bp-pair','synthetic-retained')
            await assert.rejects(native.secretsSaved(),e=>e.code==='write'&&nativeError('secure',e)!==e.message)
            assert.equal(native.secrets.get('bp-pair'),'synthetic-retained');assert.equal(native.secretsHaveFailures(),true)
            failWrite=false;native.secrets.set('bp-pair','synthetic-retained');await native.secretsSaved();assert.equal(native.secretsHaveFailures(),false)
          }
          let resolveLate;const late=withTimeout(new Promise(resolve=>resolveLate=resolve),1,'original timeout','local-timeout')
          await assert.rejects(late,e=>e.code==='local-timeout'&&e.message==='original timeout');resolveLate('late')
          assert.equal(writes,4)
        """)

    def test_plan05_pc_status_and_recovery_export_keep_default_english_and_payloads(self):
        node(TS_RESOLVE + r"""
          import assert from 'node:assert/strict'
          import fs from 'node:fs'
          import vm from 'node:vm'
          import {stripTypeScriptTypes} from 'node:module'
          import ts from './web/node_modules/typescript/lib/typescript.js'
          import {phoneWords} from './web/src/mobile/settings-words.ts'
          import {fmtDate,fmtTime} from './web/src/lib/i18n/format.ts'
          import {progress} from './web/src/lib/progress.ts'
          process.env.TZ='UTC';const RealDate=Date,fixedNow=Date.UTC(2026,10,8,15,5)
          globalThis.Date=class extends RealDate {constructor(...args){super(...(args.length?args:[fixedNow]))}static now(){return fixedNow}}
          const source=fs.readFileSync('web/src/mobile/vault/auto.svelte.ts','utf8')
          const region=source.slice(source.indexOf('function when('),source.indexOf('export async function readPc'))
          globalThis.__pcDeps={progress,fmtDate,fmtTime}
          const mod=await import('data:text/javascript,'+encodeURIComponent(stripTypeScriptTypes('const PC_STALE_MS=120000;const {progress,fmtDate,fmtTime}=globalThis.__pcDeps;'+region)))
          const base={state:'syncing',step:'Original PC step',done:30,total:60,since:Date.now()-60000,at:Date.now(),last:Date.now(),reason:'Original PC reason',summary:'Original PC summary'}
          const cases=[{}, {at:Date.now()-120001},{state:'off'},{state:'starting'},{state:'stopping'},{state:'brake'},{state:'error'},{state:'idle'},{state:'idle',summary:''}]
          const time=new Date(base.at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})
          const staleTime=new Date(base.at-120001).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})
          const expected=[`Original PC step 30/60 · 50% · about 1 min left`,`No news from the PC since ${staleTime}: its round may have stopped`,
            `Vault sync is off on the PC (Settings > Obsidian & map > Vault sync with phone) · reported ${time}`,`Starting on the PC · reported ${time}`,`Stopping on the PC · reported ${time}`,
            'Held on the PC: Original PC reason (Apply deletions anyway in Settings > Obsidian & map)','Original PC reason',`Last round ${time} · Original PC summary`,`Last round ${time}`]
          cases.forEach((over,i)=>{const p={...base,...over};assert.equal(mod.pcLine(p),expected[i]);assert.equal(mod.pcLine(p,phoneWords),expected[i]);assert.deepEqual(mod.pcProgress(p,phoneWords),mod.pcProgress(p))})
          const yesterday=new Date(base.last-86400000)
          assert.equal(mod.pcLine({...base,state:'idle',last:+yesterday,summary:''}),`Last round ${yesterday.toLocaleDateString()} ${yesterday.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}`)
          globalThis.Date=RealDate
          const downloads=[],result={};let native=false
          class Key {static fromText=async()=>({fingerprint:'synthetic-fingerprint'})}
          const deps={'../../lib/recovery':{downloadRecovery:(...args)=>downloads.push(args)},'../native':{get isApp(){return native},vaultPick:async()=>({uri:'synthetic-uri',name:'Original folder'}),vaultFs:()=>({write:async()=>{}})},'./crypto':{MirrorKey:Key}}
          vm.runInNewContext(ts.transpileModule(fs.readFileSync('web/src/mobile/mirror/recovery.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,
            {exports:result,require:s=>{assert.ok(s in deps,s);return deps[s]},TextEncoder,Date})
          const pair={k:'synthetic-key',f:'synthetic-fingerprint'}
          assert.equal(await result.exportPhoneRecovery(pair),'Recovery file downloaded. Keep it outside this phone and never share it.')
          assert.equal(await result.exportPhoneRecovery(pair,phoneWords),'Recovery file downloaded. Keep it outside this phone and never share it.')
          assert.deepEqual(downloads[0][0],downloads[1][0]);assert.equal(downloads[0][0].key,pair.k)
          assert.equal(downloads[0][0].instructions,'This file unlocks the original encrypted Drive mirror. Keep it separate from your devices. It is not a library backup. On a replacement PC: Settings > Backup & phones > Recover a library…, then Recovery file.')
          native=true;assert.equal(await result.exportPhoneRecovery(pair),'Recovery file saved in Original folder. Keep a copy outside this phone.')
          assert.equal(await result.exportPhoneRecovery(pair,phoneWords),'Recovery file saved in Original folder. Keep a copy outside this phone.')
        """)

    def test_cloud_gate_blocks_nested_work_and_rechecks_during_switch(self):
        node("""
          import assert from 'node:assert/strict'
          import * as gate from './web/src/mobile/mirror/gate.ts'
          import { registerLanguageCheck, switchLanguage } from './web/src/mobile/language-switch.ts'
          let writes = 0
          const change = () => switchLanguage('fr','en',async()=>{}, {setItem(){writes++}},()=>{})
          gate.beginCloudChange(); gate.beginCloudChange()
          assert.equal((await change()).status, 'blocked')
          gate.endCloudChange()
          assert.equal((await change()).status, 'blocked')
          gate.endCloudChange()
          gate.setReconnecting(true)
          assert.equal((await change()).status, 'blocked')
          gate.setReconnecting(false)
          let release
          const remove = registerLanguageCheck(() => new Promise(resolve => release = resolve))
          const pending = change()
          while (!release) await Promise.resolve()
          gate.beginCloudChange(); release(null)
          assert.equal((await pending).status, 'blocked')
          assert.equal(writes, 0)
          remove(); gate.endCloudChange()
          await gate.stopCloudWork()
          assert.equal(gate.cloudStopped(), true)
          assert.equal((await change()).status, 'reloaded')
          assert.equal(gate.cloudStopped(), true)
          assert.equal(writes, 1)
          gate.allowCloudWork()
        """)

    def test_journal_reports_memory_fallback_and_waits_for_commit(self):
        node("""
          import assert from 'node:assert/strict'
          const { journal } = await import('./web/src/mobile/store.ts')
          assert.equal(await journal([], [], {delivery:{next:2}}), false)
          const { items, kv } = await import('./web/src/mobile/store.ts')
          await assert.rejects(items.getRequired(1), /storage is unavailable/)
          await assert.rejects(kv.getRequired('saved-canvases'), /storage is unavailable/)
        """)
        node("""
          import assert from 'node:assert/strict'
          let active
          const db = { transaction: () => {
            const tx = { error:null, objectStore: () => ({put(){return {result:17}}, get(){return {result:'synthetic'}}, delete(){}}) }
            active = tx; return tx
          } }
          globalThis.indexedDB = {open: () => { const r = {}; queueMicrotask(() => {r.result = db; r.onsuccess()}); return r }}
          const { journal, changes, items, kv } = await import('./web/src/mobile/store.ts')
          let settled = false
          const write = journal([], [], {delivery:{next:2}}).then(value => { settled = true; return value })
          while (!active) await Promise.resolve()
          assert.equal(settled, false)
          active.oncomplete()
          assert.equal(await write, true)
          active = null
          const aborted = journal([], [], {delivery:{next:3}})
          while (!active) await Promise.resolve()
          active.onabort()
          await assert.rejects(aborted, /did not save/)
          active = null
          const failedDelete = changes.delConfirmed(17)
          while (!active) await Promise.resolve()
          active.onabort()
          assert.equal(await failedDelete, false)
          active = null
          const deleted = changes.delConfirmed(17)
          while (!active) await Promise.resolve()
          active.oncomplete()
          assert.equal(await deleted, true)
          active = null
          const read = kv.getRequired('saved-canvases')
          while (!active) await Promise.resolve()
          active.onabort()
          await assert.rejects(read, /could not complete/)
          active = null
          const saved = items.putRequired({id:1})
          while (!active) await Promise.resolve()
          active.oncomplete()
          assert.equal(await saved, 17)
        """)

    def test_known_storage_errors_localize_only_at_phone_presentation(self):
        result = json.loads(node(TS_RESOLVE + """
          const {setup}=await import('./web/src/lib/i18n/index.ts')
          const {messages:fr}=await import('./web/src/lib/i18n/fr/index.ts')
          const {messages:zh}=await import('./web/src/lib/i18n/zh-Hant/index.ts')
          const {captureError}=await import('./web/src/mobile/capture-words.ts')
          const {nativeError}=await import('./web/src/mobile/settings-words.ts')
          const {kv,putCanvasPending}=await import('./web/src/mobile/store.ts')
          const rows=[]
          for(const language of ['en','fr','zh-Hant']) {
            setup({fr,'zh-Hant':zh},language,[])
            const errors=[]
            for(const action of [()=>kv.getRequired('synthetic'),()=>putCanvasPending('synthetic',{})]) {
              try {await action();throw new Error('Expected unavailable storage')}
              catch(e){errors.push({raw:e.message,label:captureError(e),native:nativeError('backup',e)})}
            }
            rows.push({language,errors,unknown:captureError(new Error('<external original>'))})
          }
          console.log(JSON.stringify(rows))
        """))
        expected = {
            'en': ['Phone storage is unavailable. Retry when storage is available.', 'Phone storage is unavailable.'],
            'fr': ['Le stockage du téléphone est indisponible. Réessayez lorsqu’il sera disponible.', 'Le stockage du téléphone est indisponible.'],
            'zh-Hant': ['手機儲存空間無法使用。請在儲存空間可用時重試。', '手機儲存空間無法使用。'],
        }
        for row in result:
            self.assertEqual([e['raw'] for e in row['errors']], expected['en'])
            self.assertEqual([e['label'] for e in row['errors']], expected[row['language']])
            self.assertEqual([e['native'] for e in row['errors']], expected[row['language']])
            self.assertEqual(row['unknown'], '<external original>')

    def test_import_time_translation_scan(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', 'tests/check_phone_i18n_ast.mjs'], cwd=root,
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_literal_inventory_is_strict(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', 'tests/check_phone_i18n_literals.mjs'], cwd=root,
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Untranslated literal candidates: 0', result.stdout)

    def test_exact_catalog_types_reject_missing_and_spread_extra_keys(self):
        root = Path(__file__).resolve().parents[1]
        compiler = root / 'web/node_modules/typescript/bin/tsc'
        module = (root / 'web/src/lib/i18n/en/index.ts').as_posix()
        prefix = f"import {{ messages, exactCatalog }} from {json.dumps(module)};\n"
        cases = {
            'valid': ('exactCatalog({ ...messages });', True),
            'missing': ("const { 'common.retry': removed, ...rest } = messages; exactCatalog(rest);", False),
            'extra': ("exactCatalog({ ...messages, unexpected: 'x' });", False),
            'spread': ("const extra = { unexpected: 'x' }; exactCatalog({ ...messages, ...extra });", False),
        }
        with tempfile.TemporaryDirectory(prefix='brainamon-i18n-types-') as folder:
            for name, (code, expected) in cases.items():
                with self.subTest(name=name):
                    fixture = Path(folder) / (name + '.ts')
                    fixture.write_text(prefix + code + '\n', encoding='utf-8')
                    result = subprocess.run(['node', str(compiler), '--noEmit', '--skipLibCheck', '--target',
                                             'es2023', '--module', 'esnext', '--moduleResolution', 'bundler',
                                             '--allowImportingTsExtensions', str(fixture)],
                                            cwd=root, capture_output=True, text=True, encoding='utf-8')
                    self.assertEqual(result.returncode == 0, expected, result.stdout + result.stderr)

    def test_language_selection_and_default_english(self):
        result = json.loads(node("""
          import { lang, pickLang, setup, t } from './web/src/lib/i18n/index.ts'
          const before = [lang(), t('common.retry')]
          const readiness = { fr: true, 'zh-Hant': true }
          const choices = [
            pickLang('fr', ['en-US']), pickLang('zh-Hant', []),
            pickLang('auto', ['bad_tag', 'fr-CA'], readiness),
            pickLang('auto', ['zh-CN'], readiness), pickLang('auto', ['zh-Hans'], readiness),
            pickLang('auto', ['fr-FR', 'en-US']), pickLang('invalid', ['de-DE']),
            pickLang('auto', ['FR-ca'], readiness), pickLang('auto', []), pickLang('auto', null),
          ]
          setup({}, 'en', [])
          console.log(JSON.stringify({ before, choices, after: [lang(), t('common.retry')] }))
        """))
        self.assertEqual(result['before'], ['en', 'Retry'])
        self.assertEqual(result['after'], result['before'])
        self.assertEqual(result['choices'], ['fr', 'zh-Hant', 'fr', 'zh-Hant', 'zh-Hant', 'en', 'en', 'fr', 'en', 'en'])

    def test_fallback_plurals_interpolation_and_french_typography(self):
        result = json.loads(node("""
          import { frenchTypography, setup, t } from './web/src/lib/i18n/index.ts'
          const input = '« Bonjour ! » <code>x : y</code> https://example.test/a?b=1 {name} : oui;'
          const once = frenchTypography(input)
          const fr = { 'common.retry': { one: '{n} élément', other: '{n} éléments' },
                       'shell.startup.loading': 'Bonjour {name} !', 'shell.startup.title': 'Valeur {missing}',
                       'missing.key': 'Do not use' }
          setup({ fr }, 'fr', [])
          const plurals = [0, 1, 2, 1.5, 1000000, null].map(n => t('common.retry', { n }))
          const output = { once, twice: frenchTypography(once), plurals,
            inserted: t('shell.startup.loading', { name: '<b>{x}</b> !' }),
            missing: t('shell.startup.title', Object.create({ missing: 'inherited' })),
            fallback: t('shell.startup.failedTitle'), absent: t('missing.key'), invalid: t('shell.startup.title', null) }
          setup({}, 'en', [])
          console.log(JSON.stringify(output))
        """))
        self.assertEqual(result['once'], '«\u00a0Bonjour\u202f!\u00a0» <code>x : y</code> https://example.test/a?b=1 {name}\u00a0: oui\u202f;')
        self.assertEqual(result['twice'], result['once'])
        self.assertEqual(result['plurals'], ['0 élément', '1 élément', '2 éléments', '1.5 élément', '1000000 éléments', 'null éléments'])
        self.assertEqual(result['inserted'], 'Bonjour <b>{x}</b> !\u202f!')
        self.assertEqual(result['missing'], 'Valeur {missing}')
        self.assertEqual(result['fallback'], 'Brainamon could not start')
        self.assertEqual(result['absent'], 'missing.key')
        self.assertEqual(result['invalid'], 'Valeur {missing}')

    def test_plural_counts_are_own_finite_numbers_and_fallback_uses_english(self):
        node("""
          import assert from 'node:assert/strict'
          import { setup, t } from './web/src/lib/i18n/index.ts'
          const fr = { 'notes.count': { one: 'one {n}', other: 'other {n}', many: 'many {n}' } }
          setup({ fr }, 'fr', [])
          for (const n of [undefined, null, '1', NaN, Infinity])
            assert.equal(t('notes.count', { n }), `other ${n}`)
          const inherited = Object.create({ get n() { throw Error('inherited count read') } })
          assert.equal(t('notes.count', inherited), 'other {n}')
          assert.equal(t('notes.count', { n: 1000000 }), 'many 1000000')
          setup({ fr: Object.create({ 'notes.count': fr['notes.count'] }) }, 'fr', [])
          const fallback = t('notes.count', { n: 0 })
          setup({}, 'en', [])
          assert.equal(fallback, t('notes.count', { n: 0 }))
        """)

    def test_french_typography_preserves_paths_and_source_catalogs(self):
        node(r"""
          import assert from 'node:assert/strict'
          import { frenchTypography, setup, t } from './web/src/lib/i18n/index.ts'
          for (const path of [String.raw`C:\notes\a;b.md`, String.raw`\\server\share\a;b.md`,
                              './notes/a;b.md', '../notes/a;b.md', '/notes/a;b.md',
                              'https://example.test/a?b=1;c=2'])
            assert.equal(frenchTypography(path), path)
          const fr = { 'common.retry': '« Réessayer ! » <code>x : y;</code> {path}' }
          const original = JSON.stringify(fr)
          setup({ fr }, 'fr', [])
          const once = t('common.retry', { path: String.raw`C:\my notes\a;b.md` })
          setup({ fr }, 'fr', [])
          assert.equal(t('common.retry', { path: String.raw`C:\my notes\a;b.md` }), once)
          assert.equal(JSON.stringify(fr), original)
          assert.ok(once.endsWith(String.raw`C:\my notes\a;b.md`))
        """)

    def test_unknown_note_display_ids_preserve_prototype_names(self):
        node("""
          import assert from 'node:assert/strict'
          import { setup } from './web/src/lib/i18n/index.ts'
          import { noteKind, inkName, markerName, stampName } from './web/src/mobile/notes-words.ts'
          for (const language of ['en', 'fr', 'zh-Hant']) {
            setup({}, language, [])
            for (const value of ['constructor', 'toString', '__proto__', 'My own kind'])
              for (const display of [noteKind, inkName, markerName, stampName])
                assert.equal(display(value), value)
          }
        """)

    def test_rich_markup_is_parsed_before_parameters_and_rejects_unsafe_links(self):
        result = json.loads(node("""
          import { parseRich, safeHref } from './web/src/lib/i18n/rich.ts'
          const nested = parseRich('<b>Open <a:help>{name}</a></b>', { name: '<i>{other}</i>' })
          const bad = ['<b>oops', '<a:x><a:y>nested</a></a>', '<img src=x>', '<b>wrong</i>']
            .map(text => parseRich(text))
          const hrefs = ['https://example.test/help', 'http://example.test', 'javascript:alert(1)',
                         'data:text/html,x', 'https://user:pass@example.test', '/relative'].map(safeHref)
          console.log(JSON.stringify({ nested, bad, hrefs }))
        """))
        self.assertEqual(result['nested'], [{'type': 'b', 'children': [
            {'type': 'text', 'value': 'Open '},
            {'type': 'a', 'name': 'help', 'children': [{'type': 'text', 'value': '<i>{other}</i>'}]},
        ]}])
        self.assertTrue(all(len(entry) == 1 and entry[0]['type'] == 'text' for entry in result['bad']))
        self.assertEqual(result['hrefs'], ['https://example.test/help', 'http://example.test', None, None, None, None])

    def test_catalogs_have_matching_keys_shapes_and_parameters(self):
        result = json.loads(node("""
          import * as en from './web/src/lib/i18n/en/index.ts'
          import * as fr from './web/src/lib/i18n/fr/index.ts'
          import * as zh from './web/src/lib/i18n/zh-Hant/index.ts'
          import { parseRich } from './web/src/lib/i18n/rich.ts'
          import { budgets as commonBudgets } from './web/src/lib/i18n/en/common.ts'
          import { budgets as shellBudgets } from './web/src/lib/i18n/en/shell.ts'
          import { budgets as libraryBudgets } from './web/src/lib/i18n/en/library.ts'
          import { budgets as itemBudgets } from './web/src/lib/i18n/en/item.ts'
          import { budgets as settingsBudgets } from './web/src/lib/i18n/en/settings.ts'
          import { budgets as backupBudgets } from './web/src/lib/i18n/en/backup.ts'
          import { budgets as recoveryBudgets } from './web/src/lib/i18n/en/recovery.ts'
          import { budgets as notesBudgets } from './web/src/lib/i18n/en/notes.ts'
          import { budgets as canvasBudgets } from './web/src/lib/i18n/en/canvas.ts'
          import { budgets as wiskitBudgets } from './web/src/lib/i18n/en/wiskit.ts'
          import { budgets as processingBudgets } from './web/src/lib/i18n/en/processing.ts'
          import { budgets as captureBudgets } from './web/src/lib/i18n/en/capture.ts'
          import { budgets as importBudgets } from './web/src/lib/i18n/en/imports.ts'
          import { budgets as voiceBudgets } from './web/src/lib/i18n/en/voice.ts'
          import { budgets as onboardingBudgets } from './web/src/lib/i18n/en/onboarding.ts'
          import { budgets as sharedBudgets } from './web/src/lib/i18n/en/shared.ts'
          import { budgets as legalBudgets } from './web/src/lib/i18n/en/legal.ts'
          const languages = { en, fr, zh }, problems = []
          const names = object => Object.keys(object).sort().join('|')
          const tokens = text => [...text.matchAll(/\\{([\\w.-]+)\\}/g)].map(x => x[1]).sort().join('|')
          const tags = text => [...text.matchAll(/<\\/?(?:b|i|code|a(?::[\\w.-]+)?)>/g)].map(x => x[0]).sort().join('|')
          for (const [lang, data] of Object.entries(languages)) {
            const all = data.areas.flatMap(area => Object.keys(area))
            if (new Set(all).size !== all.length) problems.push(`${lang}: duplicate key`)
            if (names(data.messages) !== names(en.messages)) problems.push(`${lang}: key mismatch`)
            for (const [key, original] of Object.entries(en.messages)) {
              const translated = data.messages[key]
              if ((typeof original === 'string') !== (typeof translated === 'string')) {
                problems.push(`${lang}: shape ${key}`); continue
              }
              const branches = typeof translated === 'string' ? [translated] : Object.values(translated)
              if (typeof translated !== 'string' && (!translated.other || (lang !== 'zh' && !translated.one)))
                problems.push(`${lang}: plural ${key}`)
              const baseline = typeof original === 'string' ? original : original.other
              if (typeof translated !== 'string' && Object.keys(translated).some(form => !['zero','one','two','few','many','other'].includes(form)))
                problems.push(`${lang}: unsupported plural category ${key}`)
              for (const branch of branches) {
                if (tokens(branch) !== tokens(baseline) || tags(branch) !== tags(baseline))
                  problems.push(`${lang}: parameters or tags ${key}`)
                const rawMarkup = nodes => nodes.some(node => node.type === 'text' ? /[<>]/.test(node.value) : rawMarkup(node.children))
                if (branch.includes('<') && rawMarkup(parseRich(branch))) problems.push(`${lang}: malformed rich message ${key}`)
              }
            }
          }
          const banned = /軟件|網絡|信息|默認|視頻|文件夾|屏幕|鏈接|登錄|設置|用戶|程序|數據|質量/
          for (const [key, message] of Object.entries(zh.messages))
            if (banned.test(JSON.stringify(message))) problems.push(`zh: banned term ${key}`)
          const budgets = { ...commonBudgets, ...shellBudgets, ...libraryBudgets, ...itemBudgets, ...settingsBudgets, ...backupBudgets, ...recoveryBudgets, ...notesBudgets, ...canvasBudgets, ...wiskitBudgets, ...processingBudgets, ...captureBudgets, ...importBudgets, ...voiceBudgets, ...onboardingBudgets, ...sharedBudgets, ...legalBudgets }
          for (const [key, budget] of Object.entries(budgets)) {
            for (const [language, data] of Object.entries(languages)) {
              // rendered text only: rich tags do not count (spec section 3.2)
              const text = data.messages[key].replace(/<\\/?(?:b|i|code|a(?::[\\w.-]+)?)>/g, '')
                .replace(/\\{([\\w.-]+)\\}/g, (_, name) => String(budget.params[name] ?? ''))
              const width = [...text].reduce((n, c) => n + (/\\p{Script=Han}/u.test(c) ? 2 : 1), 0)
              if (width > budget.limit) problems.push(`${language}: budget ${key}`)
            }
          }
          console.log(JSON.stringify(problems))
        """))
        self.assertEqual(result, [])

    def test_formatters_preserve_english_boundaries_and_localize_display(self):
        result = json.loads(node("""
          import { setup } from './web/src/lib/i18n/index.ts'
          import { messages as fr } from './web/src/lib/i18n/fr/index.ts'
          import { messages as zh } from './web/src/lib/i18n/zh-Hant/index.ts'
          import { fmtAgo, fmtDate, fmtList, fmtNum, fmtSize, fmtTime } from './web/src/lib/i18n/format.ts'
          process.env.TZ = 'UTC'
          const now = 2000000000, options = { day: '2-digit', month: 'short' }
          setup({ fr, 'zh-Hant': zh }, 'en', [])
          const en = { sizes: [0, 999, 999999, 1000000, 9999999, 10000000, 1000000000, NaN].map(fmtSize),
            ago: [0, now, now - 60000, now - 3600000, now - 86400000].map(ms => fmtAgo(ms, now)),
            date: fmtDate(0, options, 'en-GB'), time: fmtTime(0, { hour: '2-digit', minute: '2-digit' }, 'en-GB'),
            number: fmtNum(1000000, 'en'), list: fmtList(['a', 'b', 'c']) }
          setup({ fr, 'zh-Hant': zh }, 'fr', [])
          const french = [fmtAgo(now - 60000, now), fmtSize(1200000), fmtList(['a', 'b'])]
          setup({ fr, 'zh-Hant': zh }, 'zh-Hant', [])
          const chinese = [fmtAgo(now - 60000, now), fmtSize(1200000), fmtList(['甲', '乙', '丙'])]
          console.log(JSON.stringify({ en, french, chinese }))
        """))
        self.assertEqual(result['en']['sizes'], ['1 KB', '1 KB', '1000 KB', '1.0 MB', '10.0 MB', '10 MB', '1.0 GB', 'NaN KB'])
        self.assertEqual(result['en']['ago'], ['never', 'just now', '1 min ago', '1 h ago', '1 d ago'])
        self.assertEqual(result['en']['date'], '01 Jan')
        self.assertEqual(result['en']['time'], '00:00')
        self.assertEqual(result['en']['number'], '1,000,000')
        self.assertEqual(result['en']['list'], 'a, b, and c')
        self.assertEqual(result['french'], ['il y a 1 min', '1,2 Mo', 'a et b'])
        self.assertEqual(result['chinese'], ['1 分鐘前', '1.2 MB', '甲、乙和丙'])

    def test_state_formatters_and_item_megabytes_equal_the_original_english(self):
        # state.svelte.ts fmtAgo / fmtMB and Item.svelte's MB text before the 2026-11-08 sweep, verbatim, against the helpers
        # they now delegate to (plan 02 task 7: the English formats are pinned over thresholds and rounding edges)
        result = json.loads(node("""
          import { fmtAgo, fmtMegabytes, fmtSize } from './web/src/lib/i18n/format.ts'
          const oldAgo = (ms, now) => { if (!ms) return 'never'; const m = Math.round((now - ms) / 60000)
            return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago` }
          const oldMB = b => (b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : b >= 1e6 ? (b / 1e6).toFixed(b < 1e7 ? 1 : 0) + ' MB' : Math.max(1, Math.round(b / 1e3)) + ' KB')
          const oldMega = b => (b / 1e6).toFixed(1) + ' MB'
          const now = 1_800_000_000_000, problems = []
          for (const offset of [-5e6, 0, 1, 29999, 30000, 30001, 59999, 60000, 89999, 90000, 3599999, 3600000, 5400000, 86399999, 86400000, 129600000, 1e10])
            if (fmtAgo(now - offset, now) !== oldAgo(now - offset, now)) problems.push(['ago', offset])
          if (fmtAgo(0, now) !== oldAgo(0, now) || fmtAgo(undefined, now) !== 'never') problems.push(['ago', 'falsy'])
          for (const bytes of [0, 1, 499, 500, 999, 1000, 1499, 1500, 999999, 1e6, 1234567, 9999999, 1e7, 123456789, 999999999, 1e9, 2.5e9, NaN]) {
            if (fmtSize(bytes) !== oldMB(bytes)) problems.push(['size', bytes])
            if (fmtMegabytes(bytes) !== oldMega(bytes)) problems.push(['megabytes', bytes])
          }
          console.log(JSON.stringify(problems))
        """))
        self.assertEqual(result, [])

    def test_empty_library_catalog_words_equal_the_shared_helper(self):
        # the phone reads catalog words for the empty library; lib/onboarding.ts phoneEmpty (desktop-shared) stays the English source
        node(r"""
          import assert from 'node:assert/strict'
          import { phoneEmpty } from './web/src/lib/onboarding.ts'
          import { messages as en } from './web/src/lib/i18n/en/index.ts'
          const pc = phoneEmpty('pc', false), phone = phoneEmpty('phone', false)
          assert.deepEqual([en['library.empty.connectLine'], en['library.empty.connectKey']], [pc.line, pc.key])
          assert.deepEqual([en['library.empty.shareLine'], en['library.empty.addKey']], [phone.line, phone.key])
        """)

    def test_shell_library_plurals_and_rich_lines_in_every_language(self):
        node(r"""
          import assert from 'node:assert/strict'
          import { setup, template, t } from './web/src/lib/i18n/index.ts'
          import { parseRich } from './web/src/lib/i18n/rich.ts'
          import { messages as fr } from './web/src/lib/i18n/fr/index.ts'
          import { messages as zh } from './web/src/lib/i18n/zh-Hant/index.ts'
          const use = language => setup({ fr, 'zh-Hant': zh }, language, [])
          // English keeps its wording for one item too, as the screens always did
          use('en')
          assert.equal(t('shell.sync.keepsCopy', { n: 1, items: '1', ago: '2 min ago' }), 'The phone keeps its copy: 1 items, read 2 min ago')
          assert.equal(t('shell.sync.labelItems', { n: 1, label: 'Drive', items: '1' }), 'Drive · 1 items')
          assert.equal(t('item.info.frames', { n: 1 }), '1 frames')
          assert.deepEqual([1, 2].map(n => t('library.summary', { n, count: String(n), order: 'newest first' })), ['1 item · newest first', '2 items · newest first'])
          // French: one covers 0 and 1; 繁中 has one form
          use('fr')
          assert.deepEqual([0, 1, 2, 3000].map(n => t('library.summary', { n, count: String(n), order: 'x' }).replace(/ · x$/, '')), ['0 élément', '1 élément', '2 éléments', '3000 éléments'])
          assert.deepEqual([1, 5].map(n => t('item.info.frames', { n })), ['1 image', '5 images'])
          use('zh-Hant')
          assert.deepEqual([1, 5].map(n => t('library.summary', { n, count: String(n), order: 'x' })), ['1 個項目・x', '5 個項目・x'])
          // the two rich lines: the label is bold, the rest is text, and a parameter that looks like markup stays text
          for (const language of ['en', 'fr', 'zh-Hant']) {
            use(language)
            const owner = parseRich(template('shell.ownerLine'), { text: '<i>{x}</i>' })
            assert.equal(owner[0].type, 'b', language)
            assert.equal(owner[1].type, 'text', language)
            assert.ok(owner[1].value.endsWith('<i>{x}</i>'), language)
            const ask = parseRich(template('shell.askWiskit'))
            assert.deepEqual(ask.map(node => node.type), ['text', 'b'], language)
            assert.equal(ask[1].children[0].value, 'Wiskit', language)
          }
        """)

    def test_card_words_replace_only_the_known_engine_nodes(self):
        node(r"""
          import assert from 'node:assert/strict'
          import fs from 'node:fs'
          import vm from 'node:vm'
          import { setup } from './web/src/lib/i18n/index.ts'
          import { messages as en } from './web/src/lib/i18n/en/index.ts'
          import { messages as fr } from './web/src/lib/i18n/fr/index.ts'
          import { messages as zh } from './web/src/lib/i18n/zh-Hant/index.ts'
          import { cardWords, sourceName, themeWords, typeName } from './web/src/mobile/card-words.ts'
          // the locked engine files, run as the page runs them (classic scripts), with the few browser globals they touch stubbed
          const context = vm.createContext({ window: {}, matchMedia: () => ({ matches: false }), localStorage: { getItem: () => null, setItem() {} },
            document: { documentElement: { classList: { toggle() {} } }, createElement: () => ({ getContext: () => null }), head: { appendChild() {} } },
            THUMBS: new Proxy({}, { get: (_, key) => '/thumb/' + String(key) }), requestAnimationFrame() {}, performance: { now: () => 0 } })
          vm.runInContext(fs.readFileSync('design/card-designs/engine.js', 'utf8'), context)
          vm.runInContext(fs.readFileSync('design/card-designs/full-art-v2/fa2.js', 'utf8'), context)
          const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
          const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c])
          // user text equal to every engine word, plus markup, braces and quotes: it must come through untouched
          const hostile = 'NEW Common unknown Flag Interesting rarity size added Illus. Saved from <img src=x onerror=alert(1)> {name} "q" \'s'
          const model = rar => ({ key: '7', id: 7, hex: '0x7', title: esc(hostile), creator: esc(hostile), src: 'Web', rar, rank: 3, isNew: true,
            size: 'Reel', date: '06 Nov 2026', cat: esc(hostile), focus: 42, desc: esc(hostile) })
          // srcMark (lib/cards/card.ts) turns the stub's first stat into "added" before cardWords runs
          const stat = html => html.replace(/<div><small>source<\/small><b><span class="(?:fa-)?ico">f<\/span>[^<]*<\/b><\/div>/, '<div><small>added</small><b>06 Nov 2026</b></div>')
          const pages = { cover: rar => stat(context.cardHTML(model(rar), 'full')), holo: rar => stat(context.cardFA2(model(rar))) }
          const tags = html => (html.match(/<\/?[a-z][^>]*>/gi) || []).length
          const parts = { source: 'Web', date: '06 Nov 2026', creator: hostile }

          // English never runs the pass, and its catalog words are the engine's own
          setup({ fr, 'zh-Hant': zh }, 'en', [])
          for (const [name, build] of Object.entries(pages)) {
            const fa = name === 'holo' ? 'fa-' : ''
            const html = build('holo')
            assert.equal(cardWords(html, esc, parts), html)
            for (const needle of [`<span class="${fa}new">${en['item.card.new']}</span>`, `<span class="${fa}stage">${en['item.card.stage']}</span>`,
              `<div class="${fa}evo">Saved from Web · 06 Nov 2026</div>`, `<span class="${fa}pill">${en['item.card.flag']}</span><b>${en['item.card.interesting']}</b>`,
              `<small>${en['item.card.rarity']} <span class="${fa}pips">`, `<b class="${fa}rv">★ ${en['item.card.holo']}</b>`,
              `<small>${en['item.card.size']}</small>`, `<small>${en['item.card.added']}</small>`, `<span class="${fa}il">Illus. ${esc(hostile)}</span>`])
              assert.ok(html.includes(needle), name + ': ' + needle)
            assert.ok(build('common').includes(`<b class="${fa}rv">● ${en['item.card.common']}</b>`), name + ' common')
          }
          assert.equal(en['item.card.savedFrom'], 'Saved from {source} · {date}')
          assert.equal(en['item.card.illus'], 'Illus. {creator}')

          const expected = {
            fr: { source: 'Web', words: ['NOUVEAU', 'Reel', 'Enregistré depuis Web · 06 Nov 2026', 'Repère', 'Intéressant', 'rareté', 'Rare holo', 'Commune', 'taille', 'ajouté', 'Illus. '] },
            'zh-Hant': { source: '網頁', words: ['新增', 'Reels', '儲存自 網頁・06 Nov 2026', '標記', '有趣', '稀有度', 'Holo 稀有', '普通', '大小', '加入於', '插畫家 '] },
          }
          for (const [language, { source, words }] of Object.entries(expected)) {
            setup({ fr, 'zh-Hant': zh }, language, [])
            const [news, stage, saved, flag, interesting, rarity, holo, common, size, added, illus] = words
            for (const [name, build] of Object.entries(pages)) {
              const fa = name === 'holo' ? 'fa-' : ''
              for (const [rar, rarityWord, symbol] of [['holo', holo, '★'], ['common', common, '●']]) {
                const original = build(rar)
                const html = cardWords(original, esc, { ...parts, source: sourceName('Web') })
                const label = `${language} ${name} ${rar}`
                assert.equal(sourceName('Web'), source, label)
                for (const needle of [`<span class="${fa}new">${news}</span>`, `<span class="${fa}stage">${stage}</span>`,
                  `<div class="${fa}evo">${saved}</div>`, `<span class="${fa}pill">${flag}</span><b>${interesting}</b>`,
                  `<small>${rarity} <span class="${fa}pips">`, `<b class="${fa}rv">${symbol} ${rarityWord}</b>`,
                  `<small>${size}</small>`, `<small>${added}</small>`, `<span class="${fa}il">${illus}${esc(hostile)}</span>`])
                  assert.ok(html.includes(needle), label + ': ' + needle)
                // the engine's English label nodes are gone; the user's text, markup structure and classes are not touched
                for (const gone of [`>NEW</span>`, `>Saved from `, `>Flag</span>`, `<b>Interesting</b>`, `<small>rarity `, `<small>size</small>`, `<small>added</small>`, `>Illus. `])
                  assert.ok(!html.includes(gone) || language === 'fr' && gone === `>Illus. ` , label + ' still has ' + gone)
                assert.equal(tags(html), tags(original), label + ' markup structure')
                for (const kept of [`<h3 class="${fa}nm">${esc(hostile)}</h3>`, `<p class="${fa}ds">${esc(hostile)}</p>`, `<em>${esc(hostile)}</em>`, `title="Web"`])
                  assert.ok(html.includes(kept), label + ' lost ' + kept)
                assert.ok(!html.includes('<img src=x'), label + ' unescaped markup')
              }
            }
          }
          // display words for stored types and sources: known ones only, anything else as stored
          setup({ fr, 'zh-Hant': zh }, 'fr', [])
          assert.deepEqual(['Reel', 'Post', 'Video', 'Short', 'reel', ''].map(typeName), ['Reel', 'Publication', 'Vidéo', 'Short', 'reel', ''])
          assert.deepEqual(['Web', 'Facebook', 'YouTube'].map(sourceName), ['Web', 'Facebook', 'YouTube'])
          setup({ fr, 'zh-Hant': zh }, 'zh-Hant', [])
          assert.deepEqual(['Reel', 'Post', 'Video', 'Short'].map(typeName), ['Reels', '貼文', '影片', 'Short'])
          assert.deepEqual(['Web', 'Instagram'].map(sourceName), ['網頁', 'Instagram'])
          // the stub's middle stat after themeSlot: label swapped, empty creator falls back, a stored creator stays as stored
          const slot = creator => { const small = { textContent: 'creator' }, b = { textContent: creator || 'unknown' }
            const st = { querySelector: s => (s === 'small' ? small : b) }
            return { small, b, node: { querySelector: () => st } } }
          for (const [creator, shown] of [['', '不詳'], ['unknown', 'unknown'], ['Common', 'Common']]) {
            const s = slot(creator); themeWords(s.node, creator)
            assert.deepEqual([s.small.textContent, s.b.textContent], ['作者', shown])
          }
          setup({ fr, 'zh-Hant': zh }, 'en', [])
          const untouched = slot(''); themeWords(untouched.node, '')
          assert.deepEqual([untouched.small.textContent, untouched.b.textContent], ['creator', 'unknown'])
        """)

    def test_switch_blocks_failures_races_and_duplicate_requests(self):
        result = json.loads(node("""
          import { languageSecretsSaved, languageSwitching, registerLanguageCheck, switchLanguage } from './web/src/mobile/language-switch.ts'
          const writes = [], storage = { setItem: (key, value) => writes.push([key, value]) }
          let reloads = 0, saves = 0
          const reload = () => reloads++
          const save = async () => { saves++ }
          const same = await switchLanguage('en', 'en', save, storage, reload)
          let release = registerLanguageCheck(() => 'unsaved')
          const blocked = await switchLanguage('fr', 'en', save, storage, reload)
          release()
          const denied = await switchLanguage('fr', 'en', save, { setItem() { throw Error('denied') } }, reload)
          let resume, first = true
          const wait = new Promise(resolve => { resume = resolve })
          release = registerLanguageCheck(async () => { if (first) { first = false; await wait } return null })
          const pending = switchLanguage('fr', 'en', save, storage, reload)
          const duplicate = await switchLanguage('zh-Hant', 'en', save, storage, reload)
          const during = languageSwitching()
          const releaseNew = registerLanguageCheck(() => 'new work')
          resume()
          const raced = await pending
          release(); releaseNew()
          const secretError = await switchLanguage('fr', 'en', async () => { throw Error('failed') }, storage, reload)
          const latched = await switchLanguage('fr', 'en', save, storage, reload)
          languageSecretsSaved()
          const success = await switchLanguage('fr', 'en', save, storage, reload)
          console.log(JSON.stringify({ same, blocked, denied, duplicate, during, raced, secretError, latched, success, writes, reloads, saves }))
        """))
        self.assertEqual(result['same']['status'], 'same')
        self.assertEqual(result['blocked'], {'status': 'blocked', 'reason': 'unsaved'})
        self.assertEqual(result['denied']['status'], 'storage-error')
        self.assertEqual(result['duplicate']['status'], 'busy')
        self.assertTrue(result['during'])
        self.assertEqual(result['raced'], {'status': 'blocked', 'reason': 'new work'})
        self.assertEqual(result['secretError']['reason'], 'settings.language.unsavedSecrets')
        self.assertEqual(result['latched']['reason'], 'settings.language.unsavedSecrets')
        self.assertEqual(result['success']['status'], 'reloaded')
        self.assertEqual(result['writes'], [['bp-lang', 'fr']])
        self.assertEqual(result['reloads'], 1)
        self.assertEqual(result['saves'], 2)

    def test_capture_drafts_block_reload_until_persisted_or_discarded(self):
        node(r"""
          import assert from 'node:assert/strict'
          import { register } from 'node:module'
          register('data:text/javascript,'+encodeURIComponent(`export async function resolve(s,c,n){
            if(s==='./store' && c.parentURL.endsWith('/mobile/capture.svelte.ts'))
              return {url:'data:text/javascript,export const drafts=globalThis.__drafts',shortCircuit:true};
            try{return await n(s,c)}catch(e){if(s.startsWith('.')&&!/\\.\\w+$/.test(s))return n(s+'.ts',c);throw e}}`),import.meta.url)
          globalThis.$state = value => value
          globalThis.$state.snapshot = value => structuredClone(value)
          let stored = [], mode = 'fail', resume
          globalThis.__drafts = { all: async () => stored, edit: async change => {
            if (mode === 'fail') return null
            if (mode === 'wait-fail') return await new Promise(resolve => { resume = () => resolve(null) })
            if (mode === 'wait') return await new Promise(resolve => { resume = () => { stored = change(stored); resolve(stored) } })
            stored = change(stored); return stored
          } }
          const { cap, captureRevision, draftEdited, shareIn, keepDraft, dropDraft, dropDraftIfUnchanged, loadDrafts } = await import('./web/src/mobile/capture.svelte.ts')
          const { switchLanguage, languageWorkChanged } = await import('./web/src/mobile/language-switch.ts')
          let writes = 0, reloads = 0
          const attempt = () => switchLanguage('fr', 'en', async () => {}, {setItem(){writes++}}, () => reloads++)
          const first = await shareIn('first synthetic draft')
          assert.equal((await attempt()).reason, 'settings.language.unsavedDraft')
          mode = 'ok'; const second = await shareIn('second synthetic draft')
          assert.deepEqual(new Set(cap.list.map(d => d.id)), new Set([first.id, second.id]))
          assert.equal((await attempt()).status, 'blocked')
          await keepDraft(first)
          cap.ask = {label:'synthetic', text:'unsent'}; languageWorkChanged()
          assert.equal((await attempt()).status, 'blocked')
          cap.ask = null; languageWorkChanged()
          assert.equal((await attempt()).status, 'reloaded')
          mode = 'fail'; const edited = {...first, text:'changed synthetic draft'}; await keepDraft(edited)
          await loadDrafts()
          assert.equal(cap.list.find(d => d.id === first.id).text, 'changed synthetic draft')
          assert.equal((await attempt()).status, 'blocked')
          mode = 'ok'; await keepDraft(edited)
          mode = 'fail'; await dropDraft(first.id)
          assert.equal((await attempt()).status, 'blocked')
          mode = 'ok'; await shareIn('third synthetic draft')
          assert.equal(cap.list.some(d => d.id === first.id), false)
          assert.equal((await attempt()).status, 'reloaded')
          assert.equal(stored.some(d => d.id === first.id), false)
          mode = 'wait'; const saving = shareIn('pending synthetic draft')
          await Promise.resolve()
          const before = writes, switching = attempt()
          await Promise.resolve(); assert.equal(writes, before)
          resume(); await saving
          assert.equal((await switching).status, 'reloaded')
          mode = 'fail'; const discarded = await shareIn('discarded memory-only draft')
          assert.equal((await attempt()).status, 'blocked')
          await dropDraft(discarded.id)
          assert.equal((await attempt()).status, 'reloaded')
          const third = cap.list.find(d => d.text === 'third synthetic draft')
          await dropDraft(third.id)
          const restored = {...third, text:'changed after failed delete'}
          await keepDraft(restored)
          mode = 'ok'
          assert.equal((await attempt()).status, 'blocked')
          await keepDraft(restored)
          assert.equal((await attempt()).status, 'reloaded')
          assert.equal(stored.find(d => d.id === third.id).text, 'changed after failed delete')
          mode = 'wait'
          const oldRevision = captureRevision(third.id)
          const deleting = dropDraftIfUnchanged(third.id, oldRevision)
          await Promise.resolve()
          draftEdited(third.id)
          resume(); await deleting
          assert.equal(stored.some(d => d.id === third.id), true)
          mode = 'ok'
          await dropDraftIfUnchanged(third.id, captureRevision(third.id))
          assert.equal(stored.some(d => d.id === third.id), false)
          assert.equal(writes, 5); assert.equal(reloads, 5)
          const blank = (await import('./web/src/lib/capture.ts')).newDraft()
          cap.ready = true; draftEdited(blank.id)
          mode = 'wait-fail'; const oldEmptyDrop = keepDraft(blank)
          await Promise.resolve()
          draftEdited(blank.id)
          const retained = {...blank,text:'newer memory-only draft français 中文'}
          mode = 'fail'; await keepDraft(retained)
          assert.equal(cap.list.find(d=>d.id===blank.id).text,retained.text)
          resume(); await oldEmptyDrop
          assert.equal(cap.list.find(d=>d.id===blank.id)?.text,retained.text)
          assert.equal((await attempt()).reason,'settings.language.unsavedDraft')
          assert.equal(cap.list.find(d=>d.id===blank.id)?.text,retained.text)
          assert.equal(writes,5);assert.equal(reloads,5)
        """)

    def test_unsaved_recordings_survive_failed_retry_until_saved_or_discarded(self):
        node(r"""
          import assert from 'node:assert/strict'
          import { register } from 'node:module'
          register('data:text/javascript,'+encodeURIComponent(`export async function resolve(s,c,n){
            if(s==='./voice' && c.parentURL.endsWith('/mobile/voice-pending.svelte.ts'))
              return {url:'data:text/javascript,export const enqueue=(...args)=>globalThis.__enqueue(...args)',shortCircuit:true};
            try{return await n(s,c)}catch(e){if(s.startsWith('.')&&!/\\.\\w+$/.test(s))return n(s+'.ts',c);throw e}}`),import.meta.url)
          globalThis.$state = value => value
          let mode = 'fail', complete, calls = 0
          globalThis.__enqueue = async () => { calls++; if (mode === 'fail') throw Error('synthetic'); await new Promise(resolve => {complete = resolve}) }
          const { unsavedVoice, retainVoice, discardVoice, retryVoice } = await import('./web/src/mobile/voice-pending.svelte.ts')
          const { switchLanguage } = await import('./web/src/mobile/language-switch.ts')
          let reloads = 0
          const attempt = () => switchLanguage('fr', 'en', async () => {}, {setItem(){}}, () => reloads++)
          retainVoice('one.md', new Blob(['one'])); retainVoice('two.md', new Blob(['two']))
          const [first, second] = unsavedVoice.items
          assert.equal((await attempt()).reason, 'settings.language.unsavedRecording')
          discardVoice(first.id)
          assert.equal(await retryVoice(second.id), false)
          assert.equal(unsavedVoice.items.length, 1)
          mode = 'wait'; const retry = retryVoice(second.id)
          assert.equal(await retryVoice(second.id), false)
          discardVoice(second.id); assert.equal(unsavedVoice.items.length, 1)
          assert.equal((await attempt()).status, 'blocked')
          complete(); assert.equal(await retry, true)
          assert.equal(unsavedVoice.items.length, 0)
          assert.equal((await attempt()).status, 'reloaded')
          assert.equal(calls, 2); assert.equal(reloads, 1)
        """)


@unittest.skipUnless(_node_ok(), 'needs Node with type stripping')
class PhonePlan03Presentation(unittest.TestCase):
    def test_tools_catalog_formatting_keeps_every_english_branch(self):
        node(TS_RESOLVE + r"""
          import assert from 'node:assert/strict'
          import * as tools from './web/src/mobile/tools.ts'
          import { toolText } from './web/src/mobile/tools-words.ts'
          for (const kind of Object.keys(tools.STEPS)) {
            const plain = tools.STEPS[kind], localized = tools.stepWords(kind, toolText)
            for (const key of ['label','verb','ing','glyph','charge','one']) assert.equal(localized[key], plain[key])
            for (const n of [0,1,2,20,21,25,26,64,65,1280,1281]) {
              assert.equal(localized.line(n), plain.line(n))
              assert.equal(tools.chargeLine(kind,n,toolText), tools.chargeLine(kind,n))
              for (const src of ['pc','solo','phone']) for (const provider of ['','OpenAI']) for (const rerun of [false,true]) {
                for (const act of [null,'retry','continue','next']) for (const join of [false,true]) for (const retained of [false,true]) {
                  const o = {kind,n,all:n+1,src,provider,rerun,act,join,retained,replace:'Original replacement detail.'}
                  assert.deepEqual(tools.confirmText(o,toolText),tools.confirmText(o))
                  assert.equal(tools.confirmGo(o,toolText),tools.confirmGo(o))
                }
                assert.equal(tools.whereLine(src,provider,'model',toolText),tools.whereLine(src,provider,'model'))
                assert.equal(tools.savedLine(src,toolText),tools.savedLine(src))
                for (const stopping of [false,true]) for (const joined of [false,true])
                  assert.equal(tools.runNote(src,stopping,joined,toolText),tools.runNote(src,stopping,joined))
              }
            }
            for (const tally of [{done:1,skip:0,err:0,left:0},{done:2,skip:3,err:4,left:5}]) {
              assert.equal(tools.summary(tally,kind,toolText),tools.summary(tally,kind))
              for (const stopped of [false,true]) for (const rest of [0,1,26])
                assert.deepEqual(tools.nextKey(tally,stopped,rest,toolText),tools.nextKey(tally,stopped,rest))
              for (const ended of [false,true]) assert.equal(tools.ringText({...tally,n:14},ended,toolText),tools.ringText({...tally,n:14},ended))
            }
          }
          assert.equal(tools.callsLine(1,toolText),'1 AI call')
          assert.equal(tools.callsLine(0,toolText),'')
          for (const joined of [false,true]) assert.equal(tools.stopLabel(joined,toolText),tools.stopLabel(joined))
          assert.deepEqual(tools.pcBusy('Describe',2,3,'Index',toolText),tools.pcBusy('Describe',2,3,'Index'))
          for (const item of [false,true]) assert.equal(tools.scopeText(item,'User category',3,toolText),tools.scopeText(item,'User category',3))
        """)

    def test_new_dated_heading_retains_existing_note_bytes_and_ids(self):
        node(TS_RESOLVE + r"""
          import assert from 'node:assert/strict'
          import { setup } from './web/src/lib/i18n/index.ts'
          import { messages as fr } from './web/src/lib/i18n/fr/index.ts'
          import { messages as zh } from './web/src/lib/i18n/zh-Hant/index.ts'
          import { datedSection,noteKind,stampName,inkName } from './web/src/mobile/notes-words.ts'
          import { askExamples } from './web/src/mobile/wiskit-words.ts'
          import { ASK_EXAMPLES } from './web/src/lib/ask-examples.ts'
          import { findMine,findKnow,words } from './web/src/mobile/notes-find.ts'
          import { noteText } from './web/src/mobile/obsidian.ts'
          const body='---\nstamps: [{"k":"flower","at":"Original section","c":"indigo"}]\ncategory: General\n---\n\n## 02 Nov, 12:30\n\n## From recording\nExact user text.'
          const now=new Date('2026-11-08T12:34:00Z')
          assert.equal(datedSection(body,now),body+'\n\n## '+now.toLocaleString('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})+'\n\n')
          assert.equal(datedSection('',now),'## '+now.toLocaleString('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})+'\n\n')
          assert.deepEqual(askExamples(),ASK_EXAMPLES)
          for(const [language,locale] of [['fr','fr'],['zh-Hant','zh-Hant-TW']]){
            setup({fr,'zh-Hant':zh},language,[])
            assert.equal(datedSection(body,now),body+'\n\n## '+now.toLocaleString(locale,{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})+'\n\n')
            assert.notEqual(stampName('flower'),'flower'); assert.notEqual(inkName('indigo'),'indigo ink')
            assert.equal(stampName('unknown-user-value'),'unknown-user-value')
            assert.equal(noteKind('My original kind'),'My original kind')
            assert.deepEqual(findMine([{file:'a',title:'',category:'General'}],words(language==='fr'?'Sans titre':'未命名')),[])
            assert.deepEqual(findKnow([{file:'a',title:'',kind:'Personal'}],words(noteKind('Personal'))),[])
            assert.equal(noteText({topic:'Original',kind:'personal',category:'General'},body),'---\ntopic: Original\nkind: personal\ncategory: General\n---\n\n'+body)
            assert.notDeepEqual(askExamples(),ASK_EXAMPLES)
          }
          assert.deepEqual(ASK_EXAMPLES,['What recipes have I saved?','List all my workout videos','What tips do I have on productivity?','Plan a weekend trip from my travel saves','Build me a 10-minute morning routine','Anything on design or drawing?'])
        """)

    def test_quick_info_and_deep_progress_keep_english_and_request_bytes(self):
        node(TS_RESOLVE + r"""
          import assert from 'node:assert/strict'
          import fs from 'node:fs'
          import {Quick} from './web/src/mobile/ai/quick.ts'
          import {describeCall,auxRows} from './web/src/mobile/ai/deep.ts'
          import {toolText} from './web/src/mobile/tools-words.ts'
          import {setup,t} from './web/src/lib/i18n/index.ts'
          import {messages as fr} from './web/src/lib/i18n/fr/index.ts'
          const P=JSON.parse(fs.readFileSync('knowledge/prompts/ask_quick.json','utf8')), Q=new Quick(P)
          for (const [key,field] of [['wiskit.info.sent','info_sent'],['wiskit.info.carried','info_carried'],['wiskit.info.notes','info_notes'],['wiskit.info.list','info_list'],['wiskit.info.retrieval','info_retrieval']]) {
            const {messages}=await import('./web/src/lib/i18n/en/wiskit.ts'); assert.equal(typeof messages[key] === 'string' ? messages[key] : messages[key].other,P[field]); if(typeof messages[key] !== 'string') assert.equal(messages[key].one,P[field])
          }
          const lib={ftsIds:()=>[],searchNotes:()=>[],getItemsByIds:()=>[],itemIdsByCategory:()=>[],countItems:()=>1}
          const rows=[{id:1,title:'Original title',description:'Original caption',category:'Original category'}]
          const plain=Q.buildTurn(lib,'all design',rows,[], 'keyword search only')
          let shown
          assert.deepEqual(Q.buildTurn(lib,'all design',rows,[], 'keyword search only',undefined,toolText,text=>shown=text),plain)
          assert.equal(shown,plain.info)
          for(const name of ['find_topics','topic_items','search_library','read_items','search_notes','find_resources','related_items','custom_tool'])
            for(const args of [{},{query:'User text',category:'Original category',offset:1,ids:[1,2],id:9}])
              assert.equal(describeCall(name,args,toolText),describeCall(name,args))
          const lines=[]
          await auxRows([{key:'a',kind:'note',text:'Original',payload:{}}],'model',null,new Map(),async()=>[[1]],64,(raw,display)=>lines.push([raw,display]),undefined,toolText)
          assert.deepEqual(lines,[['Indexing 1 topic and note sections (one-time)','Indexing 1 topic and note sections (one-time)']])
          setup({fr},'fr',[])
          assert.deepEqual(Q.buildTurn(lib,'all design',rows,[], 'keyword search only',undefined,toolText,text=>shown=text),plain)
          assert.notEqual(shown,plain.info)
          assert.ok(shown.includes('1')); assert.equal(rows[0].category,'Original category')
          assert.ok(describeCall('search_library',{query:'User text',category:'Original category'},toolText).includes('Original category'))
        """)


    def test_capture_optional_presentation_equals_all_original_english_branches(self):
        node(TS_RESOLVE + r"""
          import assert from 'node:assert/strict'
          const c = await import('./web/src/lib/capture.ts'), r = await import('./web/src/mobile/recap.ts')
          const {captureText:w, captureType, draftAgo, saveStateLabel} = await import('./web/src/mobile/capture-words.ts')
          const {setup,t} = await import('./web/src/lib/i18n/index.ts')
          const {messages:fr} = await import('./web/src/lib/i18n/fr/index.ts')
          const {messages:zh} = await import('./web/src/lib/i18n/zh-Hant/index.ts')
          const url='https://example.test/a', image={name:'<img>.png',type:'image/png',blob:null}
          const page={asked:url,url,found:true,title:'Original <b>title</b>',desc:'Original caption',creator:'User',image:''}
          const drafts=[]
          for (const text of ['', 'User content', url, 'Look '+url]) for (const pic of [null,image,{...image,name:'doc.pdf',type:'application/pdf'}])
            for (const dest of ['', 'library','note']) for (const target of ['','original.md']) for (const read of ['','digest','describe'])
              drafts.push({...c.newDraft('typed',text,pic),dest,target,read,category:'General'})
          for (const d of drafts) {
            for (const caps of [{thumb:false},{thumb:true},{thumb:false,known:7}]) assert.deepEqual(c.verdict(d,caps,w),c.verdict(d,caps))
            for (const p of [undefined,page,{...page,asked:'other'}]) {
              assert.equal(c.sourceHelp(d,p,w),c.sourceHelp(d,p))
              assert.equal(r.noteHint(d,p,w),r.noteHint(d,p))
            }
            for (const known of [undefined,7]) assert.equal(r.libraryBlock(d,known,w),r.libraryBlock(d,known))
            for (const name of ['libraryHint','draftHelp','attLine']) assert.equal(r[name](d,w),r[name](d))
          }
          for (const tags of ['', 'knives, technique', '<img>{name}']) assert.equal(r.pickedLine('User category',tags,w),r.pickedLine('User category',tags))
          for (const message of [' Failed. ', 'Failed to fetch', '<img>{name}...']) assert.equal(r.suggestFailed(message,w),r.suggestFailed(message))
          assert.equal(t('capture.suggest.name'),r.SUGGEST.name);assert.equal(t('capture.suggest.says'),r.SUGGEST.says)
          assert.equal(t('capture.destination.nameIt'),r.NAME_IT)
          assert.equal(t('capture.destination.suggested'),' · suggested: shares the most words')
          for(const n of [1,2]) assert.equal(t('capture.draft.others',{n}),`Other drafts (${n})`)
          for(const state of Object.keys(c.STATE_LABEL)) assert.equal(saveStateLabel(state),c.STATE_LABEL[state])
          for(const files of [[],[{name:'x.exe',type:'',size:1}], [{name:'x.png',type:'image/png',size:11*1024**2}], [{name:'x.pdf',type:'',size:31*1024**2}], [{name:'x.txt',type:'',size:3*1024**2}], [{name:'x.md',type:'',size:1}]])
            assert.deepEqual(c.checkFiles(files,w),c.checkFiles(files))
          for(const type of [...c.LIBRARY_TYPES,'Custom user type','__proto__','constructor']) assert.equal(captureType(type),type)
          const oldAgo=(ms,now)=>{const m=Math.round((now-ms)/60000);return m<1?'just now':m<60?`${m} min ago`:m<1440?`${Math.round(m/60)} h ago`:`${Math.round(m/1440)} d ago`}
          for(const now of [0,29999,30000,3599999,3600000,86399999,86400000,1.8e12]) for(const ms of [0,1,now,now-30000,now-90000]) assert.equal(draftAgo(ms,now),oldAgo(ms,now))
          // Changing presentation never changes stored titles, sections, tags, categories or draft IDs.
          const d={...c.newDraft('typed',url,image),read:'digest',comment:'User comment',category:'General',tags:'English tags'}
          const stored=()=>[d,c.titleFor(d,page),c.label(d),c.newBody(d,page),c.section(d,'2026-11-08 09:05',page),c.appended('Existing',d,'2026-11-08 09:05',page)]
          const original=JSON.stringify(stored())
          for(const language of ['fr','zh-Hant']) {
            setup({fr,'zh-Hant':zh},language,[])
            assert.notEqual(r.draftHelp(d,w),r.draftHelp(d));assert.notEqual(c.sourceHelp(d,page,w),c.sourceHelp(d,page))
            assert.equal(JSON.stringify(stored()),original)
            assert.equal(captureType('__proto__'),'__proto__')
          }
        """)

    def test_import_outcomes_and_coded_errors_keep_default_english_and_limits(self):
        node(TS_RESOLVE + r"""
          import assert from 'node:assert/strict'
          const {importResult,importError}=await import('./web/src/mobile/import-words.ts')
          const I=await import('./web/src/mobile/imports.ts'), F=await import('./web/src/mobile/files.ts')
          const {captureError}=await import('./web/src/mobile/capture-words.ts')
          const {setup,t}=await import('./web/src/lib/i18n/index.ts')
          const {messages:fr}=await import('./web/src/lib/i18n/fr/index.ts'),{messages:zh}=await import('./web/src/lib/i18n/zh-Hant/index.ts')
          const old=(a,d,s)=>{const parts=[`Added ${a} link${a===1?'':'s'}`];if(d)parts.push(`${d} already in the library`);if(s)parts.push(`${s} without a link skipped`);return parts.join(' · ')+(a?'. Links are saved. Public previews may arrive later; some pictures may be unavailable.':'.')}
          for(const a of [0,1,2,3000]) for(const d of [0,1,2]) for(const s of [0,1,2]) assert.equal(importResult(a,d,s),old(a,d,s))
          assert.equal(I.MAX_IMPORT_BYTES,60*1024**2)
          const invalid=await I.readExport(new TextEncoder().encode('{broken')).catch(e=>e)
          const large=await I.readExport(new Uint8Array(I.MAX_IMPORT_BYTES+1)).catch(e=>e)
          assert.equal(invalid.message,I.NOT_SAVED);assert.equal(large.message,I.TOO_BIG)
          assert.equal(invalid.code,'importNotSaved');assert.equal(large.code,'importTooBig')
          assert.equal(importError(invalid),I.NOT_SAVED);assert.equal(importError(large),I.TOO_BIG)
          const unreadable=await F.toPicked(new Blob(['a']),'a.exe','').catch(e=>e)
          const tooBig=await F.toPicked(new Blob([new Uint8Array(F.MAX_BYTES.text+1)]),'a.txt','').catch(e=>e)
          assert.equal(captureError(unreadable),F.UNREADABLE);assert.equal(captureError(tooBig),'That file is over 2 MB.')
          const hostile='<img src=x onerror=alert(1)> {name}'
          assert.equal(importError(Error(hostile)),hostile)
          for(const language of ['fr','zh-Hant']) {
            setup({fr,'zh-Hant':zh},language,[])
            assert.equal(importError(invalid),t('imports.error.notSaved'));assert.equal(importError(large),t('imports.error.tooBig'))
            assert.ok(importError(Error(hostile)).includes(hostile));assert.notEqual(importError(Error(hostile)),hostile)
            assert.equal(captureError(unreadable),t('capture.attachment.unreadable'))
            for(const n of [0,1,2,3000]) assert.ok(importResult(n,n,n).includes(String(n)))
          }
        """)

    def test_lazy_guides_preserve_the_entire_original_english_object(self):
        original = [{"id":"instagram","name":"Instagram","what":"Saved posts and reels","file":True,"page":"https://accountscenter.instagram.com/info_and_permissions/dyi/","pageLabel":"Open Instagram's page","wait":"Check Instagram for export availability; timing and menu names can vary. Download it on this phone from the same page.","steps":["Open Instagram's \"Download your information\" page and sign in if it asks.","Choose \"Download or transfer information\", then your Instagram account.","Choose \"Some of your information\" and tick only \"Saved\".","Choose \"Download to device\", date range \"All time\", format \"JSON\", then \"Create files\".","When Instagram's email comes, download the zip on this phone.","Return here and tap Import file: the zip, or saved_posts.json from inside it."]},{"id":"facebook","name":"Facebook","file":False,"page":"https://accountscenter.facebook.com/info_and_permissions/dyi/","steps":["Sign in to Facebook in Accounts Center.","Open Your information and permissions, then the option to export or download your information.","Select your Facebook profile and follow Facebook’s instructions. This app cannot import Facebook export files yet."]},{"id":"threads","name":"Threads","file":False,"page":"https://www.threads.com/settings/privacy","steps":["Sign in to Threads and open its privacy settings.","Follow the link to download your information. If Accounts Center is offered, select your Threads profile there.","Menu names and availability vary by account. This app cannot import Threads export files yet."]},{"id":"tiktok","name":"TikTok","file":False,"page":"https://support.tiktok.com/en/account-and-privacy/personalized-ads-and-data/requesting-your-data","steps":["Open TikTok’s official Requesting your data guide.","In TikTok: Profile, menu, Settings and privacy, Account, Download your data.","Choose JSON and request your data in TikTok. This app cannot import TikTok export files yet."]}]
        node(TS_RESOLVE + """
          import assert from 'node:assert/strict'
          const {importGuides}=await import('./web/src/mobile/import-words.ts')
          const {captureText}=await import('./web/src/mobile/capture-words.ts')
          const {setup}=await import('./web/src/lib/i18n/index.ts')
          const {messages:fr}=await import('./web/src/lib/i18n/fr/index.ts'), {messages:zh}=await import('./web/src/lib/i18n/zh-Hant/index.ts')
          const original=""" + json.dumps(original) + """
          assert.deepEqual(importGuides(),original);assert.deepEqual(importGuides(captureText),original)
          for(const language of ['fr','zh-Hant']) {
            setup({fr,'zh-Hant':zh},language,[])
            assert.deepEqual(importGuides(),original)
            const shown=importGuides(captureText)
            for(let i=0;i<original.length;i++) {
              for(const key of ['id','name','file','page']) assert.equal(shown[i][key],original[i][key])
              assert.equal(shown[i].steps.length,original[i].steps.length)
              shown[i].steps.forEach((text,j)=>assert.notEqual(text,original[i].steps[j]))
            }
          }
        """)

    def test_capture_voice_provider_codes_preserve_english_errors_and_requests(self):
        node(TS_RESOLVE + r"""
          import assert from 'node:assert/strict'
          const {setFetch,transcribe,CLOUD,AiError}=await import('./web/src/mobile/ai/providers.ts')
          const {captureError}=await import('./web/src/mobile/capture-words.ts')
          const {setup,t}=await import('./web/src/lib/i18n/index.ts')
          const {messages:fr}=await import('./web/src/lib/i18n/fr/index.ts'),{messages:zh}=await import('./web/src/lib/i18n/zh-Hant/index.ts')
          const audio=new Blob(['Original audio'],{type:'audio/webm'}), errors=[]
          for(const status of [401,403,429,500]) for(const detail of ['', '<img src=x> provider {name}']) {
            setFetch(async(url,init)=>{
              assert.equal(url,CLOUD.openai+'/v1/audio/transcriptions');assert.equal(init.headers.authorization,'Bearer synthetic-key')
              assert.deepEqual([...init.body.keys()],['model','response_format','file'])
              assert.equal(init.body.get('model'),'fixture-model');assert.equal(await init.body.get('file').text(),'Original audio')
              return Response.json({error:{message:detail}},{status})
            })
            const e=await transcribe(CLOUD,'synthetic-key','fixture-model',audio).catch(e=>e)
            const base=status===401||status===403?`OpenAI refused the key (${status}). Pair the phone again with a working key.`:status===429?'OpenAI says too many requests or no credit left (429).':`OpenAI answered ${status}.`
            assert.ok(e instanceof AiError);assert.equal(e.message,base+(detail?' '+detail:''));assert.equal(captureError(e),e.message)
            errors.push(e)
          }
          setFetch(async()=>{throw Error('synthetic network')})
          const e=await transcribe(CLOUD,'synthetic-key','fixture-model',audio).catch(e=>e)
          assert.equal(e.message,'OpenAI could not be reached (synthetic network).');assert.equal(e.code,'network');assert.equal(captureError(e),e.message)
          for(const language of ['fr','zh-Hant']) {
            setup({fr,'zh-Hant':zh},language,[])
            for(const error of [...errors,e]) assert.equal(captureError(error),t(error.displayKey,error.displayParams))
          }
        """)

if __name__ == '__main__':
    unittest.main()
