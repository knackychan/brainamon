#!/usr/bin/env python3
"""
video_analyzer.py — Merged Frames Extractor + Video Analyzer helper.

Features:
- `extract_frames()` samples frames into a subfolder of the output directory via ffmpeg
  (fast C decode + downscale to _FRAME_MAX_WIDTH), with local-only input protocols.
- `extract_audio_compressed()` extracts audio to a mono 16 kHz MP3 using ffmpeg.
- `transcribe_audio()` sends the audio to the OpenAI file-transcription API (the only transcription path).
- `analyze_media()` is the single analysis engine (frames + transcript + AI + report.md/json),
  shared by the V6 server analyze job (server/job_kinds.py), Video Tools, and the CLI.

Usage examples:
    python -m library.video_analyzer /path/to/video.mp4 --interval 2.5 --out data/thumbs
    python -m library.video_analyzer /path/to/video.mp4 --whisper-api-key KEY
"""

import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from core import app_console
from core import app_paths

# User-facing messages: what to do, not how the code failed. FFmpeg is not bundled with the app.
FFMPEG_MISSING = ("Video analysis needs FFmpeg (ffmpeg and ffprobe), which was not found on this PC. "
                  "Open Settings > Tools to install it or to pick the folder that holds it, then try again.")
OPENAI_KEY_MISSING = ("Audio transcription needs an OpenAI key. Add it in Settings > API keys, "
                      "or turn transcription off in the Analyze options.")
_WHISPER_API_MAX_BYTES = 24 * 1024 * 1024  # Leave room below the provider's 25 MB upload limit.


def ffmpeg_available() -> bool:
    return app_paths.find_tool("ffmpeg") is not None


def preflight(frames: bool, transcribe: bool, has_openai_key: bool) -> str:
    """The reason an analyze run cannot start on this PC, or ''. Checked before any download."""
    if transcribe and not has_openai_key:
        return OPENAI_KEY_MISSING
    if not ffmpeg_available() and (transcribe or frames):
        return FFMPEG_MISSING
    return ""


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _log(message: str, logger=None):
    app_console.emit('log', 'Video analyzer', details={'message': message})
    if logger:
        try:
            logger(message)
        except Exception:
            pass


class AnalysisStopped(Exception):
    """`should_stop()` turned true: analyze_media / find_or_download quit, killing a running
    ffmpeg / yt-dlp. Partial output of the interrupted step is removed."""


def _check_stop(should_stop):
    if should_stop is not None and should_stop():
        raise AnalysisStopped("Stopped.")


def _kill_tree(proc):
    """End `proc` and its children (yt-dlp runs ffmpeg to merge; its .exe is a two-process launcher)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=app_paths.NO_WINDOW)
    if proc.poll() is None:
        proc.kill()


def _run(command, should_stop=None, check=False, **kw):
    """subprocess.run, except that with `should_stop` the process (tree) is killed as soon as
    `should_stop()` turns true, raising AnalysisStopped. Polled every 0.2 s."""
    if should_stop is None:
        return subprocess.run(command, check=check, creationflags=app_paths.NO_WINDOW, **kw)
    _check_stop(should_stop)
    with subprocess.Popen(command, creationflags=app_paths.NO_WINDOW, **kw) as proc:
        while True:
            try:
                out, err = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if should_stop():
                    _kill_tree(proc)
                    proc.communicate()
                    raise AnalysisStopped("Stopped.")
    if check and proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, command, out, err)
    return subprocess.CompletedProcess(command, proc.returncode, out, err)


def _safe_openai_output(response):
    if response is None:
        return ""
    if isinstance(response, dict):
        if "output_text" in response:
            return str(response.get("output_text", "")).strip()
        output = response.get("output")
        if isinstance(output, list) and output:
            first = output[0]
            if isinstance(first, dict):
                content = first.get("content")
                if isinstance(content, str):
                    return content.strip()
                if isinstance(content, list):
                    for chunk in content:
                        if isinstance(chunk, dict) and "text" in chunk:
                            return str(chunk.get("text", "")).strip()
    else:
        if hasattr(response, "output_text"):
            return str(response.output_text).strip()
        output = getattr(response, "output", None)
        if isinstance(output, list) and output:
            first = output[0]
            content = getattr(first, "content", None)
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                for chunk in content:
                    if hasattr(chunk, "text"):
                        return str(chunk.text).strip()
        if hasattr(response, "text"):
            return str(response.text).strip()
    return ""


def _auto_frame_budget(total: int) -> int:
    """Pick how many frames to send to the vision model automatically — scale with the total but
    cap so cost stays bounded (each frame is ~1-1.5k image tokens)."""
    if total <= 12:
        return total
    if total <= 40:
        return 12
    if total <= 120:
        return 16
    return 20


def resolve_ai_frame_budget(setting, total: int) -> int:
    """Resolve the 'frames to send to AI' setting into a concrete count.
    setting: 'auto' (scale by total), 0/'off' (send none), or an int cap. Always <= total."""
    if total <= 0:
        return 0
    if setting in (0, '0', 'off', 'none', 'Off'):
        return 0
    if setting in (None, '', 'auto', 'Auto'):
        return _auto_frame_budget(total)
    try:
        n = int(setting)
    except (TypeError, ValueError):
        return _auto_frame_budget(total)
    return max(0, min(n, total))


def _sample_evenly(seq, n: int) -> list:
    """Return n items evenly spaced across seq. The FIRST item is always included (the opening
    frame usually carries the title / intro text), and the last is included when n >= 2."""
    seq = list(seq)
    if n <= 0:
        return []
    if n >= len(seq):
        return seq
    if n == 1:
        return [seq[0]]  # always prefer the first (title) frame over the middle
    step = (len(seq) - 1) / (n - 1)
    return [seq[round(i * step)] for i in range(n)]


_IMG_MEDIA = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
              '.webp': 'image/webp', '.gif': 'image/gif', '.bmp': 'image/bmp'}


def _encode_frame(path):
    """Return (media_type, base64_data) for an image file, or None on failure."""
    import base64
    p = Path(path)
    media = _IMG_MEDIA.get(p.suffix.lower(), 'image/jpeg')
    try:
        return media, base64.b64encode(p.read_bytes()).decode()
    except OSError:
        return None


def _build_ai_analysis_prompt(transcript, has_images, video_path=None, post_text=""):
    """Build the analysis prompt. Transcript-first information extraction; when has_images is True
    the model is also shown actual sampled frames and told to read them (on-screen text, art, lists).
    post_text is the platform caption/description for the post, included as extra context."""
    transcript = (transcript or "").strip()
    post_text = (post_text or "").strip()[:3000]  # cap so a huge caption can't dominate the prompt
    has_transcript = len(transcript) >= 15

    inputs = "several frames sampled from a short-form video (as images, in order)" if has_images else ""
    if has_images:
        intro = ("You are an expert content analyst. You are given " + inputs + ", its transcript, "
                 "and the post's own caption/description. Use ALL of them: read the on-screen text, "
                 "captions, lists, diagrams, and visual style in the frames, and combine that with "
                 "the transcript and the caption.")
    else:
        intro = ("You are an expert content analyst. You are given the transcript of a short-form "
                 "video and the post's own caption/description. Use both.")

    lines = [
        intro,
        "",
        "Your job is to EXTRACT THE SUBSTANCE — the real information, not a surface description. "
        "Pull out the main subject, the concrete points, claims, steps, tips, facts, names, tools, "
        "and numbers presented (spoken OR shown on screen), and any actionable advice. Ignore "
        "filler, sponsor reads, hashtags, and 'follow/like/comment' calls to action.",
        "",
        "Write the report in Markdown with exactly these sections and headers:",
        "",
        "### Subject",
        "One or two sentences naming the core topic and what the video is genuinely about.",
        "",
        "### Key information",
        "A bullet list of the important, specific things presented — the substance someone would "
        "want to remember. Be concrete: actual steps, names, numbers, tools. 4-10 bullets.",
        "",
        "### Summary",
        "A 2-4 sentence plain-language takeaway of the main point.",
        "",
        "### How you could use this",
        "2-4 bullets suggesting how this content could be applied or reused (project ideas, "
        "follow-ups, things worth trying or saving).",
        "",
        "### Tags",
        "A single line: 3-6 short topic tags, comma-separated.",
        "",
        "Be specific and substantive. Quote concrete details rather than speaking in generalities. "
        "No preamble, and do not restate these instructions.",
    ]
    if not has_transcript:
        if has_images:
            lines += ["", "NOTE: there is little or no spoken transcript (silent or music-only "
                      "video). Rely on the frames and the caption — read any on-screen "
                      "text/lists/captions and describe what is shown. Do not invent specifics you "
                      "cannot see."]
        elif post_text:
            lines += ["", "NOTE: there is little or no spoken transcript; rely mainly on the "
                      "caption/description below."]
        else:
            lines += ["", "NOTE: there is little or no spoken transcript and no frames were "
                      "provided, so say briefly that the content could not be determined."]
    lines += ["", "---"]
    if post_text:
        lines += ["", "Post caption / description (from the platform):", '"""', post_text, '"""']
    lines += ["", "Transcript:", '"""', transcript or "(no transcript provided)", '"""']
    if video_path:
        lines.append(f"\nSource: {video_path}")
    return "\n".join(lines)


def _analyze_with_ai(frame_paths, transcript, video_path=None, provider: str = "claude", api_key: str = None, model: str = None, logger=None, post_text=""):
    if provider not in {"claude", "openai", "freellmapi"}:
        raise ValueError("Unsupported analysis provider: %s" % provider)
    if not api_key:
        raise ValueError("Analysis API key is required for AI analysis.")

    from core import ai_client
    if not model:
        if provider == "claude":
            model = ai_client.CLAUDE_MODEL
        elif provider == "freellmapi":
            model = "auto"
        else:
            model = ai_client.OPENAI_ANALYSIS_MODEL
    # Encode the sampled frames (skip any that fail to read).
    encoded = [e for e in (_encode_frame(p) for p in (frame_paths or [])) if e]
    has_images = bool(encoded)
    prompt = _build_ai_analysis_prompt(transcript or "", has_images, video_path, post_text)
    _log(f"Starting AI analysis with provider={provider}, model={model}, frames_sent={len(encoded)}", logger)

    # Map the video pipeline's provider vocabulary ('claude'/'openai'/'freellmapi') to
    # the shared dispatch vocabulary ('anthropic'/'openai'/'freellmapi'), then hand off
    # to the one image path.
    if provider == "claude":
        disp_provider = ai_client.ASK_PROVIDER_ANTHROPIC
    elif provider == "freellmapi":
        disp_provider = ai_client.ASK_PROVIDER_FREELLMAPI
    else:
        disp_provider = ai_client.ASK_PROVIDER_OPENAI
    analysis = ai_client.complete_vision(
        disp_provider, model, prompt=prompt, images=encoded, max_tokens=2000,
    )

    if not analysis:
        raise RuntimeError("AI analysis returned no text.")
    _log("AI analysis complete", logger)
    return analysis


def extract_frames(video_path: str, interval: float = 3.0, output_dir: str = None, fmt: str = "jpg", logger=None,
                   should_stop=None):
    """Sample one frame every `interval` seconds into <output_dir>/<stem>_frames/.

    Uses ffmpeg with local-only input protocols. Returns (frame_dir, frame_count)."""
    vp = Path(video_path)
    if not vp.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    if output_dir is None:
        frame_dir = vp.parent / f"{vp.stem}_frames"
    else:
        frame_dir = Path(output_dir) / f"{vp.stem}_frames"
    _ensure_dir(frame_dir)

    try:
        count = _extract_frames_ffmpeg(vp, interval, frame_dir, fmt, logger, should_stop)
        _log(f"Frame extraction complete (ffmpeg): {count} frames saved", logger)
        return str(frame_dir), count
    except Exception as exc:
        # Remove any partial _raw_* files ffmpeg may have left so they don't pollute the gallery.
        for stray in frame_dir.glob("_raw_*"):
            try:
                stray.unlink()
            except OSError:
                pass
        if isinstance(exc, AnalysisStopped):
            raise
        raise RuntimeError("Frame extraction failed. Check FFmpeg and the local video file.") from exc


def _extract_frames_ffmpeg(vp: Path, interval: float, frame_dir: Path, fmt: str, logger=None,
                           should_stop=None) -> int:
    """Extract frames with ffmpeg's fps filter, downscaled to _FRAME_MAX_WIDTH. ffmpeg writes
    sequential frame_%05d files; we rename them to the timestamped contract used elsewhere."""
    rate = 1.0 / interval if interval and interval > 0 else 1.0
    # min(width,iw) so we only ever downscale; -2 keeps aspect ratio with an even height.
    vf = f"fps={rate:.6f},scale='min({_FRAME_MAX_WIDTH},iw)':-2"
    out_pattern = str(frame_dir / f"_raw_%05d.{fmt}")

    command = [app_paths.find_tool("ffmpeg") or "ffmpeg", "-y", "-protocol_whitelist", "file,pipe", "-i", str(vp), "-vf", vf]
    if fmt.lower() in ("jpg", "jpeg"):
        command += ["-q:v", str(_FRAME_JPEG_QUALITY)]
    command += [out_pattern]

    _log(f"Extracting frames with ffmpeg: every {interval:.2f}s (fps={rate:.4f}), max width {_FRAME_MAX_WIDTH}", logger)
    try:
        _run(command, should_stop, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise RuntimeError(FFMPEG_MISSING) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("ffmpeg exited with an error") from exc

    # Rename ffmpeg's sequential output to frame_<idx>_<ts>s.<fmt> (ts ~= idx * interval).
    raw_frames = sorted(frame_dir.glob(f"_raw_*.{fmt}"))
    for c, raw in enumerate(raw_frames):
        timestamp_s = c * interval
        raw.rename(frame_dir / f"frame_{c:05d}_{timestamp_s:08.2f}s.{fmt}")
    return len(raw_frames)


_FRAME_MAX_WIDTH = 720
_FRAME_JPEG_QUALITY = 3   # ffmpeg -q:v for JPEG (2=best … 31=worst)


def extract_audio_compressed(video_path: str, output_dir: str = None, bitrate: str = "64k", logger=None,
                             should_stop=None):
    """Extract audio as a compressed mono 16 kHz MP3 (~0.5 MB/min at 64k).

    Uncompressed 16 kHz WAV is ~1.9 MB/min, so a 20-min video exceeds the transcription API's
    25 MB upload limit; MP3 at 64k handles ~50 min in a single request."""
    vp = Path(video_path)
    output_dir = Path(output_dir) if output_dir else vp.parent
    _ensure_dir(output_dir)

    mp3_file = output_dir / f"{vp.stem}_audio.mp3"
    _log(f"Extracting compressed audio to: {mp3_file}", logger)
    command = [
        app_paths.find_tool("ffmpeg") or "ffmpeg", "-y", "-protocol_whitelist", "file,pipe", "-i", str(vp),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", bitrate,
        str(mp3_file),
    ]
    try:
        _run(command, should_stop, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise RuntimeError(FFMPEG_MISSING) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Failed to extract audio with ffmpeg.") from exc
    except AnalysisStopped:
        mp3_file.unlink(missing_ok=True)
        raise
    if not mp3_file.exists():
        raise RuntimeError("Audio extraction failed: output MP3 file was not created.")
    return str(mp3_file)


def _audio_duration_seconds(path: str):
    """Return audio duration in seconds via ffprobe, or None if unavailable."""
    try:
        out = subprocess.run(
            [app_paths.find_tool("ffprobe") or "ffprobe", "-protocol_whitelist", "file,pipe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=app_paths.NO_WINDOW,
        )
        return float(out.stdout.decode().strip())
    except Exception:
        return None


def _whisper_api_parse(response) -> str:
    """Pull the transcript text out of a file-transcription API response (dict or SDK object)."""
    if isinstance(response, dict):
        return str(response.get("text", "")).strip()
    text = getattr(response, "text", None)
    if text is None:
        text = getattr(response, "data", None)
        if isinstance(text, list) and text:
            text = getattr(text[0], "text", "")
        elif isinstance(text, dict):
            text = text.get("text", "")
        else:
            text = ""
    return str(text).strip()


def _whisper_api_transcribe_file(client, audio_path: str):
    from core import ai_client
    return ai_client.transcribe_file(audio_path, client=client)


def _whisper_api_transcribe(client, audio_path: str, logger=None, should_stop=None) -> str:
    """Transcribe via the OpenAI API, splitting into time chunks when the file exceeds the
    upload limit. Chunks are cut with ffmpeg (stream copy) and transcribed in order. An upload
    in flight is not cut: `should_stop` is checked before each one."""
    path = Path(audio_path)
    size = path.stat().st_size
    if size <= _WHISPER_API_MAX_BYTES:
        return _whisper_api_transcribe_file(client, str(path))

    # Too big — split into N time-based chunks each safely under the limit.
    duration = _audio_duration_seconds(path) or (size / 8000.0)  # 64k mono ≈ 8000 B/s
    n_chunks = int(size // _WHISPER_API_MAX_BYTES) + 1
    seg_seconds = max(60, int(duration / n_chunks * 0.95))
    _log(f"Audio is {size/1024/1024:.1f} MB; splitting into ~{seg_seconds}s chunks for the API", logger)

    chunk_dir = path.parent / f"{path.stem}_chunks"
    _ensure_dir(chunk_dir)
    pattern = str(chunk_dir / "chunk_%03d.mp3")
    try:
        _run(
            [app_paths.find_tool("ffmpeg") or "ffmpeg", "-y", "-protocol_whitelist", "file,pipe", "-i", str(path), "-f", "segment",
             "-segment_time", str(seg_seconds), "-c", "copy", pattern],
            should_stop, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(FFMPEG_MISSING) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Failed to split audio into chunks with ffmpeg.") from exc
    except AnalysisStopped:
        shutil.rmtree(chunk_dir, ignore_errors=True)
        raise

    chunks = sorted(chunk_dir.glob("chunk_*.mp3"))
    if not chunks:
        # Splitting produced nothing — fall back to a single (likely failing) call.
        return _whisper_api_transcribe_file(client, str(path))

    parts = []
    try:
        for i, chunk in enumerate(chunks):
            _check_stop(should_stop)
            _log(f"Transcribing chunk {i+1}/{len(chunks)}", logger)
            try:
                parts.append(_whisper_api_transcribe_file(client, str(chunk)))
            except Exception as exc:
                _log(f"Chunk {i+1} failed: {exc}", logger)
    finally:
        shutil.rmtree(chunk_dir, ignore_errors=True)
    return " ".join(p for p in parts if p).strip()


def transcribe_audio(video_path: str, method: str = "whisper-api", whisper_api_key: str = None, output_dir: str = None, logger=None,
                     should_stop=None):
    _log(f"Transcription method: {method}", logger)
    if method != "whisper-api":
        raise ValueError("Unknown transcription method: %s" % method)
    _log("Using OpenAI file-transcription API", logger)
    if not whisper_api_key:
        raise ValueError(OPENAI_KEY_MISSING)
    from core import ai_client
    try:
        client = ai_client.openai_client(whisper_api_key)
    except ImportError as exc:
        raise RuntimeError("OpenAI transcription is not available in this install. Turn transcription "
                           "off in the Analyze options.") from exc

    # Compressed extraction keeps short videos under the 25 MB limit; long ones are chunked.
    audio_path = extract_audio_compressed(video_path, output_dir=output_dir, logger=logger, should_stop=should_stop)
    _check_stop(should_stop)
    text = _whisper_api_transcribe(client, audio_path, logger=logger, should_stop=should_stop)
    _log("OpenAI transcription complete", logger)
    _log(f"Transcript length: {len(text)} characters", logger)
    return text, "whisper_api"


def audio_duration(path: str):
    """Seconds of audio via ffprobe, or None when ffprobe is missing."""
    return _audio_duration_seconds(path)


def transcribe_long(audio_path: str, logger=None, should_stop=None) -> str:
    """Transcribed text for an audio file of any length (chunked over 24 MB). Uses the OpenAI key from
    core/config.py; the caller has checked it exists."""
    from core import ai_client
    return _whisper_api_transcribe(ai_client.openai_client(), audio_path, logger=logger, should_stop=should_stop)


def analyze_media(
    video_path,
    item_dir,
    *,
    item_id=None,
    url="",
    post_text="",
    frame_interval=3.0,
    transcribe=True,
    transcribe_method="whisper-api",
    analysis_provider="claude",
    analysis_model=None,
    analysis_api_key=None,
    whisper_api_key=None,
    keep_frames=True,
    show_frames_in_canvas=True,
    delete_video=False,
    delete_audio=False,
    max_ai_frames='auto',
    fmt="jpg",
    step=None,
    logger=None,
    should_stop=None,
):
    """The single analysis engine, shared by the card worker, the Video Tools dialog, and the CLI.

    Given an already-located `video_path` and a destination `item_dir`, this extracts frames
    (skipped when `frame_interval` <= 0), transcribes (skipped when `transcribe` is False), runs
    AI analysis (when `analysis_provider` is not 'none'), and writes report.md / analysis.json /
    transcript.txt into `item_dir`. Returns (report_path, transcript, ai_analysis, frame_count).

    `step(msg)` is an optional progress callback (the QThread worker maps it to its step_update
    signal); `logger(msg)` is the plain text logger. `should_stop()` true raises AnalysisStopped
    and no report is written: a running ffmpeg is killed at once; a transcription upload or the AI
    call (HTTP requests) is let finish, and the run stops right after. This function never
    touches Qt or the DB."""
    import shutil
    img_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    item_dir = Path(item_dir)
    item_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = item_dir / "frames"

    def _step(msg):
        if step:
            try:
                step(msg)
            except Exception:
                pass
        _log(msg, logger)

    # 1. Frames (skipped when frame_interval <= 0)
    _check_stop(should_stop)
    frame_count = 0
    if frame_interval and frame_interval > 0:
        frames_dir.mkdir(parents=True, exist_ok=True)
        _step("Extracting frames...")
        raw_frames_dir, _ = extract_frames(str(video_path), interval=frame_interval,
                                           output_dir=str(item_dir), fmt=fmt, logger=logger,
                                           should_stop=should_stop)
        # extract_frames creates <stem>_frames/ inside item_dir — normalise into frames/.
        raw = Path(raw_frames_dir)
        if raw != frames_dir and raw.exists():
            for f in raw.iterdir():
                shutil.move(str(f), str(frames_dir / f.name))
            try:
                raw.rmdir()
            except OSError:
                pass
        frame_count = len([f for f in frames_dir.iterdir() if f.suffix.lower() in img_exts])
        _step(f"Extracted {frame_count} frames.")
    else:
        _step("Frame extraction skipped.")

    # 2. Transcribe (skipped when transcription is off)
    _check_stop(should_stop)
    transcript = ""
    no_transcript = "(no transcript generated)"
    if transcribe:
        _step("Transcribing audio...")
        try:
            transcript, _ = transcribe_audio(str(video_path), method=transcribe_method,
                                             whisper_api_key=whisper_api_key,
                                             output_dir=str(item_dir), logger=logger,
                                             should_stop=should_stop)
        except AnalysisStopped:
            raise
        except Exception as te:
            transcript = ""
            no_transcript = f"(no transcript: {te})"     # shown in the report, not only the log
            _step(f"Transcription skipped: {te}")
    else:
        _step("Transcription skipped.")
    (item_dir / "transcript.txt").write_text(transcript or "", encoding="utf-8")

    # 3. AI analysis — send a sampled subset of the extracted frames to the vision model so it
    #    can read on-screen text / art / lists (crucial for silent or music-only videos).
    _check_stop(should_stop)
    ai_analysis = ""
    if analysis_provider and analysis_provider != "none":
        all_frames = sorted(
            (p for p in frames_dir.iterdir() if p.suffix.lower() in img_exts)
        ) if frames_dir.exists() else []
        budget = resolve_ai_frame_budget(max_ai_frames, len(all_frames))
        selected = _sample_evenly(all_frames, budget)
        sent_note = f" ({len(selected)} of {len(all_frames)} frames)" if selected else ""
        _step(f"Analyzing with {analysis_provider}{sent_note}...")
        try:
            ai_analysis = _analyze_with_ai(selected, transcript or "", video_path=str(video_path),
                                           provider=analysis_provider, api_key=analysis_api_key,
                                           model=analysis_model, logger=logger, post_text=post_text)
        except Exception as ae:
            ai_analysis = ""
            _log(f"AI analysis skipped: {ae}", logger)

    # 4. Write report.md + analysis.json
    _check_stop(should_stop)
    _step("Writing report...")
    label = item_id if item_id is not None else Path(video_path).stem
    report_path = item_dir / "report.md"
    report_path.write_text(
        f"# Analysis — {label}\n\n"
        f"## Analysis\n\n{ai_analysis or '(no AI analysis generated)'}\n\n"
        + (f"## Description\n\n{post_text.strip()}\n\n" if (post_text or '').strip() else "")
        + f"## Transcript\n\n{transcript or no_transcript}\n",
        encoding="utf-8",
    )
    (item_dir / "analysis.json").write_text(
        json.dumps({
            "item_id": item_id,
            "description": post_text or "",
            "video_path": str(video_path),
            "transcript": transcript,
            "ai_analysis": ai_analysis,
            "frame_count": frame_count,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 5. Frame retention / canvas-visibility marker
    if not keep_frames and frames_dir.exists():
        shutil.rmtree(str(frames_dir), ignore_errors=True)
    elif keep_frames and frames_dir.exists():
        marker = frames_dir / ".no_canvas"
        if show_frames_in_canvas:
            if marker.exists():
                try:
                    marker.unlink()
                except OSError:
                    pass
        else:
            try:
                marker.write_text("", encoding="utf-8")
            except OSError:
                pass

    # 6. Optional cleanup of the source media once the report is written.
    if delete_audio:
        audio_exts = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac"}
        for f in item_dir.iterdir():
            if f.is_file() and f.suffix.lower() in audio_exts:
                try:
                    f.unlink()
                except OSError:
                    pass
        _step("Deleted extracted audio.")
    if delete_video:
        vp = Path(video_path)
        try:
            item_dir_r = item_dir.resolve()
            # Only delete a video the app downloaded into this item dir — never a user's local
            # file passed to the Video Tools window (which lives outside item_dir).
            if vp.exists() and item_dir_r in vp.resolve().parents:
                vp.unlink()
                parent = vp.parent
                if parent.resolve() != item_dir_r and not any(parent.iterdir()):
                    parent.rmdir()  # drop the now-empty video/ folder
                _step("Deleted downloaded video.")
        except OSError:
            pass

    return str(report_path), transcript or "", ai_analysis or "", frame_count


VIDEO_EXTS = {'.mp4', '.webm', '.mkv', '.mov', '.avi', '.m4v'}


def find_or_download(item_id: int, url: str, data_dir, cookies_resolver=None, logger=None,
                     download_if_missing: bool = True, cookies_path=None, should_stop=None) -> Path:
    """The item's video: the largest file in data/items/<id>/video/, else downloaded there with
    yt-dlp (per-URL cookies from `cookies_resolver(url)`, else `cookies_path`). Moved from
    VideoAnalysisWorker._find_or_download so the V6 server job uses the same code.
    `should_stop()` true kills a running download, removes its partial files and raises
    AnalysisStopped."""
    video_dir = Path(data_dir) / 'items' / str(item_id) / 'video'
    if video_dir.exists():
        candidates = [f for f in video_dir.iterdir() if f.suffix.lower() in VIDEO_EXTS]
        if candidates:
            return max(candidates, key=lambda f: f.stat().st_size)

    if not download_if_missing or not url:
        raise FileNotFoundError(
            f"No video in data/items/{item_id}/video/ and download_if_missing is False"
        )

    from core.urls import http_url
    if not http_url(url):
        raise ValueError('A valid HTTP(S) URL is required.')
    _check_stop(should_stop)
    video_dir.mkdir(parents=True, exist_ok=True)
    from library import ytdlp
    cmd = [
        ytdlp.find_ytdlp() or 'yt-dlp', '--ignore-config', *ytdlp.runtime_args(), '--newline', '--no-warnings', '--no-playlist',
        '-o', str(video_dir / '%(title).100s.%(ext)s'),
    ]
    from contextlib import nullcontext
    resolved = cookies_resolver(url) if cookies_resolver else cookies_path
    lifetime = resolved if hasattr(resolved, '__enter__') else nullcontext(resolved)
    before = set(video_dir.iterdir())
    deadline = time.monotonic() + 1800
    try:
        with lifetime as cookies:
            if cookies:
                cmd += ['--cookies', str(cookies)]
            cmd += ['--', url]
            _log('Downloading the selected video with yt-dlp', logger)
            from core import site_sessions
            from library.public_http import downloader
            with downloader(cmd, url) as confined:
                result = _run(confined, lambda: (should_stop and should_stop()) or site_sessions.revoked(cookies) or time.monotonic() >= deadline, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0:
                raise ytdlp.DownloadError(ytdlp.failure((result.stderr or '').splitlines()))
    except FileNotFoundError as exc:
        raise RuntimeError(ytdlp.NOT_FOUND) from exc
    except (AnalysisStopped, RuntimeError) as exc:
        # Failed fragments must not masquerade as a complete video on Retry.
        for f in set(video_dir.iterdir()) - before:
            if f.is_file():
                f.unlink(missing_ok=True)
        if isinstance(exc, AnalysisStopped) and time.monotonic() >= deadline and not (should_stop and should_stop()):
            raise ytdlp.DownloadError(ytdlp.failure(['yt-dlp timed out'])) from None
        raise

    candidates = [f for f in video_dir.iterdir() if f.suffix.lower() in VIDEO_EXTS]
    if not candidates:
        raise FileNotFoundError(
            f"yt-dlp ran but no video file produced in {video_dir}"
        )
    return max(candidates, key=lambda f: f.stat().st_size)


def main():
    parser = argparse.ArgumentParser(description="Video Analyzer (frames extraction + audio transcription)")
    parser.add_argument("video", help="Path to video file")
    parser.add_argument("--interval", "-i", type=float, default=3.0, help="Seconds between extracted frames (default: 3.0)")
    parser.add_argument("--out", "-o", default="data/thumbs", help="Output directory for thumbnails, analysis, and frame subfolder")
    parser.add_argument("--format", "-f", default="jpg", choices=["jpg", "jpeg", "png", "bmp", "webp"], help="Image format")
    parser.add_argument("--extract-only", action="store_true", help="Only extract frames, do not run analysis")
    parser.add_argument("--transcribe-method", choices=["whisper-api"], default="whisper-api", help="Audio transcription method")
    parser.add_argument("--whisper-api-key", default=None, help="OpenAI API key for file transcription (legacy flag name)")
    parser.add_argument("--analysis-provider", choices=["none", "claude", "openai", "freellmapi"], default="none", help="AI analysis provider")
    parser.add_argument("--analysis-api-key", default=None, help="Claude/OpenAI API key for analysis")
    parser.add_argument("--analysis-model", default=None, help="AI model to use for analysis")
    parser.add_argument("--ai-frames", default="auto", help="Frames sent to the vision model: 'auto', '0' (off), or a max count (default: auto)")

    args = parser.parse_args()

    # item_dir = <out>/<video-stem>; the same analyze_media engine the GUI uses.
    item_dir = Path(args.out) / Path(args.video).stem
    report_path, transcript, ai_analysis, count = analyze_media(
        args.video,
        item_dir,
        item_id=Path(args.video).stem,
        frame_interval=args.interval,
        transcribe=not args.extract_only,
        transcribe_method=args.transcribe_method,
        analysis_provider=("none" if args.extract_only else args.analysis_provider),
        analysis_api_key=args.analysis_api_key,
        whisper_api_key=args.whisper_api_key,
        max_ai_frames=args.ai_frames,
        fmt=args.format,
        logger=print,
    )
    print(f"Extracted {count} frames into: {item_dir / 'frames'}")
    if not args.extract_only:
        print(f"Report saved to: {report_path}")
        print()
        print("Transcript:")
        print(transcript or "(no transcript generated)")
        print()
        if ai_analysis:
            print("AI analysis:")
            print(ai_analysis)


if __name__ == '__main__':
    main()
