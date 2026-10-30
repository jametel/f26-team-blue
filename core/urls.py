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

    path("register/", views.register, name="register"),

    # Role dashboards
    path("dashboard/", views.dashboard, name="dashboard"),
    path("my-requests/", views.customer_dashboard, name="customer_dashboard"),
    path("staff/", views.staff_dashboard, name="staff_dashboard"),
    path("owner/", views.owner_dashboard, name="owner_dashboard"),

    # Actions
    path("requests/new/<int:song_id>/", views.request_song, name="request_song"),
    path("requests/<int:request_id>/status/", views.update_request, name="update_request"),
    path("owner/users/<int:user_id>/role/", views.set_user_role, name="set_user_role"),
]