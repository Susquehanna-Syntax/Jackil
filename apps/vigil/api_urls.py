from django.urls import path

from . import api

urlpatterns = [
    path("links/", api.vigil_links, name="vigil-links"),
    path("widgets/", api.vigil_widgets, name="vigil-widgets"),
    path("widgets/<str:kind>/", api.vigil_widget, name="vigil-widget"),
]
