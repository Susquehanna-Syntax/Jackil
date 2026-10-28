from django.urls import path

from . import api, views

app_name = "reports"

urlpatterns = [
    path("", views.reports_home, name="reports_home"),
    path("new/", views.report_create, name="report_create"),
    # API before <uuid:report_id>/ so "api" is never read as an id.
    path("api/", api.report_index, name="api_index"),
    path("api/widgets/", api.widget_catalog, name="api_widgets"),
    path("api/<uuid:report_id>/", api.report_detail, name="api_detail"),
    path("api/<uuid:report_id>/data/<int:index>/", api.report_data, name="report_data"),
    path("api/<uuid:report_id>/data/<int:index>.csv", api.report_data_csv, name="report_data_csv"),
    path("<uuid:report_id>/", views.report_page, name="report_page"),
]
