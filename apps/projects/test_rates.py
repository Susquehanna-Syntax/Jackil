"""Adding, clearing and rejecting the wage rows on the rates page."""

import re
from decimal import Decimal

from django.urls import reverse

from apps.projects.models import CostSettings, PersonRate

from .test_backlog import BacklogTest


class RatesPageTests(BacklogTest):
    def get(self):
        return self.client.get(reverse("projects:rates"))

    def post_rates(self, **fields):
        return self.client.post(reverse("projects:rates"), data={"action": "rates", **fields})

    def post_settings(self, **fields):
        return self.client.post(reverse("projects:rates"), data={"action": "settings", **fields})

    def solo(self):
        return CostSettings.objects.get(pk=1)

    def test_rates_page_admin_only(self):
        self.login(self.agent)
        self.assertEqual(self.get().status_code, 403)
        self.login(self.customer)
        self.assertEqual(self.get().status_code, 403)
        self.login(self.admin)
        self.assertEqual(self.get().status_code, 200)

    def test_rates_page_lists_every_staff_user_not_customers(self):
        self.login(self.admin)
        body = self.get().content.decode()
        people = re.search(r'<table class="rt-table">.*?</table>', body, re.S)[0]
        self.assertIn("aria", people)
        self.assertIn("coral", people)
        self.assertNotIn("boa", people)

    def test_saving_rates_creates_and_updates(self):
        self.login(self.admin)
        response = self.post_rates(
            **{
                f"u{self.agent.pk}-hourly_wage": "30.50",
                f"u{self.agent.pk}-sprint_hours": "60",
                f"u{self.admin.pk}-hourly_wage": "",
                f"u{self.admin.pk}-sprint_hours": "",
            }
        )
        self.assertRedirects(response, reverse("projects:rates"))
        rate = PersonRate.objects.get(user=self.agent)
        self.assertEqual(rate.hourly_wage, Decimal("30.50"))
        self.assertEqual(rate.sprint_hours, Decimal("60.0"))
        self.assertFalse(PersonRate.objects.filter(user=self.admin).exists())

    def test_clearing_both_fields_removes_the_rate(self):
        PersonRate.objects.create(user=self.agent, hourly_wage="20.00", sprint_hours="30.0")
        self.login(self.admin)
        response = self.post_rates(
            **{f"u{self.agent.pk}-hourly_wage": "", f"u{self.agent.pk}-sprint_hours": ""}
        )
        self.assertRedirects(response, reverse("projects:rates"))
        self.assertFalse(PersonRate.objects.filter(user=self.agent).exists())

    def test_negative_wage_is_rejected_and_nothing_saves(self):
        self.login(self.admin)
        response = self.post_rates(
            **{
                f"u{self.agent.pk}-hourly_wage": "10.00",
                f"u{self.agent.pk}-sprint_hours": "",
                f"u{self.admin.pk}-hourly_wage": "-5",
                f"u{self.admin.pk}-sprint_hours": "",
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "greater than or equal to 0")
        self.assertFalse(PersonRate.objects.filter(user__in=[self.agent, self.admin]).exists())

    def test_hours_per_point_shows_default_without_history(self):
        self.login(self.admin)
        body = self.get().content.decode()
        self.assertIn("4.00", body)
        self.assertIn("default", body)

    def test_cost_settings_save_and_validate(self):
        self.login(self.admin)
        response = self.post_settings(default_hours_per_point="3.50", currency="eur")
        self.assertRedirects(response, reverse("projects:rates"))
        solo = self.solo()
        self.assertEqual(solo.default_hours_per_point, Decimal("3.50"))
        self.assertEqual(solo.currency, "EUR")
        self.assertFalse(solo.show_cost_totals_to_agents)

        response = self.post_settings(default_hours_per_point="0", currency="EUR")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Must be more than zero.")
        self.assertEqual(self.solo().default_hours_per_point, Decimal("3.50"))

        response = self.post_settings(default_hours_per_point="4.00", currency="EURO")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Use a three-letter code such as USD.")
        self.assertEqual(self.solo().currency, "EUR")

    def actions(self):
        body = self.client.get(reverse("projects:project_list")).content.decode()
        start = body.index('<div style="display:flex; gap:8px;">')
        return body[start : body.index("</div>", start)]

    def test_project_list_links_rates_for_admins_only(self):
        url = reverse("projects:rates")
        self.login(self.agent)
        self.assertNotIn(url, self.actions())
        self.login(self.customer)
        self.assertEqual(self.client.get(reverse("projects:project_list")).status_code, 403)
        self.login(self.admin)
        self.assertIn(url, self.actions())
