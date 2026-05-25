from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import render


class CustomLoginView(LoginView):
    template_name = "pool/login.html"
    redirect_authenticated_user = True


@login_required
def matches(request):
    return render(request, "pool/matches.html", {"active_nav": "matches"})


@login_required
def ranking(request):
    return render(request, "pool/ranking.html", {"active_nav": "ranking"})


@login_required
def historic(request):
    return render(request, "pool/historic.html", {"active_nav": "historic"})


@login_required
def save_prediction(request):
    pass
