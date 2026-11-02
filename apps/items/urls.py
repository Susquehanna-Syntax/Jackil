from django.urls import path

from . import views

app_name = "items"

urlpatterns = [
    path("", views.item_list, name="item_list"),
    path("new/", views.item_create, name="item_create"),
    path("kinds/", views.kind_list, name="kind_list"),
    path("kinds/<int:pk>/delete/", views.kind_delete, name="kind_delete"),
    path("<int:pk>/", views.item_detail, name="item_detail"),
    path("<int:pk>/edit/", views.item_edit, name="item_edit"),
    path("<int:pk>/delete/", views.item_delete, name="item_delete"),
    path("<int:pk>/vigil-host/", views.item_link_host, name="item_link_host"),
]
