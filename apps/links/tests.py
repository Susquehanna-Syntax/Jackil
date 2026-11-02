"""Dynamic Links — relations, the type registry, and the links service."""

import re
from pathlib import Path

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from apps.accounts.models import User
from apps.links import registry
from apps.links.builtin import TicketResolver, VigilStubResolver
from apps.links.models import DynamicLink
from apps.links.registry import Resolver, get_resolver, register_type, types
from apps.links.relations import DEFAULT_RELATION, RELATIONS, label_for
from apps.links.service import LinkError, add_link, links_for, remove_link
from apps.tickets.models import Ticket

#: The forbidden words live as fragments so this file can't trip its own check.
FORBIDDEN = re.compile("C" + "MDB|" + r"\bC" + "Is?\b")


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


def make_ticket(title, creator):
    return Ticket.objects.create(title=title, description="body", created_by=creator)


class RelationsTests(SimpleTestCase):
    def test_every_relation_has_two_labels(self):
        for slug, labels in RELATIONS.items():
            with self.subTest(relation=slug):
                self.assertEqual(len(labels), 2)
                self.assertTrue(all(isinstance(label, str) and label for label in labels))

    def test_label_for_uses_the_inverse_from_the_target(self):
        self.assertEqual(label_for("fixed_by", from_source=True), "fixed by")
        self.assertEqual(label_for("fixed_by", from_source=False), "fixes")

    def test_unknown_relation_is_a_key_error(self):
        with self.assertRaises(KeyError):
            label_for("married_to", from_source=True)


class RegistryTests(SimpleTestCase):
    def test_builtin_types_are_registered(self):
        registered = types()
        self.assertIn("ticket", registered)
        for kind in ("host", "task", "playbook", "run", "automation"):
            self.assertIn(f"vigil:{kind}", registered)

    def test_register_type_replaces(self):
        class First(Resolver):
            pass

        class Second(Resolver):
            pass

        register_type("temp:thing", First())
        first = get_resolver("temp:thing")
        register_type("temp:thing", Second())
        second = get_resolver("temp:thing")
        self.assertIsInstance(first, First)
        self.assertIsInstance(second, Second)
        registry._TYPES.pop("temp:thing", None)

    def test_unknown_type_is_a_key_error(self):
        with self.assertRaises(KeyError):
            get_resolver("nothing:like:this")


class TicketResolverTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.customer = make_user("boa", "customer")
        self.mine = make_ticket("Printer on fire", self.customer)
        self.theirs = make_ticket("Printer jammed again", self.agent)

    def test_resolve_hides_tickets_a_customer_did_not_create(self):
        ids = [str(self.mine.pk), str(self.theirs.pk)]
        as_agent = get_resolver("ticket").resolve(ids, self.agent)
        self.assertEqual(set(as_agent), set(ids))
        target = as_agent[str(self.theirs.pk)]
        self.assertEqual(target.label, f"#{self.theirs.pk} Printer jammed again")
        self.assertEqual(target.url, f"/tickets/{self.theirs.pk}/")
        self.assertEqual(target.status, "Open")
        self.assertEqual(target.tone, "info")

        as_customer = get_resolver("ticket").resolve(ids, self.customer)
        self.assertEqual(set(as_customer), {str(self.mine.pk)})

    def test_search_by_number_and_by_title(self):
        resolver = get_resolver("ticket")
        by_number = resolver.search(f"#{self.theirs.pk}", self.agent, limit=10)
        self.assertEqual([t.id for t in by_number], [str(self.theirs.pk)])

        by_title = resolver.search("printer", self.agent, limit=10)
        self.assertEqual({t.id for t in by_title}, {str(self.mine.pk), str(self.theirs.pk)})

        customer_hits = resolver.search("printer", self.customer, limit=10)
        self.assertEqual([t.id for t in customer_hits], [str(self.mine.pk)])

        self.assertEqual(resolver.search("printer", self.agent, limit=1), by_title[:1])
        self.assertEqual(resolver.search("nothing matches", self.agent, limit=5), [])

    def test_from_url_accepts_full_and_bare_paths(self):
        resolver = TicketResolver()
        self.assertEqual(resolver.from_url("https://help.example.com/tickets/42/"), "42")
        self.assertEqual(resolver.from_url("/tickets/42/"), "42")
        self.assertIsNone(resolver.from_url("/tickets/42/edit/"))
        self.assertIsNone(resolver.from_url("/projects/42/"))


class VigilStubResolverTests(TestCase):
    def test_stub_targets_are_unavailable_but_named(self):
        targets = VigilStubResolver("vigil:host").resolve(["mx-01"], None)
        target = targets["mx-01"]
        self.assertFalse(target.available)
        self.assertEqual(target.label, "mx-01")
        self.assertEqual(target.status, "Vigil not connected")


class ServiceTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.admin = make_user("coral", "admin")
        self.customer = make_user("boa", "customer")
        self.first = make_ticket("Ticket one", self.agent)
        self.second = make_ticket("Ticket two", self.agent)
        self.theirs = make_ticket("Printer jammed again", self.agent)
        self.mine = make_ticket("Printer on fire", self.customer)

    def test_add_then_list_from_both_ends_with_inverse_labels(self):
        link = add_link(
            self.agent,
            ("ticket", str(self.first.pk)),
            ("ticket", str(self.second.pk)),
            "fixed_by",
        )
        from_source = links_for("ticket", str(self.first.pk), self.agent)
        self.assertEqual(len(from_source), 1)
        self.assertEqual(from_source[0].link_id, link.pk)
        self.assertEqual(from_source[0].label, "fixed by")
        self.assertEqual(from_source[0].other.id, str(self.second.pk))

        from_target = links_for("ticket", str(self.second.pk), self.agent)
        self.assertEqual([v.label for v in from_target], ["fixes"])
        self.assertEqual(from_target[0].other.id, str(self.first.pk))

    def test_customer_sees_no_links(self):
        add_link(
            self.agent,
            ("ticket", str(self.first.pk)),
            ("ticket", str(self.second.pk)),
            "affects",
        )
        self.assertEqual(links_for("ticket", str(self.first.pk), self.customer), [])

    def test_customer_cannot_add(self):
        with self.assertRaises(LinkError) as caught:
            add_link(self.customer, ("ticket", str(self.first.pk)), ("ticket", str(self.second.pk)))
        self.assertEqual(str(caught.exception), "You can't see that.")

    def test_cannot_link_to_itself(self):
        with self.assertRaises(LinkError) as caught:
            add_link(self.agent, ("ticket", str(self.first.pk)), ("ticket", str(self.first.pk)))
        self.assertEqual(str(caught.exception), "A thing cannot link to itself.")

    def test_duplicate_is_refused_in_either_direction(self):
        first, second = str(self.first.pk), str(self.second.pk)
        add_link(self.agent, ("ticket", first), ("ticket", second), "blocks")
        with self.assertRaises(LinkError) as caught:
            add_link(self.agent, ("ticket", first), ("ticket", second), "blocks")
        self.assertEqual(str(caught.exception), "Those are already linked.")
        with self.assertRaises(LinkError):
            add_link(self.agent, ("ticket", second), ("ticket", first), "blocks")
        # A different relation between the same pair is a different statement.
        add_link(self.agent, ("ticket", second), ("ticket", first), "caused_by")

    def test_unknown_type_and_relation_are_refused(self):
        with self.assertRaises(LinkError) as caught:
            add_link(self.agent, ("moon", "1"), ("ticket", str(self.second.pk)))
        self.assertEqual(str(caught.exception), "Unknown kind of thing: moon")
        with self.assertRaises(LinkError):
            add_link(
                self.agent,
                ("ticket", str(self.first.pk)),
                ("ticket", str(self.second.pk)),
                "married_to",
            )

    def test_missing_and_hidden_targets_give_the_same_message(self):
        hidden = make_ticket("Payroll export broken", self.agent)
        for target in ("424242", str(hidden.pk)):
            with self.subTest(target=target):
                with self.assertRaises(LinkError) as caught:
                    add_link(self.customer, ("ticket", str(self.mine.pk)), ("ticket", target))
                self.assertEqual(str(caught.exception), "You can't see that.")

    def test_vigil_target_keeps_a_cached_label(self):
        link = add_link(self.agent, ("ticket", str(self.first.pk)), ("vigil:host", "mx-01"))
        self.assertEqual(link.target_label_cache, "mx-01")
        self.assertIsNotNone(link.target_cached_at)

        views = links_for("ticket", str(self.first.pk), self.agent)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].relation, DEFAULT_RELATION)
        self.assertFalse(views[0].other.available)
        self.assertEqual(views[0].other.label, "mx-01")

    def test_remove_link(self):
        link = add_link(self.agent, ("ticket", str(self.first.pk)), ("vigil:host", "mx-01"))
        remove_link(self.admin, link.pk)
        self.assertFalse(DynamicLink.objects.filter(pk=link.pk).exists())
        with self.assertRaises(LinkError) as caught:
            remove_link(self.admin, link.pk)
        self.assertEqual(str(caught.exception), "No such link.")

    def test_remove_link_refuses_a_hidden_end(self):
        link = add_link(self.agent, ("ticket", str(self.theirs.pk)), ("ticket", str(self.mine.pk)))
        with self.assertRaises(LinkError) as caught:
            remove_link(self.customer, link.pk)
        self.assertEqual(str(caught.exception), "No such link.")
        self.assertTrue(DynamicLink.objects.filter(pk=link.pk).exists())

    def test_links_the_user_cannot_see_are_dropped(self):
        add_link(self.agent, ("ticket", str(self.theirs.pk)), ("ticket", str(self.mine.pk)))
        # The customer cannot see the other ticket, so neither link reaches them.
        self.assertEqual(links_for("ticket", str(self.mine.pk), self.customer), [])

    def test_links_are_ordered_by_relation_then_label(self):
        first = str(self.first.pk)
        add_link(self.agent, ("ticket", first), ("ticket", str(self.second.pk)), "part_of")
        add_link(self.agent, ("ticket", first), ("vigil:host", "zz-host"), "affects")
        add_link(self.agent, ("ticket", first), ("vigil:host", "ab-host"), "affects")
        views = links_for("ticket", first, self.admin)
        self.assertEqual(
            [(v.relation, v.other.label) for v in views],
            [
                ("affects", "ab-host"),
                ("affects", "zz-host"),
                ("part_of", f"#{self.second.pk} Ticket two"),
            ],
        )


class NamingTests(SimpleTestCase):
    def test_no_forbidden_words(self):
        root = Path(__file__).resolve().parent
        checked = 0
        for path in sorted(root.rglob("*.py")):
            if path.name == "tests.py" or "migrations" in path.parts:
                continue
            checked += 1
            self.assertIsNone(
                FORBIDDEN.search(path.read_text(encoding="utf-8")),
                f"{path.name} names the feature wrongly",
            )
        self.assertGreater(checked, 5)


class ModelTests(TestCase):
    def test_same_edge_cannot_be_stored_twice(self):
        edges = [
            DynamicLink(source_type="ticket", source_id="1", target_type="ticket", target_id="2"),
            DynamicLink(source_type="ticket", source_id="1", target_type="ticket", target_id="2"),
        ]
        with self.assertRaises(IntegrityError), transaction.atomic():
            DynamicLink.objects.bulk_create(edges)
