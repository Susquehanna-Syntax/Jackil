"""The reports page, its data endpoints and the cost CSV download."""

from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.projects import service
from apps.projects.models import CostSettings, PersonRate
from apps.projects.test_metrics import MetricsTest, moment

REPORTS = ("burndown", "velocity", "flow")


class ReportsTest(MetricsTest):
    def show_cost_to_agents(self):
        CostSettings.objects.filter(pk=1).update(show_cost_totals_to_agents=True)

    def priced(self, points=1):
        """A done story owned by a person with a wage behind them."""
        story = self.issue(title="Priced and done", assignee=self.waged, story_points=points)
        service.move_issue(self.admin, story, self.done)
        return story

    def page(self):
        return self.client.get(reverse("projects:reports", args=["NET"]))

    def data_at(self, name, query=""):
        url = reverse("projects:reports_data", args=["NET", name])
        return self.client.get(f"{url}?{query}" if query else url)

    def csv(self, query=""):
        url = reverse("projects:reports_cost_csv", args=["NET"])
        return self.client.get(f"{url}?{query}" if query else url)

    def test_reports_page_renders_for_staff(self):
        self.login(self.agent)
        response = self.page()
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for heading in ("Burndown", "Velocity", "Cumulative flow"):
            self.assertIn(heading, body)

    def test_each_data_endpoint_returns_an_envelope(self):
        self.login(self.admin)
        self.priced()
        for name in ("burndown", "velocity", "flow"):
            response = self.data_at(name)
            self.assertEqual(response.status_code, 200, name)
            payload = response.json()
            self.assertEqual(payload["version"], 1, name)
            self.assertEqual(payload["shape"], "series", name)

        cost = self.data_at("cost")
        self.assertEqual(cost.status_code, 200)
        self.assertEqual(cost.json()["shape"], "table")

        self.assertEqual(self.data_at("bogus").status_code, 404)
        self.assertEqual(self.data_at("cost", "by=bogus").status_code, 400)

    def test_burndown_for_a_sprint_of_another_project_is_404(self):
        other = service.create_project(self.admin, "OPS", "Operations", "scrum")
        theirs = other.sprints.create(name="Theirs", start_date=date(2026, 3, 2))
        self.login(self.admin)
        response = self.data_at("burndown", f"sprint={theirs.id}")
        self.assertEqual(response.status_code, 404)

    def test_agent_cannot_see_cost_without_the_setting(self):
        self.login(self.agent)
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Download CSV", response.content.decode())
        self.assertEqual(self.data_at("cost").status_code, 403)
        self.assertEqual(self.csv().status_code, 403)

    def test_agent_with_setting_sees_epic_and_sprint_totals_not_person(self):
        self.show_cost_to_agents()
        self.priced()
        self.login(self.agent)

        page = self.page().content.decode()
        self.assertNotIn('value="person"', page)

        for query in ("by=epic", "by=sprint"):
            self.assertEqual(self.data_at("cost", query).status_code, 200, query)
            self.assertEqual(self.csv(query).status_code, 200, query)
        self.assertEqual(self.data_at("cost", "by=person").status_code, 403)
        self.assertEqual(self.csv("by=person").status_code, 403)

    def test_admin_sees_person_breakdown_and_csv(self):
        self.priced()
        self.login(self.admin)
        response = self.csv("by=person")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        lines = response.content.decode().splitlines()
        self.assertEqual(lines[0], "Person,Points done,Cost,Cost per point,Issues left out")

    def test_no_wage_in_any_agent_response(self):
        PersonRate.objects.filter(user=self.waged).update(hourly_wage=Decimal("45.00"))
        self.priced()
        self.show_cost_to_agents()
        self.login(self.agent)

        bodies = [self.page().content.decode()]
        for name in REPORTS:
            bodies.append(self.data_at(name).content.decode())
        bodies.append(self.data_at("cost").content.decode())
        for query in ("by=epic", "by=sprint"):
            bodies.append(self.csv(query).content.decode())
        for body in bodies:
            self.assertNotIn("45.00", body)

    def test_customer_403_everywhere(self):
        self.login(self.customer)
        self.assertEqual(self.page().status_code, 403)
        for name in REPORTS:
            self.assertEqual(self.data_at(name).status_code, 403, name)
        self.assertEqual(self.csv().status_code, 403)


class ReportsSprintChoiceTest(MetricsTest):
    """The burndown card's sprint list: active first, then most recently closed."""

    def test_active_sprint_is_the_default_choice(self):
        older = self.dated_sprint("Older", state="closed", closed_at=moment(date(2026, 3, 20)))
        newer = self.dated_sprint("Newer", state="closed", closed_at=moment(date(2026, 3, 27)))
        active = self.dated_sprint("Now", state="active")
        self.sprint("Undated")

        self.login(self.admin)
        response = self.client.get(reverse("projects:reports", args=["NET"]))
        sprints = response.context["sprints"]
        self.assertEqual([sprint.pk for sprint in sprints], [active.pk, newer.pk, older.pk])

    def test_burndown_defaults_to_the_first_sprint_of_the_page(self):
        self.dated_sprint("Now", state="active", start_date=date(2026, 3, 2))
        self.login(self.admin)
        response = self.client.get(reverse("projects:reports_data", args=["NET", "burndown"]))
        self.assertEqual(response.json()["data"]["labels"][0], "2026-03-02")

    def test_burndown_with_no_dated_sprint_is_an_empty_series(self):
        self.sprint("Undated")
        self.login(self.admin)
        response = self.client.get(reverse("projects:reports_data", args=["NET", "burndown"]))
        self.assertEqual(response.json()["data"], {"kind": "line", "labels": [], "series": []})
