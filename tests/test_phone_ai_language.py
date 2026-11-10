"""Plan 07: full final request receipts with local synthetic providers, never live AI."""
import importlib.util
import json
import re
import unittest

from tests.test_mobile_info_browser import ROOT, mobile_browser, synthetic_phone

HARNESS = (ROOT / 'tests/helpers/phone_ai_language.js').read_text(encoding='utf-8')
BASELINE = ROOT / 'tests/fixtures/phone_ai_language_en.json'
POLICIES = ROOT / 'knowledge/prompts/languages.json'


def operation(name, index, request=None):
    if request and request['url'].endswith('/embeddings'):
        return None
    suffix = name.split(':')[-1]
    if suffix in ('quick', 'deep', 'canvas'):
        return 'reply'
    if suffix.startswith('describe-') or suffix == 'image-describe':
        return 'describe'
    if suffix in ('categorize', 'suggest'):
        return 'tags'
    if suffix.startswith('synth-'):
        return ('write' if index < 2 else 'keep') if suffix == 'synth-empty-first' else 'write' if index == 0 or suffix == 'synth-all-empty' else 'keep'
    return None


def expected_request(request, policy, op):
    """Only the final prose prompt changes; serialized schemas/options/tools stay pinned."""
    if not op:
        return request
    expected = dict(request)
    body = json.loads(request['body'])
    if 'tools' in body:
        key = 'instructions' if 'instructions' in body else 'system'
        final = '\nFinal answer only: state limited coverage and use available evidence.'
        text = body[key]
        body[key] = text.removesuffix(final) + '\n\n' + policy[op] + (final if text.endswith(final) else '')
    elif isinstance(body.get('messages', [{}])[0].get('content'), str):
        body['messages'][0]['content'] += '\n\n' + policy[op]
    else:
        content = body['messages'][0]['content'] if 'messages' in body else body['input'][0]['content']
        text = next(c for c in content if c['type'] in ('text', 'input_text'))
        text['text'] += '\n\n' + policy[op]
    expected['body'] = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
    return expected


def capture(page, language='en', drift=False):
    return page.evaluate(HARNESS, dict(language=language, drift=drift))


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires installed Playwright/Edge and web dependencies')
class PhoneAiLanguageTest(unittest.TestCase):
    @unittest.skipUnless((ROOT / 'projects/phone-languages/plans/07-ai-language.md').is_file(),
                         'the project plan lives in the private project folder, which a public checkout does not have')
    def test_fixed_instruction_table_is_the_complete_plan_copy(self):
        plan = (ROOT / 'projects/phone-languages/plans/07-ai-language.md').read_text(encoding='utf-8')
        expected = {'fr': {}, 'zh-Hant': {}}
        for language, key, value in re.findall(r'\| `(fr|zh-Hant)\.(reply|describe|write|keep|tags)` \| (.*?) \|', plan):
            expected[language][key] = value
        self.assertEqual(json.loads(POLICIES.read_text(encoding='utf-8')), expected)
        self.assertEqual(set(expected['fr']), {'reply', 'describe', 'write', 'keep', 'tags'})
        helper = (ROOT / 'web/src/mobile/ai/language.ts').read_text(encoding='utf-8')
        self.assertNotRegex(helper, r'\b(?:setup|localStorage|sessionStorage|document|window|lang)\(')

    def test_english_requests_and_rendering_match_pre_edit_snapshot(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360, 740, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            got = capture(page)
            self.assertEqual(got, json.loads(BASELINE.read_text(encoding='utf-8')))
            self.assertEqual(errors, [])

    def test_preview_requests_and_held_runs_change_only_the_selected_final_line(self):
        baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
        policies = json.loads(POLICIES.read_text(encoding='utf-8'))
        with mobile_browser() as (browser, base):
            for language, drift in [('fr', False), ('zh-Hant', False), ('fr', True), ('zh-Hant', True), ('en', True)]:
                with self.subTest(language=language, drift=drift), synthetic_phone(browser, base, 360, 740, 'light', language=language) as (page, errors):
                    page.route('**/api/**', lambda route: route.abort())
                    page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
                    got = capture(page, language, drift)
                    self.assertEqual(got['effects'], baseline['effects'])
                    self.assertEqual(got['basePrompts'], baseline['basePrompts'])
                    self.assertEqual(got['raw'], baseline['raw'])
                    self.assertEqual(set(got['records']), set(baseline['records']))
                    self.assertGreater(got['driftCount'], 20) if drift else self.assertEqual(got['driftCount'], 0)
                    for name, requests in baseline['records'].items():
                        expected = [expected_request(r, policies[language], operation(name, i, r)) if language != 'en' else r for i, r in enumerate(requests)]
                        self.assertEqual(got['records'][name], expected, name)
                        for i, request in enumerate(got['records'][name]):
                            if language == 'en' or not operation(name, i, request):
                                self.assertNotIn('Language policy:', str(request))
                            else:
                                self.assertEqual(request['body'].count('Language policy:'), 1, name)
                                self.assertIn(policies[language][operation(name, i, request)], json.dumps(json.loads(request['body']), ensure_ascii=False))
                    self.assertEqual(errors, [])

    def test_existing_mixed_notes_parts_uids_and_synthesis_retention(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360, 740, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            got = page.evaluate(r"""async () => {
              const {MirrorSource}=await import('/src/mobile/source/mirror.ts')
              const {Synth}=await import('/src/mobile/ai/synth.ts')
              const {SYNTH,LANGUAGES}=await import('/src/mobile/ai/prompts.ts')
              const {appendLanguage}=await import('/src/mobile/ai/language.ts')
              const {setup}=await import('/src/lib/i18n/index.ts')
              const {setFetch}=await import('/src/mobile/ai/providers.ts')
              const S=new Synth(SYNTH), results=[], sent=[], journal=[]
              const item={id:-2,description:'Caption 原文',notes:'My note 简体',tags:' ancien ,保留 ',category:'SPORT',short_desc:'Original',url:'https://example.test/2'}
              for(const language of ['en','fr','zh-Hant'])for(const existing of ['', '  ', 'English note [id -2]', 'Texte français.\n中文原文 [id -2]'])for(const mode of ['append','reorganize']){
                const original=S.batchPrompt('Topic',existing,[item],mode)
                const op=existing.trim()?'keep':'write'
                const actual=appendLanguage(original,language,op)
                if(actual!==(language==='en'?original:original+'\n\n'+LANGUAGES[language][op]))throw Error('existing policy')
                if(existing.trim()&&!actual.includes(existing))throw Error('existing note changed')
                results.push(op)
              }
              const source=Object.create(MirrorSource.prototype)
              Object.assign(source,{pair:{solo:true},byId:new Map([[-2,{uid:'phone-uid',tags:item.tags}]]),
                item:async()=>item,keys:()=>({anthropic:'synthetic'}),synthChoice:()=>['anthropic','synthetic-model'],
                endpoints:()=>({anthropic:'https://api.anthropic.com'}),newNoteFile:async()=> 'note.md',flushSoon(){},
                changes:{add:async e=>journal.push(e)}})
              setFetch(async(url,init)=>{sent.push(JSON.parse(init.body));return Response.json({content:[{type:'text',text:'Note 繁中 [id -2]'}]})})
              try{setup({},'zh-Hant',[]);await source.synthesize('Topic',[-2],()=>{},new AbortController().signal)}
              finally{setFetch((url,init)=>fetch(url,init))}
              return {results,sent,journal,block:S.sourceBlock(item)}
            }""")
            self.assertEqual(len(got['results']), 24)
            self.assertEqual(got['journal'], [dict(op='synth', topic='Topic', sources=[-2], uids=['phone-uid'], body='Note 繁中 [id -2]', file='note.md')])
            self.assertIn('Caption 原文', got['block'])
            self.assertIn('My note 简体', got['block'])
            self.assertIn('Tags: ancien, 保留', got['block'])
            self.assertEqual(got['sent'][0]['messages'][0]['content'].count('Language policy:'), 1)
            self.assertEqual(errors, [])

    def test_renderer_escapes_labels_and_provider_content_and_keeps_marker_parsers(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360, 740, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            got = page.evaluate(r"""async () => {
              const {setup}=await import('/src/lib/i18n/index.ts')
              const {fmtAnswer,mdHTML,setCardLookup}=await import('/src/lib/md.ts')
              const {citedIds,citedNotes}=await import('/src/mobile/ai/quick.ts')
              const {esc}=await import('/src/lib/cards/card.ts')
              const hostile='$& <img src=x onerror=alert(1)> " &'
              setup({fr:{'wiskit.generalKnowledge':hostile,'wiskit.citation.missing':hostile}},'fr',[])
              setCardLookup(n=>n===1?{title:hostile,cat:'SPORT'}:undefined)
              const raw='## 來源\n[id 1] [id 999] [note: a" onclick="evil.md] (GeNeRaL KnOwLeDgE)\n<img src=x onerror=alert(1)>'
              const copy=raw,html=fmtAnswer(raw),box=document.createElement('div')
              box.innerHTML=html;document.body.append(box)
              const safe=mdHTML('[unsafe](javascript:alert(1)) [safe](https://example.test/help)')
              return {raw,unchanged:raw===copy,ids:citedIds(raw),notes:citedNotes(raw),html,safe,
                labels:[box.querySelector('.gk').textContent,box.querySelector('.miss').title],
                nodes:box.querySelectorAll('img,script,[onerror],[onclick]').length,escaped:esc(hostile)}
            }""")
            self.assertTrue(got['unchanged'])
            self.assertEqual(got['ids'], [1, 999])
            self.assertEqual(got['notes'], ['a" onclick="evil.md'])
            self.assertEqual(got['labels'], ['$& <img src=x onerror=alert(1)> " &'] * 2)
            self.assertEqual(got['nodes'], 0)
            self.assertIn('<span class="gk">' + got['escaped'] + '</span>', got['html'])
            self.assertNotIn('href="javascript:', got['safe'])
            self.assertIn('href="https://example.test/help"', got['safe'])
            self.assertEqual(errors, [])

    def test_desktop_default_renderer_ignores_all_phone_preferences(self):
        baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
        with mobile_browser() as (browser, base):
            for language in ('fr', 'zh-Hant'):
                with browser.new_context(locale='en-US') as context:
                    context.route('**/api/**', lambda route: route.abort())
                    context.add_init_script("localStorage.setItem('bp-lang'," + json.dumps(language) + ");localStorage.setItem('brainamon-language','fr')")
                    page = context.new_page()
                    page.goto(base + '/', wait_until='domcontentloaded')
                    page.evaluate("window.TYPE={SPORT:'#9cc4e2'}")
                    rendered = page.evaluate(r"""async raw => {
                      const {lang}=await import('/src/lib/i18n/index.ts')
                      const {fmtAnswer,mdHTML,setCardLookup}=await import('/src/lib/md.ts')
                      setCardLookup(n=>n===1?{title:'<img src=x onerror=alert(1)>',cat:'SPORT'}:undefined)
                      if(lang()!=='en')throw Error('desktop language changed')
                      return {answer:fmtAnswer(raw),markdown:mdHTML('# 來源\n[id 1] [id 999]\n[unsafe](javascript:alert(1))\nhttps://example.test/')}
                    }""", baseline['raw'])
                    self.assertEqual(rendered, baseline['rendered'])


if __name__ == '__main__':
    unittest.main()
