from django import forms

from apps.saml.models import SamlConfig


class SamlConfigForm(forms.ModelForm):
    """The identity provider connection. All optional until SAML is turned on."""

    class Meta:
        model = SamlConfig
        fields = [
            "enabled",
            "idp_entity_id",
            "idp_sso_url",
            "idp_x509_cert",
            "email_attribute",
            "name_attribute",
            "new_user_role",
            "allow_new_users",
        ]
        widgets = {
            "idp_entity_id": forms.TextInput(
                attrs={"class": "form-input", "placeholder": "https://idp.example.com/"}
            ),
            "idp_sso_url": forms.URLInput(
                attrs={"class": "form-input", "placeholder": "https://idp.example.com/sso"}
            ),
            "idp_x509_cert": forms.Textarea(
                attrs={
                    "class": "form-input",
                    "rows": 6,
                    "placeholder": "-----BEGIN CERTIFICATE-----",
                }
            ),
            "email_attribute": forms.TextInput(attrs={"class": "form-input"}),
            "name_attribute": forms.TextInput(attrs={"class": "form-input"}),
            "new_user_role": forms.Select(attrs={"class": "form-input"}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled") and not (
            cleaned.get("idp_entity_id")
            and cleaned.get("idp_sso_url")
            and cleaned.get("idp_x509_cert")
        ):
            self.add_error(
                "idp_sso_url",
                "An enabled connection needs the IdP entity ID, SSO URL and certificate.",
            )
        return cleaned
