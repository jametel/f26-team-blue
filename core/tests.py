from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from tempfile import NamedTemporaryFile
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from unittest import skipUnless
from unittest.mock import patch
from io import BytesIO
from urllib.parse import urlsplit
import requests
from PIL import Image

try:
    import zxingcpp
except ImportError:
    zxingcpp = None

from core import roles
from core.models import (Queue, Song, SongDecision, SongFeatures, SongRequest, Venue, VenueConfig,
                         VenueSongBlacklist, venueGenreFilter)
from core.services.queue import move_queue_entry, set_queue_priority, update_request_status
from core.services.musicbrainz import MusicBrainzClient, MusicBrainzError
from core.services.song_features import FeatureData, get_song_features, refresh_song_features
from core.services.vibe_engine import evaluate_request
from core.services.venue import lock_venue

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


class NavigationTests(TestCase):
    def test_home_lists_venues_and_guest_can_open_requests(self):
        venue = Venue.objects.create(name='Navigation venue')
        home = self.client.get(reverse('home'))
        self.assertContains(home, reverse('select_venue', args=[venue.slug]))
        self.assertContains(home, 'An account is optional')
        self.client.get(reverse('select_venue', args=[venue.slug]))
        search = self.client.get(reverse('venue_song_search', args=[venue.slug]))
        self.assertContains(search, reverse('venue_customer_dashboard', args=[venue.slug]))
        self.assertEqual(self.client.get(reverse('venue_customer_dashboard', args=[venue.slug])).status_code, 200)

    def test_account_button_routes_users_to_their_dashboard(self):
        owner = make_user('nav_owner', roles.OWNER)
        staff = make_user('nav_staff', roles.STAFF)
        customer = make_user('nav_customer', roles.CUSTOMER)
        venue = Venue.objects.create(name='Team venue', owner=owner)
        venue.staff.add(staff)
        for user, target in ((owner, 'owner_dashboard'), (staff, 'staff_dashboard'),
                             (customer, 'customer_dashboard')):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                choose_venue(self.client, venue)
                home = self.client.get(reverse('home'))
                self.assertContains(home, f'href="{reverse("dashboard")}"')
                self.assertContains(home, f'Logged in as {user.username}')
                self.assertRedirects(self.client.get(reverse('dashboard')), reverse(target))
                self.client.logout()

    def test_admin_link_and_no_venue_prompt(self):
        admin = User.objects.create_superuser('nav_admin', password=PASSWORD)
        self.client.force_login(admin)
        home = self.client.get(reverse('home'))
        self.assertContains(home, reverse('admin:index'))
        self.assertContains(home, reverse('admin:core_venue_add'))
        response = self.client.get(reverse('dashboard'), follow=True)
        self.assertContains(response, 'Choose a venue')
        self.assertContains(response, 'Your account')
        self.assertContains(response, reverse('admin:core_venue_add'))
        venue = Venue.objects.create(name='Admin venue', owner=admin)
        response = self.client.get(reverse('venue_owner_dashboard', args=[venue.slug]))
        self.assertContains(response, reverse('admin:core_venue_change', args=[venue.pk]))

    def test_account_venue_picker_opens_the_correct_dashboard(self):
        owner = make_user('picker_owner', roles.OWNER)
        venue = Venue.objects.create(name='Owner venue', owner=owner)
        other = Venue.objects.create(name='Other venue')
        self.client.force_login(owner)
        page = self.client.get(reverse('dashboard'))
        self.assertContains(page, reverse('select_dashboard_venue', args=[venue.slug]))
        self.assertNotContains(page, reverse('select_dashboard_venue', args=[other.slug]))
        self.assertEqual(self.client.get(reverse('select_dashboard_venue', args=[other.slug])).status_code, 403)
        response = self.client.get(reverse('select_dashboard_venue', args=[venue.slug]), follow=True)
        self.assertContains(response, 'Owner Dashboard')

    def test_customer_can_choose_venue_from_account_page(self):
        customer = make_user('picker_customer', roles.CUSTOMER)
        venue = Venue.objects.create(name='Customer venue')
        self.client.force_login(customer)
        response = self.client.get(reverse('select_dashboard_venue', args=[venue.slug]), follow=True)
        self.assertContains(response, 'My Song Requests')

    def test_staff_account_with_unmanaged_venue_is_sent_to_venue_picker(self):
        staff = make_user('other_nav_staff', roles.STAFF)
        self.client.force_login(staff)
        choose_venue(self.client, Venue.objects.create(name='Unmanaged venue'))
        response = self.client.get(reverse('dashboard'), follow=True)
        self.assertContains(response, 'Choose a venue you manage')
        self.assertNotContains(response, 'Staff Dashboard')


@override_settings(PUBLIC_BASE_URL='https://music.example.test')
class VenueQRTests(TestCase):
    def setUp(self):
        self.owner = make_user('qr_owner', roles.OWNER)
        self.staff = make_user('qr_staff', roles.STAFF)
        self.other = make_user('qr_other', roles.STAFF)
        self.venue = Venue.objects.create(name='QR Venue', owner=self.owner)
        self.venue.staff.add(self.staff)

    def test_venue_managers_can_view_and_download_their_qr_code(self):
        for user in (self.owner, self.staff):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                page = self.client.get(reverse('venue_qr', args=[self.venue.slug]))
                self.assertContains(page, f'https://music.example.test/venues/{self.venue.slug}/')
                image = self.client.get(reverse('venue_qr_image', args=[self.venue.slug]), {'download': '1'})
                self.assertEqual(image['Content-Type'], 'image/png')
                self.assertIn('attachment;', image['Content-Disposition'])

    @skipUnless(zxingcpp is not None, 'Install requirements-test.txt to decode QR codes')
    def test_generated_image_scans_to_the_correct_public_venue(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('venue_qr_image', args=[self.venue.slug]))
        result = zxingcpp.read_barcode(Image.open(BytesIO(response.content)))
        self.assertIsNotNone(result)
        self.assertEqual(result.text, f'https://music.example.test/venues/{self.venue.slug}/')
        guest = self.client_class()
        entry = guest.get(reverse('select_venue', args=[self.venue.slug]), follow=True)
        self.assertEqual(entry.status_code, 200)
        self.assertContains(entry, self.venue.name)

    def test_other_users_cannot_access_qr_management(self):
        url = reverse('venue_qr', args=[self.venue.slug])
        image_url = reverse('venue_qr_image', args=[self.venue.slug])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(image_url).status_code, 403)

    def test_invalid_public_origin_is_reported_without_using_the_request_host(self):
        self.client.force_login(self.owner)
        for origin in ('', 'https://user:password@example.test', 'https://example.test/path', 'javascript:bad'):
            with self.subTest(origin=origin), self.settings(PUBLIC_BASE_URL=origin):
                page = self.client.get(reverse('venue_qr', args=[self.venue.slug]))
                self.assertContains(page, 'Set PUBLIC_BASE_URL')
                self.assertEqual(self.client.get(reverse('venue_qr_image', args=[self.venue.slug])).status_code, 503)


class RequestAvailabilityTests(TestCase):
    def setUp(self):
        self.owner = make_user('availability_owner', roles.OWNER)
        self.staff = make_user('availability_staff', roles.STAFF)
        self.other = make_user('availability_other', roles.STAFF)
        self.venue = Venue.objects.create(name='Availability venue', owner=self.owner)
        self.venue.staff.add(self.staff)
        self.song = Song.objects.create(title='Available song', artist='Artist', id='available-song')
        self.url = reverse('venue_request_availability', args=[self.venue.slug])
        self.request_url = reverse('venue_request_song', args=[self.venue.slug, self.song.pk])

    def test_owner_and_assigned_staff_can_change_availability(self):
        for user in (self.owner, self.staff):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.post(self.url, {'enabled': 'false'}).status_code, 302)
                self.venue.refresh_from_db()
                self.assertFalse(self.venue.requests_enabled)
                self.client.post(self.url, {'enabled': 'true'})
                self.venue.refresh_from_db()
                self.assertTrue(self.venue.requests_enabled)

    def test_other_users_cannot_change_availability(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.url, {'enabled': 'false'}).status_code, 403)
        self.venue.refresh_from_db()
        self.assertTrue(self.venue.requests_enabled)

    def test_disabled_venue_rejects_direct_post_and_preserves_existing_data(self):
        existing = SongRequest.objects.create(venue_id=self.venue, song_id=self.song, status=SongRequest.APPROVED)
        entry = Queue.objects.create(venue_id=self.venue, song_request_id=existing, position=1)
        self.venue.requests_enabled = False
        self.venue.save(update_fields=['requests_enabled'])
        page = self.client.get(reverse('venue_song_search', args=[self.venue.slug]))
        self.assertContains(page, 'Song requests are currently unavailable')
        response = self.client.post(self.request_url, follow=True)
        self.assertContains(response, 'Song requests are currently unavailable')
        self.assertEqual(list(SongRequest.objects.values_list('pk', flat=True)), [existing.pk])
        self.assertFalse(SongDecision.objects.exists())
        self.assertEqual(list(Queue.objects.values_list('pk', flat=True)), [entry.pk])

    def test_new_venue_accepts_requests_by_default_without_config(self):
        self.assertTrue(self.venue.requests_enabled)
        self.client.post(self.request_url)
        self.assertTrue(SongRequest.objects.filter(venue_id=self.venue).exists())

    def test_invalid_availability_is_rejected(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(self.url, {'enabled': 'invalid'}).status_code, 400)
        self.venue.refresh_from_db()
        self.assertTrue(self.venue.requests_enabled)


class RequestFlowTests(TestCase):
    def setUp(self):
        self.song = Song.objects.create(title="Song A", artist="Artist", id="mb-1")
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
            song = Song.objects.create(title=f"S{i}", artist="A", id=f"id-{i}")
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
            "title": "New song", "artist": "Artist", "id": "new-id", "genre": None, "is_explicit": False,
        }]
        response = self.client.get(reverse("song_search"), {"q": "New song"})
        self.assertContains(response, "New song")
        song = Song.objects.get(id="new-id")
        self.assertIsNone(get_song_features(song))


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


class SongFeaturesTests(TestCase):
    def setUp(self):
        self.song = Song.objects.create(title='Metadata song', artist='Artist', id='metadata')

    def test_refresh_saves_valid_provider_data(self):
        provider = type('Provider', (), {'fetch': lambda self, song: FeatureData(
            source='manual', genre='Jazz', bpm=90, is_explicit=False,
        )})()
        features = refresh_song_features(self.song, provider)
        self.assertEqual(features.bpm, 90)
        self.assertIs(features.is_explicit, False)
        self.assertEqual(features.source, 'manual')
        self.assertIsNotNone(features.refreshed_at)
        self.assertEqual(get_song_features(self.song).pk, features.pk)

    def test_unavailable_provider_keeps_cached_data(self):
        cached = SongFeatures.objects.create(song=self.song, source='manual', bpm=100)
        provider = type('Provider', (), {'fetch': lambda self, song: None})()
        self.assertEqual(refresh_song_features(self.song, provider).pk, cached.pk)
        self.assertEqual(get_song_features(self.song).bpm, 100)

    def test_invalid_provider_data_does_not_replace_the_cache(self):
        SongFeatures.objects.create(song=self.song, source='manual', bpm=100)
        provider = type('Provider', (), {'fetch': lambda self, song: FeatureData(source='bad', bpm=-1)})()
        with self.assertRaises(ValidationError):
            refresh_song_features(self.song, provider)
        self.assertEqual(get_song_features(self.song).bpm, 100)


class VenueRequestIsolationTests(TestCase):
    def setUp(self):
        self.owner = make_user('owner_a', roles.OWNER)
        self.staff = make_user('staff_a', roles.STAFF)
        self.venue = Venue.objects.create(name='Venue A', owner=self.owner)
        self.venue.staff.add(self.staff)
        self.other = Venue.objects.create(name='Venue B')
        self.song = Song.objects.create(title='A song', artist='Artist', id='venue-song')

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


class VibeEngineTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(name='Vibe venue')
        self.config = VenueConfig.objects.create(venue=self.venue, min_bpm=80, max_bpm=120)
        self.song = Song.objects.create(title='Vibe song', artist='Artist', id='vibe-song')
        self.features = SongFeatures.objects.create(
            song=self.song, source='manual', genre='Jazz', bpm=80, is_explicit=False,
        )
        venueGenreFilter.objects.create(venue_id=self.venue, genre='Jazz', is_allowed=True)

    def test_matching_song_and_bpm_boundaries_are_accepted(self):
        self.assertEqual(evaluate_request(self.venue, self.song).outcome, 'ACCEPT')
        self.features.bpm = 120
        self.features.save()
        self.assertEqual(evaluate_request(self.venue, self.song).outcome, 'ACCEPT')

    def test_blacklist_genre_explicit_and_bpm_rules_reject(self):
        VenueSongBlacklist.objects.create(venue_id=self.venue, song_id=self.song)
        self.features.genre = 'Rock'
        self.features.bpm = 121
        self.features.is_explicit = True
        self.features.save()
        result = evaluate_request(self.venue, self.song)
        self.assertEqual(result.outcome, 'REJECT')
        self.assertEqual(set(result.reasons), {
            'song_blacklisted', 'genre_not_allowed', 'bpm_out_of_range', 'explicit_content',
        })

    def test_unknown_values_follow_each_venue_policy(self):
        self.features.is_explicit = None
        self.features.genre = None
        self.features.bpm = None
        self.features.save()
        self.assertEqual(evaluate_request(self.venue, self.song).outcome, 'REVIEW')
        self.config.unknown_policy = VenueConfig.UnknownPolicy.ACCEPT
        self.config.save()
        self.assertEqual(evaluate_request(self.venue, self.song).outcome, 'ACCEPT')
        self.config.unknown_policy = VenueConfig.UnknownPolicy.REJECT
        self.config.save()
        result = evaluate_request(self.venue, self.song)
        self.assertEqual(result.outcome, 'REJECT')
        self.assertEqual(set(result.reasons), {'explicit_unknown', 'genre_unknown', 'bpm_unknown'})

    def test_legacy_features_are_not_treated_as_verified(self):
        self.features.source = 'legacy-unverified'
        self.features.save()
        self.assertEqual(evaluate_request(self.venue, self.song).outcome, 'REVIEW')

    def test_request_records_review_or_rejection(self):
        self.features.is_explicit = None
        self.features.save()
        url = reverse('venue_request_song', args=[self.venue.slug, self.song.pk])
        self.client.post(url)
        decision = SongDecision.objects.get()
        self.assertEqual(decision.outcome, 'REVIEW')
        self.assertIsNotNone(decision.request)
        self.assertIn('explicit_unknown', decision.reasons)
        other = Venue.objects.create(name='Other venue')
        VenueSongBlacklist.objects.create(venue_id=other, song_id=self.song)
        self.client.post(reverse('venue_request_song', args=[other.slug, self.song.pk]))
        rejected = SongDecision.objects.get(venue=other)
        self.assertEqual(rejected.outcome, 'REJECT')
        self.assertIsNone(rejected.request)
        self.assertFalse(SongRequest.objects.filter(venue_id=other).exists())


class QueueTests(TestCase):
    def setUp(self):
        self.staff = make_user('queue_staff', roles.STAFF)
        self.venue = Venue.objects.create(name='Queue venue')
        self.venue.staff.add(self.staff)
        self.requests = []
        for index in range(3):
            song = Song.objects.create(title=f'Song {index}', artist='Artist', id=f'queue-{index}')
            self.requests.append(SongRequest.objects.create(song_id=song, venue_id=self.venue))

    def test_approval_order_priority_and_staff_reordering(self):
        for request in self.requests:
            update_request_status(self.venue, request.pk, SongRequest.APPROVED)
        entries = list(Queue.objects.filter(venue_id=self.venue).order_by('position'))
        move_queue_entry(self.venue, entries[1].pk, 'up')
        ordered = list(Queue.objects.filter(venue_id=self.venue).order_by('-priority', 'position'))
        self.assertEqual([item.pk for item in ordered], [entries[1].pk, entries[0].pk, entries[2].pk])
        set_queue_priority(self.venue, entries[2].pk, 1)
        self.assertEqual(Queue.objects.filter(venue_id=self.venue).order_by('-priority', 'position').first().pk, entries[2].pk)

    def test_played_and_removed_requests_leave_the_queue(self):
        for request in self.requests[:2]:
            update_request_status(self.venue, request.pk, SongRequest.APPROVED)
        update_request_status(self.venue, self.requests[0].pk, SongRequest.PLAYED)
        update_request_status(self.venue, self.requests[1].pk, SongRequest.REMOVED)
        self.assertFalse(Queue.objects.filter(venue_id=self.venue).exists())
        self.requests[1].refresh_from_db()
        self.assertEqual(self.requests[1].status, SongRequest.REMOVED)

    def test_rejected_decision_cannot_be_queued(self):
        SongDecision.objects.create(
            venue=self.venue, song=self.requests[0].song_id, request=self.requests[0],
            outcome=SongDecision.Outcome.REJECT, reasons=['song_blacklisted'],
        )
        with self.assertRaises(ValueError):
            update_request_status(self.venue, self.requests[0].pk, SongRequest.APPROVED)
        self.assertFalse(Queue.objects.exists())

    def test_staff_cannot_change_another_venue_queue(self):
        other = Venue.objects.create(name='Other queue')
        request = SongRequest.objects.create(song_id=self.requests[0].song_id, venue_id=other)
        update_request_status(other, request.pk, SongRequest.APPROVED)
        entry = Queue.objects.get(song_request_id=request)
        self.client.login(username='queue_staff', password=PASSWORD)
        response = self.client.post(
            reverse('venue_change_queue', args=[self.venue.slug, entry.pk]), {'action': 'remove'},
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Queue.objects.filter(pk=entry.pk).exists())

    def test_invalid_priority_shows_a_readable_error(self):
        update_request_status(self.venue, self.requests[0].pk, SongRequest.APPROVED)
        entry = Queue.objects.get(song_request_id=self.requests[0])
        self.client.login(username='queue_staff', password=PASSWORD)
        response = self.client.post(
            reverse('venue_change_queue', args=[self.venue.slug, entry.pk]),
            {'action': 'priority', 'priority': 'invalid'}, follow=True,
        )
        self.assertContains(response, 'Priority must be a number between -10 and 10.')
        entry.refresh_from_db()
        self.assertEqual(entry.priority, 0)


class SearchReliabilityTests(TestCase):
    @patch('core.views.MusicBrainzClient.search_songs')
    def test_combined_terms_match_title_and_artist_in_cache(self, search):
        Song.objects.create(title='Dreams', artist='Fleetwood Mac', id='dreams-match')
        Song.objects.create(title='Dreams', artist='Other Artist', id='dreams-other')
        venue = Venue.objects.create(name='Search venue')
        response = self.client.get(reverse('venue_song_search', args=[venue.slug]), {'q': '  DREAM fleetwood  '})
        self.assertContains(response, 'Fleetwood Mac')
        self.assertNotContains(response, 'Other Artist')
        self.assertContains(response, reverse('venue_request_song', args=[venue.slug, Song.objects.get(id='dreams-match').pk]))
        search.assert_not_called()

    @patch('core.views.MusicBrainzClient.search_songs')
    def test_duplicate_provider_recordings_appear_once(self, search):
        recording = {'title': 'A unique recording', 'artist': 'Artist', 'id': 'duplicate-result', 'genre': None, 'is_explicit': False}
        search.return_value = [recording, recording]
        response = self.client.get(reverse('song_search'), {'q': 'provider query'})
        self.assertContains(response, 'A unique recording', count=1)
        self.assertEqual(Song.objects.filter(id='duplicate-result').count(), 1)

    @patch('core.views.MusicBrainzClient.search_songs', return_value=[])
    def test_no_matches_is_distinct_from_provider_failure(self, search):
        response = self.client.get(reverse('song_search'), {'q': 'no such recording'})
        self.assertContains(response, 'No matches found')
        self.assertNotContains(response, 'Search unavailable')

    @patch('core.views.MusicBrainzClient.search_songs')
    def test_search_by_artist_uses_local_cache(self, search):
        Song.objects.create(title='A song', artist='A unique artist', id='artist-cached')
        response = self.client.get(reverse('song_search'), {'q': 'unique artist'})
        self.assertContains(response, 'A song')
        search.assert_not_called()

    @patch('core.views.MusicBrainzClient.search_songs')
    def test_provider_results_are_shown_even_if_query_is_not_in_title(self, search):
        search.return_value = [{'title': 'Song', 'artist': 'Artist', 'id': 'provider-match', 'genre': None, 'is_explicit': False}]
        response = self.client.get(reverse('song_search'), {'q': 'a provider match'})
        self.assertContains(response, 'Song')
        self.assertTrue(Song.objects.filter(id='provider-match').exists())

    @patch('core.services.musicbrainz.requests.get', side_effect=requests.Timeout())
    def test_timeout_is_reported_as_provider_error(self, get):
        with self.assertRaises(MusicBrainzError):
            MusicBrainzClient().search_songs('song')

    @patch('core.services.musicbrainz.requests.get')
    def test_http_failure_is_reported_as_provider_error(self, get):
        get.return_value.raise_for_status.side_effect = requests.HTTPError()
        with self.assertRaises(MusicBrainzError):
            MusicBrainzClient().search_songs('song')

    @patch('core.services.musicbrainz.requests.get')
    def test_malformed_response_is_reported_as_provider_error(self, get):
        get.return_value.json.return_value = {'recordings': 'invalid'}
        with self.assertRaises(MusicBrainzError):
            MusicBrainzClient().search_songs('song')

    @patch('core.views.MusicBrainzClient.search_songs', side_effect=MusicBrainzError())
    def test_search_shows_unavailable_instead_of_no_matches(self, search):
        response = self.client.get(reverse('song_search'), {'q': 'unavailable'})
        self.assertContains(response, 'Search unavailable')
        self.assertNotContains(response, 'No matches found')

    @patch('core.views.MusicBrainzClient.search_songs', side_effect=MusicBrainzError())
    def test_cached_results_are_available_without_the_provider(self, search):
        Song.objects.create(title='Cached song', artist='Artist', id='cached')
        response = self.client.get(reverse('song_search'), {'q': 'Cached'})
        self.assertContains(response, 'Cached song')
        search.assert_not_called()

    @patch('core.services.musicbrainz.requests.get')
    def test_incomplete_recordings_are_skipped_safely(self, get):
        get.return_value.json.return_value = {'recordings': [
            None, {'id': 'valid', 'title': 'Song', 'artist-credit': None}, {'title': 'No ID'},
        ]}
        results = MusicBrainzClient().search_songs('song')
        self.assertEqual(results, [{'id': 'valid', 'title': 'Song', 'artist': 'Unknown Artist', 'genre': None, 'BPM': None, 'vibe_characteristics': None, 'is_explicit': False}])


class RequestIntegrationTests(TestCase):
    @override_settings(PUBLIC_BASE_URL='https://music.example.test')
    @skipUnless(zxingcpp is not None, 'Install requirements-test.txt to decode QR codes')
    def test_guest_flow_from_qr_to_queue_and_disabled_requests(self):
        owner = make_user('flow_owner', roles.OWNER)
        venue = Venue.objects.create(name='Flow venue', owner=owner)
        first_song = Song.objects.create(title='Flow song', artist='Artist', id='flow-song')
        second_song = Song.objects.create(title='Other song', artist='Artist', id='flow-other')
        self.client.force_login(owner)
        image = self.client.get(reverse('venue_qr_image', args=[venue.slug]))
        decoded = zxingcpp.read_barcode(Image.open(BytesIO(image.content)))
        self.assertIsNotNone(decoded)

        guest = self.client_class()
        self.assertEqual(guest.get(urlsplit(decoded.text).path, follow=True).status_code, 200)
        search = guest.get(reverse('venue_song_search', args=[venue.slug]), {'q': 'Flow song'})
        self.assertContains(search, reverse('venue_request_song', args=[venue.slug, first_song.pk]))
        guest.post(reverse('venue_request_song', args=[venue.slug, first_song.pk]))
        song_request = SongRequest.objects.get(venue_id=venue, song_id=first_song)
        self.client.post(reverse('venue_update_request', args=[venue.slug, song_request.pk]), {'status': 'APPROVED'})
        self.assertTrue(Queue.objects.filter(venue_id=venue, song_request_id=song_request).exists())

        self.client.post(reverse('venue_request_availability', args=[venue.slug]), {'enabled': 'false'})
        blocked = guest.post(reverse('venue_request_song', args=[venue.slug, second_song.pk]), follow=True)
        self.assertContains(blocked, 'Song requests are currently unavailable')
        self.assertEqual(SongRequest.objects.filter(venue_id=venue).count(), 1)
        self.assertTrue(Queue.objects.filter(venue_id=venue, song_request_id=song_request).exists())

    def test_guest_review_approval_and_status_are_scoped_to_the_session(self):
        staff = make_user('review_staff', roles.STAFF)
        venue = Venue.objects.create(name='Review venue')
        venue.staff.add(staff)
        song = Song.objects.create(id='review-flow-song', title='Review flow song', artist='Artist')
        guest = self.client_class()
        guest.get(reverse('select_venue', args=[venue.slug]))
        response = guest.post(reverse('venue_request_song', args=[venue.slug, song.pk]), follow=True)
        self.assertContains(response, 'needs staff review')
        request = SongRequest.objects.get(venue_id=venue, song_id=song)
        self.assertEqual(request.decisions.get().outcome, SongDecision.Outcome.REVIEW)
        self.assertFalse(Queue.objects.filter(song_request_id=request).exists())

        outsider = self.client_class()
        response = outsider.post(reverse('venue_update_request', args=[venue.slug, request.pk]), {'status': 'APPROVED'})
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(Queue.objects.filter(song_request_id=request).exists())
        staff_client = self.client_class()
        staff_client.force_login(staff)
        staff_client.post(reverse('venue_update_request', args=[venue.slug, request.pk]), {'status': 'APPROVED'})
        self.assertTrue(Queue.objects.filter(venue_id=venue, song_request_id=request).exists())
        self.assertContains(guest.get(reverse('venue_customer_dashboard', args=[venue.slug])), 'Approved')
        self.assertNotContains(outsider.get(reverse('venue_customer_dashboard', args=[venue.slug])), 'Review flow song')

    def test_guest_request_reaches_the_staff_queue(self):
        staff = make_user('integration_staff', roles.STAFF)
        venue = Venue.objects.create(name='Integration venue')
        venue.staff.add(staff)
        VenueConfig.objects.create(venue=venue, min_bpm=80, max_bpm=120)
        song = Song.objects.create(title='Integration song', artist='Artist', id='integration')
        SongFeatures.objects.create(song=song, source='manual', bpm=100, is_explicit=False)

        self.client.get(reverse('select_venue', args=[venue.slug]))
        search = self.client.get(reverse('venue_song_search', args=[venue.slug]), {'q': 'Integration'})
        self.assertContains(search, 'Integration song')
        self.assertContains(search, reverse('venue_request_song', args=[venue.slug, song.pk]))
        self.client.post(reverse('venue_request_song', args=[venue.slug, song.pk]))
        song_request = SongRequest.objects.get(venue_id=venue)
        self.assertEqual(song_request.decisions.get().outcome, SongDecision.Outcome.ACCEPT)
        self.assertContains(self.client.get(reverse('venue_customer_dashboard', args=[venue.slug])), 'Integration song')

        staff_client = self.client_class()
        staff_client.login(username='integration_staff', password=PASSWORD)
        staff_client.post(reverse('venue_update_request', args=[venue.slug, song_request.pk]), {'status': 'APPROVED'})
        self.assertTrue(Queue.objects.filter(venue_id=venue, song_request_id=song_request).exists())
        self.assertContains(self.client.get(reverse('venue_customer_dashboard', args=[venue.slug])), 'Approved')
        staff_client.post(reverse('venue_update_request', args=[venue.slug, song_request.pk]), {'status': 'PLAYED'})
        song_request.refresh_from_db()
        self.assertEqual(song_request.status, SongRequest.PLAYED)
        self.assertFalse(Queue.objects.filter(song_request_id=song_request).exists())


@skipUnless(connection.vendor == 'postgresql', 'Request concurrency requires PostgreSQL')
class RequestSubmissionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        for role in roles.ROLES:
            Group.objects.get_or_create(name=role)
        self.venue = Venue.objects.create(name='Concurrent requests')
        self.songs = [Song.objects.create(title=f'Concurrent {i}', artist='Artist', id=f'limit-{i}') for i in range(7)]

    def guest_clients(self):
        first = self.client_class()
        session = first.session
        session.save()
        second = self.client_class()
        second.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
        return first, second, session.session_key

    def submit_together(self, submissions):
        start = Barrier(len(submissions))
        first_evaluation = Event()
        both_attempted = Event()
        release = Event()
        counter_lock = Lock()
        attempts = 0

        def track_lock(venue):
            nonlocal attempts
            with counter_lock:
                attempts += 1
                if attempts == len(submissions):
                    both_attempted.set()
            return lock_venue(venue)

        def pause_first(venue, song):
            if not first_evaluation.is_set():
                first_evaluation.set()
                if not release.wait(10):
                    raise TimeoutError('Concurrent requests were not released')
            return evaluate_request(venue, song)

        def submit(client, venue, song):
            from django.db import connections
            try:
                start.wait(timeout=10)
                return client.post(reverse('venue_request_song', args=[venue.slug, song.pk])).status_code
            finally:
                connections.close_all()

        with patch('core.views.lock_venue', side_effect=track_lock), patch('core.views.evaluate_request', side_effect=pause_first):
            with ThreadPoolExecutor(max_workers=len(submissions)) as executor:
                futures = [executor.submit(submit, *submission) for submission in submissions]
                try:
                    self.assertTrue(first_evaluation.wait(10))
                    self.assertTrue(both_attempted.wait(10))
                finally:
                    release.set()
                self.assertEqual([future.result(timeout=20) for future in futures], [302] * len(submissions))

    def test_simultaneous_duplicate_guest_requests_create_one_pending_request(self):
        first, second, session_key = self.guest_clients()
        self.submit_together([(first, self.venue, self.songs[0]), (second, self.venue, self.songs[0])])
        requests = SongRequest.objects.filter(venue_id=self.venue, session_key=session_key, status=SongRequest.PENDING)
        self.assertEqual(requests.count(), 1)
        self.assertEqual(SongDecision.objects.filter(venue=self.venue).count(), 1)

    def test_simultaneous_guest_requests_cannot_take_the_same_last_slot(self):
        first, second, session_key = self.guest_clients()
        for song in self.songs[:4]:
            SongRequest.objects.create(venue_id=self.venue, song_id=song, session_key=session_key)
        self.submit_together([(first, self.venue, self.songs[4]), (second, self.venue, self.songs[5])])
        self.assertEqual(SongRequest.objects.filter(venue_id=self.venue, session_key=session_key, status=SongRequest.PENDING).count(), 5)
        self.assertEqual(SongDecision.objects.filter(venue=self.venue).count(), 1)

    def test_account_limit_applies_across_separate_sessions(self):
        user = make_user('concurrent_customer', roles.CUSTOMER)
        first, second = self.client_class(), self.client_class()
        first.force_login(user)
        second.force_login(user)
        for song in self.songs[:4]:
            SongRequest.objects.create(venue_id=self.venue, song_id=song, requested_by=user)
        self.submit_together([(first, self.venue, self.songs[4]), (second, self.venue, self.songs[5])])
        self.assertEqual(SongRequest.objects.filter(venue_id=self.venue, requested_by=user, status=SongRequest.PENDING).count(), 5)

    def test_different_visitors_and_venues_do_not_share_limits(self):
        first, _, first_key = self.guest_clients()
        second, _, second_key = self.guest_clients()
        other_venue = Venue.objects.create(name='Another concurrent venue')
        self.submit_together([(first, self.venue, self.songs[0]), (second, self.venue, self.songs[0])])
        self.assertEqual(SongRequest.objects.filter(venue_id=self.venue, session_key__in=[first_key, second_key]).count(), 2)
        self.assertEqual(first.post(reverse('venue_request_song', args=[other_venue.slug, self.songs[0].pk])).status_code, 302)
        self.assertTrue(SongRequest.objects.filter(venue_id=other_venue, session_key=first_key).exists())

    def test_same_guest_can_request_the_same_song_at_two_venues(self):
        first, second, session_key = self.guest_clients()
        other_venue = Venue.objects.create(name='Independent venue')
        self.submit_together([(first, self.venue, self.songs[0]), (second, other_venue, self.songs[0])])
        self.assertEqual(SongRequest.objects.filter(session_key=session_key, song_id=self.songs[0]).count(), 2)

    def test_disabled_requests_create_no_partial_records(self):
        self.venue.requests_enabled = False
        self.venue.save(update_fields=['requests_enabled'])
        self.client.post(reverse('venue_request_song', args=[self.venue.slug, self.songs[0].pk]))
        self.assertFalse(SongRequest.objects.filter(venue_id=self.venue).exists())
        self.assertFalse(SongDecision.objects.filter(venue=self.venue).exists())

    def test_failed_decision_recording_rolls_back_the_request(self):
        with patch('core.views.record_decision', side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('venue_request_song', args=[self.venue.slug, self.songs[0].pk]))
        self.assertFalse(SongRequest.objects.filter(venue_id=self.venue).exists())
        self.assertFalse(SongDecision.objects.filter(venue=self.venue).exists())


@skipUnless(connection.vendor == 'postgresql', 'Request concurrency requires PostgreSQL')
class AvailabilityConcurrencyTests(TransactionTestCase):
    def test_disable_waits_for_in_progress_request(self):
        for role in roles.ROLES:
            Group.objects.get_or_create(name=role)
        owner = make_user('concurrent_owner', roles.OWNER)
        venue = Venue.objects.create(name='Concurrent availability', owner=owner)
        song = Song.objects.create(title='Concurrent song', artist='Artist', id='concurrent-availability')
        guest = self.client_class()
        owner_client = self.client_class()
        owner_client.force_login(owner)
        evaluating = Event()
        finish_request = Event()
        toggle_attempted = Event()

        def track_lock(venue_arg):
            if evaluating.is_set():
                toggle_attempted.set()
            return lock_venue(venue_arg)

        def paused_evaluation(venue_arg, song_arg):
            evaluating.set()
            if not finish_request.wait(10):
                raise TimeoutError('Request was not released')
            return evaluate_request(venue_arg, song_arg)

        def submit():
            from django.db import connections
            try:
                return guest.post(reverse('venue_request_song', args=[venue.slug, song.pk])).status_code
            finally:
                connections.close_all()

        def disable():
            from django.db import connections
            try:
                return owner_client.post(reverse('venue_request_availability', args=[venue.slug]), {'enabled': 'false'}).status_code
            finally:
                connections.close_all()

        with patch('core.views.evaluate_request', side_effect=paused_evaluation), patch('core.views.lock_venue', side_effect=track_lock):
            with ThreadPoolExecutor(max_workers=2) as executor:
                request_future = executor.submit(submit)
                self.assertTrue(evaluating.wait(10))
                toggle_future = executor.submit(disable)
                self.assertTrue(toggle_attempted.wait(10))
                self.assertFalse(toggle_future.done())
                finish_request.set()
                self.assertEqual(request_future.result(timeout=20), 302)
                self.assertEqual(toggle_future.result(timeout=20), 302)
        venue.refresh_from_db()
        self.assertFalse(venue.requests_enabled)
        self.assertEqual(SongRequest.objects.filter(venue_id=venue).count(), 1)
        guest.post(reverse('venue_request_song', args=[venue.slug, song.pk]))
        self.assertEqual(SongRequest.objects.filter(venue_id=venue).count(), 1)


@skipUnless(connection.vendor == 'postgresql', 'Queue concurrency requires PostgreSQL')
class QueueConcurrencyTests(TransactionTestCase):
    def test_concurrent_approvals_receive_distinct_positions(self):
        venue = Venue.objects.create(name='Concurrent venue')
        requests = []
        for index in range(2):
            song = Song.objects.create(title=f'Song {index}', artist='Artist', id=f'concurrent-{index}')
            requests.append(SongRequest.objects.create(song_id=song, venue_id=venue))
        barrier = Barrier(2)

        def approve(request_id):
            from django.db import connections
            try:
                barrier.wait(timeout=10)
                update_request_status(venue, request_id, SongRequest.APPROVED)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(approve, request.pk) for request in requests]
            for future in futures:
                future.result(timeout=20)
        self.assertEqual(list(Queue.objects.filter(venue_id=venue).order_by('position').values_list('position', flat=True)), [1, 2])


class SongIdentifierRecoveryTests(TransactionTestCase):
    def test_recovery_dry_run_and_apply_preserve_request(self):
        song = Song.objects.create(id='1', title='Legacy', artist='Artist')
        venue = Venue.objects.create(name='Recovery venue')
        request = SongRequest.objects.create(song_id=song, venue_id=venue)
        with NamedTemporaryFile(mode='w', suffix='.csv', encoding='utf-8', delete=False) as mapping:
            mapping.write('old_id,musicbrainz_id\n1,recording-one\n')
            path = mapping.name
        try:
            call_command('restore_song_identifiers', path, verbosity=0)
            self.assertTrue(Song.objects.filter(pk='1').exists())
            call_command('restore_song_identifiers', path, apply=True, verbosity=0)
            request.refresh_from_db()
            self.assertEqual(request.song_id_id, 'recording-one')
        finally:
            from pathlib import Path
            Path(path).unlink()


    def test_recovery_can_swap_existing_song_identifiers(self):
        first = Song.objects.create(id='1', title='First', artist='Artist')
        second = Song.objects.create(id='2', title='Second', artist='Artist')
        venue = Venue.objects.create(name='Swap venue')
        request = SongRequest.objects.create(song_id=first, venue_id=venue)
        with NamedTemporaryFile(mode='w', suffix='.csv', encoding='utf-8', delete=False) as mapping:
            mapping.write('old_id,musicbrainz_id\n1,2\n2,1\n')
            path = mapping.name
        try:
            call_command('restore_song_identifiers', path, apply=True, verbosity=0)
            request.refresh_from_db()
            self.assertEqual(request.song_id_id, '2')
            self.assertEqual(Song.objects.get(pk='2').title, 'First')
            self.assertEqual(Song.objects.get(pk='1').title, 'Second')
        finally:
            from pathlib import Path
            Path(path).unlink()

    def test_invalid_or_colliding_mapping_leaves_data_unchanged(self):
        Song.objects.create(id='1', title='First', artist='Artist')
        Song.objects.create(id='existing', title='Second', artist='Artist')
        with NamedTemporaryFile(mode='w', suffix='.csv', encoding='utf-8', delete=False) as mapping:
            mapping.write('old_id,musicbrainz_id\n1,existing\n')
            path = mapping.name
        try:
            with self.assertRaises(CommandError):
                call_command('restore_song_identifiers', path, apply=True, verbosity=0)
            self.assertEqual(set(Song.objects.values_list('pk', flat=True)), {'1', 'existing'})
        finally:
            from pathlib import Path
            Path(path).unlink()


class RequestMigrationTests(TransactionTestCase):
    def migrate_to(self, target, replace_migrations=True):
        executor = MigrationExecutor(connection)
        if not replace_migrations:
            executor.loader = MigrationLoader(connection, replace_migrations=False)
        executor.migrate([('core', target)])
        return executor.loader.project_state([('core', target)]).apps

    def tearDown(self):
        self.migrate_to('0020_payments_stripe_checkout_session_id_and_more')
        super().tearDown()

    def test_song_identifiers_and_related_records_survive_0019(self):
        old = self.migrate_to('0018_venue_requests_enabled')
        venue = old.get_model('core', 'Venue').objects.create(name='Migration venue', slug='migration-venue')
        song = old.get_model('core', 'Song').objects.create(title='Old', artist='Artist', musicbrainz_id='recording-one')
        other = old.get_model('core', 'Song').objects.create(title='Other', artist='Artist', musicbrainz_id='recording-two')
        request = old.get_model('core', 'SongRequest').objects.create(song_id=song, venue_id=venue, status='APPROVED')
        old.get_model('core', 'Queue').objects.create(venue_id=venue, song_request_id=request, position=1)
        old.get_model('core', 'SongFeatures').objects.create(song=song, source='manual')
        old.get_model('core', 'VenueSongBlacklist').objects.create(venue_id=venue, song_id=other)
        old.get_model('core', 'SongDecision').objects.create(venue=venue, song=song, request=request, outcome='ACCEPT')
        current = self.migrate_to('0019_remove_song_musicbrainz_id_song_bpm_song_genre_and_more')
        self.assertEqual(current.get_model('core', 'SongRequest').objects.get(pk=request.pk).song_id_id, 'recording-one')
        self.assertTrue(current.get_model('core', 'SongFeatures').objects.filter(song_id='recording-one').exists())
        self.assertTrue(current.get_model('core', 'SongDecision').objects.filter(song_id='recording-one', request_id=request.pk).exists())
        self.assertTrue(current.get_model('core', 'VenueSongBlacklist').objects.filter(song_id_id='recording-two').exists())
        self.assertTrue(current.get_model('core', 'Queue').objects.filter(song_request_id_id=request.pk).exists())

    def test_request_availability_upgrade_keeps_existing_venues_enabled(self):
        old = self.migrate_to('0017_queue_constraints')
        venue = old.get_model('core', 'Venue').objects.create(name='Existing venue', slug='existing-venue')
        current = self.migrate_to('0018_venue_requests_enabled')
        self.assertTrue(current.get_model('core', 'Venue').objects.get(pk=venue.pk).requests_enabled)

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

    def test_existing_metadata_is_preserved_as_unverified(self):
        old = self.migrate_to('0010_request_venue_constraint')
        song = old.get_model('core', 'Song').objects.create(
            title='Legacy', artist='Artist', musicbrainz_id='legacy-features',
            genre='Jazz', BPM=95, is_explicit=False,
        )
        current = self.migrate_to('0013_remove_song_metadata')
        features = current.get_model('core', 'SongFeatures').objects.get(song_id=song.pk)
        self.assertEqual(features.genre, 'Jazz')
        self.assertEqual(features.bpm, 95)
        self.assertFalse(features.is_explicit)
        self.assertEqual(features.source, 'legacy-unverified')

    def test_existing_approved_requests_are_added_to_queue(self):
        old = self.migrate_to('0014_song_decision')
        venue = old.get_model('core', 'Venue').objects.create(name='Old queue', slug='old-queue')
        song = old.get_model('core', 'Song').objects.create(title='Old song', artist='Artist', musicbrainz_id='old-queue-song')
        first = old.get_model('core', 'SongRequest').objects.create(song_id=song, venue_id=venue, status='APPROVED')
        second = old.get_model('core', 'SongRequest').objects.create(song_id=song, venue_id=venue, status='APPROVED')
        old.get_model('core', 'Queue').objects.create(venue_id=venue, song_request_id=first)
        current = self.migrate_to('0017_queue_constraints')
        entries = current.get_model('core', 'Queue').objects.order_by('position')
        self.assertEqual(list(entries.values_list('song_request_id_id', flat=True)), [first.pk, second.pk])
        self.assertEqual(list(entries.values_list('position', flat=True)), [1, 2])
