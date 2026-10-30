"""The Items list filters as you type: partial responses, live form, tab bar."""

from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.items.models import Item, ItemKind


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class ItemsLiveFilterTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.client.force_login(self.agent)
        kind = ItemKind.objects.get(name="Server")
        Item.objects.create(name="Printer", kind=kind)
        Item.objects.create(name="Router", kind=kind)

    def test_partial_returns_only_the_results_fragment(self):
        response = self.client.get(f"{reverse('items:item_list')}?q=print&partial=1")
        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("data-live-results", body)
        self.assertIn("Printer", body)
        self.assertNotIn("Router", body)
        self.assertNotIn("<html", body)

    def test_full_page_has_live_form_and_no_filter_button(self):
        body = self.client.get(reverse("items:item_list")).content.decode()
        self.assertIn("data-live-filter", body)
        self.assertIn("data-live-count", body)
        self.assertNotIn(">Filter<", body)

    def test_count_label_matches_results(self):
        body = self.client.get(f"{reverse('items:item_list')}?q=print&partial=1").content.decode()
        self.assertIn('data-count-label="1 item"', body)

    def test_empty_filtered_result_offers_clear(self):
        body = self.client.get(f"{reverse('items:item_list')}?q=zzz&partial=1").content.decode()
        self.assertIn("No items match", body)
        self.assertIn('href="/items/"', body)


class TabBarPartialTests(TestCase):
    def test_tab_bar_marks_the_active_tab(self):
        html = render_to_string(
            "partials/tab_bar.html",
            {
                "tabs": [
                    {
                        "label": "All",
                        "url": "/a/",
                        "colour": "all",
                        "active": True,
                        "count": 3,
                    },
                    {
                        "label": "Hosts",
                        "url": "/h/",
                        "colour": "sky",
                        "active": False,
                        "note": "from Vigil",
                    },
                ]
            },
        )
        self.assertIn('class="tab t-all" href="/a/" aria-selected="true"', html)
        self.assertIn('<span class="tab-count">3</span>', html)
        self.assertIn('class="tab t-sky" href="/h/">', html)
        self.assertIn('<span class="tab-note">from Vigil</span>', html)
