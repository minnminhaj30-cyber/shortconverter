from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from .models import VideoClip, VideoJob
from .processor import (
    SUBTITLE_STYLE_SETTINGS,
    VideoDownloadError,
    describe_youtube_download_error,
    download_source_video,
    find_video_only_segments,
    find_highlights,
    process_job,
    render_video,
    rerender_clip,
    transcribe_video,
    validate_youtube_url,
    write_srt,
)


class YouTubeUrlValidationTests(SimpleTestCase):
    def test_accepts_supported_https_youtube_hosts(self):
        for source_url in (
            "https://youtube.com/watch?v=video-id",
            "https://www.youtube.com/shorts/video-id",
            "https://youtu.be/video-id",
        ):
            with self.subTest(source_url=source_url):
                validate_youtube_url(source_url)

    def test_rejects_non_youtube_and_malformed_urls(self):
        for source_url in (
            "http://youtube.com/watch?v=video-id",
            "https://example.com/video",
            "https://youtube.com:invalid/watch?v=video-id",
            "https://user:password@youtube.com/watch?v=video-id",
        ):
            with self.subTest(source_url=source_url):
                with self.assertRaises(VideoDownloadError):
                    validate_youtube_url(source_url)


class YouTubeDownloadTests(SimpleTestCase):
    def test_unavailable_video_error_is_specific_and_actionable(self):
        message = describe_youtube_download_error(
            "[youtube] video-id: This video is not available"
        )

        self.assertIn("YouTube reports that this video is unavailable", message)
        self.assertIn("upload a video file", message)
        self.assertNotIn("permission to process", message)

    def test_unknown_download_error_includes_short_provider_reason(self):
        message = describe_youtube_download_error(
            "Temporary network failure"
        )

        self.assertIn("YouTube could not provide this video", message)
        self.assertIn("Temporary network failure", message)

    def test_uses_downloaded_extension_when_prepared_path_differs(self):
        with tempfile.TemporaryDirectory() as download_root:
            downloaded_path = Path(download_root) / "source.webm"
            downloaded_path.write_bytes(b"downloaded video")

            with patch("yt_dlp.YoutubeDL") as youtube_dl:
                downloader = (
                    youtube_dl.return_value.__enter__.return_value
                )
                downloader.extract_info.return_value = {
                    "ext": "mp4",
                    "title": "Fetched title",
                }
                downloader.prepare_filename.return_value = str(
                    Path(download_root) / "source.mp4"
                )

                result_path, title = download_source_video(
                    "https://youtu.be/video-id",
                    download_root,
                )

            self.assertEqual(result_path, downloaded_path)
            self.assertEqual(title, "Fetched title")
            options = youtube_dl.call_args.args[0]
            self.assertTrue(options["noplaylist"])
            self.assertIn("bestvideo", options["format"])
            self.assertIn("+bestaudio", options["format"])
            self.assertEqual(options["js_runtimes"], {"node": {}})
            self.assertEqual(options["merge_output_format"], "mp4")
            self.assertEqual(
                options["max_filesize"],
                500 * 1024 * 1024,
            )


class ProcessJobTests(SimpleTestCase):
    def test_missing_ffmpeg_fails_before_loading_whisper(self):
        job = SimpleNamespace(source_file=object())

        with (
            patch("clips.processor.shutil.which", return_value=None),
            patch("clips.processor.get_whisper_model") as get_whisper_model,
        ):
            with self.assertRaisesRegex(RuntimeError, "FFmpeg was not found"):
                process_job(job)

        get_whisper_model.assert_not_called()

    def test_short_video_with_speech_produces_a_single_highlight(self):
        segments = [{
            "start": 0,
            "end": 42,
            "text": "A useful explanation with a clear conclusion.",
        }]

        highlights = find_highlights(segments, video_duration=42)

        self.assertEqual(len(highlights), 1)
        self.assertEqual(highlights[0]["start"], 0)
        self.assertEqual(highlights[0]["end"], 40)
        self.assertGreaterEqual(
            highlights[0]["end"] - highlights[0]["start"],
            30,
        )
        self.assertIn("clear conclusion", highlights[0]["text"])

    def test_selects_the_highest_scoring_moment_in_a_40_second_clip(self):
        segments = [
            {
                "start": start,
                "end": start + 5,
                "text": "steady update",
            }
            for start in range(0, 180, 5)
        ]
        segments.extend(
            {
                "start": start,
                "end": start + 5,
                "text": (
                    "The surprising truth is this important lesson! "
                    "Here is how you can discover the best result?"
                ),
            }
            for start in range(80, 120, 5)
        )

        highlights = find_highlights(
            segments,
            video_duration=180,
            max_clips=1,
        )

        self.assertEqual(len(highlights), 1)
        duration = highlights[0]["end"] - highlights[0]["start"]
        self.assertGreaterEqual(duration, 30)
        self.assertLessEqual(duration, 45)
        self.assertLessEqual(highlights[0]["start"], 80)
        self.assertGreaterEqual(highlights[0]["end"], 120)
        self.assertIn("surprising truth", highlights[0]["text"])

    def test_speech_highlight_duration_is_bounded_for_long_videos(self):
        segments = [
            {
                "start": start,
                "end": start + 5,
                "text": "This useful point explains how the important idea works!",
            }
            for start in range(0, 240, 5)
        ]

        highlights = find_highlights(segments, video_duration=240)

        self.assertTrue(highlights)
        for highlight in highlights:
            with self.subTest(highlight=highlight):
                duration = highlight["end"] - highlight["start"]
                self.assertGreaterEqual(duration, 30)
                self.assertLessEqual(duration, 45)

    def test_video_without_speech_gets_spread_out_clips(self):
        clips = find_video_only_segments(173.0)

        self.assertEqual(len(clips), 5)
        self.assertEqual(clips[0]["start"], 0)
        self.assertAlmostEqual(clips[0]["end"], 34.6)
        self.assertAlmostEqual(clips[-1]["end"], 173.0)
        self.assertTrue(all(not clip["text"] for clip in clips))
        for clip in clips:
            with self.subTest(clip=clip):
                duration = clip["end"] - clip["start"]
                self.assertGreaterEqual(duration, 30)
                self.assertLessEqual(duration, 45)

    def test_short_video_without_speech_uses_one_clip(self):
        clips = find_video_only_segments(42.0)

        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["start"], 0)
        self.assertEqual(clips[0]["end"], 42.0)

    def test_invalid_video_duration_does_not_create_clips(self):
        self.assertEqual(find_video_only_segments(0), [])
        self.assertEqual(find_video_only_segments(float("nan")), [])

    def test_transcription_reads_duration_when_whisper_returns_no_segments(self):
        job = SimpleNamespace(
            source_file=SimpleNamespace(path="source.mp4"),
            language="ml",
        )
        model = SimpleNamespace(
            transcribe=Mock(
                return_value={
                    "segments": [],
                    "text": "",
                },
            )
        )

        with (
            patch("clips.processor.get_whisper_model", return_value=model),
            patch(
                "clips.processor.get_video_duration",
                return_value=173.0,
            ) as get_duration,
        ):
            segments, duration = transcribe_video(job)

        self.assertEqual(segments, [])
        self.assertEqual(duration, 173.0)
        get_duration.assert_called_once_with("source.mp4")
        model.transcribe.assert_called_once_with(
            "source.mp4",
            language=None,
            task="translate",
            verbose=False,
        )

    def test_video_without_speech_skips_subtitle_filter(self):
        with tempfile.TemporaryDirectory() as work_dir:
            subtitle_path = Path(work_dir) / "empty.srt"
            write_srt([], 0, 30, subtitle_path)
            self.assertEqual(subtitle_path.read_bytes(), b"\xef\xbb\xbf")

            with patch("clips.processor.run_ffmpeg") as run_ffmpeg:
                render_video(
                    source_path="source.mp4",
                    clip_start=0,
                    clip_end=30,
                    subtitle_path=subtitle_path,
                    output_path="clip.mp4",
                    ffmpeg_path="ffmpeg",
                )

            command = run_ffmpeg.call_args.args[0]
            video_filter = command[command.index("-vf") + 1]
            self.assertNotIn("subtitles=", video_filter)
            self.assertIn("scale=1080:1920", video_filter)

    def test_video_ratio_and_subtitle_preset_are_applied_to_ffmpeg(self):
        with tempfile.TemporaryDirectory() as work_dir:
            subtitle_path = Path(work_dir) / "caption.srt"
            write_srt(
                [{"start": 0, "end": 5, "text": "Test caption"}],
                0,
                5,
                subtitle_path,
            )

            for ratio, dimensions in (
                ("9:16", "1080:1920"),
                ("1:1", "1080:1080"),
                ("16:9", "1920:1080"),
            ):
                with self.subTest(ratio=ratio):
                    with patch("clips.processor.run_ffmpeg") as run_ffmpeg:
                        render_video(
                            source_path="source.mp4",
                            clip_start=0,
                            clip_end=5,
                            subtitle_path=subtitle_path,
                            output_path="clip.mp4",
                            aspect_ratio=ratio,
                            subtitle_style="boxed",
                            subtitle_position="top",
                        )

                    command = run_ffmpeg.call_args.args[0]
                    video_filter = command[command.index("-vf") + 1]
                    self.assertIn(f"scale={dimensions}", video_filter)
                    self.assertIn(f"crop={dimensions},setsar=1", video_filter)
                    self.assertIn("BorderStyle=3", video_filter)
                    self.assertIn("Alignment=8", video_filter)

    def test_every_subtitle_preset_is_supported_by_video_renderer(self):
        self.assertEqual(
            set(SUBTITLE_STYLE_SETTINGS),
            {choice[0] for choice in VideoJob.SUBTITLE_STYLE_CHOICES},
        )

        with tempfile.TemporaryDirectory() as work_dir:
            subtitle_path = Path(work_dir) / "caption.srt"
            write_srt(
                [{"start": 0, "end": 5, "text": "Test caption"}],
                0,
                5,
                subtitle_path,
            )

            for style in SUBTITLE_STYLE_SETTINGS:
                with self.subTest(style=style):
                    with patch("clips.processor.run_ffmpeg") as run_ffmpeg:
                        render_video(
                            source_path="source.mp4",
                            clip_start=0,
                            clip_end=5,
                            subtitle_path=subtitle_path,
                            output_path="clip.mp4",
                            subtitle_style=style,
                        )

                    video_filter = run_ffmpeg.call_args.args[0][
                        run_ffmpeg.call_args.args[0].index("-vf") + 1
                    ]
                    self.assertIn("subtitles=", video_filter)
                    for style_setting in SUBTITLE_STYLE_SETTINGS[style].split(","):
                        self.assertIn(style_setting, video_filter)

    def test_video_renderer_omits_subtitle_filter_when_disabled(self):
        with tempfile.TemporaryDirectory() as work_dir:
            subtitle_path = Path(work_dir) / "caption.srt"
            write_srt(
                [{"start": 0, "end": 5, "text": "Test caption"}],
                0,
                5,
                subtitle_path,
            )

            with patch("clips.processor.run_ffmpeg") as run_ffmpeg:
                render_video(
                    source_path="source.mp4",
                    clip_start=0,
                    clip_end=5,
                    subtitle_path=subtitle_path,
                    output_path="clip.mp4",
                    include_subtitles=False,
                )

            command = run_ffmpeg.call_args.args[0]
            video_filter = command[command.index("-vf") + 1]
            self.assertNotIn("subtitles=", video_filter)
            self.assertIn("scale=1080:1920", video_filter)
            self.assertIn("setsar=1", video_filter)


class JobUploadTests(TestCase):
    def test_source_file_upload_is_saved_and_returned(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    "/api/jobs/",
                    {
                        "title": "Sample project",
                        "language": "ml",
                        "source_file": SimpleUploadedFile(
                            "sample.mp4",
                            b"video data",
                            content_type="video/mp4",
                        ),
                    },
                )

                self.assertEqual(response.status_code, 201, response.content)
                job = VideoJob.objects.get(title="Sample project")
                self.assertTrue(
                    job.source_file.name.startswith("source_videos/")
                )
                self.assertTrue(Path(job.source_file.path).is_file())
                self.assertEqual(
                    response.json()["job"]["source_file_url"],
                    f"http://testserver{job.source_file.url}",
                )
                self.assertEqual(job.language, "auto")
                self.assertTrue(job.include_subtitles)

                job.source_file.delete(save=False)

    def test_project_creation_persists_video_and_subtitle_settings(self):
        response = self.client.post(
            "/api/jobs/",
            {
                "title": "Custom style project",
                "source_url": "https://youtu.be/video-id",
                "language": "ml",
                "aspect_ratio": "1:1",
                "subtitle_style": "boxed",
                "include_subtitles": "false",
                "subtitle_position": "top",
                "subtitle_font_size": "28",
                "subtitle_color": "#FFD700",
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        job = VideoJob.objects.get(title="Custom style project")
        self.assertEqual(job.aspect_ratio, "1:1")
        self.assertEqual(job.subtitle_style, "boxed")
        self.assertFalse(job.include_subtitles)
        self.assertEqual(job.subtitle_position, "top")
        self.assertEqual(job.subtitle_font_size, 28)
        self.assertEqual(job.subtitle_color, "#FFD700")
        self.assertEqual(job.language, "auto")
        self.assertEqual(response.json()["job"]["aspect_ratio"], "1:1")
        self.assertFalse(response.json()["job"]["include_subtitles"])

    def test_project_creation_rejects_invalid_ratio_and_subtitle_options(self):
        for field, value in (
            ("aspect_ratio", "4:3"),
            ("subtitle_style", "comic"),
            ("subtitle_position", "left"),
            ("include_subtitles", "maybe"),
            ("subtitle_font_size", "50"),
            ("subtitle_color", "not-a-color"),
        ):
            with self.subTest(field=field):
                response = self.client.post(
                    "/api/jobs/",
                    {
                        "title": "Invalid setting",
                        "source_url": "https://youtu.be/video-id",
                        field: value,
                    },
                )
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(field, response.json()["fields"])

    def test_invalid_source_url_returns_a_useful_validation_error(self):
        response = self.client.post(
            "/api/jobs/",
            {
                "title": "Bad URL project",
                "language": "en",
                "source_url": "not-a-url",
            },
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("error", response.json())
        self.assertIn("source_url", response.json()["fields"])

    def test_youtube_url_project_downloads_source_and_processes(self):
        with tempfile.TemporaryDirectory() as media_root:
            with tempfile.TemporaryDirectory() as download_root:
                with override_settings(MEDIA_ROOT=media_root):
                    job = VideoJob.objects.create(
                        title="Untitled project",
                        source_url="https://youtu.be/video-id",
                    )
                    downloaded_path = Path(download_root) / "source.mp4"
                    downloaded_path.write_bytes(b"downloaded video")

                    with (
                        patch(
                            "clips.views.download_source_video",
                            return_value=(downloaded_path, "Fetched title"),
                        ) as download_source,
                        patch(
                            "clips.views.process_job",
                            return_value=[],
                        ) as process,
                    ):
                        response = self.client.post(
                            f"/api/jobs/{job.id}/process/",
                        )

                    self.assertEqual(response.status_code, 200, response.content)
                    download_source.assert_called_once()
                    self.assertEqual(
                        download_source.call_args.args[0],
                        job.source_url,
                    )
                    process.assert_called_once()

                    job.refresh_from_db()
                    self.assertEqual(job.status, "completed")
                    self.assertEqual(job.title, "Fetched title")
                    self.assertEqual(
                        Path(job.source_file.path).read_bytes(),
                        b"downloaded video",
                    )
                    self.assertEqual(
                        list((Path(media_root) / "work").iterdir()),
                        [],
                    )

                    job.source_file.delete(save=False)

    def test_invalid_youtube_port_is_rejected_without_network_access(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = VideoJob.objects.create(
                    title="Malformed URL project",
                    source_url="https://youtube.com:invalid/video-id",
                )

                response = self.client.post(
                    f"/api/jobs/{job.id}/process/",
                )

                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(
                    "public HTTPS YouTube",
                    response.json()["error"],
                )
                job.refresh_from_db()
                self.assertEqual(job.status, "failed")

    def test_failed_youtube_download_is_reported_and_saved(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = VideoJob.objects.create(
                    title="Unavailable video",
                    source_url="https://youtu.be/video-id",
                )

                with (
                    patch(
                        "clips.views.download_source_video",
                        side_effect=VideoDownloadError(
                            "Could not download this YouTube video."
                        ),
                    ),
                    patch("clips.views.process_job") as process,
                ):
                    response = self.client.post(
                        f"/api/jobs/{job.id}/process/",
                    )

                self.assertEqual(response.status_code, 400, response.content)
                process.assert_not_called()
                job.refresh_from_db()
                self.assertEqual(job.status, "failed")
                self.assertIn("Could not download", job.error_message)
                self.assertFalse(job.source_file)

    def test_processing_failure_is_saved_on_the_project(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = VideoJob.objects.create(title="Failed project")
                job.source_file.save(
                    "source.mp4",
                    ContentFile(b"video data"),
                    save=True,
                )

                with patch(
                    "clips.views.process_job",
                    side_effect=RuntimeError("Transcription failed"),
                ):
                    response = self.client.post(
                        f"/api/jobs/{job.id}/process/",
                    )

                self.assertEqual(response.status_code, 500)
                self.assertEqual(
                    response.json()["job"]["status"],
                    "failed",
                )
                self.assertIn(
                    "Transcription failed",
                    response.json()["job"]["error_message"],
                )

                job.source_file.delete(save=False)

    def test_successful_processing_marks_the_project_completed(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = VideoJob.objects.create(title="Completed project")
                job.source_file.save(
                    "source.mp4",
                    ContentFile(b"video data"),
                    save=True,
                )

                with patch("clips.views.process_job", return_value=[]):
                    response = self.client.post(
                        f"/api/jobs/{job.id}/process/",
                    )

                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(
                    response.json()["job"]["status"],
                    "completed",
                )

                job.source_file.delete(save=False)

    def test_failed_clip_render_options_return_a_validation_error(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = VideoJob.objects.create(title="Render project")
                job.source_file.save(
                    "source.mp4",
                    ContentFile(b"video data"),
                    save=True,
                )
                clip = VideoClip.objects.create(
                    job=job,
                    title="Highlight 1",
                    start_time=0,
                    end_time=20,
                )

                response = self.client.post(
                    f"/api/clips/{clip.id}/render/",
                    {"font_size": 50, "text_color": "#FFFFFF"},
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("between 12 and 36", response.json()["error"])

                job.source_file.delete(save=False)

    def test_re_render_saves_video_ratio_and_subtitle_options(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = VideoJob.objects.create(title="Render project")
                job.source_file.save(
                    "source.mp4",
                    ContentFile(b"video data"),
                    save=True,
                )
                clip = VideoClip.objects.create(
                    job=job,
                    title="Highlight 1",
                    start_time=0,
                    end_time=20,
                )

                with patch("clips.views.rerender_clip") as rerender:
                    response = self.client.post(
                        f"/api/clips/{clip.id}/render/",
                        {
                            "font_size": 30,
                            "text_color": "#00AACC",
                            "aspect_ratio": "16:9",
                            "subtitle_style": "minimal",
                            "subtitle_position": "center",
                            "include_subtitles": False,
                        },
                        content_type="application/json",
                    )

                self.assertEqual(response.status_code, 200, response.content)
                rerender.assert_called_once_with(
                    clip,
                    font_size=30,
                    text_color="#00AACC",
                    aspect_ratio="16:9",
                    subtitle_style="minimal",
                    subtitle_position="center",
                    include_subtitles=False,
                )
                job.refresh_from_db()
                self.assertEqual(job.aspect_ratio, "16:9")
                self.assertEqual(job.subtitle_style, "minimal")
                self.assertEqual(job.subtitle_position, "center")
                self.assertFalse(job.include_subtitles)
                self.assertEqual(job.subtitle_font_size, 30)
                self.assertEqual(job.subtitle_color, "#00AACC")

                job.source_file.delete(save=False)

    def test_deleting_a_project_removes_its_media_files(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = VideoJob.objects.create(title="Delete project")
                job.source_file.save(
                    "source.mp4",
                    ContentFile(b"source video"),
                    save=True,
                )
                clip = VideoClip.objects.create(
                    job=job,
                    title="Highlight 1",
                    start_time=0,
                    end_time=20,
                )
                clip.video_file.save(
                    "clip.mp4",
                    ContentFile(b"generated video"),
                    save=True,
                )
                source_path = Path(job.source_file.path)
                clip_path = Path(clip.video_file.path)

                response = self.client.delete(
                    f"/api/jobs/{job.id}/delete/",
                )

                self.assertEqual(response.status_code, 204)
                self.assertFalse(VideoJob.objects.filter(pk=job.pk).exists())
                self.assertFalse(source_path.exists())
                self.assertFalse(clip_path.exists())


class VideoProcessingTests(TestCase):
    def create_job_with_source(self):
        job = VideoJob.objects.create(title="Processing project")
        job.source_file.save(
            "source.mp4",
            ContentFile(b"source video"),
            save=True,
        )
        return job

    def render_fake_video(self, **kwargs):
        Path(kwargs["output_path"]).write_bytes(b"generated video")

    def test_video_without_speech_generates_unsubtitled_clips(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = self.create_job_with_source()
                job.aspect_ratio = "1:1"
                job.subtitle_style = "boxed"
                job.subtitle_position = "top"
                job.subtitle_font_size = 30
                job.subtitle_color = "#00AACC"
                job.include_subtitles = False
                job.save()

                with (
                    patch(
                        "clips.processor.get_ffmpeg_path",
                        return_value="ffmpeg",
                    ),
                    patch(
                        "clips.processor.transcribe_video",
                        return_value=([], 42.0),
                    ),
                    patch("clips.processor.write_srt") as write_srt,
                    patch(
                        "clips.processor.render_video",
                        side_effect=self.render_fake_video,
                    ) as render_video,
                ):
                    clips = process_job(job)

                self.assertEqual(len(clips), 1)
                self.assertEqual(
                    [clip.title for clip in clips],
                    ["Clip 1"],
                )
                self.assertTrue(
                    all(not clip.transcript for clip in clips)
                )
                self.assertTrue(
                    all(
                        Path(clip.video_file.path).is_file()
                        for clip in clips
                    )
                )
                self.assertEqual(render_video.call_count, 1)
                self.assertEqual(clips[0].duration, 42.0)
                self.assertEqual(
                    render_video.call_args.kwargs["aspect_ratio"],
                    "1:1",
                )
                self.assertEqual(
                    render_video.call_args.kwargs["subtitle_style"],
                    "boxed",
                )
                self.assertEqual(
                    render_video.call_args.kwargs["subtitle_position"],
                    "top",
                )
                self.assertEqual(
                    render_video.call_args.kwargs["font_size"],
                    30,
                )
                self.assertEqual(
                    render_video.call_args.kwargs["text_color"],
                    "#00AACC",
                )
                self.assertFalse(
                    render_video.call_args.kwargs["include_subtitles"]
                )
                write_srt.assert_not_called()
                job.source_file.delete(save=False)
                for clip in clips:
                    clip.video_file.delete(save=False)

    def test_re_render_without_subtitles_skips_transcription(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = self.create_job_with_source()
                clip = VideoClip.objects.create(
                    job=job,
                    title="Highlight 1",
                    start_time=0,
                    end_time=35,
                    transcript="Keep this transcript",
                )
                clip.video_file.save(
                    "original.mp4",
                    ContentFile(b"original video"),
                    save=True,
                )

                with (
                    patch(
                        "clips.processor.get_ffmpeg_path",
                        return_value="ffmpeg",
                    ),
                    patch("clips.processor.transcribe_video") as transcribe,
                    patch(
                        "clips.processor.render_video",
                        side_effect=self.render_fake_video,
                    ) as render_video,
                ):
                    rerender_clip(clip, include_subtitles=False)

                transcribe.assert_not_called()
                self.assertFalse(
                    render_video.call_args.kwargs["include_subtitles"]
                )
                clip.refresh_from_db()
                self.assertEqual(clip.transcript, "Keep this transcript")
                job.source_file.delete(save=False)
                clip.video_file.delete(save=False)

    def test_successful_reprocessing_replaces_old_clips_and_files(self):
        segments = [{
            "start": 0,
            "end": 42,
            "text": "A useful explanation with a clear conclusion.",
        }]

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = self.create_job_with_source()

                with (
                    patch(
                        "clips.processor.get_ffmpeg_path",
                        return_value="ffmpeg",
                    ),
                    patch(
                        "clips.processor.transcribe_video",
                        return_value=(segments, 42),
                    ),
                    patch(
                        "clips.processor.render_video",
                        side_effect=self.render_fake_video,
                    ),
                ):
                    first_run = process_job(job)
                    old_file_path = Path(first_run[0].video_file.path)

                    second_run = process_job(job)

                self.assertEqual(len(second_run), 1)
                self.assertEqual(job.clips.count(), 1)
                self.assertTrue(Path(second_run[0].video_file.path).is_file())
                self.assertFalse(old_file_path.exists())

                job.source_file.delete(save=False)
                second_run[0].video_file.delete(save=False)

    def test_processing_failure_preserves_existing_clips(self):
        segments = [{
            "start": 0,
            "end": 42,
            "text": "A useful explanation with a clear conclusion.",
        }]

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = self.create_job_with_source()

                with (
                    patch(
                        "clips.processor.get_ffmpeg_path",
                        return_value="ffmpeg",
                    ),
                    patch(
                        "clips.processor.transcribe_video",
                        return_value=(segments, 42),
                    ),
                    patch(
                        "clips.processor.render_video",
                        side_effect=self.render_fake_video,
                    ),
                ):
                    old_clip = process_job(job)[0]

                old_file_path = Path(old_clip.video_file.path)

                with (
                    patch(
                        "clips.processor.get_ffmpeg_path",
                        return_value="ffmpeg",
                    ),
                    patch(
                        "clips.processor.transcribe_video",
                        side_effect=RuntimeError("Transcription failed"),
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "Transcription failed",
                    ):
                        process_job(job)

                self.assertEqual(job.clips.count(), 1)
                self.assertTrue(old_file_path.is_file())

                old_clip.video_file.delete(save=False)
                job.source_file.delete(save=False)

    def test_partial_render_failure_preserves_previous_clip_files(self):
        short_segments = [{
            "start": 0,
            "end": 42,
            "text": "A useful explanation with a clear conclusion.",
        }]
        long_segments = [{
            "start": 0,
            "end": 90,
            "text": "A useful explanation with a clear conclusion.",
        }]

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = self.create_job_with_source()

                with (
                    patch(
                        "clips.processor.get_ffmpeg_path",
                        return_value="ffmpeg",
                    ),
                    patch(
                        "clips.processor.transcribe_video",
                        return_value=(short_segments, 42),
                    ),
                    patch(
                        "clips.processor.render_video",
                        side_effect=self.render_fake_video,
                    ),
                ):
                    old_clip = process_job(job)[0]

                old_file_path = Path(old_clip.video_file.path)
                render_calls = 0

                def fail_after_one_render(**kwargs):
                    nonlocal render_calls
                    render_calls += 1

                    if render_calls == 2:
                        raise RuntimeError("FFmpeg failed")

                    self.render_fake_video(**kwargs)

                with (
                    patch(
                        "clips.processor.get_ffmpeg_path",
                        return_value="ffmpeg",
                    ),
                    patch(
                        "clips.processor.transcribe_video",
                        return_value=(long_segments, 90),
                    ),
                    patch(
                        "clips.processor.render_video",
                        side_effect=fail_after_one_render,
                    ),
                ):
                    with self.assertRaisesRegex(RuntimeError, "FFmpeg failed"):
                        process_job(job)

                self.assertEqual(job.clips.count(), 1)
                self.assertTrue(old_file_path.is_file())
                generated_files = list(
                    (Path(media_root) / "generated_clips").rglob("*.mp4")
                )
                self.assertEqual(generated_files, [old_file_path])

                old_clip.video_file.delete(save=False)
                job.source_file.delete(save=False)
