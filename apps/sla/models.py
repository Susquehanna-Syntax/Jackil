from django.db import models

WEEKDAYS = [(0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"), (4, "Fri"), (5, "Sat"), (6, "Sun")]


class BusinessSchedule(models.Model):
    MODE_CHOICES = [("24_7", "24 / 7"), ("business", "Business hours")]
    name = models.CharField(max_length=100, default="Default schedule")
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default="24_7")
    workday_start = models.TimeField(default="09:00")
    workday_end = models.TimeField(default="17:00")
    workdays = models.CharField(
        max_length=20, default="0,1,2,3,4", help_text="Comma weekday ints, Mon=0"
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    @classmethod
    def active(cls):
        """The active schedule, or None (None \u21d2 treat as 24/7)."""
        return cls.objects.filter(is_active=True).order_by("id").first()

    def workday_set(self):
        return {int(x) for x in self.workdays.split(",") if x.strip().isdigit()}


class SLATarget(models.Model):
    PRIORITY_CHOICES = [
        ("critical", "Critical"),
        ("high", "High"),
        ("medium", "Medium"),
        ("low", "Low"),
    ]
    name = models.CharField(max_length=100, blank=True, default="")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, unique=True)
    response_minutes = models.PositiveIntegerField(default=240)
    resolution_minutes = models.PositiveIntegerField(default=1440)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["priority"]

    def __str__(self):
        return f"SLA[{self.priority}] {self.response_minutes}/{self.resolution_minutes}m"
