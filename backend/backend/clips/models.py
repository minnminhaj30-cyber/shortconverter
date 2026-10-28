
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models


class VideoJob(models.Model):
    STATUS_CHOICES = [
        ("created", "Created"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    LANGUAGE_CHOICES = [
        ("auto", "Auto Detect"),
    ]

    ASPECT_RATIO_CHOICES = [
        ("9:16", "Portrait (9:16)"),
        ("1:1", "Square (1:1)"),
        ("16:9", "Landscape (16:9)"),
    ]

    SUBTITLE_STYLE_CHOICES = [
        ("classic", "Classic Outline"),
        ("bold", "Bold Pop"),
        ("boxed", "Caption Box"),
        ("minimal", "Minimal Shadow"),
        ("neon", "Neon Glow"),
        ("highlight", "Highlight Bar"),
        ("cinema", "Cinema Serif"),
        ("typewriter", "Typewriter"),
        ("heavy_outline", "Heavy Outline"),
        ("soft_shadow", "Soft Shadow"),
    ]

    SUBTITLE_POSITION_CHOICES = [
        ("bottom", "Bottom"),
        ("center", "Center"),
        ("top", "Top"),
    ]

    title = models.CharField(
        max_length=200,
        default="Untitled project",
    )

    source_url = models.URLField(
        blank=True,
        max_length=2000,
    )

    source_file = models.FileField(
        upload_to="source_videos/%Y/%m/",
        blank=True,
        null=True,
    )

    language = models.CharField(
        max_length=10,
        choices=LANGUAGE_CHOICES,
        default="auto",
    )

    aspect_ratio = models.CharField(
        max_length=5,
        choices=ASPECT_RATIO_CHOICES,
        default="9:16",
    )

    subtitle_style = models.CharField(
        max_length=20,
        choices=SUBTITLE_STYLE_CHOICES,
        default="classic",
    )

    include_subtitles = models.BooleanField(default=True)

    subtitle_position = models.CharField(
        max_length=10,
        choices=SUBTITLE_POSITION_CHOICES,
        default="bottom",
    )

    subtitle_font_size = models.PositiveSmallIntegerField(
        default=20,
        validators=[
            MinValueValidator(12),
            MaxValueValidator(36),
        ],
    )

    subtitle_color = models.CharField(
        max_length=7,
        default="#FFFFFF",
        validators=[
            RegexValidator(
                regex=r"^#[0-9A-Fa-f]{6}$",
                message="Enter a valid six-digit hex color.",
            )
        ],
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="created",
    )

    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.status})"


class VideoClip(models.Model):
    job = models.ForeignKey(
        VideoJob,
        related_name="clips",
        on_delete=models.CASCADE,
    )

    title = models.CharField(max_length=200)

    start_time = models.FloatField()
    end_time = models.FloatField()

    duration = models.FloatField(default=0)

    video_file = models.FileField(
        upload_to="generated_clips/%Y/%m/",
        blank=True,
        null=True,
    )

    transcript = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_time"]

    def save(self, *args, **kwargs):
        self.duration = max(
            0,
            self.end_time - self.start_time,
        )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
