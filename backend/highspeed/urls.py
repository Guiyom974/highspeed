"""Root URLconf: API under /api, everything else serves the built SPA (single port)."""
from __future__ import annotations

from django.contrib import admin
from django.urls import include, path, re_path

from showcase import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("showcase.urls")),
    re_path(r"^assets/(?P<path>.+)$", views.spa_asset),
    re_path(r"^(?!api/).*$", views.spa_index),
]
