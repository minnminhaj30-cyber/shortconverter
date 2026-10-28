
from rest_framework import serializers

from .models import VideoClip, VideoJob


class VideoClipSerializer(serializers.ModelSerializer):
    video_url = serializers.SerializerMethodField()

    class Meta:
        model = VideoClip
        fields = [
            "id",
            "job",
            "title",
            "start_time",
            "end_time",
            "duration",
            "video_file",
            "video_url",
            "transcript",
            "created_at",
        ]

    def get_video_url(self, obj):
        if not obj.video_file:
            return None

        request = self.context.get("request")
        url = obj.video_file.url

        if request:
            return request.build_absolute_uri(url)

        return url


class VideoJobSerializer(serializers.ModelSerializer):
    clips = VideoClipSerializer(many=True, read_only=True)
    source_file_url = serializers.SerializerMethodField()

    class Meta:
        model = VideoJob
        fields = [
            "id",
            "title",
            "source_url",
            "source_file",
            "source_file_url",
            "language",
            "aspect_ratio",
            "subtitle_style",
            "include_subtitles",
            "subtitle_position",
            "subtitle_font_size",
            "subtitle_color",
            "status",
            "error_message",
            "created_at",
            "updated_at",
            "clips",
        ]

    def get_source_file_url(self, obj):
        if not obj.source_file:
            return None

        request = self.context.get("request")
        url = obj.source_file.url

        if request:
            return request.build_absolute_uri(url)

        return url
