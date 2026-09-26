"""HighSpeed Django settings — demo-oriented, single-port, no external services."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
BIN_DIR = BACKEND_DIR.parent
APP_ROOT = BIN_DIR.parent

SECRET_KEY = os.environ.get("FASTHS_SECRET_KEY", "highspeed-local-demo-not-a-secret")
DEBUG = os.environ.get("FASTHS_DEBUG", "0") == "1"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "showcase",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "highspeed.urls"

FRONTEND_DIST = BIN_DIR / "frontend" / "dist"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [FRONTEND_DIST],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "highspeed.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BACKEND_DIR / "data" / "highspeed.sqlite3",
    }
}

DATA_DIR = BACKEND_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

AUTH_PASSWORD_VALIDATORS: list[dict] = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BACKEND_DIR / "staticfiles"
STATICFILES_DIRS = [FRONTEND_DIST / "assets"] if (FRONTEND_DIST / "assets").exists() else []

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Open local showcase: no authentication, JSON only.
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}

CORS_ALLOWED_ORIGINS = [
    "http://127.0.0.1:5174",
    "http://localhost:5174",
    "http://127.0.0.1:8010",
    "http://localhost:8010",
]
CORS_ALLOW_ALL_ORIGINS = os.environ.get("FASTHS_CORS_OPEN", "0") == "1"

# ---------------------------------------------------------------------------
# System One (Jev-class decision model) integration
# ---------------------------------------------------------------------------
# The client ships vendored at backend/systemone_vendor/systemone_client.py.
# Weights are NOT vendored: download the openjev NLI model (see models/README.md)
# and point SYSTEMONE_MODELS_DIR at the directory containing it.
SYSTEMONE = {
    "SCRIPTS_DIR": os.environ.get(
        "SYSTEMONE_SCRIPTS_DIR", str(BACKEND_DIR / "systemone_vendor")
    ),
    "MODELS_DIR": os.environ.get("SYSTEMONE_MODELS_DIR", ""),
    "PROFILE": os.environ.get("SYSTEMONE_PROFILE") or os.environ.get("FASTHS_PROFILE", "gpu-nli"),
    "CPU_FALLBACK": os.environ.get("SYSTEMONE_CPU_FALLBACK", "1") == "1",
    "PREWARM": os.environ.get("FASTHS_PREWARM", "1") == "1",
    "ACT_GATE": float(os.environ.get("FASTHS_ACT_GATE", "0.90")),
    "FLOOR": float(os.environ.get("FASTHS_FLOOR", "0.50")),
    # After engine warm-up, auto-run this many use cases in the background (launcher default).
    "AUTORUN": int(os.environ.get("FASTHS_AUTORUN", "2")),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "[{levelname}] {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": os.environ.get("FASTHS_LOGLEVEL", "INFO")},
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "showcase": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
