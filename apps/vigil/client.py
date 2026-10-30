"""Read-only client for Vigil's Jackil integration endpoints."""

import json
import ssl
import urllib.error
import urllib.parse
from urllib.request import Request, urlopen

from django.core.cache import cache

TIMEOUT = 3  # seconds
TYPES = ("host", "device", "task", "playbook", "automation", "run")

MAX_IDS = 100
MAX_BYTES = 2 * 1024 * 1024

BASE_PATH = "api/v1/jackil/integration"


class VigilUnavailable(Exception):
    """Vigil could not be read; str(exc) is a sentence for the page."""


class _NotFound(Exception):
    """Internal signal: Vigil answered 404 where an item was expected."""


#: Per-item paths (one object, one widget) answer 404 with "not found"; a 404
#: anywhere else, the widget list included, means the integration is missing.
_ITEM_PATHS = tuple(f"{t}/" for t in TYPES) + ("widgets/",)


def _check_type(value):
    if value not in TYPES:
        raise ValueError(f"Unknown Vigil type: {value}")


class VigilClient:
    def __init__(self, base_url: str, key: str, timeout: float = TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.timeout = timeout

    @property
    def host(self) -> str:
        return urllib.parse.urlparse(self.base_url).netloc

    def _get(self, path, params=None):
        url = f"{self.base_url}/{BASE_PATH}/{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        # A 404 on a per-item path is Vigil's "no such item"; elsewhere it means
        # the integration itself is missing.
        try:
            payload = self._fetch(url)
        except _NotFound:
            if path != "widgets/" and path.startswith(_ITEM_PATHS):
                raise
            raise self._missing_integration() from None
        return payload

    def _fetch(self, url):
        request = Request(  # noqa: S310 - admin-entered Vigil address
            url,
            headers={
                "Authorization": f"Bearer {self.key}",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read(MAX_BYTES)
        except TimeoutError:
            raise VigilUnavailable("Vigil did not answer in time.") from None
        except ssl.SSLError:
            raise VigilUnavailable("Vigil's certificate was not accepted.") from None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise _NotFound from None
            raise self._http_failure(exc) from None
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, TimeoutError):
                raise VigilUnavailable("Vigil did not answer in time.") from None
            if isinstance(reason, ssl.SSLError):
                raise VigilUnavailable("Vigil's certificate was not accepted.") from None
            raise VigilUnavailable(f"Can't reach Vigil at {self.host}.") from None
        except OSError:
            raise VigilUnavailable(f"Can't reach Vigil at {self.host}.") from None

        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise VigilUnavailable("Vigil sent an answer Jackil could not read.") from None
        if not isinstance(payload, dict):
            raise VigilUnavailable("Vigil sent an answer Jackil could not read.")
        return payload

    @staticmethod
    def _missing_integration():
        return VigilUnavailable(
            "Vigil does not have the Jackil integration. Update Vigil to 2026.16 or later."
        )

    def _http_failure(self, exc):
        code = exc.code
        if code in (401, 403):
            return VigilUnavailable("Vigil refused the integration key.")
        if code == 404:
            return self._missing_integration()
        if code == 400:
            detail = ""
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError, OSError):
                payload = None
            if isinstance(payload, dict):
                detail = str(payload.get("error") or "")
            return VigilUnavailable(f"Vigil did not accept the request: {detail or exc.reason}.")
        return VigilUnavailable(f"Vigil had an error ({code}).")

    def _get_or_none(self, path, params=None):
        try:
            return self._get(path, params)
        except _NotFound:
            return None

    def ping(self) -> dict:
        return self._get("ping/")

    def capabilities(self) -> set[str]:
        """What this Vigil says it can do; an older Vigil lists nothing."""
        answer = self.ping()
        listed = answer.get("capabilities")
        if not isinstance(listed, list):
            return set()
        return {str(item) for item in listed}

    def licence(self) -> dict:
        return self._get("licence/")

    def search(self, q: str, type: str | None = None) -> list[dict]:
        if type is not None:
            _check_type(type)
        if len(q.strip()) < 2:
            return []
        params = {"q": q}
        if type:
            params["type"] = type
        results = self._get("search/", params).get("results")
        return list(results) if isinstance(results, list) else []

    def resolve(self, type: str, ids: list[str]) -> dict[str, dict]:
        _check_type(type)
        ids = [str(item) for item in ids if str(item)]
        if not ids:
            return {}
        items: dict[str, dict] = {}
        for start in range(0, len(ids), MAX_IDS):
            batch = ids[start : start + MAX_IDS]
            found = self._get("resolve/", {"type": type, "ids": ",".join(batch)}).get("items")
            if isinstance(found, dict):
                items.update(found)
        return items

    def detail(self, type: str, id: str) -> dict | None:
        _check_type(type)
        return self._get_or_none(f"{type}/{urllib.parse.quote(str(id), safe='')}/")

    def widgets(self) -> list[dict]:
        widgets = self._get("widgets/").get("widgets")
        return list(widgets) if isinstance(widgets, list) else []

    def widget(self, kind: str, params: dict) -> dict | None:
        return self._get_or_none(f"widgets/{urllib.parse.quote(str(kind))}/", params)

    def status_page(self, token: str) -> dict | None:
        """A Vigil status page's public JSON; None when Vigil has no such page.

        Public pages need no integration key and live outside the ``/api/v1``
        path every other call uses, so this goes straight to ``_fetch``, which
        keeps the same timeout, error mapping and size cap. Its 404 (our
        ``_NotFound``) is an ordinary answer here, not a failure.
        """
        url = f"{self.base_url}/status/{urllib.parse.quote(str(token), safe='')}/data/"
        try:
            return self._fetch(url)
        except _NotFound:
            return None


def get_client() -> VigilClient | None:
    """A client for the saved connection, or None when it is not configured."""
    from apps.vigil.models import VigilConnection

    connection = VigilConnection.get_solo()
    if not connection.is_configured:
        return None
    return VigilClient(connection.base_url, connection.get_key())


CAPABILITIES_KEY = "vigil:capabilities"
CAPABILITIES_SECONDS = 300


def vigil_capabilities() -> set[str]:
    """What the connected Vigil says it can do, cached for a few minutes.

    An older Vigil's ping has no ``capabilities`` key, and a Vigil that will
    not answer gives nothing either — the latter is not cached, so the next
    request asks again.
    """
    client = get_client()
    if client is None:
        return set()
    cached = cache.get(CAPABILITIES_KEY)
    if cached is not None:
        return set(cached)
    try:
        found = client.capabilities()
    except VigilUnavailable:
        return set()
    cache.set(CAPABILITIES_KEY, sorted(found), CAPABILITIES_SECONDS)
    return found
