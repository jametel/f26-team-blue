from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from unittest.mock import patch

from core import roles
from core.models import Song, SongRequest, Venue, VenueConfig

User = get_user_model()
PASSWORD = "pw-12345"


def make_user(username, role=None):
    user = User.objects.create_user(username=username, password=PASSWORD)
    if role:
        roles.set_role(user, role)
    return user


def choose_venue(client, venue):
    session = client.session
    session['venue_slug'] = venue.slug
    session.save()


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
        venue = Venue.objects.create(name='Login venue')
        cases = {
            roles.CUSTOMER: "customer_dashboard",
            roles.STAFF: "staff_dashboard",
            roles.OWNER: "owner_dashboard",
        }
        for role, target in cases.items():
            with self.subTest(role=role):
                user = make_user(f"u_{role}", role)
                if role == roles.OWNER:
                    venue.owner = user
                    venue.save()
                elif role == roles.STAFF:
                    venue.staff.add(user)
                choose_venue(self.client, venue)
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
        venue = Venue.objects.create(name='Role venue')
        allowed = {
            roles.CUSTOMER: {"customer_dashboard"},
            roles.STAFF: {"customer_dashboard", "staff_dashboard"},
            roles.OWNER: {"customer_dashboard", "staff_dashboard", "owner_dashboard"},
        }
        pages = ["customer_dashboard", "staff_dashboard", "owner_dashboard"]
        for role, ok in allowed.items():
            self.client.logout()
            user = make_user(f"m_{role}", role)
            if role == roles.OWNER:
                venue.owner = user
                venue.save()
            elif role == roles.STAFF:
                venue.staff.add(user)
            self.client.login(username=f"m_{role}", password=PASSWORD)
            choose_venue(self.client, venue)
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
        choose_venue(self.client, Venue.objects.create(name='Menu venue'))
        html = self.client.get(reverse("customer_dashboard")).content.decode()
        self.assertIn("My Requests", html)
        self.assertNotIn(reverse("staff_dashboard"), html)
        self.assertNotIn(reverse("owner_dashboard"), html)


class RequestFlowTests(TestCase):
    def setUp(self):
        self.song = Song.objects.create(title="Song A", artist="Artist", musicbrainz_id="mb-1")
        self.customer = make_user("cust", roles.CUSTOMER)
        self.staff = make_user("staffer", roles.STAFF)
        self.venue = Venue.objects.create(name='Request venue')
        self.venue.staff.add(self.staff)
        choose_venue(self.client, self.venue)

    def test_guest_can_request_without_login(self):
        url = reverse("request_song", args=[self.song.id])
        resp = self.client.post(url)
        self.assertRedirects(resp, reverse("venue_customer_dashboard", args=[self.venue.slug]), fetch_redirect_response=False)
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
        self.assertNotContains(other.get(reverse("venue_customer_dashboard", args=[self.venue.slug])), "Song A")

    def test_get_not_allowed(self):
        resp = self.client.get(reverse("request_song", args=[self.song.id]))
        self.assertEqual(resp.status_code, 405)

    def test_logged_in_request_records_user(self):
        self.client.login(username="cust", password=PASSWORD)
        self.client.post(reverse("request_song", args=[self.song.id]))
        self.assertEqual(SongRequest.objects.get().requested_by, self.customer)

    def test_staff_can_update_status_customer_cannot(self):
        req = SongRequest.objects.create(song_id=self.song, venue_id=self.venue, requested_by=self.customer)
        url = reverse("update_request", args=[req.id])

        self.client.login(username="cust", password=PASSWORD)
        self.assertEqual(self.client.post(url, {"status": "Approved"}).status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, SongRequest.PENDING)

        self.client.logout()
        self.client.login(username="staffer", password=PASSWORD)
        choose_venue(self.client, self.venue)
        self.client.post(url, {"status": "APPROVED"})
        req.refresh_from_db()
        self.assertEqual(req.status, SongRequest.APPROVED)

        self.client.post(url, {"status": "Bogus"})
        req.refresh_from_db()
        self.assertEqual(req.status, SongRequest.APPROVED)

    def test_staff_cannot_mark_pending_request_played(self):
        req = SongRequest.objects.create(song_id=self.song, venue_id=self.venue)
        self.client.login(username="staffer", password=PASSWORD)
        self.client.post(reverse("update_request", args=[req.id]), {"status": "PLAYED"})
        req.refresh_from_db()
        self.assertEqual(req.status, SongRequest.PENDING)

    @patch("core.views.MusicBrainzClient.search_songs")
    def test_search_can_save_song_with_unknown_features(self, search):
        search.return_value = [{
            "name": "New song", "artist": {"name": "Artist"}, "musicbrainz_id": "new-id",
        }]
        response = self.client.get(reverse("song_search"), {"q": "New song"})
        self.assertContains(response, "New song")
        song = Song.objects.get(musicbrainz_id="new-id")
        self.assertIsNone(song.BPM)
        self.assertIsNone(song.is_explicit)


class OwnerRoleManagementTests(TestCase):
    def setUp(self):
        self.owner = make_user("boss", roles.OWNER)
        self.target = make_user("target", roles.CUSTOMER)
        self.venue = Venue.objects.create(name='Owner venue', owner=self.owner)
        self.venue.staff.add(self.target)
        choose_venue(self.client, self.venue)

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


class VenuePolicyTests(TestCase):
    def setUp(self):
        self.owner = make_user('venue_owner', roles.OWNER)
        self.staff = make_user('venue_staff', roles.STAFF)
        self.other = make_user('other_staff', roles.STAFF)
        self.venue = Venue.objects.create(name='Coffee House', owner=self.owner)
        self.venue.staff.add(self.staff)

    def test_slug_is_unique_for_venues_with_the_same_name(self):
        other_venue = Venue.objects.create(name='Coffee House')
        self.assertTrue(self.venue.slug.startswith('coffee-house-'))
        self.assertNotEqual(self.venue.slug, other_venue.slug)

    def test_venue_access_requires_ownership_or_staff_membership(self):
        self.assertTrue(roles.can_manage_venue(self.owner, self.venue))
        self.assertTrue(roles.can_manage_venue(self.staff, self.venue))
        self.assertFalse(roles.can_manage_venue(self.other, self.venue))
        other_venue = Venue.objects.create(name='Another venue', owner=self.other)
        self.assertFalse(roles.can_manage_venue(self.staff, other_venue))
        customer = make_user('venue_customer', roles.CUSTOMER)
        self.venue.staff.add(customer)
        self.assertFalse(roles.can_manage_venue(customer, self.venue))

    def test_default_unknown_policy_requires_staff_review(self):
        config = VenueConfig.objects.create(venue=self.venue)
        self.assertEqual(config.unknown_policy, VenueConfig.UnknownPolicy.REVIEW)
        self.assertFalse(config.allow_explicit)

    def test_database_rejects_invalid_bpm_range(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            VenueConfig.objects.create(venue=self.venue, min_bpm=120, max_bpm=80)


class VenueRequestIsolationTests(TestCase):
    def setUp(self):
        self.owner = make_user('owner_a', roles.OWNER)
        self.staff = make_user('staff_a', roles.STAFF)
        self.venue = Venue.objects.create(name='Venue A', owner=self.owner)
        self.venue.staff.add(self.staff)
        self.other = Venue.objects.create(name='Venue B')
        self.song = Song.objects.create(title='A song', artist='Artist', musicbrainz_id='venue-song')

    def test_guest_requests_follow_the_venue_in_the_url(self):
        first = reverse('venue_request_song', args=[self.venue.slug, self.song.pk])
        second = reverse('venue_request_song', args=[self.other.slug, self.song.pk])
        self.client.post(first)
        self.client.post(second)
        self.assertEqual(SongRequest.objects.filter(venue_id=self.venue).count(), 1)
        self.assertEqual(SongRequest.objects.filter(venue_id=self.other).count(), 1)
        page = self.client.get(reverse('venue_customer_dashboard', args=[self.venue.slug]))
        self.assertEqual(len(page.context['requests']), 1)

    def test_staff_cannot_view_or_change_another_venue(self):
        other_request = SongRequest.objects.create(song_id=self.song, venue_id=self.other)
        self.client.login(username='staff_a', password=PASSWORD)
        response = self.client.get(reverse('venue_staff_dashboard', args=[self.other.slug]))
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            reverse('venue_update_request', args=[self.venue.slug, other_request.pk]),
            {'status': SongRequest.APPROVED},
        )
        self.assertEqual(response.status_code, 404)
        other_request.refresh_from_db()
        self.assertEqual(other_request.status, SongRequest.PENDING)

    def test_new_request_must_have_a_venue(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SongRequest.objects.create(song_id=self.song)
        legacy = SongRequest.objects.create(song_id=self.song, legacy_unassigned=True)
        self.assertIsNone(legacy.venue_id)

    def test_request_without_a_venue_is_not_created(self):
        response = self.client.post(reverse('request_song', args=[self.song.pk]))
        self.assertRedirects(response, reverse('home'))
        self.assertFalse(SongRequest.objects.exists())

    def test_owner_cannot_change_staff_from_another_venue(self):
        outsider = make_user('staff_b', roles.STAFF)
        self.other.staff.add(outsider)
        self.client.login(username='owner_a', password=PASSWORD)
        response = self.client.post(
            reverse('venue_set_user_role', args=[self.venue.slug, outsider.pk]),
            {'role': roles.CUSTOMER},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(roles.get_role(outsider), roles.STAFF)


class RequestMigrationTests(TransactionTestCase):
    def migrate_to(self, target, replace_migrations=True):
        executor = MigrationExecutor(connection)
        if not replace_migrations:
            executor.loader = MigrationLoader(connection, replace_migrations=False)
        executor.migrate([('core', target)])
        return executor.loader.project_state([('core', target)]).apps

    def tearDown(self):
        self.migrate_to('0010_request_venue_constraint')
        super().tearDown()

    def test_upgrade_from_0004_preserves_request_identity(self):
        old = self.migrate_to('0004_songrequest_session_key')
        user = old.get_model('auth', 'User').objects.create(username='legacy')
        song = old.get_model('core', 'Song').objects.create(
            title='Old song', artist='Artist', musicbrainz_id='legacy-song'
        )
        request = old.get_model('core', 'SongRequest').objects.create(
            song=song, requested_by=user, session_key='legacy-session', status='Approved'
        )
        guest = old.get_model('core', 'SongRequest').objects.create(
            song=song, session_key='guest-session', status='Pending'
        )
        created_at = request.requested_at

        current = self.migrate_to('0007_restore_request_identity')
        restored = current.get_model('core', 'SongRequest').objects.get(pk=request.pk)
        restored_song = current.get_model('core', 'Song').objects.get(pk=song.pk)
        self.assertEqual(restored.requested_by_id, user.pk)
        self.assertEqual(restored.session_key, 'legacy-session')
        self.assertEqual(restored.status, 'APPROVED')
        self.assertEqual(restored.created_at, created_at)
        self.assertIsNone(restored.venue_id_id)
        self.assertIsNone(restored_song.BPM)
        self.assertIsNone(restored_song.is_explicit)
        restored_guest = current.get_model('core', 'SongRequest').objects.get(pk=guest.pk)
        self.assertIsNone(restored_guest.requested_by_id)
        self.assertEqual(restored_guest.session_key, 'guest-session')
        self.assertEqual(restored_guest.status, 'PENDING')
        scoped = self.migrate_to('0010_request_venue_constraint')
        legacy = scoped.get_model('core', 'SongRequest').objects.get(pk=guest.pk)
        self.assertTrue(legacy.legacy_unassigned)
        self.assertIsNone(legacy.venue_id_id)

    def test_existing_original_0005_upgrades_without_replaying_it(self):
        self.migrate_to('0004_songrequest_session_key')
        old = self.migrate_to('0005_userprofile_venue_and_more', replace_migrations=False)
        user = old.get_model('auth', 'User').objects.create(username='existing')
        profile = old.get_model('core', 'UserProfile').objects.create(user_id=user.pk)
        venue = old.get_model('core', 'Venue').objects.create(name='Existing venue')
        song = old.get_model('core', 'Song').objects.create(
            title='Existing', artist='Artist', musicbrainz_id='existing-song', genre='Jazz', BPM=90
        )
        request = old.get_model('core', 'SongRequest').objects.create(
            song_id=song, user_id=profile, venue_id=venue, status='PENDING'
        )

        current = self.migrate_to('0007_restore_request_identity')
        restored = current.get_model('core', 'SongRequest').objects.get(pk=request.pk)
        self.assertEqual(restored.venue_id_id, venue.pk)
        self.assertEqual(restored.user_id_id, profile.pk)
        self.assertIsNone(restored.requested_by_id)

    def test_existing_venue_receives_a_public_slug(self):
        old = self.migrate_to('0007_restore_request_identity')
        venue = old.get_model('core', 'Venue').objects.create(name='Old venue')
        current = self.migrate_to('0008_venue_policies')
        restored = current.get_model('core', 'Venue').objects.get(pk=venue.pk)
        self.assertEqual(restored.slug, f'old-venue-{venue.pk}')
        self.assertIsNone(restored.owner_id)
