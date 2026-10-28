
from pathlib import Path
import tempfile

from django.conf import settings
from django.core.files import File
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import VideoClip, VideoJob
from .processor import (
    VideoDownloadError,
    download_source_video,
    process_job,
    rerender_clip,
)
from .serializers import VideoClipSerializer, VideoJobSerializer


MAX_UPLOAD_BYTES = 500 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
}


def job_data(job, request):
    return VideoJobSerializer(
        job,
        context={"request": request},
    ).data


def clip_data(clip, request):
    return VideoClipSerializer(
        clip,
        context={"request": request},
    ).data


def remove_file(field):
    if field and field.name:
        field.storage.delete(field.name)


@api_view(["GET", "POST"])
def jobs(request):
    if request.method == "GET":
        queryset = VideoJob.objects.prefetch_related("clips").all()

        serializer = VideoJobSerializer(
            queryset,
            many=True,
            context={"request": request},
        )

        return Response(serializer.data)

    uploaded_file = request.FILES.get("source_file")
    source_url = request.data.get("source_url", "").strip()

    if not uploaded_file and not source_url:
        return Response(
            {"error": "Upload a video file or provide a source URL."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if uploaded_file:
        extension = Path(uploaded_file.name).suffix.lower()

        if extension not in ALLOWED_EXTENSIONS:
            return Response(
                {
                    "error": (
                        "Unsupported video extension. "
                        "Use MP4, MOV, MKV, or WebM."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if uploaded_file.size > MAX_UPLOAD_BYTES:
            return Response(
                {"error": "The maximum upload size is 500 MB."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

    payload = {
        "title": (
            request.data.get("title", "").strip()
            or (
                Path(uploaded_file.name).stem
                if uploaded_file
                else "Untitled project"
            )
        ),
        "source_url": source_url,
        "language": "auto",
        "aspect_ratio": request.data.get("aspect_ratio", "9:16"),
        "subtitle_style": request.data.get(
            "subtitle_style",
            "classic",
        ),
        "include_subtitles": request.data.get(
            "include_subtitles",
            True,
        ),
        "subtitle_position": request.data.get(
            "subtitle_position",
            "bottom",
        ),
        "subtitle_font_size": request.data.get(
            "subtitle_font_size",
            20,
        ),
        "subtitle_color": request.data.get(
            "subtitle_color",
            "#FFFFFF",
        ),
    }

    if uploaded_file:
        payload["source_file"] = uploaded_file

    serializer = VideoJobSerializer(
        data=payload,
        context={"request": request},
    )

    if not serializer.is_valid():
        first_error = next(iter(serializer.errors.values()))
        if isinstance(first_error, list):
            first_error = first_error[0]

        return Response(
            {
                "error": str(first_error),
                "fields": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    job = serializer.save()

    return Response(
        {"job": job_data(job, request)},
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
def job_detail(request, job_id):
    job = get_object_or_404(
        VideoJob.objects.prefetch_related("clips"),
        pk=job_id,
    )

    return Response({"job": job_data(job, request)})


@api_view(["POST"])
def process_job_view(request, job_id):
    job = get_object_or_404(VideoJob, pk=job_id)

    if not job.source_file and not job.source_url:
        return Response(
            {
                "error": (
                    "This project has no uploaded source video or video URL."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if job.status == "processing":
        return Response(
            {"error": "This project is already processing."},
            status=status.HTTP_409_CONFLICT,
        )

    job.status = "processing"
    job.error_message = ""
    job.save(update_fields=[
        "status",
        "error_message",
        "updated_at",
    ])

    try:
        if not job.source_file:
            work_root = Path(settings.MEDIA_ROOT) / "work"
            work_root.mkdir(parents=True, exist_ok=True)

            with tempfile.TemporaryDirectory(
                prefix=f"source_{job.id}_",
                dir=work_root,
            ) as temporary_dir:
                downloaded_path, downloaded_title = download_source_video(
                    job.source_url,
                    temporary_dir,
                )

                extension = downloaded_path.suffix.lower()
                if extension not in ALLOWED_EXTENSIONS:
                    raise VideoDownloadError(
                        "The downloaded video format is not supported."
                    )

                with downloaded_path.open("rb") as source_video:
                    job.source_file.save(
                        f"job_{job.id}_source{extension}",
                        File(source_video),
                        save=False,
                    )

            fields_to_update = ["source_file", "updated_at"]
            if (
                downloaded_title
                and job.title == "Untitled project"
            ):
                job.title = downloaded_title[:200]
                fields_to_update.append("title")

            job.save(update_fields=fields_to_update)

        process_job(job)

        job.status = "completed"
        job.error_message = ""

        job.save(update_fields=[
            "status",
            "error_message",
            "updated_at",
        ])

        job.refresh_from_db()

        return Response({"job": job_data(job, request)})

    except (ValueError, ValidationError) as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.save(update_fields=[
            "status",
            "error_message",
            "updated_at",
        ])

        return Response(
            {
                "error": str(exc),
                "job": job_data(job, request),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)[:5000]
        job.save(update_fields=[
            "status",
            "error_message",
            "updated_at",
        ])

        return Response(
            {
                "error": (
                    "Video processing failed. Check the Django "
                    "terminal for details."
                ),
                "details": str(exc)[:2000],
                "job": job_data(job, request),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["DELETE"])
def delete_job(request, job_id):
    job = get_object_or_404(VideoJob, pk=job_id)

    # Capture file names before deleting the database records.
    source_field = job.source_file
    clip_fields = [
        clip.video_file
        for clip in job.clips.all()
        if clip.video_file
    ]

    job.delete()

    # Delete media after successful database deletion.
    remove_file(source_field)

    for field in clip_fields:
        remove_file(field)

    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
def render_clip(request, clip_id):
    clip = get_object_or_404(
        VideoClip.objects.select_related("job"),
        pk=clip_id,
    )

    try:
        font_size = int(request.data.get(
            "font_size",
            clip.job.subtitle_font_size,
        ))
        text_color = request.data.get(
            "text_color",
            clip.job.subtitle_color,
        )
        aspect_ratio = request.data.get(
            "aspect_ratio",
            clip.job.aspect_ratio,
        )
        subtitle_style = request.data.get(
            "subtitle_style",
            clip.job.subtitle_style,
        )
        include_subtitles = serializers.BooleanField().to_internal_value(
            request.data.get(
                "include_subtitles",
                clip.job.include_subtitles,
            )
        )
        subtitle_position = request.data.get(
            "subtitle_position",
            clip.job.subtitle_position,
        )

        if aspect_ratio not in dict(VideoJob.ASPECT_RATIO_CHOICES):
            raise ValueError("Unsupported video aspect ratio.")

        if subtitle_style not in dict(VideoJob.SUBTITLE_STYLE_CHOICES):
            raise ValueError("Unsupported subtitle style.")

        if subtitle_position not in dict(
            VideoJob.SUBTITLE_POSITION_CHOICES
        ):
            raise ValueError("Unsupported subtitle position.")

        if not isinstance(text_color, str):
            raise ValueError("Invalid subtitle color.")

        rerender_clip(
            clip,
            font_size=font_size,
            text_color=text_color,
            aspect_ratio=aspect_ratio,
            subtitle_style=subtitle_style,
            subtitle_position=subtitle_position,
            include_subtitles=include_subtitles,
        )

        clip.job.subtitle_font_size = font_size
        clip.job.subtitle_color = text_color
        clip.job.aspect_ratio = aspect_ratio
        clip.job.subtitle_style = subtitle_style
        clip.job.subtitle_position = subtitle_position
        clip.job.include_subtitles = include_subtitles
        clip.job.save(update_fields=[
            "subtitle_font_size",
            "subtitle_color",
            "aspect_ratio",
            "subtitle_style",
            "subtitle_position",
            "include_subtitles",
            "updated_at",
        ])

        clip.refresh_from_db()

        return Response({
            "message": "Clip re-rendered successfully.",
            "clip": clip_data(clip, request),
        })

    except (ValueError, TypeError) as exc:
        return Response(
            {"error": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as exc:
        return Response(
            {
                "error": "Unable to re-render this clip.",
                "details": str(exc)[:2000],
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
