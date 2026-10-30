from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("venues/<slug:venue_slug>/", views.select_venue, name="select_venue"),
    path("venues/<slug:venue_slug>/search/", views.song_search, name="venue_song_search"),
    path("venues/<slug:venue_slug>/my-requests/", views.customer_dashboard, name="venue_customer_dashboard"),
    path("venues/<slug:venue_slug>/requests/new/<int:song_id>/", views.request_song, name="venue_request_song"),
    path("venues/<slug:venue_slug>/staff/", views.staff_dashboard, name="venue_staff_dashboard"),
    path("venues/<slug:venue_slug>/owner/", views.owner_dashboard, name="venue_owner_dashboard"),
    path("venues/<slug:venue_slug>/requests/<int:request_id>/status/", views.update_request, name="venue_update_request"),
    path("venues/<slug:venue_slug>/users/<int:user_id>/role/", views.set_user_role, name="venue_set_user_role"),
    path("venues/<slug:venue_slug>/queue/<int:entry_id>/", views.change_queue, name="venue_change_queue"),
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
