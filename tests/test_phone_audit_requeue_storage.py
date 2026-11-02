"""Unreadable or uncleared requeue markers must never be mistaken for completed preparation."""
import unittest

from tests.test_phone_resend import JOURNAL, run


class RequeueStorage(unittest.TestCase):
    def test_unreadable_marker_refuses_a_numbered_upload(self):
        result = run(JOURNAL + """
            mem.set('bp-requeue', '1')
            const get = localStorage.getItem
            localStorage.getItem = k => {
              if (k === 'bp-requeue') throw new Error('synthetic storage read failure')
              return get(k)
            }
            let error = ''
            try { await new Changes().flush(send, 'phone', true, true) } catch (e) { error = e.message }
            console.log(JSON.stringify({ error, sent: sent.length }))
        """, STATE={'rows': [{'id': 1, 'op': 'note_append', 'text': 'kept', 'at': 100, 'state': 'queued'}], 'kv': {}})
        self.assertEqual(result, {'error': 'synthetic storage read failure', 'sent': 0})

    def test_clearing_the_marker_reports_storage_failure(self):
        result = run(JOURNAL + """
            const P = await import('./web/src/mobile/mirror/pairing.ts')
            mem.set('bp-requeue', '1')
            localStorage.removeItem = () => { throw new Error('synthetic storage removal failure') }
            let error = ''
            try { P.takeRequeue() } catch (e) { error = e.message }
            console.log(JSON.stringify({ error, marker: mem.get('bp-requeue') }))
        """, STATE={'rows': [], 'kv': {}})
        self.assertEqual(result, {'error': 'synthetic storage removal failure', 'marker': '1'})
