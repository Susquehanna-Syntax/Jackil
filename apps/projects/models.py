"""Projects: the board's tables, the audit trail, and who costs what an hour."""

import re
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

#: "NET", "IT2", "SUPPORT24" — a letter, then up to nine letters or digits.
KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")

#: Issue types that may be a sub-task's parent.
PARENT_TYPES_FOR_SUBTASK = ("story", "task", "bug")


class Project(models.Model):
    METHOD_CHOICES = [("scrum", "Scrum"), ("kanban", "Kanban")]

    key = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default="scrum")
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="led_projects",
    )
    department = models.ForeignKey(
        "accounts.Department", null=True, blank=True, on_delete=models.SET_NULL
    )
    is_archived = models.BooleanField(default=False)
    next_number = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.key} — {self.name}"

    def clean(self):
        super().clean()
        if not KEY_RE.match(self.key or ""):
            raise ValidationError(
                {"key": "Project key must be 2-10 characters, A-Z or 0-9, starting with a letter."}
            )


class Column(models.Model):
    CATEGORY_CHOICES = [("todo", "To do"), ("in_progress", "In progress"), ("done", "Done")]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="columns")
    name = models.CharField(max_length=60)
    category = models.CharField(max_length=12, choices=CATEGORY_CHOICES)
    order = models.PositiveIntegerField(default=0)
    #: Kanban only; None means no limit.
    wip_limit = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.project.key}: {self.name}"


class Sprint(models.Model):
    STATE_CHOICES = [("planned", "Planned"), ("active", "Active"), ("closed", "Closed")]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="sprints")
    name = models.CharField(max_length=120)
    goal = models.CharField(max_length=300, blank=True, default="")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="planned")
    started_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.project.key}: {self.name}"


class Issue(models.Model):
    TYPE_CHOICES = [
        ("epic", "Epic"),
        ("story", "Story"),
        ("task", "Task"),
        ("bug", "Bug"),
        ("subtask", "Sub-task"),
    ]
    PRIORITY_CHOICES = [
        ("critical", "Critical"),
        ("high", "High"),
        ("medium", "Medium"),
        ("low", "Low"),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="issues")
    number = models.PositiveIntegerField()
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, default="story")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_issues",
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reported_issues",
    )
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="medium")
    labels = models.CharField(max_length=300, blank=True, default="")
    story_points = models.PositiveSmallIntegerField(null=True, blank=True)
    sprint = models.ForeignKey(
        Sprint, null=True, blank=True, on_delete=models.SET_NULL, related_name="issues"
    )
    column = models.ForeignKey(
        Column, null=True, blank=True, on_delete=models.SET_NULL, related_name="issues"
    )
    #: Backlog / column order, ascending.
    rank = models.FloatField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    #: Assignee frozen when the issue reaches a done column (cost.freeze_cost).
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    frozen_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    frozen_hours_per_point = models.DecimalField(
        max_digits=8, decimal_places=3, null=True, blank=True
    )

    class Meta:
        unique_together = [("project", "number")]
        ordering = ["rank", "number"]

    def __str__(self):
        return self.key

    @property
    def key(self):
        return f"{self.project.key}-{self.number}"

    @property
    def is_done(self):
        return self.column is not None and self.column.category == "done"

    def clean(self):
        super().clean()
        errors = {}
        if self.parent_id is not None:
            parent = self.parent
            if self.type == "epic":
                errors["parent"] = "An epic has no parent."
            elif parent.project_id != self.project_id:
                errors["parent"] = "A parent must be in the same project."
            elif self.type == "subtask":
                if parent.type not in PARENT_TYPES_FOR_SUBTASK:
                    errors["parent"] = "A sub-task's parent must be a story, task or bug."
            elif parent.type != "epic":
                errors["parent"] = "A story, task or bug can only sit under an epic."
        elif self.type == "subtask":
            errors["parent"] = "A sub-task must sit under a story, task or bug."
        if errors:
            raise ValidationError(errors)


class IssueComment(models.Model):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"comment on {self.issue.key}"


class IssueEvent(models.Model):
    """Audit trail, and the history burndown and cumulative flow read."""

    KIND_CHOICES = [
        ("created", "Created"),
        ("moved", "Moved column"),
        ("sprint_added", "Added to sprint"),
        ("sprint_removed", "Removed from sprint"),
        ("points", "Points changed"),
        ("assigned", "Assigned"),
        ("edited", "Edited"),
    ]

    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.kind} on {self.issue.key}"


class PersonRate(models.Model):
    """Admin-only. What an hour of this person costs and how many they work per sprint."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rate"
    )
    hourly_wage = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    sprint_hours = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)

    def __str__(self):
        return f"rate for {self.user}"


class CostSettings(models.Model):
    """Singleton (pk=1)."""

    default_hours_per_point = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("4.00")
    )
    show_cost_totals_to_agents = models.BooleanField(default=False)
    currency = models.CharField(max_length=3, default="USD")

    class Meta:
        verbose_name = "cost settings"

    def __str__(self):
        return f"cost settings ({self.currency})"

    @classmethod
    def get_solo(cls):
        solo, _created = cls.objects.get_or_create(pk=1)
        return solo
