"""``ItemForm`` attribute-text boundaries: the 60/300/50 limits, malformed
lines, Windows line endings, duplicate keys — and an Item with no owner,
department or warranty."""

from django.test import TestCase

from apps.items.forms import MAX_KEY_LENGTH, MAX_VALUE_LENGTH, ItemForm
from apps.items.models import Item, ItemKind


class AttributeLimitTests(TestCase):
    """``parse_attributes`` runs inside ``ItemForm.clean``, so the form is the
    boundary where these limits are enforced."""

    def setUp(self):
        self.kind = ItemKind.objects.get(name="Server")

    def form(self, text):
        return ItemForm(
            {"name": "Edge probe", "kind": self.kind.pk, "attributes_text": text},
        )

    def errors(self, text):
        form = self.form(text)
        self.assertFalse(form.is_valid(), "form unexpectedly valid")
        return form.errors["attributes_text"]

    def test_key_of_exactly_the_limit_passes_and_one_more_fails(self):
        ok = self.form(f"{'k' * MAX_KEY_LENGTH}: value")
        self.assertTrue(ok.is_valid(), ok.errors)
        self.assertEqual(ok.cleaned_data["attributes"], {"k" * MAX_KEY_LENGTH: "value"})

        message = self.errors(f"{'k' * (MAX_KEY_LENGTH + 1)}: value")
        self.assertIn(str(MAX_KEY_LENGTH), str(message))

    def test_value_of_exactly_the_limit_passes_and_one_more_fails(self):
        ok = self.form(f"Serial: {'v' * MAX_VALUE_LENGTH}")
        self.assertTrue(ok.is_valid(), ok.errors)
        self.assertEqual(ok.cleaned_data["attributes"], {"Serial": "v" * MAX_VALUE_LENGTH})

        message = self.errors(f"Serial: {'v' * (MAX_VALUE_LENGTH + 1)}")
        self.assertIn(str(MAX_VALUE_LENGTH), str(message))

    def test_fifty_attributes_pass_and_one_more_fails(self):
        text = "\n".join(f"Key{i}: value{i}" for i in range(50))
        ok = self.form(text)
        self.assertTrue(ok.is_valid(), ok.errors)
        self.assertEqual(len(ok.cleaned_data["attributes"]), 50)

        over = "\n".join(f"Key{i}: value{i}" for i in range(51))
        message = self.errors(over)
        self.assertIn("50", str(message))

    def test_line_without_a_key_is_skipped_and_a_key_with_no_value_keeps_empty(self):
        form = self.form(": value\nKey:")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["attributes"], {"Key": ""})

    def test_windows_line_endings_parse_like_unix_ones(self):
        unix = ItemForm(
            {"name": "Edge probe", "kind": self.kind.pk, "attributes_text": "A: 1\nB: 2"}
        )
        windows = ItemForm(
            {"name": "Edge probe", "kind": self.kind.pk, "attributes_text": "A: 1\r\nB: 2"}
        )
        self.assertTrue(unix.is_valid(), unix.errors)
        self.assertTrue(windows.is_valid(), windows.errors)
        self.assertEqual(unix.cleaned_data["attributes"], windows.cleaned_data["attributes"])
        self.assertEqual(windows.cleaned_data["attributes"], {"A": "1", "B": "2"})

    def test_duplicate_keys_the_later_line_wins(self):
        form = self.form("Serial: first\nSerial: second")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["attributes"], {"Serial": "second"})


class ItemWithoutOptionalFieldsTests(TestCase):
    def test_item_can_be_created_without_owner_department_or_warranty(self):
        kind = ItemKind.objects.get(name="Server")
        form = ItemForm({"name": "Bare asset", "kind": kind.pk, "attributes_text": ""})
        self.assertTrue(form.is_valid(), form.errors)
        item = form.save()
        self.assertIsNone(item.owner)
        self.assertIsNone(item.department)
        self.assertIsNone(item.warranty_end)
        self.assertEqual(item.attributes, {})
        self.assertTrue(Item.objects.filter(pk=item.pk).exists())
