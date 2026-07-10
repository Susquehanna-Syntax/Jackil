from .models import RequestForm, TicketFieldValue


def active_forms():
    return RequestForm.objects.filter(is_active=True).prefetch_related("form_fields__field")


def get_form(slug):
    return RequestForm.objects.filter(slug=slug, is_active=True).first()


def save_field_values(ticket, form, post_data):
    """Persist submitted custom-field values for a ticket. Field inputs are named
    ``cf_<key>``. Returns the list of missing required field labels (if any)."""
    missing = []
    for field in form.ordered_fields():
        raw = post_data.get(f"cf_{field.key}", "").strip()
        if field.field_type == "checkbox":
            raw = "on" if post_data.get(f"cf_{field.key}") else ""
        if field.required and not raw:
            missing.append(field.label)
        TicketFieldValue.objects.update_or_create(
            ticket=ticket, field=field, defaults={"value": raw}
        )
    return missing
