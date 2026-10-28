"""The report builder page: who may edit, what saving does to a report."""

from django.urls import reverse

from apps.reports.models import Report
from apps.reports.test_compute import ReportTestCase


class BuilderFormMixin:
    """Posting the editor's form: card rows keyed by their position."""

    def url(self, report):
        return f"/reports/{report.id}/edit/"

    def row(
        self, index, kind, *, chart="", title="", x_label="", y_label="", w="", h="", order=None
    ):
        return {
            f"card-{index}-kind": kind,
            f"card-{index}-chart": chart,
            f"card-{index}-title": title,
            f"card-{index}-x_label": x_label,
            f"card-{index}-y_label": y_label,
            f"card-{index}-w": w,
            f"card-{index}-h": h,
            f"card-{index}-order": str(index + 1) if order is None else str(order),
        }

    def form(self, report, *, rows=None, count=None, name="Weekly", range_days=30, **extra):
        fields = {
            "name": name,
            "description": report.description,
            "range_days": str(range_days),
            "action": "save",
            "card_count": str(len(rows) if rows is not None else count or 0),
        }
        for row in rows if rows is not None else []:
            fields.update(row)
        fields.update(extra)
        return fields


class BuilderAccessTests(ReportTestCase, BuilderFormMixin):
    def test_only_the_owner_may_edit(self):
        report = self.report([{"kind": "status_mix"}], owner=self.agent, shared=True)

        self.client.force_login(self.colleague)
        self.assertEqual(self.client.get(self.url(report)).status_code, 403)
        saved = self.client.post(
            self.url(report), self.form(report, rows=[self.row(0, "status_mix")])
        )
        self.assertEqual(saved.status_code, 403)
        report.refresh_from_db()
        self.assertEqual(report.name, "Weekly")

        self.client.force_login(self.customer)
        redirect = self.client.get(self.url(report))
        self.assertEqual(redirect.status_code, 302)
        self.assertEqual(redirect["Location"], reverse("tickets:dashboard"))

    def test_someone_elses_private_report_is_not_there(self):
        hidden = self.report([{"kind": "status_mix"}], owner=self.colleague)
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(self.url(hidden)).status_code, 404)


class BuilderRenderTests(ReportTestCase, BuilderFormMixin):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.agent)

    def test_edit_page_renders_current_cards_and_sources(self):
        from apps.accounts.models import Department
        from apps.tickets.models import SavedView

        sales = Department.objects.create(name="Sales")
        Department.objects.create(name="Quiet department")
        view = SavedView.objects.create(owner=self.agent, name="Urgent ones", query="q=1")

        report = self.report(
            [{"kind": "ticket_volume", "chart": "bar", "title": "How busy"}],
            departments=[sales],
            saved_views=[view],
            range_days=90,
            shared=True,
        )
        body = self.client.get(self.url(report)).content.decode()

        self.assertIn("Edit report", body)
        self.assertIn('value="ticket_volume"', body)
        self.assertIn('<option value="bar" selected>', body)
        self.assertIn('value="How busy"', body)
        self.assertIn('value="90"', body)
        self.assertIn(f'value="{sales.pk}"', body)
        self.assertIn("Sales", body)
        self.assertIn("Quiet department", body)
        self.assertIn("Urgent ones", body)
        self.assertIn('name="card-0-chart"', body)
        self.assertIn('name="add_kind"', body)
        self.assertIn("Pick one and save to add it.", body)

    def test_kinds_you_cannot_use_are_left_out_of_the_picker(self):
        report = self.report([{"kind": "ticket_volume"}])
        body = self.client.get(self.url(report)).content.decode()

        self.assertNotIn('value="cost_by_project"', body)
        self.assertIn("Ticket volume", body)

    def test_report_page_shows_edit_link_to_owner_only(self):
        report = self.report([{"kind": "status_mix"}], owner=self.agent, shared=True)

        mine = self.client.get(f"/reports/{report.id}/").content.decode()
        self.assertIn("Edit report", mine)
        self.assertIn(f"/reports/{report.id}/edit/", mine)

        self.client.force_login(self.colleague)
        theirs = self.client.get(f"/reports/{report.id}/").content.decode()
        self.assertNotIn("Edit report", theirs)


class BuilderSaveTests(ReportTestCase, BuilderFormMixin):
    """Every saved card names its chart: a select always posts one of its own
    values, so the kind's default cannot be told apart from a pick of it."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.agent)

    def test_save_updates_fields_sources_and_cards(self):
        from apps.accounts.models import Department

        sales = Department.objects.create(name="Sales")
        report = self.report([{"kind": "ticket_volume", "chart": "line"}], owner=self.agent)

        resp = self.client.post(
            self.url(report),
            self.form(
                report,
                name="Renamed report",
                range_days=90,
                shared="on",
                departments=[str(sales.pk)],
                rows=[self.row(0, "ticket_volume", chart="bar", title="Weekly volume")],
            ),
        )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], f"/reports/{report.id}/")
        report.refresh_from_db()
        self.assertEqual(report.name, "Renamed report")
        self.assertEqual(report.range_days, 90)
        self.assertTrue(report.shared)
        self.assertEqual(list(report.departments.values_list("pk", flat=True)), [sales.pk])
        self.assertEqual(
            report.widgets, [{"kind": "ticket_volume", "chart": "bar", "title": "Weekly volume"}]
        )

    def test_add_card_appends_and_returns_to_the_editor(self):
        report = self.report([{"kind": "status_mix"}], owner=self.agent)

        resp = self.client.post(
            self.url(report),
            self.form(
                report,
                rows=[self.row(0, "status_mix")],
                add_kind="ticket_volume",
            ),
        )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], f"/reports/{report.id}/edit/")
        report.refresh_from_db()
        self.assertEqual(
            report.widgets,
            [{"kind": "status_mix", "chart": "bar"}, {"kind": "ticket_volume"}],
        )

    def test_kind_change_resets_an_unsuitable_chart(self):
        report = self.report([{"kind": "csat", "chart": "line"}], owner=self.agent)

        # The chart select still shows the old kind's chart: "line" is not one
        # status_mix offers, so the kind's own default takes its place.
        self.client.post(
            self.url(report),
            self.form(report, rows=[self.row(0, "status_mix", chart="line")]),
        )

        report.refresh_from_db()
        self.assertEqual(report.widgets, [{"kind": "status_mix", "chart": "bar"}])

    def test_a_chart_that_fits_the_new_kind_is_kept(self):
        report = self.report([{"kind": "ticket_volume", "chart": "line"}], owner=self.agent)

        self.client.post(
            self.url(report),
            self.form(report, rows=[self.row(0, "sla_compliance", chart="line")]),
        )

        report.refresh_from_db()
        self.assertEqual(report.widgets, [{"kind": "sla_compliance", "chart": "line"}])

    def test_an_untouched_row_keeps_the_charts_that_were_saved(self):
        report = self.report([{"kind": "ticket_volume"}, {"kind": "status_mix"}])

        rows = [self.row(i, card["kind"]) for i, card in enumerate(report.widgets)]
        self.client.post(self.url(report), self.form(report, rows=rows))

        report.refresh_from_db()
        self.assertEqual(
            report.widgets,
            [{"kind": "ticket_volume", "chart": "line"}, {"kind": "status_mix", "chart": "bar"}],
        )


class BuilderReorderTests(ReportTestCase, BuilderFormMixin):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.agent)

    def test_remove_and_reorder_cards(self):
        report = self.report(
            [{"kind": "ticket_volume"}, {"kind": "status_mix"}, {"kind": "agent_load"}],
            owner=self.agent,
        )

        rows = [
            self.row(0, "agent_load", order=1),
            {"card-1-kind": "ticket_volume", "card-1-order": "2"},
            {
                "card-2-kind": "status_mix",
                "card-2-order": "3",
                "card-2-remove": "on",
            },
        ]
        resp = self.client.post(self.url(report), self.form(report, rows=rows))

        self.assertEqual(resp.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(
            report.widgets,
            [{"kind": "agent_load", "chart": "bar"}, {"kind": "ticket_volume", "chart": "line"}],
        )


class BuilderInvalidTests(ReportTestCase, BuilderFormMixin):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.agent)

    def test_invalid_range_rerenders_with_the_message_and_saves_nothing(self):
        report = self.report([{"kind": "status_mix"}], owner=self.agent, range_days=30)

        resp = self.client.post(
            self.url(report),
            self.form(report, name="Renamed", range_days=21, rows=[self.row(0, "status_mix")]),
        )

        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Pick a range of 7, 14, 30, 90, 180 or 365 days.", body)
        self.assertIn('value="Renamed"', body)
        report.refresh_from_db()
        self.assertEqual(report.name, "Weekly")
        self.assertEqual(report.range_days, 30)

    def test_agent_without_cost_cannot_add_a_cost_card(self):
        report = self.report([{"kind": "status_mix"}], owner=self.agent)

        resp = self.client.post(
            self.url(report),
            self.form(report, rows=[self.row(0, "status_mix")], add_kind="cost_by_project"),
        )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Card 2: you can&#x27;t add cost cards.", resp.content.decode())
        report.refresh_from_db()
        self.assertEqual(report.widgets, [{"kind": "status_mix"}])


class BuilderDeleteTests(ReportTestCase, BuilderFormMixin):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.agent)

    def test_delete_removes_the_report(self):
        report = self.report([{"kind": "status_mix"}], owner=self.agent)

        resp = self.client.post(
            self.url(report), self.form(report, rows=[self.row(0, "status_mix")], action="delete")
        )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/reports/")
        self.assertFalse(Report.objects.filter(id=report.id).exists())
