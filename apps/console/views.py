from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from apps.automation.engine import ACTION_TYPES, CONDITION_FIELDS
from apps.automation.models import AutomationRule, Macro
from apps.inbox.models import Inbox
from apps.kb.models import KBArticle
from apps.sla.models import WEEKDAYS, BusinessSchedule, SLATarget

from .decorators import admin_required
from .forms import InboxForm, KBArticleForm, MacroForm


@admin_required
def settings_home(request):
    from .models import SiteBranding

    branding = SiteBranding.get()
    if request.method == "POST":
        branding.product_name = request.POST.get("product_name", "").strip() or "Jackil"
        branding.tagline = request.POST.get("tagline", "").strip()
        accent = request.POST.get("accent", branding.accent)
        if accent in ("lavender", "mint", "peach", "sky", "rose", "coral", "lemon"):
            branding.accent = accent
        branding.save()
        messages.success(request, "Branding updated.")
        return redirect("console:settings_home")
    ctx = {
        "inbox_count": Inbox.objects.count(),
        "active_inbox_count": Inbox.objects.filter(active=True).count(),
        "default_inbox": Inbox.get_default(),
        "branding": branding,
        "accent_colors": ["lavender", "mint", "peach", "sky", "rose", "coral", "lemon"],
        "section": "home",
    }
    return render(request, "console/settings_home.html", ctx)


@admin_required
def inbox_list(request):
    ctx = {"inboxes": Inbox.objects.all(), "section": "email"}
    return render(request, "console/inbox_list.html", ctx)


@admin_required
def inbox_create(request):
    return _inbox_form(request, None)


@admin_required
def inbox_edit(request, pk):
    return _inbox_form(request, get_object_or_404(Inbox, pk=pk))


def _inbox_form(request, inbox):
    if request.method == "POST":
        form = InboxForm(request.POST, instance=inbox)
        if form.is_valid():
            obj = form.save()
            _enforce_single_default(obj)
            messages.success(request, f"Inbox “{obj.name}” saved.")
            return redirect("console:inbox_list")
    else:
        form = InboxForm(instance=inbox)
    ctx = {"form": form, "inbox": inbox, "section": "email"}
    return render(request, "console/inbox_form.html", ctx)


@admin_required
def inbox_delete(request, pk):
    inbox = get_object_or_404(Inbox, pk=pk)
    if request.method == "POST":
        name = inbox.name
        inbox.delete()
        messages.success(request, f"Inbox “{name}” deleted.")
        return redirect("console:inbox_list")
    return render(
        request, "console/inbox_confirm_delete.html", {"inbox": inbox, "section": "email"}
    )


def _enforce_single_default(inbox):
    """Only one inbox may be the default."""
    if inbox.is_default:
        Inbox.objects.exclude(pk=inbox.pk).filter(is_default=True).update(is_default=False)


@admin_required
def sla_settings(request):
    targets = list(SLATarget.objects.all())
    schedule = BusinessSchedule.active()
    if schedule is None:
        schedule = BusinessSchedule.objects.create(name="Default schedule")

    if request.method == "POST":
        for target in targets:
            resp = request.POST.get(f"response_{target.priority}")
            reso = request.POST.get(f"resolution_{target.priority}")
            if resp and resp.isdigit():
                target.response_minutes = int(resp)
            if reso and reso.isdigit():
                target.resolution_minutes = int(reso)
            target.active = request.POST.get(f"active_{target.priority}") == "on"
            target.save()

        schedule.mode = request.POST.get("mode", schedule.mode)
        schedule.workday_start = request.POST.get("workday_start") or schedule.workday_start
        schedule.workday_end = request.POST.get("workday_end") or schedule.workday_end
        selected_days = request.POST.getlist("workdays")
        if selected_days:
            schedule.workdays = ",".join(d for d in selected_days if d.isdigit())
        schedule.save()

        messages.success(request, "SLA policies updated.")
        return redirect("console:sla_settings")

    ctx = {
        "targets": targets,
        "schedule": schedule,
        "weekdays": WEEKDAYS,
        "schedule_days": schedule.workday_set(),
        "section": "sla",
    }
    return render(request, "console/sla_settings.html", ctx)


@admin_required
def kb_list(request):
    ctx = {"articles": KBArticle.objects.select_related("category", "author"), "section": "kb"}
    return render(request, "console/kb_list.html", ctx)


@admin_required
def kb_create(request):
    return _kb_form(request, None)


@admin_required
def kb_edit(request, pk):
    return _kb_form(request, get_object_or_404(KBArticle, pk=pk))


def _kb_form(request, article):
    if request.method == "POST":
        form = KBArticleForm(request.POST, instance=article)
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.author_id is None:
                obj.author = request.user
            obj.save()
            messages.success(request, f"Article “{obj.title}” saved.")
            return redirect("console:kb_list")
    else:
        form = KBArticleForm(instance=article)
    return render(
        request, "console/kb_form.html", {"form": form, "article": article, "section": "kb"}
    )


@admin_required
def kb_delete(request, pk):
    article = get_object_or_404(KBArticle, pk=pk)
    if request.method == "POST":
        title = article.title
        article.delete()
        messages.success(request, f"Article “{title}” deleted.")
        return redirect("console:kb_list")
    return render(request, "console/kb_confirm_delete.html", {"article": article, "section": "kb"})


# ── Automation: rules + macros ──────────────────────────────────────────────


@admin_required
def automation_home(request):
    ctx = {
        "rules": AutomationRule.objects.all(),
        "macros": Macro.objects.all(),
        "section": "automation",
    }
    return render(request, "console/automation_home.html", ctx)


@admin_required
def macro_create(request):
    return _macro_form(request, None)


@admin_required
def macro_edit(request, pk):
    return _macro_form(request, get_object_or_404(Macro, pk=pk))


def _macro_form(request, macro):
    if request.method == "POST":
        form = MacroForm(request.POST, instance=macro)
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.created_by_id is None:
                obj.created_by = request.user
            obj.save()
            messages.success(request, f"Macro “{obj.name}” saved.")
            return redirect("console:automation_home")
    else:
        form = MacroForm(instance=macro)
    return render(
        request, "console/macro_form.html", {"form": form, "macro": macro, "section": "automation"}
    )


@admin_required
def macro_delete(request, pk):
    macro = get_object_or_404(Macro, pk=pk)
    if request.method == "POST":
        macro.delete()
        messages.success(request, "Macro deleted.")
        return redirect("console:automation_home")
    return render(
        request, "console/macro_confirm_delete.html", {"macro": macro, "section": "automation"}
    )


@admin_required
def rule_create(request):
    return _rule_form(request, None)


@admin_required
def rule_edit(request, pk):
    return _rule_form(request, get_object_or_404(AutomationRule, pk=pk))


def _parse_rule_post(request):
    conditions = []
    fields = request.POST.getlist("cond_field")
    ops = request.POST.getlist("cond_op")
    values = request.POST.getlist("cond_value")
    for f, o, v in zip(fields, ops, values, strict=False):
        if f and v:
            conditions.append({"field": f, "op": o or "eq", "value": v})
    actions = []
    atypes = request.POST.getlist("act_type")
    avalues = request.POST.getlist("act_value")
    for t, v in zip(atypes, avalues, strict=False):
        if t and v != "":
            actions.append({"type": t, "value": v})
    return conditions, actions


def _rule_form(request, rule):
    if request.method == "POST":
        conditions, actions = _parse_rule_post(request)
        name = request.POST.get("name", "").strip()
        trigger = request.POST.get("trigger", "on_create")
        is_active = request.POST.get("is_active") == "on"
        order = request.POST.get("order", "0")
        if name:
            if rule is None:
                rule = AutomationRule()
            rule.name = name
            rule.trigger = trigger
            rule.is_active = is_active
            rule.order = int(order) if order.isdigit() else 0
            rule.conditions = conditions
            rule.actions = actions
            rule.save()
            messages.success(request, f"Rule “{rule.name}” saved.")
            return redirect("console:automation_home")
        messages.error(request, "Rule name is required.")
    ctx = {
        "rule": rule,
        "condition_fields": CONDITION_FIELDS,
        "action_types": ACTION_TYPES,
        "triggers": AutomationRule.TRIGGER_CHOICES,
        "section": "automation",
    }
    return render(request, "console/rule_form.html", ctx)


@admin_required
def rule_delete(request, pk):
    rule = get_object_or_404(AutomationRule, pk=pk)
    if request.method == "POST":
        rule.delete()
        messages.success(request, "Rule deleted.")
        return redirect("console:automation_home")
    return render(
        request, "console/rule_confirm_delete.html", {"rule": rule, "section": "automation"}
    )


# ── API keys + webhooks ─────────────────────────────────────────────────────


@admin_required
def api_home(request):
    from apps.api.models import ApiKey, Webhook

    ctx = {
        "keys": ApiKey.objects.select_related("user"),
        "webhooks": Webhook.objects.all(),
        "new_key": request.session.pop("new_api_key", None),
        "section": "api",
    }
    return render(request, "console/api_home.html", ctx)


@admin_required
def key_create(request):
    from apps.api.models import ApiKey

    if request.method == "POST":
        name = request.POST.get("name", "").strip() or "API key"
        key = ApiKey.objects.create(name=name, user=request.user)
        request.session["new_api_key"] = key.key
        messages.success(request, "API key created — copy it now, it won't be shown in full again.")
    return redirect("console:api_home")


@admin_required
def key_delete(request, pk):
    from apps.api.models import ApiKey

    if request.method == "POST":
        ApiKey.objects.filter(pk=pk).delete()
        messages.success(request, "API key revoked.")
    return redirect("console:api_home")


@admin_required
def webhook_create(request):
    return _webhook_form(request, None)


@admin_required
def webhook_edit(request, pk):
    from apps.api.models import Webhook

    return _webhook_form(request, get_object_or_404(Webhook, pk=pk))


def _webhook_form(request, webhook):
    from .forms import WebhookForm

    if request.method == "POST":
        form = WebhookForm(request.POST, instance=webhook)
        if form.is_valid():
            form.save()
            messages.success(request, "Webhook saved.")
            return redirect("console:api_home")
    else:
        form = WebhookForm(instance=webhook)
    return render(
        request, "console/webhook_form.html", {"form": form, "webhook": webhook, "section": "api"}
    )


@admin_required
def webhook_delete(request, pk):
    from apps.api.models import Webhook

    if request.method == "POST":
        Webhook.objects.filter(pk=pk).delete()
        messages.success(request, "Webhook deleted.")
    return redirect("console:api_home")


# ── Custom fields + request forms ───────────────────────────────────────────


@admin_required
def field_list(request):
    from apps.customfields.models import CustomField, RequestForm

    ctx = {
        "fields": CustomField.objects.all(),
        "forms_list": RequestForm.objects.all(),
        "section": "forms",
    }
    return render(request, "console/field_list.html", ctx)


@admin_required
def field_create(request):
    return _field_form(request, None)


@admin_required
def field_edit(request, pk):
    from apps.customfields.models import CustomField

    return _field_form(request, get_object_or_404(CustomField, pk=pk))


def _field_form(request, field):
    from .forms import CustomFieldForm

    if request.method == "POST":
        form = CustomFieldForm(request.POST, instance=field)
        if form.is_valid():
            form.save()
            messages.success(request, "Custom field saved.")
            return redirect("console:field_list")
    else:
        form = CustomFieldForm(instance=field)
    return render(
        request, "console/field_form.html", {"form": form, "field": field, "section": "forms"}
    )


@admin_required
def field_delete(request, pk):
    from apps.customfields.models import CustomField

    if request.method == "POST":
        CustomField.objects.filter(pk=pk).delete()
        messages.success(request, "Custom field deleted.")
    return redirect("console:field_list")


@admin_required
def reqform_create(request):
    return _reqform_form(request, None)


@admin_required
def reqform_edit(request, pk):
    from apps.customfields.models import RequestForm

    return _reqform_form(request, get_object_or_404(RequestForm, pk=pk))


def _reqform_form(request, reqform):
    from apps.customfields.models import CustomField, RequestFormField

    from .forms import RequestFormForm

    if request.method == "POST":
        form = RequestFormForm(request.POST, instance=reqform)
        if form.is_valid():
            obj = form.save()
            # Rebuild the form's field set from checked custom fields.
            RequestFormField.objects.filter(form=obj).delete()
            for i, field_id in enumerate(request.POST.getlist("form_fields")):
                if field_id.isdigit():
                    RequestFormField.objects.create(form=obj, field_id=int(field_id), order=i)
            messages.success(request, f"Request form “{obj.name}” saved.")
            return redirect("console:field_list")
    else:
        form = RequestFormForm(instance=reqform)
    selected_ids = list(reqform.fields.values_list("id", flat=True)) if reqform else []
    return render(
        request,
        "console/reqform_form.html",
        {
            "form": form,
            "reqform": reqform,
            "all_fields": CustomField.objects.filter(is_active=True),
            "selected_ids": selected_ids,
            "section": "forms",
        },
    )


@admin_required
def reqform_delete(request, pk):
    from apps.customfields.models import RequestForm

    if request.method == "POST":
        RequestForm.objects.filter(pk=pk).delete()
        messages.success(request, "Request form deleted.")
    return redirect("console:field_list")
