from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from config.features import feature_enabled

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.civilsso.urls")),
    path("", include("apps.tickets.urls", namespace="tickets")),
    path("accounts/", include("apps.accounts.urls", namespace="accounts")),
    path("settings/", include("apps.console.urls", namespace="console")),
    path("help/", include("apps.kb.urls", namespace="kb")),
    path("notifications/", include("apps.notifications.urls", namespace="notifications")),
]

if feature_enabled("api"):
    urlpatterns.append(path("api/v1/", include("apps.api.urls", namespace="api")))
if feature_enabled("reports"):
    urlpatterns.append(path("reports/", include("apps.reports.urls", namespace="reports")))

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
