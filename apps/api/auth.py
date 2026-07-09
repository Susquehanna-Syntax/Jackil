from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import ApiKey


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate via ``Authorization: Api-Key <key>`` header."""

    keyword = "Api-Key"

    def authenticate(self, request):
        auth = authentication.get_authorization_header(request).split()
        if not auth or auth[0].decode().lower() != self.keyword.lower():
            return None
        if len(auth) != 2:
            raise exceptions.AuthenticationFailed("Invalid Api-Key header.")
        raw_key = auth[1].decode()
        try:
            api_key = ApiKey.objects.select_related("user").get(key=raw_key, is_active=True)
        except ApiKey.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid or inactive API key.") from None
        ApiKey.objects.filter(pk=api_key.pk).update(last_used_at=timezone.now())
        return (api_key.user, api_key)

    def authenticate_header(self, request):
        # Presence of this header makes DRF return 401 (not 403) on auth failure.
        return self.keyword
