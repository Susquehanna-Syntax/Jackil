from django import forms
from django.utils.text import slugify

from apps.accounts.models import User

from .models import Item, ItemKind

MAX_ATTRIBUTES = 50
MAX_KEY_LENGTH = 60
MAX_VALUE_LENGTH = 300


class ItemForm(forms.ModelForm):
    attributes_text = forms.CharField(
        label="Attributes",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-textarea", "rows": 5}),
        help_text="One fact per line, as Key: value — e.g. Serial: X1.",
    )

    class Meta:
        model = Item
        fields = [
            "name",
            "kind",
            "owner",
            "department",
            "vendor",
            "warranty_end",
            "notes",
            "vigil_host_id",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input"}),
            "kind": forms.Select(attrs={"class": "form-select"}),
            "owner": forms.Select(attrs={"class": "form-select"}),
            "department": forms.Select(attrs={"class": "form-select"}),
            "vendor": forms.TextInput(attrs={"class": "form-input"}),
            "warranty_end": forms.DateInput(
                attrs={"class": "form-input", "type": "date"}, format="%Y-%m-%d"
            ),
            "notes": forms.Textarea(attrs={"class": "form-textarea", "rows": 4}),
            "vigil_host_id": forms.TextInput(attrs={"class": "form-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = User.objects.filter(role__in=["agent", "admin"]).order_by(
            "username"
        )
        self.fields["owner"].required = False
        self.fields["department"].required = False
        if self.instance.pk:
            self.initial["attributes_text"] = render_attributes(self.instance.attributes)

    def clean(self):
        cleaned = super().clean()
        try:
            cleaned["attributes"] = parse_attributes(cleaned.get("attributes_text", ""))
        except ValueError as exc:
            self.add_error("attributes_text", str(exc))
        return cleaned

    def save(self, commit=True):
        item = super().save(commit=False)
        item.attributes = self.cleaned_data.get("attributes", {})
        if commit:
            item.save()
        return item


def parse_attributes(text: str) -> dict[str, str]:
    """The textarea's `Key: value` lines as a dict of free-form facts."""
    attributes: dict[str, str] = {}
    for line in (text or "").splitlines():
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            continue
        if len(attributes) >= MAX_ATTRIBUTES:
            raise ValueError(f"A Dynamic Item can hold at most {MAX_ATTRIBUTES} attributes.")
        if len(key) > MAX_KEY_LENGTH:
            raise ValueError(f"Attribute names are limited to {MAX_KEY_LENGTH} characters.")
        if len(value) > MAX_VALUE_LENGTH:
            raise ValueError(f"Attribute values are limited to {MAX_VALUE_LENGTH} characters.")
        attributes[key] = value
    return attributes


def render_attributes(attributes: dict[str, str]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in (attributes or {}).items())


class ItemKindForm(forms.ModelForm):
    DEVICE_TYPE_CHOICES = [
        ("", "Not a device"),
        ("router", "Router"),
        ("switch", "Switch"),
        ("access_point", "Access point"),
        ("firewall", "Firewall"),
        ("printer", "Printer"),
        ("nas", "NAS"),
        ("server", "Server"),
        ("camera", "Camera"),
        ("iot", "IoT device"),
        ("other", "Other"),
    ]

    vigil_device_type = forms.ChoiceField(choices=DEVICE_TYPE_CHOICES, required=False)

    class Meta:
        model = ItemKind
        fields = ["name", "icon_color", "is_device_like", "vigil_device_type"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input"}),
            "is_device_like": forms.CheckboxInput(attrs={"class": "form-checkbox"}),
            "icon_color": forms.Select(
                attrs={"class": "form-select"},
                choices=[
                    ("sky", "Sky"),
                    ("lavender", "Lavender"),
                    ("mint", "Mint"),
                    ("peach", "Peach"),
                    ("lemon", "Lemon"),
                    ("rose", "Rose"),
                    ("coral", "Coral"),
                ],
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vigil_device_type"].widget = forms.Select(
            attrs={"class": "form-select"}, choices=self.DEVICE_TYPE_CHOICES
        )

    def save(self, commit=True):
        kind = super().save(commit=False)
        if not kind.slug:
            kind.slug = slugify(kind.name)[:70]
        highest = (
            ItemKind.objects.exclude(pk=kind.pk)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
        )
        kind.order = 10 if highest is None else highest + 10
        if commit:
            kind.save()
        return kind
