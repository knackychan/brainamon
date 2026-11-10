"""Voice notes: an audio upload -> compressed MP3 -> transcribed text (projects/voice-notes/plans/01-pc.md).

Qt-free and DB-free: runs on a worker thread (asyncio.to_thread in server/routes/my_notes.py). The
caller owns `work_dir` and deletes it."""
from pathlib import Path

from library import video_analyzer

MAX_SECONDS = 30 * 60


class VoiceError(Exception):
    """A problem the user can act on (shown as a 400)."""


def transcribe_upload(src, work_dir, should_stop=None) -> str:
    try:
        mp3 = video_analyzer.extract_audio_compressed(str(src), output_dir=str(Path(work_dir)), should_stop=should_stop)
    except RuntimeError as e:
        raise VoiceError(str(e))
    secs = video_analyzer.audio_duration(mp3)
    if secs and secs > MAX_SECONDS:
        raise VoiceError('That recording is longer than 30 minutes. Split it and try again.')
    return video_analyzer.transcribe_long(mp3, should_stop=should_stop).strip()
