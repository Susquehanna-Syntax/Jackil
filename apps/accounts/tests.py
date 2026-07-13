from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from apps.accounts.models import User


class AvatarUploadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("aria", "aria@x.com", "password123", role="agent")
        self.client = Client(SERVER_NAME="localhost")
        self.client.force_login(self.user)

    def _img(self, size=64, name="pic.png", content_type="image/png"):
        return SimpleUploadedFile(name, b"\x89PNG" + b"0" * size, content_type=content_type)

    def test_upload_sets_data_uri(self):
        self.client.post("/accounts/profile/avatar/", {"avatar": self._img()})
        self.user.refresh_from_db()
        self.assertTrue(self.user.avatar.startswith("data:image/png;base64,"))

    def test_upload_rejects_non_image(self):
        f = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
        self.client.post("/accounts/profile/avatar/", {"avatar": f})
        self.user.refresh_from_db()
        self.assertEqual(self.user.avatar, "")

    def test_upload_rejects_oversize(self):
        big = SimpleUploadedFile(
            "big.png", b"\x89PNG" + b"0" * (2 * 1024 * 1024 + 10), content_type="image/png"
        )
        self.client.post("/accounts/profile/avatar/", {"avatar": big})
        self.user.refresh_from_db()
        self.assertEqual(self.user.avatar, "")

    def test_remove_avatar(self):
        self.user.avatar = "data:image/png;base64,AAAA"
        self.user.save()
        self.client.post("/accounts/profile/avatar/", {"remove": "1"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.avatar, "")

    def test_upload_requires_login(self):
        self.client.logout()
        r = self.client.post("/accounts/profile/avatar/", {"avatar": self._img()})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r["Location"])
