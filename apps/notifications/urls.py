from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notifications_list, name="list"),
    path("<int:pk>/open/", views.notification_open, name="open"),
    path("read-all/", views.notifications_read_all, name="read_all"),
]
