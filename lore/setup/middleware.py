"""The setup key guards the website. `lore mcp` never sees it."""

from __future__ import annotations

import os

from django.http import HttpRequest, HttpResponse, JsonResponse


class SetupKeyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path == "/api/health":
            return self.get_response(request)
        expected = os.environ.get("LORE_SETUP_KEY", "")
        presented = (
            request.headers.get("X-Lore-Key")
            or request.GET.get("key")
            or request.COOKIES.get("lore_key")
        )
        if not expected or presented != expected:
            if request.path.startswith("/api/"):
                return JsonResponse(
                    {"error": "Open the link printed in the terminal."},
                    status=401,
                )
            return HttpResponse("Open the link printed in the terminal.", status=401)
        return self.get_response(request)
