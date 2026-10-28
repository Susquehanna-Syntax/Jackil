from django import forms


class VigilConnectionForm(forms.Form):
    """The Vigil connection fields; the key is write-only."""

    base_url = forms.URLField(
        label="Vigil address",
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "https://vigil.example.gov"}
        ),
    )
    key = forms.CharField(
        label="Integration key",
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"class": "form-input"}),
    )
    enabled = forms.BooleanField(label="Read from Vigil", required=False)

    def __init__(self, *args, has_key=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_key = has_key

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled") and not cleaned.get("base_url"):
            self.add_error("base_url", "Enter the address of your Vigil server.")
        return cleaned

    def clean_key(self):
        key = (self.cleaned_data.get("key") or "").strip()
        if key and not key.startswith("vjk_"):
            raise forms.ValidationError(
                "That is not a Jackil integration key; they start with vjk_."
            )
        return key
