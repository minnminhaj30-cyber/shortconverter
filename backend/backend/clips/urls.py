
from django.urls import path

from . import views

urlpatterns = [
    path("jobs/", views.jobs, name="jobs"),

    path(
        "jobs/<int:job_id>/",
        views.job_detail,
        name="job-detail",
    ),

    path(
        "jobs/<int:job_id>/process/",
        views.process_job_view,
        name="process-job",
    ),

    path(
        "jobs/<int:job_id>/delete/",
        views.delete_job,
        name="delete-job",
    ),

    path(
        "clips/<int:clip_id>/render/",
        views.render_clip,
        name="render-clip",
    ),
]
