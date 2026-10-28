from django.urls import path, register_converter

from . import backlog, converters, views

register_converter(converters.ProjectKeyConverter, "projkey")
register_converter(converters.IssueRefConverter, "issueref")

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
    path("<projkey:key>/backlog/", backlog.backlog_page, name="backlog"),
    path("<projkey:key>/backlog/data/", backlog.backlog_data, name="backlog_data"),
    path("<projkey:key>/backlog/rank/", backlog.backlog_rank, name="backlog_rank"),
    path("<projkey:key>/sprints/", backlog.sprint_create, name="sprint_create"),
    path(
        "<projkey:key>/sprints/<int:id>/start/",
        backlog.sprint_start,
        name="sprint_start",
    ),
    path(
        "<projkey:key>/sprints/<int:id>/complete/",
        backlog.sprint_complete,
        name="sprint_complete",
    ),
    path("<projkey:key>/sprints/<int:id>/edit/", backlog.sprint_edit, name="sprint_edit"),
]
