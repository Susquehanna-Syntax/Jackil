"""The reports API and the two pages: visibility, ownership, data and CSV."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.reports.api import DEFAULT_CARDS
from apps.reports.models import Report
from apps.reports.test_compute import ReportTestCase, make_user


class ApiVisibilityTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_index_lists_own_and_shared_reports_only(self):
        mine = self.report([{"kind": "status_mix"}], owner=self.agent)
        shared = self.report([{"kind": "status_mix"}], owner=self.colleague, shared=True)
        hidden = self.report([{"kind": "status_mix"}], owner=self.colleague)

        self.client.force_authenticate(self.agent)
        body = self.client.get("/reports/api/").json()

        listed = {row["id"] for row in body}
        self.assertEqual(listed, {str(mine.id), str(shared.id)})
        self.assertNotIn(str(hidden.id), listed)
        row = next(r for r in body if r["id"] == str(mine.id))
        self.assertEqual(row["owner"], "agent")
        self.assertTrue(row["can_edit"])
        shared_row = next(r for r in body if r["id"] == str(shared.id))
        self.assertFalse(shared_row["can_edit"])


class ApiCreateTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.agent)

    def test_create_rejects_a_range_the_model_does_not_offer(self):
        resp = self.client.post(
            "/reports/api/",
            {"name": "Bad range", "range_days": 21},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(
            "Pick a range of 7, 14, 30, 90, 180 or 365 days.",
            resp.json()["errors"],
        )

    def test_create_defaults_the_cards_when_none_are_given(self):
        resp = self.client.post(
            "/reports/api/",
            {"name": "Fresh report", "range_days": 30},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["widgets"], DEFAULT_CARDS)
        self.assertEqual(len(body["widgets"]), 4)
        self.assertTrue(Report.objects.filter(id=body["id"], owner=self.agent).exists())


class ApiOwnershipTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_only_the_owner_can_patch_or_delete(self):
        report = self.report([{"kind": "status_mix"}], owner=self.agent, shared=True)
        url = f"/reports/api/{report.id}/"
        self.client.force_authenticate(self.colleague)

        self.assertEqual(self.client.get(url).status_code, 200)
        patch = self.client.patch(url, {"name": "Hijacked"}, format="json")
        self.assertEqual(patch.status_code, 403)
        self.assertEqual(patch.json()["detail"], "Only the owner can change this report.")
        self.assertEqual(self.client.delete(url).status_code, 403)

        report.refresh_from_db()
        self.assertEqual(report.name, "Weekly")

    def test_patch_merges_and_validates(self):
        report = self.report([{"kind": "status_mix"}], owner=self.agent, description="notes")
        url = f"/reports/api/{report.id}/"
        self.client.force_authenticate(self.agent)

        bad = self.client.patch(url, {"range_days": 3}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("Pick a range of 7, 14, 30, 90, 180 or 365 days.", bad.json()["errors"])

        ok = self.client.patch(url, {"name": "Renamed"}, format="json")
        self.assertEqual(ok.status_code, 200)
        report.refresh_from_db()
        self.assertEqual(report.name, "Renamed")
        self.assertEqual(report.description, "notes")
        self.assertEqual(report.widgets, [{"kind": "status_mix"}])

    def test_delete_removes_the_report(self):
        report = self.report([{"kind": "status_mix"}], owner=self.agent)
        self.client.force_authenticate(self.agent)
        self.assertEqual(self.client.delete(f"/reports/api/{report.id}/").status_code, 204)
        self.assertFalse(Report.objects.filter(id=report.id).exists())


class WidgetCatalogTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_widget_catalog_marks_cost_cards_unavailable_for_agents(self):
        self.client.force_authenticate(self.agent)
        body = self.client.get("/reports/api/widgets/").json()

        self.assertEqual(body["groups"][0], "tickets")
        self.assertTrue(body["widgets"]["ticket_volume"]["available"])
        self.assertFalse(body["widgets"]["cost_by_project"]["available"])
        self.assertFalse(body["widgets"]["cost_per_point"]["available"])
        self.assertEqual(body["widgets"]["status_mix"]["size"], {"w": 6, "h": 4})

        admin = make_user("chief", "admin")
        self.client.force_authenticate(admin)
        as_admin = self.client.get("/reports/api/widgets/").json()
        self.assertTrue(as_admin["widgets"]["cost_by_project"]["available"])


class ReportDataTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.agent)
        self.report = self.report([{"kind": "status_mix"}, {"kind": "unknown_kind"}])

    def test_report_data_returns_an_envelope(self):
        resp = self.client.get(f"/reports/api/{self.report.id}/data/0/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["shape"], "series")
        self.assertEqual(body["data"]["kind"], "bar")

    def test_report_data_404s_a_card_index_that_is_not_there(self):
        resp = self.client.get(f"/reports/api/{self.report.id}/data/9/")
        self.assertEqual(resp.status_code, 404)

    def test_report_data_400s_a_card_whose_kind_is_unknown(self):
        resp = self.client.get(f"/reports/api/{self.report.id}/data/1/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unknown report card kind", resp.json()["detail"])

    def test_report_csv_downloads_with_a_filename(self):
        resp = self.client.get(f"/reports/api/{self.report.id}/data/0.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertEqual(resp["Content-Disposition"], 'attachment; filename="weekly-1.csv"')
        self.assertEqual(resp.content.splitlines()[0], b"Status,Tickets")

    def test_report_csv_404s_a_card_index_that_is_not_there(self):
        resp = self.client.get(f"/reports/api/{self.report.id}/data/9.csv")
        self.assertEqual(resp.status_code, 404)


class CustomerLockoutTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.report = self.report([{"kind": "status_mix"}], owner=self.agent, shared=True)
        self.client = APIClient()
        self.client.force_authenticate(self.customer)

    def test_customers_get_403_everywhere(self):
        api_urls = [
            "/reports/api/",
            "/reports/api/widgets/",
            f"/reports/api/{self.report.id}/",
            f"/reports/api/{self.report.id}/data/0/",
            f"/reports/api/{self.report.id}/data/0.csv",
        ]
        for url in api_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_customers_never_get_a_reports_page(self):
        for url in ["/reports/", f"/reports/{self.report.id}/"]:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertIn(resp.status_code, (302, 403))
                self.assertNotEqual(resp.status_code, 200)
        created = self.client.post("/reports/new/")
        self.assertIn(created.status_code, (302, 403))
        self.assertEqual(Report.objects.filter(owner=self.customer).count(), 0)


class PagesTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.agent)

    def test_list_page_shows_the_reports_you_can_see(self):
        self.report([{"kind": "status_mix"}], name="Visible report", owner=self.agent)
        self.report([{"kind": "status_mix"}], name="Hidden report", owner=self.colleague)

        body = self.client.get("/reports/").content.decode()

        self.assertIn("Visible report", body)
        self.assertNotIn("Hidden report", body)

    def test_report_page_has_one_body_per_card(self):
        report = self.report([{"kind": "status_mix"}, {"kind": "agent_load"}], owner=self.agent)
        body = self.client.get(f"/reports/{report.id}/").content.decode()

        self.assertEqual(body.count('class="rv-body"'), 2)
        self.assertIn('data-report="' + str(report.id) + '"', body)

    def test_new_report_button_creates_and_redirects(self):
        resp = self.client.post("/reports/new/")
        self.assertEqual(resp.status_code, 302)
        created = Report.objects.filter(owner=self.agent, name="Untitled report")
        self.assertEqual(created.count(), 1)
        self.assertEqual(created.first().widgets, DEFAULT_CARDS)
        self.assertEqual(resp["Location"], f"/reports/{created.first().id}/")


class EmptyListTests(TestCase):
    def setUp(self):
        self.agent = make_user("lonely", "agent")
        self.client.force_login(self.agent)

    def test_list_page_offers_to_make_the_first_report(self):
        Report.objects.all().delete()
        body = self.client.get("/reports/").content.decode()
        self.assertIn("No reports yet. Make one to start.", body)
