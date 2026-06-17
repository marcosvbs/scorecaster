from django.urls import path
from django.contrib.auth.views import LogoutView
from django.views.generic.base import RedirectView
from . import views

app_name = "pool"

urlpatterns = [
    path("login/", views.CustomLoginView.as_view(), name="login"),
    # Shareable shortcut to the static demo (committed under static/). GET-only
    # redirect — no DB, no auth, no view logic; the demo itself is static files.
    path(
        "demo/",
        RedirectView.as_view(url="/static/pool/demo/index.html", permanent=False),
        name="demo",
    ),
    path("logout/", LogoutView.as_view(next_page="pool:login"), name="logout"),
    path("", views.matches, name="matches"),
    path("ranking/", views.ranking, name="ranking"),
    path("historic/", views.historic, name="historic"),
    path("predictions/save/", views.save_prediction, name="save_prediction"),
    path(
        "matches/<int:match_id>/predictions/",
        views.match_predictions,
        name="match_predictions",
    ),
]
