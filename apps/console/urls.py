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
    path("kb/", views.kb_list, name="kb_list"),
    path("kb/new/", views.kb_create, name="kb_create"),
    path("kb/<int:pk>/", views.kb_edit, name="kb_edit"),
    path("kb/<int:pk>/delete/", views.kb_delete, name="kb_delete"),
    path("automation/", views.automation_home, name="automation_home"),
    path("automation/macros/new/", views.macro_create, name="macro_create"),
    path("automation/macros/<int:pk>/", views.macro_edit, name="macro_edit"),
    path("automation/macros/<int:pk>/delete/", views.macro_delete, name="macro_delete"),
    path("automation/rules/new/", views.rule_create, name="rule_create"),
    path("automation/rules/<int:pk>/", views.rule_edit, name="rule_edit"),
    path("automation/rules/<int:pk>/delete/", views.rule_delete, name="rule_delete"),
]
