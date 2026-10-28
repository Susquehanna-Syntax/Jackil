import re

from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.models import User

from .models import Column, CostSettings, Issue, Project

INPUT = {"class": "form-input"}
SELECT = {"class": "form-select"}
TEXTAREA = {"class": "form-textarea"}


def staff_users():
    return User.objects.filter(role__in=["agent", "admin"]).order_by("username")


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["key", "name", "method", "lead", "department", "description", "is_archived"]
        widgets = {
            "key": forms.TextInput(attrs=INPUT),
            "name": forms.TextInput(attrs=INPUT),
            "method": forms.Select(attrs=SELECT),
            "lead": forms.Select(attrs=SELECT),
            "department": forms.Select(attrs=SELECT),
            "description": forms.Textarea(attrs=TEXTAREA),
            "is_archived": forms.CheckboxInput(attrs={"class": "form-check"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lead"].required = False
        self.fields["lead"].queryset = staff_users()
        self.fields["department"].required = False
        self.fields["is_archived"].label = "Archived"

    def clean_key(self):
        key = self.cleaned_data["key"].strip().upper()
        probe = Project(key=key, name=self.cleaned_data.get("name") or "probe")
        try:
            probe.clean()
        except ValidationError as exc:
            raise ValidationError(exc.error_dict["key"][0].messages) from None
        return key


class ColumnForm(forms.ModelForm):
    class Meta:
        model = Column
        fields = ["name", "category", "order", "wip_limit"]
        widgets = {
            "name": forms.TextInput(attrs=INPUT),
            "category": forms.Select(attrs=SELECT),
            "order": forms.NumberInput(attrs=INPUT),
            "wip_limit": forms.NumberInput(attrs=INPUT),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["wip_limit"].required = False
        self.fields["wip_limit"].label = "WIP limit"
        # A new column goes to the end; the view sets its order.
        self.fields["order"].required = False


class IssueForm(forms.ModelForm):
    """Create and edit an issue. Numbering, columns and rank stay with the service."""

    class Meta:
        model = Issue
        fields = [
            "type",
            "title",
            "description",
            "parent",
            "assignee",
            "priority",
            "labels",
            "story_points",
            "sprint",
        ]
        widgets = {
            "type": forms.Select(attrs=SELECT),
            "title": forms.TextInput(attrs=INPUT),
            "description": forms.Textarea(attrs=TEXTAREA),
            "parent": forms.Select(attrs=SELECT),
            "assignee": forms.Select(attrs=SELECT),
            "priority": forms.Select(attrs=SELECT),
            "labels": forms.TextInput(attrs=INPUT),
            "story_points": forms.NumberInput(attrs=INPUT),
            "sprint": forms.Select(attrs=SELECT),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project or getattr(self.instance, "project", None)
        if self.instance.project_id is None and self.project is not None:
            # ModelForm runs the model's clean() on this instance, and the
            # parent rules compare projects, so a new issue needs its own.
            self.instance.project = self.project
        self.fields["parent"].required = False
        self.fields["parent"].queryset = (
            Issue.objects.filter(project=self.project)
            .exclude(pk=self.instance.pk)
            .order_by("number")
            if self.project is not None
            else Issue.objects.none()
        )
        self.fields["assignee"].required = False
        self.fields["assignee"].queryset = staff_users()
        self.fields["labels"].required = False
        self.fields["labels"].help_text = "Comma-separated."
        self.fields["story_points"].widget.attrs["data-points-field"] = "1"
        self.fields["labels"].initial = _labels_text(self.instance.labels)
        self.fields["story_points"].required = False
        self.fields["sprint"].required = False
        self.fields["sprint"].queryset = self._sprint_choices()
        if self.issue_type == "subtask":
            # Sub-tasks carry no points, so the field is not offered and a
            # posted value is a stale form at best.
            self.fields.pop("story_points")

    def _sprint_choices(self):
        if self.project is None:
            return Issue.objects.none()
        sprints = self.project.sprints.all()
        wanted = sprints.filter(state__in=["planned", "active"])
        if self.instance.sprint_id is not None:
            wanted = wanted | sprints.filter(pk=self.instance.sprint_id)
        return wanted

    @property
    def issue_type(self):
        if self.is_bound:
            return (self.data.get("type") or "").strip()
        return self.initial.get("type") or self.instance.type

    def clean_labels(self):
        return ",".join(_split_labels(self.cleaned_data["labels"]))

    def clean(self):
        cleaned = super().clean()
        if self.cleaned_data.get("type") == "subtask":
            # The field is not even offered for a sub-task; this covers an edit
            # that changed the type underneath a posted points value.
            cleaned["story_points"] = None
        if self.project is not None:
            cleaned["labels"] = _labels_text(cleaned.get("labels", ""))
        return cleaned


class CostSettingsForm(forms.ModelForm):
    class Meta:
        model = CostSettings
        fields = ["default_hours_per_point", "show_cost_totals_to_agents", "currency"]
        labels = {
            "default_hours_per_point": "Default hours per point",
            "show_cost_totals_to_agents": "Show cost totals to agents",
            "currency": "Currency",
        }
        widgets = {
            "default_hours_per_point": forms.NumberInput(attrs=INPUT),
            "currency": forms.TextInput(attrs=INPUT),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # "EURO" should fail with the remedy below, not Django's stock
        # max-length message; clean_currency covers every shape anyway.
        self.fields["currency"].validators = [
            v for v in self.fields["currency"].validators if getattr(v, "limit_value", None) != 3
        ]

    def clean_default_hours_per_point(self):
        hours = self.cleaned_data["default_hours_per_point"]
        if hours <= 0:
            raise forms.ValidationError("Must be more than zero.")
        return hours

    def clean_currency(self):
        code = self.cleaned_data["currency"].strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise forms.ValidationError("Use a three-letter code such as USD.")
        return code


class RateForm(forms.Form):
    """One row of the rates table, bound with prefix=f"u{user.pk}"."""

    hourly_wage = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=8,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "any"}),
    )
    sprint_hours = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=6,
        decimal_places=1,
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "any"}),
    )


def _split_labels(value) -> list[str]:
    """A label list never keeps an empty item or a repeat."""
    seen: list[str] = []
    for label in (value or "").split(","):
        label = label.strip()
        if label and label not in seen:
            seen.append(label)
    return seen


def _labels_text(value) -> str:
    return ", ".join(_split_labels(value))
