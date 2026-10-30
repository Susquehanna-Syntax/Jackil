from django.urls import path

from . import views

app_name = "wiki"

urlpatterns = [
    path("", views.home, name="home"),
    path("tree/", views.all_pages, name="tree"),
    path("preview/", views.preview, name="preview"),
    path("spaces/new/", views.space_create, name="space_create"),
    path("s/<slug:slug>/", views.space_detail, name="space_detail"),
    path("s/<slug:slug>/edit/", views.space_edit, name="space_edit"),
    path("templates/", views.template_list, name="template_list"),
    path("templates/new/", views.template_create, name="template_create"),
    path("templates/<int:pk>/edit/", views.template_edit, name="template_edit"),
    path("templates/<int:pk>/delete/", views.template_delete, name="template_delete"),
    path("new/", views.page_new, name="page_new"),
    path("p/<slug:slug>/", views.page_detail, name="page_detail"),
    path("p/<slug:slug>/edit/", views.page_edit, name="page_edit"),
    path("p/<slug:slug>/history/", views.page_history, name="page_history"),
    path("p/<slug:slug>/history/<int:number>/", views.page_version, name="page_version"),
    path("p/<slug:slug>/diff/", views.page_diff, name="page_diff"),
    path("p/<slug:slug>/restore/<int:number>/", views.page_restore, name="page_restore"),
    path("p/<slug:slug>/move/", views.page_move, name="page_move"),
    path("p/<slug:slug>/delete/", views.page_delete, name="page_delete"),
    path("p/<slug:slug>/attach/", views.page_attach, name="page_attach"),
    path("attachment/<int:pk>/", views.attachment_download, name="attachment_download"),
]
