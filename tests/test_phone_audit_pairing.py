"""Pairing must retain the solo library when its requeue marker cannot be saved."""
import unittest

from tests.test_phone_resend import JOURNAL, PAIRING, keys, run


class PairingStorage(unittest.TestCase):
    def test_flush_waits_for_the_solo_requeue_to_finish(self):
        out = run(JOURNAL + """
            const P = await import('./web/src/mobile/mirror/pairing.ts')
            const c = new Changes()
            mem.set('bp-requeue', '1')
            let error = ''
            try { await c.flush(send, 'phone', true, true) } catch (e) { error = e.message }
            const early = sent.length
            await c.requeue(); P.takeRequeue()
            await c.flush(send, 'phone', true, true)
            console.log(JSON.stringify({ error, early, batches: sent.map(d => [d.seq, d.changes.length]) }))
        """, STATE={'rows': [
            {'id': 1, 'op': 'note_append', 'text': 'saved solo note', 'at': 100, 'state': 'sent',
             'sentAt': 100, 'stream': 'a' * 32, 'seq': 2},
            {'id': 2, 'op': 'note_append', 'text': 'new note', 'at': 200, 'state': 'queued'}],
            'kv': {'delivery': {'stream': 'a' * 32, 'next': 3, 'acked': 1}}})
        self.assertEqual(out['early'], 0)
        self.assertIn('Reopen Brainamon', out['error'])
        self.assertEqual(out['batches'], [[1, 2]])

    def test_failed_solo_requeue_marker_keeps_the_original_pairing(self):
        out = run(PAIRING + """
            await P.startSolo(K[1].k)
            const before = secrets.get('bp-pair')
            const set = localStorage.setItem
            localStorage.setItem = (k, v) => {
              if (k === 'bp-requeue') throw new DOMException('synthetic quota', 'QuotaExceededError')
              set(k, v)
            }
            const scan = { v: 2, k: K[0].k, f: K[0].f, l: A, c: 'client', e: 'fixture@example.com' }
            const note = await P.acceptLink(link(scan))
            console.log(JSON.stringify({ note, kept: secrets.get('bp-pair') === before, solo: P.pairing()?.solo }))
        """, KEYS=keys())
        self.assertEqual(out, {'note': 'That pairing code could not be read. Show the QR on the PC again.',
                               'kept': True, 'solo': True})
