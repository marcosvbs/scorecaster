from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views

app_name = "pool"

urlpatterns = [
    path("login/", views.CustomLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(next_page="pool:login"), name="logout"),
    path("", views.matches, name="matches"),
    path("ranking/", views.ranking, name="ranking"),
    path("historic/", views.historic, name="historic"),
    path("predictions/save/", views.save_prediction, name="save_prediction"),
]
