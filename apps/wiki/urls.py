from django.urls import path

from . import views

app_name = "wiki"

urlpatterns = [
    # Placeholders until phase 02 implements the wiki screens; they exist so
    # reverse("wiki:page_detail") and reverse("wiki:page_new") resolve.
    path("p/<slug:slug>/", views.page_detail, name="page_detail"),
    path("new/", views.page_new, name="page_new"),
]
