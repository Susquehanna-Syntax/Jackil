from django.urls import path

from . import views

app_name = "kb"

urlpatterns = [
    path("", views.help_home, name="help_home"),
    path("<slug:slug>/", views.article_detail, name="article_detail"),
]
