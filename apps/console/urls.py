from django.urls import path

from config.features import feature_enabled

from . import views

app_name = "console"

urlpatterns = [
    path("", views.settings_home, name="settings_home"),
    path("email/", views.inbox_list, name="inbox_list"),
    path("email/new/", views.inbox_create, name="inbox_create"),
    path("email/<int:pk>/", views.inbox_edit, name="inbox_edit"),
    path("email/<int:pk>/delete/", views.inbox_delete, name="inbox_delete"),
    path("kb/", views.kb_list, name="kb_list"),
    path("kb/new/", views.kb_create, name="kb_create"),
    path("kb/<int:pk>/", views.kb_edit, name="kb_edit"),
    path("kb/<int:pk>/delete/", views.kb_delete, name="kb_delete"),
]

if feature_enabled("sla"):
    urlpatterns += [
        path("sla/", views.sla_settings, name="sla_settings"),
    ]

if feature_enabled("automation"):
    urlpatterns += [
        path("automation/", views.automation_home, name="automation_home"),
        path("automation/macros/new/", views.macro_create, name="macro_create"),
        path("automation/macros/<int:pk>/", views.macro_edit, name="macro_edit"),
        path("automation/macros/<int:pk>/delete/", views.macro_delete, name="macro_delete"),
        path("automation/rules/new/", views.rule_create, name="rule_create"),
        path("automation/rules/<int:pk>/", views.rule_edit, name="rule_edit"),
        path("automation/rules/<int:pk>/delete/", views.rule_delete, name="rule_delete"),
    ]

if feature_enabled("api"):
    urlpatterns += [
        path("api/", views.api_home, name="api_home"),
        path("api/keys/new/", views.key_create, name="key_create"),
        path("api/keys/<int:pk>/delete/", views.key_delete, name="key_delete"),
        path("api/webhooks/new/", views.webhook_create, name="webhook_create"),
        path("api/webhooks/<int:pk>/", views.webhook_edit, name="webhook_edit"),
        path("api/webhooks/<int:pk>/delete/", views.webhook_delete, name="webhook_delete"),
    ]

if feature_enabled("customfields"):
    urlpatterns += [
        path("forms/", views.field_list, name="field_list"),
        path("forms/fields/new/", views.field_create, name="field_create"),
        path("forms/fields/<int:pk>/", views.field_edit, name="field_edit"),
        path("forms/fields/<int:pk>/delete/", views.field_delete, name="field_delete"),
        path("forms/requests/new/", views.reqform_create, name="reqform_create"),
        path("forms/requests/<int:pk>/", views.reqform_edit, name="reqform_edit"),
        path("forms/requests/<int:pk>/delete/", views.reqform_delete, name="reqform_delete"),
    ]
