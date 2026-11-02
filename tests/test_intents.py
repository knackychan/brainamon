"""Saved intents (S3): one list in the protected cloud folder, no passphrase in it, a double click refused."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core import private_storage
from server import intents
from server.cloud_errors import Busy


class IntentsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.path = self.root / 'intents.json'
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_an_intent_is_saved_and_survives_a_restart(self):
        item = intents.Intents(self.path).add(intents.REMOVE, {'new': 'abc'})
        self.assertEqual((item['kind'], item['stage'], item['payload']), ('remove_phones', 'requested', {'new': 'abc'}))
        again = intents.Intents(self.path)                                      # a second process start reads the same list
        self.assertEqual(again.all(), [item])
        again.update(intents.REMOVE, stage='publishing', payload={'x': 1})
        found = intents.Intents(self.path).find(intents.REMOVE)
        self.assertEqual((found['stage'], found['payload']), ('publishing', {'new': 'abc', 'x': 1}))

    def test_a_second_intent_of_the_same_kind_is_a_double_click(self):
        store = intents.Intents(self.path)
        store.add(intents.ENROLL, {'record': 'a'})
        with self.assertRaises(Busy):
            store.add(intents.ENROLL, {'record': 'b'})
        self.assertEqual(store.find(intents.ENROLL)['payload'], {'record': 'a'})
        store.add(intents.SWITCH)                                               # another kind is a different task

    def test_a_failed_intent_is_replaced_by_the_retry(self):
        store = intents.Intents(self.path)
        store.add(intents.ENROLL, {'record': 'a'})
        store.update(intents.ENROLL, error='Google Drive is full.', code='drive_full')
        retry = store.add(intents.ENROLL, {'record': 'b'})
        self.assertEqual((store.all(), retry['error']), ([retry], ''))

    def test_finishing_the_last_one_removes_the_file(self):
        store = intents.Intents(self.path)
        store.add(intents.RESET)
        self.assertTrue(private_storage.location(self.path).exists())
        store.finish(intents.RESET)
        self.assertFalse(private_storage.location(self.path).exists())
        store.finish(intents.RESET)                                             # nothing to finish: nothing happens

    def test_a_damaged_list_reads_as_empty_and_never_blocks(self):
        private_storage.write(self.path, b'not json {')
        self.assertEqual(intents.Intents(self.path).all(), [])
        private_storage.write(self.path, json.dumps([{'kind': 'unknown'}, {'kind': 'enroll', 'stage': 'queued', 'id': '1', 'created': 1, 'payload': {}}]).encode())
        self.assertEqual([i['kind'] for i in intents.Intents(self.path).all()], ['enroll'])

    def test_a_task_belongs_to_one_library(self):
        """Another data folder opening the same cloud folder neither sees nor runs it, and keeps it when it writes its own."""
        mine, other = intents.Intents(self.path, 'd:/library-a'), intents.Intents(self.path, 'd:/library-b')
        mine.add(intents.REMOVE, {'new': 'abc'})
        self.assertEqual(other.all(), [])
        self.assertFalse(other.preempting())
        other.add(intents.REMOVE, {'new': 'xyz'})                               # not a double click: another library
        other.finish(intents.REMOVE)
        self.assertEqual([i['payload'] for i in intents.Intents(self.path, 'd:/library-a').all()], [{'new': 'abc'}])
        self.assertEqual(intents.Intents(self.path, 'd:/library-b').all(), [])

    def test_which_intent_wants_the_slot_between_two_upload_requests(self):
        store = intents.Intents(self.path)
        self.assertFalse(store.preempting())
        store.add(intents.ONE_SHOT)
        self.assertFalse(store.preempting())                                    # a one-time backup waits for no slot
        store.add(intents.REMOVE)
        self.assertTrue(store.preempting())                                     # not switched yet
        store.update(intents.REMOVE, stage='publishing')
        self.assertFalse(store.preempting())                                    # the key switched: its export is the new one
        store.add(intents.ENROLL)
        self.assertTrue(store.preempting())
        store.update(intents.ENROLL, stage='uploading')
        self.assertFalse(store.preempting())
        store.update(intents.ENROLL, stage='queued', error='failed')
        self.assertFalse(store.preempting())                                    # a failed one waits for its retry, not for the slot


if __name__ == '__main__':
    unittest.main()
