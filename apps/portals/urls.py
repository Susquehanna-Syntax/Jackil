from django.urls import path

from . import public

app_name = "portals"

urlpatterns = [
    path("", public.default_portal, name="default"),
    path("<slug:slug>/", public.portal_home, name="portal"),
    path("<slug:slug>/search/", public.portal_search, name="portal_search"),
    path("<slug:slug>/suggest/", public.suggest, name="portal_suggest"),
    path("<slug:slug>/pins/", public.save_pins, name="portal_pins"),
]
