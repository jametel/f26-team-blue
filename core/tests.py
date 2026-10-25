from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from core import roles
from core.models import Song, SongRequest

User = get_user_model()
PASSWORD = "pw-12345"


def make_user(username, role=None):
    user = User.objects.create_user(username=username, password=PASSWORD)
    if role:
        roles.set_role(user, role)
    return user


class RoleGroupTests(TestCase):
    def test_groups_exist_after_migrations(self):
        names = set(Group.objects.filter(name__in=roles.ROLES).values_list("name", flat=True))
        self.assertEqual(names, set(roles.ROLES))

    def test_get_role_picks_highest(self):
        user = make_user("both", roles.STAFF)
        user.groups.add(Group.objects.get(name=roles.OWNER))
        self.assertEqual(roles.get_role(user), roles.OWNER)

    def test_superuser_is_owner(self):
        admin = User.objects.create_superuser("root", password=PASSWORD)
        self.assertEqual(roles.get_role(admin), roles.OWNER)


class AuthTests(TestCase):
    def test_register_creates_customer_and_logs_in(self):
        resp = self.client.post(reverse("register"), {
            "username": "newbie",
            "password1": "a-Strong-pass-77",
            "password2": "a-Strong-pass-77",
        })
        self.assertRedirects(resp, reverse("dashboard"), fetch_redirect_response=False)
        user = User.objects.get(username="newbie")
        self.assertEqual(roles.get_role(user), roles.CUSTOMER)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_login_redirects_to_role_dashboard(self):
        cases = {
            roles.CUSTOMER: "customer_dashboard",
            roles.STAFF: "staff_dashboard",
            roles.OWNER: "owner_dashboard",
        }
        for role, target in cases.items():
            with self.subTest(role=role):
                make_user(f"u_{role}", role)
                resp = self.client.post(
                    reverse("login"),
                    {"username": f"u_{role}", "password": PASSWORD},
                    follow=True,
                )
                self.assertEqual(resp.redirect_chain[-1][0], reverse(target))
                self.assertEqual(resp.status_code, 200)
                self.client.logout()

    def test_login_honours_next(self):
        make_user("nexty", roles.STAFF)
        resp = self.client.post(
            reverse("login") + "?next=" + reverse("song_search"),
            {"username": "nexty", "password": PASSWORD},
        )
        self.assertRedirects(resp, reverse("song_search"), fetch_redirect_response=False)

    def test_logout(self):
        make_user("bye", roles.CUSTOMER)
        self.client.login(username="bye", password=PASSWORD)
        self.client.post(reverse("logout"))
        self.assertNotIn("_auth_user_id", self.client.session)


class AccessControlTests(TestCase):
    def test_anonymous_redirected_to_login(self):
        for name in ("staff_dashboard", "owner_dashboard"):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn(reverse("login"), resp["Location"])

    def test_role_matrix(self):
        allowed = {
            roles.CUSTOMER: {"customer_dashboard"},
            roles.STAFF: {"customer_dashboard", "staff_dashboard"},
            roles.OWNER: {"customer_dashboard", "staff_dashboard", "owner_dashboard"},
        }
        pages = ["customer_dashboard", "staff_dashboard", "owner_dashboard"]
        for role, ok in allowed.items():
            self.client.logout()
            make_user(f"m_{role}", role)
            self.client.login(username=f"m_{role}", password=PASSWORD)
            for page in pages:
                with self.subTest(role=role, page=page):
                    status = self.client.get(reverse(page)).status_code
                    self.assertEqual(status, 200 if page in ok else 403)

    def test_user_without_role_cannot_use_staff_pages(self):
        make_user("norole")
        self.client.login(username="norole", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("staff_dashboard")).status_code, 403)

    def test_menu_shows_only_permitted_links(self):
        make_user("menu_c", roles.CUSTOMER)
        self.client.login(username="menu_c", password=PASSWORD)
        html = self.client.get(reverse("customer_dashboard")).content.decode()
        self.assertIn("My Requests", html)
        self.assertNotIn(reverse("staff_dashboard"), html)
        self.assertNotIn(reverse("owner_dashboard"), html)


class RequestFlowTests(TestCase):
    def setUp(self):
        self.song = Song.objects.create(title="Song A", artist="Artist", musicbrainz_id="mb-1")
        self.customer = make_user("cust", roles.CUSTOMER)
        self.staff = make_user("staffer", roles.STAFF)

    def test_guest_can_request_without_login(self):
        url = reverse("request_song", args=[self.song.id])
        resp = self.client.post(url)
        self.assertRedirects(resp, reverse("customer_dashboard"), fetch_redirect_response=False)
        req = SongRequest.objects.get()
        self.assertIsNone(req.requested_by)
        self.assertTrue(req.session_key)
        self.assertContains(self.client.get(reverse("customer_dashboard")), "Song A")

    def test_duplicate_pending_is_ignored(self):
        url = reverse("request_song", args=[self.song.id])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(SongRequest.objects.count(), 1)

    def test_pending_cap_per_session(self):
        from core.views import MAX_PENDING_PER_PATRON

        for i in range(MAX_PENDING_PER_PATRON + 2):
            song = Song.objects.create(title=f"S{i}", artist="A", musicbrainz_id=f"id-{i}")
            self.client.post(reverse("request_song", args=[song.id]))
        self.assertEqual(SongRequest.objects.count(), MAX_PENDING_PER_PATRON)

    def test_sessions_do_not_see_each_others_requests(self):
        self.client.post(reverse("request_song", args=[self.song.id]))
        other = self.client_class()
        self.assertNotContains(other.get(reverse("customer_dashboard")), "Song A")

    def test_get_not_allowed(self):
        resp = self.client.get(reverse("request_song", args=[self.song.id]))
        self.assertEqual(resp.status_code, 405)

    def test_logged_in_request_records_user(self):
        self.client.login(username="cust", password=PASSWORD)
        self.client.post(reverse("request_song", args=[self.song.id]))
        self.assertEqual(SongRequest.objects.get().requested_by, self.customer)

    def test_staff_can_update_status_customer_cannot(self):
        req = SongRequest.objects.create(song=self.song, requested_by=self.customer)
        url = reverse("update_request", args=[req.id])

        self.client.login(username="cust", password=PASSWORD)
        self.assertEqual(self.client.post(url, {"status": "Approved"}).status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, SongRequest.PENDING)

        self.client.logout()
        self.client.login(username="staffer", password=PASSWORD)
        self.client.post(url, {"status": "Approved"})
        req.refresh_from_db()
        self.assertEqual(req.status, SongRequest.APPROVED)

        self.client.post(url, {"status": "Bogus"})
        req.refresh_from_db()
        self.assertEqual(req.status, SongRequest.APPROVED)


class OwnerRoleManagementTests(TestCase):
    def setUp(self):
        self.owner = make_user("boss", roles.OWNER)
        self.target = make_user("target", roles.CUSTOMER)

    def test_owner_can_promote_user(self):
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("set_user_role", args=[self.target.id]), {"role": roles.STAFF})
        self.assertEqual(roles.get_role(self.target), roles.STAFF)

    def test_owner_cannot_change_own_role(self):
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("set_user_role", args=[self.owner.id]), {"role": roles.CUSTOMER})
        self.assertEqual(roles.get_role(self.owner), roles.OWNER)

    def test_staff_cannot_change_roles(self):
        make_user("st", roles.STAFF)
        self.client.login(username="st", password=PASSWORD)
        resp = self.client.post(reverse("set_user_role", args=[self.target.id]), {"role": roles.OWNER})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(roles.get_role(self.target), roles.CUSTOMER)

    def test_invalid_role_rejected(self):
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("set_user_role", args=[self.target.id]), {"role": "Admin"})
        self.assertEqual(roles.get_role(self.target), roles.CUSTOMER)
