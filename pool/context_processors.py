from django.conf import settings


def demo_mode(request):
    """Expose DEMO_MODE to every template (banner, login buttons)."""
    return {"DEMO_MODE": settings.DEMO_MODE}
