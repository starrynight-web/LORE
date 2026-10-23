"""Django settings for the setup site. It has no database of its own."""

from __future__ import annotations

import os

SECRET_KEY = os.environ.get("LORE_SETUP_KEY", "lore-setup-dev-key")
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
ROOT_URLCONF = "lore.setup.urls"
MIDDLEWARE = ["lore.setup.middleware.SetupKeyMiddleware"]
INSTALLED_APPS: list[str] = []
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
USE_TZ = True
APPEND_SLASH = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
