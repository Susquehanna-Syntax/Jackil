"""Vigil status-page embeds for a portal home — shown, cached, and hidden quietly."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.portals.models import Portal
from apps.portals.status import _embed, status_embeds
from apps.vigil.client import VigilUnavailable
from apps.vigil.links import DOWN_KEY


def page_json(*, all_up=True, up=3, total=3, hostname="Mail"):
    return {
        "all_up": all_up,
        "up_count": up,
        "total": total,
        "hosts": [
            {
                "id": "opaque-host-id",
                "hostname": hostname,
                "up": all_up,
                "uptime_pct": "99.95",
                "bars": [{"pct": 0.998, "state": "up", "label": "Oct 1: 99.8% up"}] * 30,
            }
        ],
    }


class FakeStatusClient:
    """Answers status_page() from a token -> payload map; never the network."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def status_page(self, token):
        self.calls.append(token)
        answer = self.pages[token]
        if isinstance(answer, Exception):
            raise answer
        return answer


class StatusEmbedsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.customer = User.objects.create_user("status-cust", "s@x.com", "pw", role="customer")
        self.portal = Portal.objects.create(
            name="Service desk",
            slug="service-desk",
            is_published=True,
            vigil_status_pages=["tok"],
        )

    def home(self):
        self.client.force_login(self.customer)
        return self.client.get(reverse("portals:portal", args=[self.portal.slug]))

    def patch_client(self, pages):
        fake = FakeStatusClient(pages)
        patcher = patch("apps.portals.status.get_client", return_value=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_portal_shows_status_embeds(self):
        self.portal.vigil_status_pages = ["Kx7pQ2mZ-v_a"]
        self.portal.save()
        self.patch_client({"Kx7pQ2mZ-v_a": page_json(all_up=False, up=2, total=3)})

        response = self.home()
        self.assertContains(response, "Service status")
        self.assertContains(response, "1 of 3 services down")
        self.assertContains(response, "Mail")
        self.assertContains(response, "99.95")
        self.assertContains(response, 'class="pt-bar pt-bar-up" title="Oct 1: 99.8% up"')
        self.assertNotContains(response, "opaque-host-id")

    def test_portal_says_all_systems_up(self):
        self.patch_client({"tok": page_json()})

        self.assertContains(self.home(), "All systems up")

    def test_embeds_hidden_when_vigil_not_connected_or_down(self):
        not_connected = patch("apps.portals.status.get_client", return_value=None)
        with not_connected:
            response = self.home()
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Service status")

        self.patch_client({"tok": page_json()})
        cache.set(DOWN_KEY, "Can't reach Vigil at vigil.example.gov.", 30)
        response = self.home()
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Service status")

    def test_missing_status_page_is_skipped_quietly(self):
        self.portal.vigil_status_pages = ["gone", "tok"]
        self.portal.save()
        fake = self.patch_client({"gone": None, "tok": page_json(hostname="Portal")})

        response = self.home()
        self.assertContains(response, "Service status")
        self.assertContains(response, "Portal")
        self.assertEqual(fake.calls, ["gone", "tok"])

    def test_embeds_are_cached(self):
        fake = self.patch_client({"tok": page_json()})

        first = status_embeds(self.portal)
        self.assertEqual(len(first), 1)
        self.assertEqual(fake.calls, ["tok"])
        self.assertEqual(status_embeds(self.portal), first)
        self.assertEqual(fake.calls, ["tok"])

        response = self.home()
        self.assertContains(response, "Mail")
        self.assertEqual(fake.calls, ["tok"])

    def test_malformed_answer_is_skipped(self):
        self.portal.vigil_status_pages = ["nonsense", "tok"]
        self.portal.save()
        self.patch_client({"nonsense": {"hosts": "not a page"}, "tok": page_json()})

        response = self.home()
        self.assertContains(response, "Service status")
        self.assertEqual(len(status_embeds(self.portal)), 1)

    def test_status_json_that_is_not_a_page_shows_no_card(self):
        """Vigil answering with a list, not the page object, is no different to garbage."""
        self.patch_client({"tok": [1, 2]})

        response = self.home()
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Service status")

    def test_vigil_down_stops_calling_for_the_rest(self):
        self.portal.vigil_status_pages = ["gone", "tok", "second", "third"]
        self.portal.save()
        fake = self.patch_client(
            {
                "gone": None,
                "tok": page_json(),
                "second": VigilUnavailable("Can't reach Vigil."),
                "third": page_json(),
            }
        )

        embeds = status_embeds(self.portal)
        self.assertEqual(len(embeds), 1)
        self.assertEqual(fake.calls, ["gone", "tok", "second"])
        self.assertEqual(cache.get(DOWN_KEY), "Can't reach Vigil.")

        response = self.home()
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Service status")


class StatusEmbedsUnitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.portal = Portal.objects.create(name="Desk", slug="desk")

    def test_nothing_listed_means_no_call_at_all(self):
        with patch("apps.portals.status.get_client") as get_client:
            self.assertEqual(status_embeds(self.portal), [])
        get_client.assert_not_called()

    def test_only_the_first_ten_pages_are_read(self):
        self.portal.vigil_status_pages = [f"tok{i}" for i in range(12)]
        fake = FakeStatusClient({f"tok{i}": page_json() for i in range(12)})
        with patch("apps.portals.status.get_client", return_value=fake):
            self.assertEqual(len(status_embeds(self.portal)), 10)
        self.assertEqual(len(fake.calls), 10)

    def test_only_the_fields_the_card_renders_survive(self):
        embed = _embed(page_json())
        host = embed["hosts"][0]
        self.assertEqual(sorted(embed), ["all_up", "headline", "hosts", "total", "up_count"])
        self.assertEqual(sorted(host), ["bars", "hostname", "up", "uptime_pct"])
        self.assertEqual(sorted(host["bars"][0]), ["label", "state"])

    def test_unsafe_bar_states_are_treated_as_nodata(self):
        payload = page_json()
        payload["hosts"][0]["bars"] = [{"state": "<script>", "label": "Oct 4: odd"}] * 2
        self.assertEqual(
            _embed(payload)["hosts"][0]["bars"],
            [{"state": "nodata", "label": "Oct 4: odd"}] * 2,
        )

    def test_answer_without_the_page_fields_is_skipped(self):
        for payload in ([], {}, {"all_up": True}, {"all_up": True, "up_count": 1}):
            with self.subTest(payload=payload):
                self.assertIsNone(_embed(payload))

    def test_headline_counts_the_services_that_are_not_up(self):
        embed = _embed(page_json(all_up=False, up=1, total=4))
        self.assertEqual(embed["headline"], "3 of 4 services down")

    def test_headline_when_every_service_answers_up(self):
        self.assertEqual(_embed(page_json())["headline"], "All systems up")

    def test_unknown_bar_state_renders_as_nodata(self):
        self.portal.vigil_status_pages = ["t"]
        payload = page_json()
        payload["hosts"][0]["bars"] = [{"state": "wobbly", "label": "Oct 3: odd"}]
        with patch("apps.portals.status.get_client", return_value=FakeStatusClient({"t": payload})):
            embed = status_embeds(self.portal)[0]
        self.assertEqual(embed["hosts"][0]["bars"], [{"state": "nodata", "label": "Oct 3: odd"}])
