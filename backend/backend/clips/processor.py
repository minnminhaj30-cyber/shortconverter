import math
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import whisper
from django.conf import settings
from django.core.files import File
from django.db import transaction

from .models import VideoClip


_WHISPER_MODEL = None
MAX_SOURCE_DOWNLOAD_BYTES = 500 * 1024 * 1024
TARGET_CLIP_DURATION = 40.0
MIN_CLIP_DURATION = 30.0
MAX_CLIP_DURATION = 45.0
ASPECT_RATIO_DIMENSIONS = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}
SUBTITLE_STYLE_SETTINGS = {
    "classic": (
        "Bold=1,Outline=2,Shadow=1,BorderStyle=1,"
        "BackColour=&H80000000"
    ),
    "bold": (
        "Bold=1,Outline=3,Shadow=2,BorderStyle=1,"
        "BackColour=&H80000000"
    ),
    "boxed": (
        "Bold=1,Outline=1,Shadow=0,BorderStyle=3,"
        "BackColour=&H90000000"
    ),
    "minimal": (
        "Bold=0,Outline=0,Shadow=2,BorderStyle=1,"
        "BackColour=&H80000000"
    ),
    "neon": (
        "Bold=1,Outline=2,Shadow=0,BorderStyle=1,"
        "OutlineColour=&H00FF55FF,BackColour=&H80000000"
    ),
    "highlight": (
        "Bold=1,Outline=0,Shadow=0,BorderStyle=3,"
        "BackColour=&H3000D7FF"
    ),
    "cinema": (
        "FontName=Georgia,Bold=0,Italic=1,Outline=1,Shadow=2,"
        "BorderStyle=1,BackColour=&H80000000"
    ),
    "typewriter": (
        "FontName=Consolas,Bold=0,Outline=1,Shadow=0,"
        "BorderStyle=1,BackColour=&H90000000"
    ),
    "heavy_outline": (
        "Bold=1,Outline=4,Shadow=1,BorderStyle=1,"
        "BackColour=&H80000000"
    ),
    "soft_shadow": (
        "Bold=0,Outline=0,Shadow=4,BorderStyle=1,"
        "BackColour=&H80000000"
    ),
}
SUBTITLE_POSITION_SETTINGS = {
    "bottom": (2, 80),
    "center": (5, 0),
    "top": (8, 80),
}


class VideoDownloadError(ValueError):
    pass


def validate_youtube_url(source_url):
    try:
        parsed = urlsplit(source_url)
        hostname = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise VideoDownloadError(
            "Use a public HTTPS YouTube video link "
            "(youtube.com or youtu.be)."
        ) from exc

    is_youtube_host = (
        hostname == "youtu.be"
        or hostname == "youtube.com"
        or hostname.endswith(".youtube.com")
    )

    if (
        parsed.scheme != "https"
        or not is_youtube_host
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        raise VideoDownloadError(
            "Use a public HTTPS YouTube video link "
            "(youtube.com or youtu.be)."
        )


def describe_youtube_download_error(error):
    message = str(error).strip()
    normalized_message = message.casefold()

    if "this video is not available" in normalized_message:
        return (
            "YouTube reports that this video is unavailable. It may have "
            "been removed, made private, or restricted in your region. "
            "Check the link or upload a video file instead."
        )

    if "private video" in normalized_message:
        return (
            "This YouTube video is private and cannot be downloaded. "
            "Use a public video or upload a video file you can access."
        )

    if (
        "not available in your country" in normalized_message
        or "geo-restricted" in normalized_message
    ):
        return (
            "This YouTube video is unavailable in your region. "
            "Try a video available in your region or upload a video file."
        )

    if (
        "sign in to confirm" in normalized_message
        or "age-restricted" in normalized_message
    ):
        return (
            "This YouTube video requires sign-in or age verification, "
            "which ClipCut does not support. Use a public unrestricted "
            "video or upload a video file."
        )

    if "requested format is not available" in normalized_message:
        return (
            "YouTube did not provide a compatible video format for this "
            "link. Try another public video or upload a video file."
        )

    if message:
        return (
            "YouTube could not provide this video: "
            f"{message[:300]}"
        )

    return (
        "YouTube could not provide this video. Check that the video is "
        "public, available in your region, and not age-restricted."
    )


def download_source_video(source_url, destination_dir):
    validate_youtube_url(source_url)

    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(
            "The video URL downloader is not installed. "
            "Install backend requirements and restart the backend."
        ) from exc

    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(destination_dir / "source.%(ext)s")

    def enforce_download_size(progress):
        if (
            progress.get("status") == "downloading"
            and progress.get("downloaded_bytes", 0)
            > MAX_SOURCE_DOWNLOAD_BYTES
        ):
            raise VideoDownloadError(
                "The downloaded video exceeds the 500 MB limit."
            )

    options = {
        "format": (
            "bestvideo[ext=mp4][height<=1080]+"
            "bestaudio[ext=m4a]/"
            "bestvideo[height<=1080]+bestaudio/"
            "best[height<=1080]/best"
        ),
        "js_runtimes": {"node": {}},
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "noplaylist": True,
        "max_filesize": MAX_SOURCE_DOWNLOAD_BYTES,
        "socket_timeout": 30,
        "retries": 2,
        "no_warnings": True,
        "quiet": True,
        "progress_hooks": [enforce_download_size],
    }

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(
                source_url,
                download=True,
            )
            if not info or info.get("_type") == "playlist":
                raise VideoDownloadError(
                    "Paste a link to one public video, not a playlist."
                )

            expected_path = Path(downloader.prepare_filename(info))

        downloaded_path = expected_path
        if not downloaded_path.is_file():
            candidates = [
                path
                for path in destination_dir.glob("source.*")
                if path.suffix.lower() in {
                    ".mp4",
                    ".mov",
                    ".mkv",
                    ".webm",
                }
            ]
            if len(candidates) != 1:
                raise VideoDownloadError(
                    "The YouTube video did not download in a supported format."
                )
            downloaded_path = candidates[0]

        if downloaded_path.stat().st_size > MAX_SOURCE_DOWNLOAD_BYTES:
            downloaded_path.unlink(missing_ok=True)
            raise VideoDownloadError(
                "The downloaded video exceeds the 500 MB limit."
            )

        return downloaded_path, str(info.get("title") or "").strip()
    except VideoDownloadError:
        raise
    except yt_dlp.utils.DownloadError as exc:
        raise VideoDownloadError(
            describe_youtube_download_error(exc)
        ) from exc


def get_ffmpeg_path():
    ffmpeg_path = shutil.which("ffmpeg")

    if ffmpeg_path is None:
        raise RuntimeError(
            "FFmpeg was not found. Install FFmpeg and add it to PATH."
        )

    return ffmpeg_path


def get_whisper_model():
    global _WHISPER_MODEL

    if _WHISPER_MODEL is None:
        model_name = getattr(
            settings,
            "WHISPER_MODEL",
            "base",
        )
        _WHISPER_MODEL = whisper.load_model(model_name)

    return _WHISPER_MODEL


def get_video_duration(video_path):
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path is None:
        raise RuntimeError(
            "FFprobe was not found. Install FFmpeg and add it to PATH."
        )

    result = subprocess.run(
        [
            ffprobe_path,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Unable to read video duration. "
            f"{result.stderr[-2000:]}"
        )

    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(
            "FFprobe returned an invalid video duration."
        ) from exc

    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("The video has no valid duration.")

    return duration


def run_ffmpeg(command):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=None,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "FFmpeg was not found. Install FFmpeg and add it to PATH."
        ) from exc

    if result.returncode != 0:
        message = result.stderr[-5000:] if result.stderr else ""
        raise RuntimeError(
            f"FFmpeg failed with exit code {result.returncode}.\n"
            f"{message}"
        )

    return result


def timestamp_srt(seconds):
    milliseconds = max(0, int(round(seconds * 1000)))

    hours = milliseconds // 3_600_000
    milliseconds %= 3_600_000

    minutes = milliseconds // 60_000
    milliseconds %= 60_000

    secs = milliseconds // 1000
    milliseconds %= 1000

    return (
        f"{hours:02}:{minutes:02}:{secs:02},"
        f"{milliseconds:03}"
    )


def write_srt(segments, clip_start, clip_end, destination):
    lines = []
    index = 1

    for segment in segments:
        start = max(
            float(segment["start"]),
            float(clip_start),
        )
        end = min(
            float(segment["end"]),
            float(clip_end),
        )

        if end <= start:
            continue

        # Subtitle timestamps must be relative to the clip.
        relative_start = start - clip_start
        relative_end = end - clip_start

        text = str(segment.get("text", "")).strip()

        if not text:
            continue

        lines.extend([
            str(index),
            (
                f"{timestamp_srt(relative_start)} --> "
                f"{timestamp_srt(relative_end)}"
            ),
            text,
            "",
        ])

        index += 1

    destination.write_text(
        "\n".join(lines),
        encoding="utf-8-sig",
    )


def score_window(segments, start, end):
    selected = [
        segment
        for segment in segments
        if segment["end"] > start
        and segment["start"] < end
    ]

    if not selected:
        return 0.0, ""

    text = " ".join(
        segment.get("text", "").strip()
        for segment in selected
    ).strip()

    words = re.findall(r"\w+", text, flags=re.UNICODE)

    # Basic heuristic, not a trained viral-content model.
    duration = max(end - start, 1)
    speech_density = len(words) / duration

    punctuation_bonus = sum(
        text.count(mark)
        for mark in ("!", "?", "।")
    )
    cue_words = {
        "actually",
        "because",
        "best",
        "discover",
        "finally",
        "how",
        "important",
        "imagine",
        "lesson",
        "mistake",
        "never",
        "remember",
        "secret",
        "surprising",
        "tip",
        "truth",
        "why",
        "worst",
    }
    cue_bonus = sum(word.casefold() in cue_words for word in words)

    score = (
        min(len(words), 150) * 0.5
        + min(speech_density, 4) * 5
        + min(punctuation_bonus, 5) * 1.5
        + min(cue_bonus, 8) * 1.25
    )

    return score, text


def find_highlights(segments, video_duration, max_clips=5):
    if not math.isfinite(video_duration) or video_duration <= 0:
        return []

    if max_clips <= 0:
        return []

    if video_duration < MIN_CLIP_DURATION:
        score, text = score_window(
            segments,
            0,
            video_duration,
        )

        if text:
            return [{
                "start": 0.0,
                "end": float(video_duration),
                "score": score,
                "text": text,
            }]

        return []

    window_size = min(TARGET_CLIP_DURATION, video_duration)
    last_start = video_duration - window_size
    step = 5.0

    candidates = []
    start = 0.0

    while start <= last_start:
        end = start + window_size
        score, text = score_window(
            segments,
            start,
            end,
        )

        if text:
            candidates.append({
                "start": float(start),
                "end": float(end),
                "score": float(score),
                "text": text,
            })

        start += step

    if not candidates or candidates[-1]["start"] < last_start:
        score, text = score_window(
            segments,
            last_start,
            video_duration,
        )
        if text:
            candidates.append({
                "start": float(last_start),
                "end": float(video_duration),
                "score": float(score),
                "text": text,
            })

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    chosen = []

    for candidate in candidates:
        overlaps = any(
            candidate["start"] < item["end"]
            and candidate["end"] > item["start"]
            for item in chosen
        )

        if overlaps:
            continue

        chosen.append(candidate)

        if len(chosen) >= max_clips:
            break

    chosen.sort(key=lambda item: item["start"])

    return chosen


def safe_subtitle_path(path):
    # FFmpeg filter syntax needs special handling for paths.
    return (
        str(Path(path).resolve())
        .replace("\\", "/")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
    )


def render_video(
    source_path,
    clip_start,
    clip_end,
    subtitle_path,
    output_path,
    font_size=20,
    text_color="#FFFFFF",
    aspect_ratio="9:16",
    subtitle_style="classic",
    subtitle_position="bottom",
    include_subtitles=True,
    ffmpeg_path=None,
):
    font_size = int(font_size)

    if not 12 <= font_size <= 36:
        raise ValueError("Font size must be between 12 and 36.")

    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", text_color):
        raise ValueError("Invalid subtitle color.")

    if aspect_ratio not in ASPECT_RATIO_DIMENSIONS:
        raise ValueError("Unsupported video aspect ratio.")

    if subtitle_style not in SUBTITLE_STYLE_SETTINGS:
        raise ValueError("Unsupported subtitle style.")

    if subtitle_position not in SUBTITLE_POSITION_SETTINGS:
        raise ValueError("Unsupported subtitle position.")

    width, height = ASPECT_RATIO_DIMENSIONS[aspect_ratio]
    red = text_color[1:3]
    green = text_color[3:5]
    blue = text_color[5:7]

    # ASS uses alpha-blue-green-red colour order.
    ass_color = f"&H00{blue}{green}{red}"

    video_filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1",
    ]

    if include_subtitles and Path(subtitle_path).read_text(
        encoding="utf-8-sig"
    ).strip():
        escaped_subtitles = safe_subtitle_path(subtitle_path)
        alignment, margin = SUBTITLE_POSITION_SETTINGS[
            subtitle_position
        ]
        video_filters.append(
            f"subtitles='{escaped_subtitles}':"
            "force_style='"
            "FontName=Arial,"
            f"FontSize={font_size},"
            f"PrimaryColour={ass_color},"
            "OutlineColour=&H00000000,"
            f"{SUBTITLE_STYLE_SETTINGS[subtitle_style]},"
            f"Alignment={alignment},MarginV={margin}"
            "'"
        )
    video_filter = ",".join(video_filters)

    run_ffmpeg([
        ffmpeg_path or get_ffmpeg_path(),
        "-y",
        "-ss", str(clip_start),
        "-i", str(source_path),
        "-t", str(clip_end - clip_start),
        "-vf", video_filter,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ])


def transcribe_video(job):
    if not job.source_file:
        raise ValueError("Upload a source video before processing.")

    model = get_whisper_model()

    result = model.transcribe(
        job.source_file.path,
        language=None,
        task="translate",
        verbose=False,
    )

    segments = result.get("segments", [])
    duration = float(result.get("duration") or 0)

    if duration <= 0 and segments:
        duration = max(
            float(segment["end"])
            for segment in segments
        )
    elif duration <= 0:
        duration = get_video_duration(job.source_file.path)

    return segments, duration


def find_video_only_segments(video_duration, max_clips=5):
    if not math.isfinite(video_duration) or video_duration <= 0:
        return []

    if max_clips <= 0:
        return []

    clip_count = min(
        max_clips,
        max(1, int(video_duration // MIN_CLIP_DURATION)),
    )
    clip_duration = min(
        MAX_CLIP_DURATION,
        video_duration / clip_count,
    )
    last_start = video_duration - clip_duration

    if clip_count == 1:
        starts = [0.0]
    else:
        starts = [
            last_start * index / (clip_count - 1)
            for index in range(clip_count)
        ]

    return [
        {
            "start": float(start),
            "end": float(min(start + clip_duration, video_duration)),
            "score": 0.0,
            "text": "",
        }
        for start in starts
    ]


def process_job(job):
    if not job.source_file:
        raise ValueError("This project has no uploaded video file.")

    ffmpeg_path = get_ffmpeg_path()
    old_clips = list(job.clips.all())

    work_dir = (
        Path(settings.MEDIA_ROOT)
        / "work"
        / str(job.id)
        / uuid.uuid4().hex
    )

    work_dir.mkdir(parents=True, exist_ok=True)

    created_clips = []

    try:
        segments, duration = transcribe_video(job)

        has_speech = bool(segments)
        if has_speech:
            highlights = find_highlights(
                segments,
                duration,
                max_clips=5,
            )
        else:
            highlights = find_video_only_segments(
                duration,
                max_clips=5,
            )

        if not highlights:
            if has_speech:
                raise ValueError(
                    "No usable highlight segments were found."
                )
            raise ValueError(
                "No speech was detected and the video duration "
                "could not be used to create clips."
            )

        for index, highlight in enumerate(highlights, start=1):
            start = highlight["start"]
            end = highlight["end"]

            subtitle_path = work_dir / f"clip_{index}.srt"
            output_path = work_dir / f"clip_{index}.mp4"

            if job.include_subtitles:
                write_srt(
                    segments,
                    start,
                    end,
                    subtitle_path,
                )

            render_video(
                source_path=job.source_file.path,
                clip_start=start,
                clip_end=end,
                subtitle_path=subtitle_path,
                output_path=output_path,
                font_size=job.subtitle_font_size,
                text_color=job.subtitle_color,
                aspect_ratio=job.aspect_ratio,
                subtitle_style=job.subtitle_style,
                subtitle_position=job.subtitle_position,
                include_subtitles=job.include_subtitles,
                ffmpeg_path=ffmpeg_path,
            )

            clip = VideoClip.objects.create(
                job=job,
                title=(
                    f"Highlight {index}"
                    if has_speech
                    else f"Clip {index}"
                ),
                start_time=start,
                end_time=end,
                transcript=highlight["text"],
            )

            try:
                with output_path.open("rb") as video:
                    clip.video_file.save(
                        f"job_{job.id}_clip_{index}.mp4",
                        File(video),
                        save=True,
                    )
            except Exception:
                if clip.video_file:
                    clip.video_file.delete(save=False)
                clip.delete()
                raise

            created_clips.append(clip)

        with transaction.atomic():
            VideoClip.objects.filter(
                pk__in=[clip.pk for clip in old_clips]
            ).delete()

    except Exception:
        for clip in created_clips:
            if clip.video_file:
                clip.video_file.delete(save=False)
            clip.delete()

        raise
    finally:
        # Remove temporary SRT/MP4 work files.
        # Saved output files live in MEDIA_ROOT/generated_clips.
        shutil.rmtree(work_dir, ignore_errors=True)

    for clip in old_clips:
        if clip.video_file:
            clip.video_file.delete(save=False)

    return created_clips


def rerender_clip(
    clip,
    font_size=None,
    text_color=None,
    aspect_ratio=None,
    subtitle_style=None,
    subtitle_position=None,
    include_subtitles=None,
):
    if not clip.job.source_file:
        raise ValueError("Original source video is missing.")

    font_size = (
        clip.job.subtitle_font_size
        if font_size is None
        else int(font_size)
    )
    text_color = (
        clip.job.subtitle_color
        if text_color is None
        else text_color
    )
    aspect_ratio = (
        clip.job.aspect_ratio
        if aspect_ratio is None
        else aspect_ratio
    )
    subtitle_style = (
        clip.job.subtitle_style
        if subtitle_style is None
        else subtitle_style
    )
    subtitle_position = (
        clip.job.subtitle_position
        if subtitle_position is None
        else subtitle_position
    )
    include_subtitles = (
        clip.job.include_subtitles
        if include_subtitles is None
        else include_subtitles
    )

    if not 12 <= font_size <= 36:
        raise ValueError("Font size must be between 12 and 36.")

    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", text_color):
        raise ValueError("Invalid subtitle color.")

    if aspect_ratio not in ASPECT_RATIO_DIMENSIONS:
        raise ValueError("Unsupported video aspect ratio.")

    if subtitle_style not in SUBTITLE_STYLE_SETTINGS:
        raise ValueError("Unsupported subtitle style.")

    if subtitle_position not in SUBTITLE_POSITION_SETTINGS:
        raise ValueError("Unsupported subtitle position.")

    ffmpeg_path = get_ffmpeg_path()

    work_dir = (
        Path(settings.MEDIA_ROOT)
        / "work"
        / str(clip.job_id)
        / uuid.uuid4().hex
    )

    work_dir.mkdir(parents=True, exist_ok=True)

    subtitle_path = work_dir / "edited.srt"
    output_path = work_dir / "edited.mp4"

    try:
        if include_subtitles:
            segments, _ = transcribe_video(clip.job)
            write_srt(
                segments,
                clip.start_time,
                clip.end_time,
                subtitle_path,
            )

        render_video(
            source_path=clip.job.source_file.path,
            clip_start=clip.start_time,
            clip_end=clip.end_time,
            subtitle_path=subtitle_path,
            output_path=output_path,
            font_size=font_size,
            text_color=text_color,
            aspect_ratio=aspect_ratio,
            subtitle_style=subtitle_style,
            subtitle_position=subtitle_position,
            include_subtitles=include_subtitles,
            ffmpeg_path=ffmpeg_path,
        )

        old_name = clip.video_file.name if clip.video_file else None

        with output_path.open("rb") as video:
            clip.video_file.save(
                f"job_{clip.job_id}_clip_{clip.id}_edited.mp4",
                File(video),
                save=False,
            )

        clip.save()

        if old_name:
            storage = clip.video_file.storage

            if storage.exists(old_name):
                storage.delete(old_name)

        return clip

    finally:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
