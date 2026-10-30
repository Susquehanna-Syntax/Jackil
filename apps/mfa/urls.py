from django.urls import path

from . import views

app_name = "mfa"

urlpatterns = [
    path("verify/", views.verify, name="verify"),
    path("verify/key/options/", views.verify_key_options, name="verify-key-options"),
    path("verify/key/", views.verify_key, name="verify-key"),
    path("codes/", views.codes, name="codes"),
    path("", views.security, name="security"),
    path("keys/options/", views.key_options, name="key-options"),
    path("keys/", views.key_register, name="key-register"),
    path("keys/<int:key_id>/delete/", views.key_delete, name="key-delete"),
    path("setup/", views.setup, name="setup"),
]
