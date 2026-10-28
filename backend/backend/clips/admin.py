
from django.contrib import admin

from .models import VideoClip, VideoJob


class VideoClipInline(admin.TabularInline):
    model = VideoClip
    extra = 0
    readonly_fields = (
        "start_time",
        "end_time",
        "duration",
        "created_at",
    )


@admin.register(VideoJob)
class VideoJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "language",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "language",
        "created_at",
    )

    search_fields = (
        "title",
        "source_url",
        "error_message",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    inlines = [VideoClipInline]


@admin.register(VideoClip)
class VideoClipAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "job",
        "start_time",
        "end_time",
        "duration",
    )

    search_fields = (
        "title",
        "transcript",
    )

    list_filter = ("created_at",)
