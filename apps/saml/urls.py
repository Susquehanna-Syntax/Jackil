from django.urls import path

from apps.saml import views

urlpatterns = [
    path("saml/login/", views.login_start, name="saml-login"),
    path("saml/acs/", views.acs, name="saml-acs"),
    path("saml/metadata/", views.metadata, name="saml-metadata"),
]
