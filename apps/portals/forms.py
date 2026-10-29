"""The admin portal form."""

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_slug

from .models import RESERVED_SLUGS, Portal
from .service import form_choices


def parse_status_pages(raw):
    """Comma-separated Vigil status-page slugs -> cleaned list. Raises when a
    slug is invalid or more than ten are given."""
    slugs = [part.strip() for part in (raw or "").split(",")]
    slugs = [slug for slug in slugs if slug]
    if len(slugs) > 10:
        raise forms.ValidationError("Use up to ten Vigil status-page slugs, separated by commas.")
    for slug in slugs:
        try:
            validate_slug(slug)
        except ValidationError:
            raise forms.ValidationError(
                "Status-page slugs may use letters, numbers, hyphens and underscores."
            ) from None
    return slugs


class PortalForm(forms.ModelForm):
    request_forms = forms.MultipleChoiceField(
        label="Request forms",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    vigil_status_pages = forms.CharField(
        label="Vigil status pages",
        required=False,
        help_text="Slugs separated by commas.",
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "mail, portal"}),
    )

    class Meta:
        model = Portal
        fields = [
            "name",
            "slug",
            "intro",
            "is_published",
            "is_default",
            "department",
            "request_forms",
            "spaces",
            "show_search",
            "show_my_tickets",
            "vigil_status_pages",
            "logo_url",
            "accent",
            "custom_css",
            "hide_powered_by",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input"}),
            "slug": forms.TextInput(attrs={"class": "form-input"}),
            "intro": forms.Textarea(attrs={"class": "form-textarea", "rows": 3}),
            "department": forms.Select(attrs={"class": "form-select"}),
            "spaces": forms.CheckboxSelectMultiple,
            "logo_url": forms.TextInput(attrs={"class": "form-input"}),
            "accent": forms.Select(attrs={"class": "form-select"}),
            "custom_css": forms.Textarea(attrs={"class": "form-textarea", "rows": 6}),
        }

    def __init__(self, *args, styling=False, **kwargs):
        super().__init__(*args, **kwargs)
        choices = form_choices()
        self.fields["request_forms"].choices = choices
        if self.instance.pk and not self.is_bound:
            allowed = {slug for slug, _ in choices}
            self.initial["request_forms"] = [
                slug for slug in (self.instance.request_forms or []) if slug in allowed
            ]
        if not styling:
            for name in ("logo_url", "accent", "custom_css", "hide_powered_by"):
                del self.fields[name]

    def clean_slug(self):
        slug = self.cleaned_data.get("slug", "")
        if slug in RESERVED_SLUGS:
            raise forms.ValidationError(f"“{slug}” is a reserved address.")
        return slug

    def clean_request_forms(self):
        chosen = self.cleaned_data.get("request_forms", [])
        allowed = {slug for slug, _ in self.fields["request_forms"].choices}
        return [slug for slug in chosen if slug in allowed]

    def clean_vigil_status_pages(self):
        return parse_status_pages(self.cleaned_data.get("vigil_status_pages"))
