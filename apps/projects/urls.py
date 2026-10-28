from django.urls import path, register_converter

from . import views
from .converters import IssueRefConverter, ProjectKeyConverter

register_converter(ProjectKeyConverter, "projkey")
register_converter(IssueRefConverter, "issueref")

app_name = "projects"

urlpatterns = [
    path("", views.project_list, name="project_list"),
    path("new/", views.project_create, name="project_create"),
    # Issue routes first: a bare project-key pattern would happily match "NET-12".
    path("<issueref:ref>/", views.issue_detail, name="issue_detail"),
    path("<issueref:ref>/edit/", views.issue_edit, name="issue_edit"),
    path("<issueref:ref>/move/", views.issue_move, name="issue_move"),
    path("<issueref:ref>/comment/", views.issue_comment, name="issue_comment"),
    path("<projkey:key>/", views.project_detail, name="project_detail"),
    path("<projkey:key>/settings/", views.project_settings, name="project_settings"),
    path("<projkey:key>/new/", views.issue_create, name="issue_create"),
]
