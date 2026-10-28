"""The endpoints Vigil reads: Jackil links on a Vigil object, and widgets."""

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.api.models import ApiKey
from apps.dashboards.contract import validate_payload
from apps.items.models import Item, ItemKind
from apps.links.models import DynamicLink
from apps.tickets.models import Ticket

LINKS_URL = "/api/v1/vigil/links/"
WIDGETS_URL = "/api/v1/vigil/widgets/"


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class VigilApiTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.key = ApiKey.objects.create(name="vigil", user=self.agent)
        self.customer = make_user("boa", "customer")

    def _auth(self, key=None):
        return {"HTTP_AUTHORIZATION": f"Api-Key {key or self.key.key}"}


class LinksTests(VigilApiTests):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create(
            title="Printer on fire", description="d", created_by=self.customer, priority="high"
        )
        DynamicLink.objects.create(
            source_type="ticket",
            source_id=str(self.ticket.pk),
            target_type="vigil:host",
            target_id="h-1",
            relation="fixed_by",
            target_label_cache="edge-sw-01",
        )

    def test_links_lists_what_jackil_links_to_a_vigil_host(self):
        body = self.client.get(f"{LINKS_URL}?type=host&id=h-1", **self._auth()).json()
        self.assertEqual(body["type"], "host")
        self.assertEqual(body["id"], "h-1")
        self.assertEqual(len(body["links"]), 1)
        link = body["links"][0]
        self.assertEqual(link["relation"], "fixes")
        self.assertEqual(link["type"], "ticket")
        self.assertEqual(link["id"], str(self.ticket.pk))
        self.assertEqual(link["label"], f"#{self.ticket.pk} Printer on fire")
        self.assertTrue(link["url"].endswith(f"/tickets/{self.ticket.pk}/"))
        self.assertTrue(link["url"].startswith("http"))

    def test_links_include_items_on_that_host(self):
        kind = ItemKind.objects.first()
        switch = Item.objects.create(name="Edge switch", kind=kind, vigil_host_id="h-1")
        Item.objects.create(name="On another host", kind=kind, vigil_host_id="h-2")
        body = self.client.get(f"{LINKS_URL}?type=host&id=h-1", **self._auth()).json()
        self.assertEqual(
            body["items"],
            [
                {
                    "id": str(switch.pk),
                    "name": "Edge switch",
                    "url": f"http://testserver/items/{switch.pk}/",
                }
            ],
        )

    def test_links_of_a_task_ask_after_the_task(self):
        DynamicLink.objects.create(
            source_type="ticket",
            source_id=str(self.ticket.pk),
            target_type="vigil:task",
            target_id="t-9",
            relation="caused_by",
        )
        body = self.client.get(f"{LINKS_URL}?type=task&id=t-9", **self._auth()).json()
        self.assertEqual([link["relation"] for link in body["links"]], ["caused"])
        self.assertEqual(body["items"], [])

    def test_links_stops_at_a_hundred(self):
        kind = ItemKind.objects.first()
        for n in range(101):
            other = Ticket.objects.create(
                title=f"Bulk {n}", description="d", created_by=self.customer, priority="low"
            )
            DynamicLink.objects.create(
                source_type="ticket",
                source_id=str(other.pk),
                target_type="vigil:host",
                target_id="bulk",
                relation="relates_to",
            )
        for n in range(51):
            Item.objects.create(name=f"Bulk item {n}", kind=kind, vigil_host_id="bulk")
        body = self.client.get(f"{LINKS_URL}?type=host&id=bulk", **self._auth()).json()
        self.assertEqual(len(body["links"]), 100)
        self.assertEqual(len(body["items"]), 50)

    def test_links_refuse_unknown_type_and_missing_id(self):
        r = self.client.get(f"{LINKS_URL}?type=widget&id=h-1", **self._auth())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "Unknown type"})
        r = self.client.get(f"{LINKS_URL}?type=host&id=", **self._auth())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "Missing id"})
        r = self.client.get(LINKS_URL, **self._auth())
        self.assertEqual(r.status_code, 400)

    def test_links_need_a_staff_key(self):
        self.assertEqual(self.client.get(f"{LINKS_URL}?type=host&id=h-1").status_code, 401)
        customer_key = ApiKey.objects.create(name="cust", user=self.customer)
        r = self.client.get(
            f"{LINKS_URL}?type=host&id=h-1", HTTP_AUTHORIZATION=f"Api-Key {customer_key.key}"
        )
        self.assertEqual(r.status_code, 403)
        r = self.client.get(f"{LINKS_URL}?type=host&id=h-1", HTTP_AUTHORIZATION="Api-Key bogus")
        self.assertEqual(r.status_code, 401)

    def test_links_never_include_other_vigil_ends(self):
        DynamicLink.objects.create(
            source_type="vigil:task",
            source_id="t-9",
            target_type="vigil:host",
            target_id="h-1",
            relation="affects",
        )
        body = self.client.get(f"{LINKS_URL}?type=host&id=h-1", **self._auth()).json()
        self.assertEqual([link["type"] for link in body["links"]], ["ticket"])


class WidgetCatalogTests(VigilApiTests):
    def test_widgets_list_only_kinds_vigil_can_draw(self):
        body = self.client.get(WIDGETS_URL, **self._auth()).json()
        self.assertEqual(body["version"], 1)
        kinds = {w["kind"]: w for w in body["widgets"]}
        self.assertIn("stat_tile", kinds)
        self.assertNotIn("report_chart", kinds)
        for excluded in ("ticket_list", "sprint_burndown", "team_load", "project_cost"):
            self.assertNotIn(excluded, kinds)
        stat = kinds["stat_tile"]
        self.assertEqual(stat["title"], "Stat tile")
        self.assertEqual(stat["shape"], "stat")
        self.assertTrue(stat["description"])
        setting = stat["settings"]["stat"]
        self.assertEqual(setting["type"], "choice")
        self.assertEqual(setting["default"], "open")
        self.assertIn(["open", "open"], setting["choices"])
        self.assertEqual(kinds["volume_trend"]["settings"]["range_days"]["min"], 7)

    def test_widget_data_returns_the_envelope(self):
        body = self.client.get(f"{WIDGETS_URL}stat_tile/?stat=unassigned", **self._auth()).json()
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["shape"], "stat")
        validate_payload(body["shape"], body["data"])

    def test_unknown_widget_is_404(self):
        for kind in ("report_chart", "ticket_list", "nope"):
            r = self.client.get(f"{WIDGETS_URL}{kind}/", **self._auth())
            self.assertEqual(r.status_code, 404, kind)
            self.assertEqual(r.json(), {"error": "Unknown widget"})

    def test_widgets_need_a_staff_key(self):
        self.assertEqual(self.client.get(WIDGETS_URL).status_code, 401)
        customer_key = ApiKey.objects.create(name="cust", user=self.customer)
        r = self.client.get(WIDGETS_URL, HTTP_AUTHORIZATION=f"Api-Key {customer_key.key}")
        self.assertEqual(r.status_code, 403)


class MountTests(VigilApiTests):
    def test_links_url_is_mounted_outside_the_api_feature(self):
        self.assertEqual(reverse("vigil_api:vigil-links"), "/api/v1/vigil/links/")


class WidgetHrefTests(VigilApiTests):
    def test_widget_links_point_at_jackil_not_vigil(self):
        response = self.client.get("/api/v1/vigil/widgets/stat_tile/?stat=open", **self._auth())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["href"].startswith("http://testserver/"))
