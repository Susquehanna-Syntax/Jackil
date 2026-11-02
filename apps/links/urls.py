from django.urls import path

from . import views

app_name = "links"

urlpatterns = [
    path("for/<str:type>/<str:id>/", views.links_for_endpoint, name="links-for"),
    path("add/", views.links_add, name="links-add"),
    path("<int:link_id>/remove/", views.links_remove, name="links-remove"),
    path("search/", views.links_search, name="links-search"),
    path("types/", views.links_types, name="links-types"),
    path("preview/<str:type>/<str:id>/", views.links_preview, name="links-preview"),
    path("resolve-url/", views.links_resolve_url, name="links-resolve-url"),
]
