from django.urls import path

from . import views

app_name = "console"

urlpatterns = [
    path("", views.settings_home, name="settings_home"),
    path("email/", views.inbox_list, name="inbox_list"),
    path("email/new/", views.inbox_create, name="inbox_create"),
    path("email/<int:pk>/", views.inbox_edit, name="inbox_edit"),
    path("email/<int:pk>/delete/", views.inbox_delete, name="inbox_delete"),
    path("sla/", views.sla_settings, name="sla_settings"),
]
