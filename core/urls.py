from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.song_search, name="song_search"),
     # Authentication
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="core/login.html"),
        name="login"
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout"
    ),

    # Role dashboards
    path("staff/", views.staff_dashboard, name="staff_dashboard"),
    path("owner/", views.owner_dashboard, name="owner_dashboard"),
]