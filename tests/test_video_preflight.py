"""Analyze video on a clean PC: the preflight check and the reason a missing transcript gives in
report.md (library/video_analyzer.py). No ffmpeg runs here.

Run from the project root:  py -m unittest tests.test_video_preflight -v
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from library import video_analyzer as va


class PreflightTest(unittest.TestCase):
    def patch(self, ffmpeg=True):
        patch = mock.patch.object(va, 'ffmpeg_available', lambda: ffmpeg)
        patch.start()
        self.addCleanup(patch.stop)

    def test_all_present(self):
        self.patch()
        self.assertEqual(va.preflight(True, True, True), '')

    def test_transcription_needs_openai_key(self):
        self.patch()
        self.assertEqual(va.preflight(False, True, False), va.OPENAI_KEY_MISSING)
        self.assertEqual(va.preflight(False, False, False), '')     # transcription off: fine

    def test_ffmpeg_missing(self):
        self.patch(ffmpeg=False)
        self.assertEqual(va.preflight(False, True, True), va.FFMPEG_MISSING)
        self.assertEqual(va.preflight(True, False, True), va.FFMPEG_MISSING)
        self.assertEqual(va.preflight(False, False, True), '')     # nothing needs ffmpeg

    def test_frames_require_the_confined_ffmpeg_reader(self):
        self.patch(ffmpeg=False)
        self.assertEqual(va.preflight(True, False, True), va.FFMPEG_MISSING)

    def test_messages_are_plain(self):
        for msg in (va.FFMPEG_MISSING, va.OPENAI_KEY_MISSING):
            self.assertNotIn('pip install', msg)
            self.assertNotIn('PATH', msg)

    def test_only_whisper_api_is_accepted(self):
        with self.assertRaises(ValueError):
            va.transcribe_audio('x.mp4', method='free', whisper_api_key='k')


class TranscriptionTest(unittest.TestCase):
    def test_audio_at_upload_limit_reaches_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.mp3'
            with path.open('wb') as audio:
                audio.truncate(24 * 1024 * 1024)
            client = object()
            with mock.patch.object(va, '_whisper_api_transcribe_file', return_value='synthetic transcript') as transcribe, \
                    mock.patch.object(va, '_run') as split:
                self.assertEqual(va._whisper_api_transcribe(client, str(path)), 'synthetic transcript')
                transcribe.assert_called_once_with(client, str(path))
                split.assert_not_called()

    def test_audio_over_upload_limit_is_split_and_cleaned(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.mp3'
            with path.open('wb') as audio:
                audio.truncate(24 * 1024 * 1024 + 1)
            def split(command, *args, **kwargs):
                self.assertEqual(command[2:4], ['-protocol_whitelist', 'file,pipe'])
                for i in range(2):
                    Path(command[-1] % i).write_bytes(b'synthetic chunk')
            with mock.patch.object(va, '_audio_duration_seconds', return_value=600), \
                    mock.patch.object(va, '_run', side_effect=split), \
                    mock.patch.object(va, '_whisper_api_transcribe_file', side_effect=['first', 'second']) as transcribe:
                self.assertEqual(va._whisper_api_transcribe(object(), str(path)), 'first second')
                self.assertEqual(transcribe.call_count, 2)
                self.assertFalse((path.parent / 'synthetic_chunks').exists())


class TranscriptReasonTest(unittest.TestCase):
    def test_report_says_why_there_is_no_transcript(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(va, 'transcribe_audio', side_effect=RuntimeError(va.OPENAI_KEY_MISSING)):
            steps = []
            report, transcript, _ai, _n = va.analyze_media(Path(td) / 'v.mp4', Path(td) / 'out', frame_interval=0,
                                                           analysis_provider='none', step=steps.append)
            self.assertEqual(transcript, '')
            self.assertIn(va.OPENAI_KEY_MISSING, Path(report).read_text(encoding='utf-8'))
            self.assertTrue(any(s.startswith('Transcription skipped: ') for s in steps))


if __name__ == '__main__':
    unittest.main()
