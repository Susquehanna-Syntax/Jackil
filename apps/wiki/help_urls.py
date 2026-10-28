from django.urls import path

from . import help_views

app_name = "help"

urlpatterns = [
    path("", help_views.home, name="home"),
    path("a/<slug:slug>/", help_views.article, name="article"),
    # Kept so pre-migration KB links still resolve.
    path("<slug:slug>/", help_views.legacy, name="legacy"),
]
