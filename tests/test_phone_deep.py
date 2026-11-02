"""Wiskit Deep on the phone (projects/mobile-app/plans/07-wiskit-deep.md): the TypeScript port of the
librarian tools (web/src/mobile/ai/deep.ts) against knowledge/librarian.py on the same library, and
the agent loop (providers.ts askAgent) against the stand-in providers (server/dev_drive.py).

The library is the Phase 5 fixture (tests/phone_ai_fixture.py) plus what Deep reads besides the
items: topic clusters (data/obsidian_graph.json), a websites and tools index (the resources
table), an About me note, reports with a "How you could use this" section, and topic and
note-section vectors, some of them missing or stale so the phone embeds them itself. The phone
reads all of it from the mirror's files (library/mirror.py), as it would from Drive.

Every tool call the model can make is run on both sides and the text handed back to the model is
compared, in both modes: with embeddings (fake vectors, tests/phone_ai_fixture.fake_vec) and by
keywords only (no OpenAI key). No AI provider is called. Runs under Node 22.6+ type stripping
(skips without it), like tests/test_phone_ai.py."""
import base64
import gzip
import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from core import ai_client
from knowledge import ask_core, librarian, prompt_files
from library import export, mirror, search
from server import dev_drive
from server.sync import deep_rows
from tests import phone_ai_fixture as F
from tests.test_phone_js import _node_ok, node

MODEL = ai_client.EMBEDDING_MODEL

CLUSTERS = {
    '2': {'title': 'Knee and hip prehab', 'synthesis': 'Knee prehab drills, hip airplanes and the Turkish get-up for sore knees.', 'member_ids': [102, 104, 107, 108, 111]},
    '10': {'title': 'Kettlebell training', 'synthesis': 'Kettlebell swings, finishers and leg day sessions.', 'member_ids': [112, 115, 116, 117]},
    '0': {'title': 'Claude Code and AI tools', 'synthesis': 'Subagents, MCP servers and coding agents.', 'member_ids': [131, 134, 137, 139]},
    '7': {'title': '', 'synthesis': '', 'member_ids': [142]},                       # skipped: nothing to embed
    '3': {'title': 'Cooking', 'synthesis': 'Vegan recipes and crème brûlée.', 'member_ids': [144, 147, 149, 151, 999]},
}
RESOURCES = [
    (102, 'kneeprehab.com', 'https://kneeprehab.com/plan', 'Full knee prehab plan at kneeprehab.com'),
    (104, 'kneeprehab.com', 'https://kneeprehab.com', 'kneeprehab.com has the airplanes'),
    (112, 'kettlebell.app', 'https://kettlebell.app', 'Kettlebell swing timer: kettlebell.app'),
    (131, 'skills.sh', 'https://skills.sh/agents', 'Claude Code subagents gallery skills.sh'),
    (134, 'modelcontextprotocol.io', 'https://modelcontextprotocol.io', 'MCP servers docs'),
    (102, 'youtube.com', 'https://youtube.com/watch', 'Knee video on YouTube'),
    (147, 'veganrecipes.co', 'https://veganrecipes.co', 'Vegan Recipes site'),
    (139, 'my_tool.dev', 'https://my_tool.dev', 'A tool with an underscore in its name'),
]
PROFILE = '---\ntopic: About me\nkind: personal\n---\n\nI am 45, my left knee hurts, I train at home with one kettlebell.\n'
QUESTIONS = ['What helps knee pain?', 'kettlebell swing finisher', 'How do I set up Claude Code subagents and MCP servers?',
             'which website for knee prehab', 'vegan recipes', 'test it']


def _calls():
    """(name, args) of every tool call compared, including the paths that end in an error."""
    out = []
    for q in QUESTIONS:
        out += [('find_topics', {'query': q}), ('search_library', {'query': q}), ('search_notes', {'query': q}),
                ('find_resources', {'query': q}), ('read_items', {'ids': [102, 112, 131, 999], 'query': q})]
    out += [
        ('find_topics', {'query': 'knee', 'limit': 2}), ('find_topics', {'query': 'knee', 'limit': '50'}),
        ('topic_items', {'topic_id': '2'}), ('topic_items', {'topic_id': 'topic:10', 'query': 'swing', 'limit': 2}),
        ('topic_items', {'topic_id': '3', 'offset': 2, 'limit': 2}), ('topic_items', {'topic_id': 'nope'}),
        ('topic_items', {'topic_id': 7}),
        ('search_library', {'query': 'knee', 'category': 'sport'}), ('search_library', {'query': 'knee', 'category': 'NOPE'}),
        ('search_library', {'query': 'knee', 'offset': 3, 'limit': 4}), ('search_library', {'query': 'knee', 'offset': 400}),
        ('search_library', {'query': 'knee', 'limit': 2.7}), ('search_library', {'query': 'knee', 'limit': True}),
        ('read_items', {'ids': ['104', 107]}), ('read_items', {'ids': []}), ('read_items', {'ids': [1, 2]}),
        ('read_items', {'ids': [102, 104, 107, 108, 111, 112, 115, 116, 117, 118, 119, 120, 123, 125]}),
        ('read_items', {'ids': '12'}), ('read_items', {'ids': ['x']}),
        ('search_notes', {'query': 'knee', 'limit': 8}), ('search_notes', {'query': 'zzzz'}),
        ('find_resources', {'query': 'tool', 'limit': 2}), ('find_resources', {'query': 'zzzz'}),
        ('related_items', {'id': 102}), ('related_items', {'id': '131', 'limit': 3}), ('related_items', {'id': 5}),
        ('related_items', {'id': 'x'}),
        ('nope', {}), ('find_topics', {}), ('find_topics', {'query': 'knee', 'bogus': 1}),
    ]
    return out


def _vec(text: str) -> list:
    """F.fake_vec plus a little dense noise seeded by the text, so no two rows score exactly the same
    against a question (numpy's sort does not keep the order of exact ties, the phone's does)."""
    rng = np.random.default_rng(int.from_bytes(hashlib.sha256(text.encode('utf-8')).digest()[:8], 'big'))
    return (np.asarray(F.fake_vec(text), dtype=np.float32) + rng.uniform(-0.05, 0.05, F.DIM).astype(np.float32)).tolist()


def _int8(vectors: bytes, aux_bin: bytes, aux: list):
    """The desktop's index and aux rows rebuilt from the mirror's int8 files (what the phone ranks on)."""
    def read(blob):
        n = int.from_bytes(blob[4:8], 'big')
        head = json.loads(blob[8:8 + n])
        return head, np.frombuffer(blob[8 + n:], dtype=np.int8).reshape(head['count'], head['dim']).astype(np.float32)
    head, mat = read(vectors)
    index = search.EmbeddingIndex([(i, head['dim'], mat[k].tobytes()) for k, i in enumerate(head['ids'])])
    head, mat = read(aux_bin)
    stored = {key: mat[k] for k, key in enumerate(head['keys'])}
    return index, [dict(a, vec=stored.get(a['key'], a['vec'])) for a in aux]


def _mirror(db, data_dir: Path) -> dict:
    """The mirror's files as the phone opens them."""
    payload = export.build_export_payload(db, None, {}, mirror=True, vectors_model=MODEL)
    payload['deep'] = deep_rows(db)
    out = {'texts': [], 'rows': []}
    for f in mirror.build_files(payload, data_dir, mirror.Options(videos='off', canvases=False)):
        if f.name.startswith('search/text-'):
            out['texts'] += json.loads(gzip.decompress(f.data()))
        elif f.name.startswith('library/part-'):
            out['rows'] += json.loads(f.data())
        elif f.name == 'search/deep.json.gz':
            out['deep'] = json.loads(gzip.decompress(f.data()))
        elif f.name in ('vectors.bin', 'search/aux.bin'):
            out[f.name] = f.data()
    return out


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneDeepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        db = cls.db = F.build(cls.tmp, MODEL)
        (cls.tmp / 'obsidian_graph.json').write_text(json.dumps({'nodes': [], 'clusters': CLUSTERS}), encoding='utf-8')
        (db.notes_dir / librarian.PROFILE_FILE).write_text(PROFILE, encoding='utf-8')
        (db.notes_dir / 'knee-plan.md').write_text(
            '---\ntopic: Knee plan\nsources: 102, 104\n---\n\n## Warm-up\nTen minutes of knee prehab and hip airplanes before any squat.\n'
            '## Main\nKettlebell goblet squats to a box, three sets of eight, slow on the way down.\n## Tiny\nshort\n', encoding='utf-8')
        db.reindex_notes()
        for i, extra in ((102, 'Do it before squats; pair with hip airplanes.'), (112, 'Use it as a finisher after leg day.')):
            p = db.items_dir / str(i) / 'report.md'
            p.write_text(p.read_text(encoding='utf-8') + f'\n### How you could use this\n{extra}\n', encoding='utf-8')
        db.replace_resources(RESOURCES)
        for it in F.load()['items']:
            text = ' '.join(it.get(k) or '' for k in ('description', 'ai_desc', 'tags', 'creator'))
            db.upsert_embedding(it['id'], MODEL, F.DIM, 'h', np.asarray(_vec(text), dtype=np.float32).tobytes())
        # topic and note-section vectors: stored in the canonical order; the last section has none and
        # the one before it a stale hash, so both sides embed them before answering
        jobs, _ = librarian.aux_jobs(cls.tmp, db.notes_dir, {}, MODEL)
        cls.vecs = {j['text']: _vec(j['text']) for j in jobs}
        stored = [dict(j, dim=F.DIM, blob=np.asarray(cls.vecs[j['text']], dtype=np.float32).tobytes()) for j in jobs[:-1]]
        stored[-1]['hash'] = 'stale'
        db.upsert_aux_embeddings(MODEL, stored)
        cls.n_jobs = len(jobs)

        cls.files = _mirror(db, cls.tmp)
        cls.index = search.EmbeddingIndex.from_db(db, MODEL)
        cls.reports = {it['id']: (db.items_dir / str(it['id']) / 'report.md').read_text(encoding='utf-8')
                       for it in F.load()['items'] if (db.items_dir / str(it['id']) / 'report.md').exists()}
        cls.calls = _calls()
        queries = {str(a.get('query')) for _, a in cls.calls if a.get('query')} | set(QUESTIONS)
        qvecs = {q.strip(): _vec(q.strip()) for q in queries}

        # the desktop: deep_setup + deep_answer's aux step, with and without an embeddings key
        setup = ask_core.deep_setup(db, 'k', cls.index)
        cls.stale = len(setup['jobs'])
        aux = setup['aux_rows'] + [{'key': j['key'], 'kind': j['kind'], 'payload': j['payload'], 'vec': _vec(j['text'])} for j in setup['jobs']]
        kw = ask_core.deep_setup(db, '', None)
        # the same desktop code on the vectors the phone has (int8): the port must match it exactly
        q8_index, q8_aux = _int8(cls.files['vectors.bin'], cls.files['search/aux.bin'], aux)
        cls.py = {}
        for mode, lib in (('vec', librarian.Librarian(db, cls.index, aux, lambda q: _vec(q))),
                          ('q8', librarian.Librarian(db, q8_index, q8_aux, lambda q: _vec(q))),
                          ('kw', librarian.Librarian(db, kw['index'], kw['aux_rows'], lambda q: None))):
            cls.py[mode] = {'calls': [lib.run_tool(n, a) for n, a in cls.calls],
                            'orient': [lib.orientation(q) for q in QUESTIONS], 'consulted': list(dict.fromkeys(lib.consulted))}
        cls.system = setup['system']

        notes = [[p.name, p.read_text(encoding='utf-8')] for p in sorted(db.notes_dir.glob('*.md'))]
        src = {'texts': cls.files['texts'], 'rows': cls.files['rows'], 'deep': cls.files['deep'], 'notes': notes,
               'vec': base64.b64encode(cls.files['vectors.bin']).decode(), 'aux': base64.b64encode(cls.files['search/aux.bin']).decode(),
               'qvecs': qvecs, 'tvecs': cls.vecs, 'reports': cls.reports, 'calls': cls.calls, 'questions': QUESTIONS, 'model': MODEL,
               'P': prompt_files.load('ask_deep')}
        (cls.tmp / 'in.json').write_text(json.dumps(src), encoding='utf-8')
        cls.out = json.loads(node(f"""
            import fs from 'node:fs'
            import {{ PhoneLibrary, noteOf }} from './web/src/mobile/ai/library.ts'
            import {{ Librarian, auxRows, describeCall, deepTurn, noteSections, profileOf, readAux, systemPrompt, topicTexts, PROFILE_FILE }} from './web/src/mobile/ai/deep.ts'
            import {{ readVectors }} from './web/src/mobile/mirror/crypto.ts'
            const S = JSON.parse(fs.readFileSync({json.dumps(str(cls.tmp / 'in.json'))}, 'utf8'))
            const b64 = s => Uint8Array.from(Buffer.from(s, 'base64'))
            const lib = new PhoneLibrary(S.texts, S.rows, S.notes.map(([f, t]) => noteOf(f, t)))
            lib.setResources(S.deep.resources)
            const v = readVectors(b64(S.vec)), stored = readAux(b64(S.aux))
            const live = [...topicTexts(S.deep.topics), ...noteSections(S.notes, S.P.limits.section_max)]
            const embedded = []
            const vecMode = await auxRows(live, S.model, stored, new Map(), async texts => {{ embedded.push(...texts); return texts.map(t => S.tvecs[t]) }}, S.P.limits.aux_batch)
            const kwMode = await auxRows(live, S.model, stored, new Map(), null, S.P.limits.aux_batch)
            const report = async id => S.reports[id] ?? ''
            const out = {{ live: live.map(e => e.key), embedded: embedded.length, fresh: vecMode.fresh.size }}
            for (const [mode, L] of [['q8', new Librarian(S.P, lib, v, vecMode.rows, async q => S.qvecs[q.trim()] ?? null, report)],
                                     ['kw', new Librarian(S.P, lib, null, kwMode.rows, async () => null, report)]]) {{
              const calls = []
              for (const [n, a] of S.calls) calls.push(await L.runTool(n, a))
              const orient = []
              for (const q of S.questions) orient.push(await L.orientation(q))
              out[mode] = {{ calls, orient, consulted: [...new Set(L.consulted)] }}
            }}
            const profile = profileOf(S.notes.find(([f]) => f === PROFILE_FILE)?.[1], S.P.limits.profile_max)
            out.system = systemPrompt(S.P, profile, lib.countByCategory(), lib.countItems())
            out.describe = S.calls.map(([n, a]) => describeCall(n, a))
            out.turn = await deepTurn(new Librarian(S.P, lib, v, vecMode.rows, async q => S.qvecs[q.trim()] ?? null, report), S.questions[0])
            console.log(JSON.stringify(out))
        """, timeout=120))

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _compare(self, mode):
        py, ts = self.py[mode], self.out[mode]
        for (name, args), want, got in zip(self.calls, py['calls'], ts['calls']):
            with self.subTest(mode=mode, tool=name, args=args):
                if want.startswith('Error: bad arguments') or 'failed:' in want.split('\n', 1)[0]:
                    self.assertEqual(got.split(':', 2)[:2], want.split(':', 2)[:2])     # same kind of error
                else:
                    self.assertEqual(got, want)
        for q, want, got in zip(QUESTIONS, py['orient'], ts['orient']):
            with self.subTest(mode=mode, orientation=q):
                self.assertEqual(got, want)
        self.assertEqual(ts['consulted'], py['consulted'])

    def test_tools_give_the_model_the_same_text_with_embeddings(self):
        """The desktop's code on the phone's int8 vectors: the same text, byte for byte."""
        self._compare('q8')

    def test_tools_rank_like_the_desktop_on_its_own_vectors(self):
        """Against the desktop's float32 vectors (the phone has int8 ones) only near-ties may swap: nine
        results in ten start with the same reference, and the rest share one of their first three."""
        ref = re.compile(r'\[(?:id \d+|note: [^\]]+)\]')
        pairs = list(zip(self.calls, self.py['vec']['calls'], self.out['q8']['calls']))
        pairs += [(('orientation', q), w, g) for q, w, g in zip(QUESTIONS, self.py['vec']['orient'], self.out['q8']['orient'])]
        swapped = 0
        for (name, args), want, got in pairs:
            w, g = ref.findall(want)[:3], ref.findall(got)[:3]
            if g[:1] != w[:1]:
                swapped += 1
                with self.subTest(tool=name, args=args):
                    self.assertTrue(set(g) & set(w))
        self.assertLessEqual(swapped, len(pairs) // 10)

    def test_tools_give_the_model_the_same_text_by_keywords(self):
        """No OpenAI key: keyword ranking only, and only the vectors the PC sent."""
        self._compare('kw')

    def test_phone_embeds_what_the_pc_has_not(self):
        self.assertEqual(self.out['live'], [j['key'] for j in librarian.aux_jobs(self.tmp, self.db.notes_dir, {}, MODEL)[0]])
        self.assertEqual(self.stale, 2)
        self.assertEqual(self.out['embedded'], 2)
        self.assertEqual(self.out['fresh'], 2)

    def test_system_prompt_turn_and_progress_lines(self):
        self.assertEqual(self.out['system'], self.system)
        self.assertIn('my left knee hurts', self.system)
        self.assertEqual(self.out['describe'], [librarian.describe_call(n, a) for n, a in self.calls])
        lib = librarian.Librarian(self.db, self.index, [], lambda q: _vec(q))
        aux = ask_core.deep_setup(self.db, 'k', self.index)
        lib = librarian.Librarian(self.db, self.index, aux['aux_rows'] + [{'key': j['key'], 'kind': j['kind'], 'payload': j['payload'],
                                  'vec': _vec(j['text'])} for j in aux['jobs']], lambda q: _vec(q))
        q = QUESTIONS[0]
        want = prompt_files.fill(librarian.PROMPTS['turn'], question=q, orientation=lib.orientation(q))
        self.assertEqual(self.out['turn'], want)

    def test_mirror_files(self):
        deep = self.files['deep']
        self.assertEqual([t[0] for t in deep['topics']], list(CLUSTERS))                  # file order, not JSON key order
        self.assertEqual([tuple(r) for r in deep['resources']], RESOURCES)
        head_len = int.from_bytes(self.files['search/aux.bin'][4:8], 'big')
        head = json.loads(self.files['search/aux.bin'][8:8 + head_len])
        self.assertEqual(head['count'], self.n_jobs - 1)
        self.assertEqual(head['dim'], F.DIM)
        self.assertEqual(head['hashes'][-1], 'stale')
        meta = ai_client.phone_settings('anthropic', 'm')
        self.assertEqual((meta['agent_max_rounds'], meta['agent_max_tokens']), (ai_client._AGENT_MAX_ROUNDS, ai_client._AGENT_MAX_TOKENS))


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class DeepAgentTest(unittest.TestCase):
    """askAgent against the stand-ins: the tool rounds, then an answer citing what the tools returned."""

    def test_agent_loop_on_both_providers(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        srv = dev_drive.serve(root, port=0, fake_ai=True, fake_dim=8)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        base = f'http://127.0.0.1:{srv.server_address[1]}/ai'
        out = json.loads(node(f"""
            import {{ askAgent }} from './web/src/mobile/ai/providers.ts'
            const ep = {{ anthropic: '{base}/anthropic', openai: '{base}/openai' }}
            const tools = [{{ name: 'search_library', description: 'd', parameters: {{ type: 'object', properties: {{}} }} }},
                           {{ name: 'read_items', description: 'd', parameters: {{ type: 'object', properties: {{}} }} }}]
            const run = async (n, a) => n === 'search_library' ? '[id 12] knee (coach)\\n[id 30] hips' : n === 'read_items' ? '[id ' + a.ids.join('] x\\n[id ') + '] x' : 'Error: no'
            const out = {{}}
            for (const p of ['anthropic', 'openai']) {{
              const seen = []
              const text = await askAgent(ep, p, 'k', 'm', 'sys', [{{ role: 'user', content: 'earlier?' }}, {{ role: 'assistant', content: 'See [id 99].' }}, {{ role: 'user', content: 'Question: knees?\\n\\nStarting points\\nNOTES\\n[note: knee.md] Knee\\n\\nAnswer this question: knees?' }}],
                tools, run, (n, a) => seen.push([n, a]), 8, 100)
              const short = await askAgent(ep, p, 'k', 'm', 'sys', [{{ role: 'user', content: 'Question: q\\n\\nAnswer this question: q' }}], tools, run, () => {{}}, 1, 100)
              out[p] = {{ text, seen, short }}
            }}
            console.log(JSON.stringify(out))
        """, development=True))
        for p in ('anthropic', 'openai'):
            with self.subTest(provider=p):
                o = out[p]
                self.assertEqual([n for n, _ in o['seen']], ['search_library', 'read_items'])
                self.assertEqual(o['seen'][1][1], {'ids': [12, 30]})
                self.assertIn('[id 12]', o['text'])
                self.assertIn('[id 30]', o['text'])
                self.assertIn('[note: knee.md]', o['text'])
                self.assertIn('knees?', o['text'])
                self.assertTrue(o['short'].startswith('Stand-in'))          # one round: tools forbidden, text at once


if __name__ == '__main__':
    unittest.main()
