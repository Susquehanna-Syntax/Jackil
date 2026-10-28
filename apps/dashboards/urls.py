from django.urls import path

from . import views

app_name = "dashboards"

urlpatterns = [
    path("", views.dashboard_list, name="dashboard-list"),
    path("catalog/", views.catalog, name="dashboard-catalog"),
    path("options/saved_view/", views.saved_view_options, name="dashboard-options-saved-view"),
    path("options/project/", views.project_options, name="dashboard-options-project"),
    path("<uuid:dashboard_id>/", views.dashboard_detail, name="dashboard-detail"),
    path("<uuid:dashboard_id>/layout/", views.layout_update, name="dashboard-layout"),
    path("<uuid:dashboard_id>/share/", views.dashboard_share, name="dashboard-share"),
    path("widgets/<str:kind>/data/", views.widget_data_view, name="widget-data"),
]
