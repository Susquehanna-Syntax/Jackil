"""A Vigil status page's public JSON, read without the integration path."""

import urllib.error
from unittest import mock

from django.test import SimpleTestCase

from apps.vigil.client import VigilClient, VigilUnavailable


def refuse(code):
    def raise_http_error(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, code, "Not Found", {}, None)

    return raise_http_error


class StatusPageTests(SimpleTestCase):
    def test_client_status_page_reads_public_json_and_none_on_404(self):
        answer = '{"all_up": true, "up_count": 3, "total": 3, "hosts": []}'
        with mock.patch("apps.vigil.client.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = answer.encode()
            payload = VigilClient("https://vigil.example.gov/", "vjk_test").status_page(
                "Kx7pQ2mZ-v_a"
            )
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            "https://vigil.example.gov/status/Kx7pQ2mZ-v_a/data/",
        )
        self.assertEqual(payload["all_up"], True)
        self.assertEqual(payload["total"], 3)

    def test_client_status_page_is_none_when_vigil_has_no_such_page(self):
        with mock.patch("apps.vigil.client.urlopen", side_effect=refuse(404)):
            self.assertIsNone(VigilClient("https://vigil.example.gov", "vjk_test").status_page("x"))

    def test_client_status_page_still_reports_a_dead_vigil(self):
        with mock.patch("apps.vigil.client.urlopen", side_effect=refuse(500)):
            with self.assertRaises(VigilUnavailable) as caught:
                VigilClient("https://vigil.example.gov", "vjk_test").status_page("x")
        self.assertIn("Vigil had an error (500).", str(caught.exception))

    def test_client_status_page_reports_a_body_that_is_not_json_as_unreachable(self):
        with mock.patch("apps.vigil.client.urlopen", return_value=FakeResponse("<html>")):
            with self.assertRaises(VigilUnavailable) as caught:
                VigilClient("https://vigil.example.gov", "vjk_test").status_page("x")
        self.assertIn("Vigil sent an answer Jackil could not read.", str(caught.exception))


class FakeResponse:
    def __init__(self, body):
        self.body = body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, _limit=-1):
        return self.body
