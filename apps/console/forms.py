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


from apps.kb.models import KBArticle  # noqa: E402


class KBArticleForm(forms.ModelForm):
    class Meta:
        model = KBArticle
        fields = ["title", "category", "summary", "body", "is_published", "is_public"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 12}),
            "summary": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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


def macro_form_class():
    from apps.automation.models import Macro

    class MacroForm(forms.ModelForm):
        class Meta:
            model = Macro
            fields = ["name", "body", "is_shared"]
            widgets = {"body": forms.Textarea(attrs={"rows": 6})}

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            for field in self.fields.values():
                w = field.widget
                if isinstance(w, forms.CheckboxInput):
                    w.attrs.setdefault("class", "form-check")
                elif isinstance(w, forms.Textarea):
                    w.attrs.setdefault("class", "form-textarea")
                else:
                    w.attrs.setdefault("class", "form-input")

    return MacroForm


def webhook_form_class():
    from apps.api.models import Webhook

    class WebhookForm(forms.ModelForm):
        class Meta:
            model = Webhook
            fields = ["name", "url", "event", "is_active"]

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            for field in self.fields.values():
                w = field.widget
                if isinstance(w, forms.CheckboxInput):
                    w.attrs.setdefault("class", "form-check")
                elif isinstance(w, forms.Select):
                    w.attrs.setdefault("class", "form-select")
                else:
                    w.attrs.setdefault("class", "form-input")

    return WebhookForm


def customfield_form_class():
    from apps.customfields.models import CustomField

    class CustomFieldForm(forms.ModelForm):
        class Meta:
            model = CustomField
            fields = [
                "label",
                "field_type",
                "choices",
                "help_text",
                "required",
                "is_active",
                "order",
            ]
            widgets = {"choices": forms.Textarea(attrs={"rows": 4})}

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            for field in self.fields.values():
                w = field.widget
                if isinstance(w, forms.CheckboxInput):
                    w.attrs.setdefault("class", "form-check")
                elif isinstance(w, forms.Textarea):
                    w.attrs.setdefault("class", "form-textarea")
                elif isinstance(w, forms.Select):
                    w.attrs.setdefault("class", "form-select")
                else:
                    w.attrs.setdefault("class", "form-input")

    return CustomFieldForm


def requestform_form_class():
    from apps.customfields.models import RequestForm

    class RequestFormForm(forms.ModelForm):
        class Meta:
            model = RequestForm
            fields = ["name", "description", "intro", "department", "is_active", "order"]
            widgets = {"intro": forms.Textarea(attrs={"rows": 3})}

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            for field in self.fields.values():
                w = field.widget
                if isinstance(w, forms.CheckboxInput):
                    w.attrs.setdefault("class", "form-check")
                elif isinstance(w, forms.Textarea):
                    w.attrs.setdefault("class", "form-textarea")
                elif isinstance(w, forms.Select):
                    w.attrs.setdefault("class", "form-select")
                else:
                    w.attrs.setdefault("class", "form-input")

    return RequestFormForm
