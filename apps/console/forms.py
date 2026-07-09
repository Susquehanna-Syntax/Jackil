from django import forms

from apps.inbox.models import Inbox

# Password fields we keep unchanged when the admin leaves them blank on edit.
SECRET_FIELDS = ("smtp_password", "imap_password")


class InboxForm(forms.ModelForm):
    class Meta:
        model = Inbox
        fields = [
            "name",
            "email_address",
            "is_default",
            "active",
            "signature",
            "smtp_host",
            "smtp_port",
            "smtp_username",
            "smtp_password",
            "smtp_use_tls",
            "imap_host",
            "imap_port",
            "imap_username",
            "imap_password",
            "imap_use_ssl",
            "imap_folder",
        ]
        widgets = {
            "smtp_password": forms.PasswordInput(render_value=False),
            "imap_password": forms.PasswordInput(render_value=False),
            "signature": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Attach design-system classes to each widget.
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check")
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", "form-textarea")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-input")
        # On edit, blank password means "keep the stored value".
        if self.instance and self.instance.pk:
            for field in SECRET_FIELDS:
                self.fields[field].required = False
                self.fields[field].widget.attrs["placeholder"] = "•••••• (unchanged)"

    def clean(self):
        cleaned = super().clean()
        if self.instance and self.instance.pk:
            for field in SECRET_FIELDS:
                if not cleaned.get(field):
                    cleaned[field] = getattr(self.instance, field)
        return cleaned
