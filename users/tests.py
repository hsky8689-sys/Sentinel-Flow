import json
import secrets
from datetime import date

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from users.models import Friendship, User, UserProfileSection, UserRequest, UserTechnicalSkill, \
    UserTechnicalSkillSection


class UsersTests(TestCase):
    def setUp(self):
        # django_ratelimit's counters live in Redis, not the DB - TestCase's
        # transaction rollback doesn't touch them, so leftover counts from a
        # previous test (or a previous run) would otherwise leak in here and
        # trip a limit early. Clearing at the start of setUp (not tearDown)
        # means every test gets a clean slate regardless of run order.
        cache.clear()
        self.users = []
        for _ in range(3):
            suffix = secrets.token_hex(4)
            user = User.objects.create_user(
                username=f'testuser_{suffix}',
                email=f'testuser_{suffix}@example.com',
                password='CorrectHorseBatteryStaple123',
                birthday=date(2000, 1, 1),
            )
            self.users.append(user)

    def tearDown(self):
        pass

    def test_login_rate_limit_blocks_after_twenty_attempts_per_username(self):
        """
        login_page rate-limits POST by 'post:username' at 20/m. The first 20
        attempts (wrong password) should each behave like a normal failed
        login (401 JSON error response); the 21st within the same minute
        should be blocked by django_ratelimit before the view even runs.
        """
        target_user = self.users[0]
        login_url = reverse('user_login')

        # A different fake REMOTE_ADDR per attempt keeps the separate 'ip'
        # limit (10/m) from tripping first - it would otherwise block at the
        # 11th request, well before the username limit (20/m) is reached.
        for attempt in range(20):
            response = self.client.post(
                login_url,
                {'username': target_user.username, 'password': 'wrong-password'},
                REMOTE_ADDR=f'10.0.{attempt // 256}.{attempt % 256}',
            )
            self.assertEqual(
                response.status_code, 401,
                f"attempt {attempt + 1} should be a normal failed-login response, got {response.status_code}"
            )

        blocked_response = self.client.post(
            login_url,
            {'username': target_user.username, 'password': 'wrong-password'},
            REMOTE_ADDR='10.0.99.99',
        )
        self.assertEqual(
            blocked_response.status_code, 403,
            "21st attempt within a minute should be rate-limited (post:username, 20/m)"
        )

    def test_login_rate_limit_blocks_after_ten_attempts_per_ip(self):
        """
        login_page also rate-limits POST by 'ip' at 10/m, independent of
        username. A different (nonexistent) username on every attempt keeps
        the stricter 'post:username' limit (5/m) from tripping first, so this
        isolates the per-IP limit specifically.
        """
        login_url = reverse('user_login')

        for attempt in range(10):
            response = self.client.post(login_url, {
                'username': f'nonexistent_{attempt}_{secrets.token_hex(4)}',
                'password': 'wrong-password',
            })
            self.assertEqual(
                response.status_code, 401,
                f"attempt {attempt + 1} should be a normal failed-login response, got {response.status_code}"
            )

        blocked_response = self.client.post(login_url, {
            'username': f'nonexistent_10_{secrets.token_hex(4)}',
            'password': 'wrong-password',
        })
        self.assertEqual(
            blocked_response.status_code, 403,
            "11th attempt within a minute from the same IP should be rate-limited (ip, 10/m)"
        )

    def test_login_page_get_rate_limit_blocks_after_twenty_requests(self):
        """
        login_page rate-limits GET by 'user_or_ip' at 20/m (an anonymous
        client falls back to its IP for this key).
        """
        login_url = reverse('user_login')

        for attempt in range(20):
            response = self.client.get(login_url)
            self.assertEqual(
                response.status_code, 200,
                f"GET attempt {attempt + 1} should render the login page normally"
            )

        blocked_response = self.client.get(login_url)
        self.assertEqual(
            blocked_response.status_code, 403,
            "21st GET within a minute should be rate-limited (user_or_ip, 20/m)"
        )

    def test_login_post_while_authenticated_rejects_with_400_and_keeps_session(self):
        """
        login_page's POST branch rejects with 400 if already authenticated -
        you must log out first before logging in as anyone else, whether the
        submitted credentials are right or wrong. The original session is
        left completely untouched either way (no more silent logout on a
        rejected attempt).
        """
        user_a, user_b = self.users[0], self.users[1]
        login_url = reverse('user_login')

        self.client.force_login(user_a)

        wrong_password_response = self.client.post(login_url, {
            'username': user_b.username,
            'password': 'wrong-password',
        })
        self.assertEqual(wrong_password_response.status_code, 400)
        self.assertEqual(
            self.client.session['_auth_user_id'], str(user_a.id),
            "A's session must survive a rejected login attempt with a wrong password"
        )

        correct_password_response = self.client.post(login_url, {
            'username': user_b.username,
            'password': 'CorrectHorseBatteryStaple123',
        })
        self.assertEqual(
            correct_password_response.status_code, 400,
            "even B's correct password should be rejected while A is still logged in"
        )
        self.assertEqual(
            self.client.session['_auth_user_id'], str(user_a.id),
            "A's session must survive even when B's credentials were valid - login while authenticated is refused outright"
        )

    def test_login_rejected_for_inactive_user_even_with_correct_password(self):
        """
        ModelBackend.user_can_authenticate checks is_active - a deactivated
        account with the right password should still be refused.
        """
        user = self.users[0]
        user.is_active = False
        user.save(update_fields=['is_active'])

        login_url = reverse('user_login')
        response = self.client.post(login_url, {
            'username': user.username,
            'password': 'CorrectHorseBatteryStaple123',
        })
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_page_get_while_authenticated_returns_400_and_keeps_session(self):
        """
        login_page's GET branch rejects with 400 if already authenticated,
        instead of silently logging the user out.
        """
        user = self.users[0]
        self.client.force_login(user)

        login_url = reverse('user_login')
        response = self.client.get(login_url)
        self.assertEqual(response.status_code, 400)

        self.assertEqual(
            self.client.session['_auth_user_id'], str(user.id),
            "session should remain intact - GET must not force-logout an authenticated user"
        )

    def test_concurrent_logins_as_same_user_get_different_session_keys(self):
        """
        Logging in as the same user from two independent clients ("threads")
        should produce two independent session keys - Django cycles the
        session key on every login specifically to prevent session fixation,
        so there's no risk of the same key being handed out twice or reused.
        """
        user = self.users[0]
        login_url = reverse('user_login')

        client_1 = Client()
        client_2 = Client()

        resp1 = client_1.post(login_url, {'username': user.username, 'password': 'CorrectHorseBatteryStaple123'})
        resp2 = client_2.post(login_url, {'username': user.username, 'password': 'CorrectHorseBatteryStaple123'})

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)

        key_1 = client_1.session.session_key
        key_2 = client_2.session.session_key
        self.assertIsNotNone(key_1)
        self.assertIsNotNone(key_2)
        self.assertNotEqual(key_1, key_2, "each concurrent login should get its own independent session key")

        self.assertEqual(client_1.session['_auth_user_id'], str(user.id))
        self.assertEqual(client_2.session['_auth_user_id'], str(user.id))

    def test_identity_always_comes_from_session_never_from_request_data(self):
        """
        request.user is resolved purely from the session cookie by
        AuthenticationMiddleware - nothing an attacker puts in the request
        body or query string can override it. Log in as B, then send a
        request that also carries A's id/username as if trying to "become" A
        via the payload - the server must still resolve the identity as B.
        """
        user_a, user_b = self.users[0], self.users[1]
        self.client.force_login(user_b)

        response = self.client.get(reverse('users:search_page'), {
            'username': user_a.username,
            'user_id': user_a.id,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['user_id'], user_b.id,
            "spoofed A identity in the query string must be ignored - the session says B"
        )

    # ---- signup_page ----

    def test_signup_creates_new_user_and_logs_them_in(self):
        """A genuinely new username/email should succeed and log the user in."""
        signup_url = reverse('user_signup')
        response = self.client.post(signup_url, {
            'username': 'brandnewuser',
            'email': 'brandnewuser@example.com',
            'password': 'SomeReasonablyStrongPassword987',
            'birthday': '2000-01-01',
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['user']['username'], 'brandnewuser')
        self.assertTrue(User.objects.filter(username='brandnewuser').exists())
        self.assertEqual(
            self.client.session['_auth_user_id'], str(data['user']['id']),
            "signup should log the new user in immediately"
        )

    def test_signup_rejects_duplicate_username(self):
        """An already-taken username must be rejected, even with a fresh email."""
        existing = self.users[0]
        signup_url = reverse('user_signup')
        response = self.client.post(signup_url, {
            'username': existing.username,
            'email': 'totally_different_email@example.com',
            'password': 'SomeReasonablyStrongPassword987',
            'birthday': '2000-01-01',
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            User.objects.filter(username=existing.username).count(), 1,
            "the existing account must be untouched, and no duplicate created"
        )
        self.assertFalse(User.objects.filter(email='totally_different_email@example.com').exists())

    def test_signup_rejects_duplicate_email(self):
        """An already-taken email must be rejected, even with a fresh username."""
        existing = self.users[0]
        signup_url = reverse('user_signup')
        response = self.client.post(signup_url, {
            'username': 'a_totally_new_username',
            'email': existing.email,
            'password': 'SomeReasonablyStrongPassword987',
            'birthday': '2000-01-01',
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='a_totally_new_username').exists())
        self.assertEqual(User.objects.filter(email=existing.email).count(), 1)

    def test_signup_missing_field_does_not_crash(self):
        """
        signup_page reads request.POST['username'] etc. directly (not .get()) -
        a request missing one of these fields should be handled gracefully,
        not blow up with an unhandled 500.
        """
        signup_url = reverse('user_signup')
        response = self.client.post(signup_url, {
            'email': 'missingusername@example.com',
            'password': 'SomeReasonablyStrongPassword987',
            'birthday': '2000-01-01',
            # 'username' intentionally omitted
        })
        self.assertIn(
            response.status_code, (200, 400),
            f"a missing required field should be a clean 4xx, not a 500 - got {response.status_code}"
        )

    def test_signup_rejects_weak_or_common_password(self):
        """
        create_user() now calls validate_password() against
        AUTH_PASSWORD_VALIDATORS (MinimumLength, CommonPassword, etc.) before
        hashing - a common weak password must be rejected, and no account
        should be left behind.
        """
        signup_url = reverse('user_signup')
        response = self.client.post(signup_url, {
            'username': 'weakpassworduser',
            'email': 'weakpassworduser@example.com',
            'password': 'password',
            'birthday': '2000-01-01',
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='weakpassworduser').exists())

    def test_signup_rejects_username_that_fails_slug_validation(self):
        """
        create_user() now calls full_clean() before saving, which enforces
        validate_slug on username - a username with spaces/special characters
        must be rejected, with no account left behind.
        """
        signup_url = reverse('user_signup')
        response = self.client.post(signup_url, {
            'username': 'not a valid slug!!!',
            'email': 'notaslug@example.com',
            'password': 'SomeReasonablyStrongPassword987',
            'birthday': '2000-01-01',
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email='notaslug@example.com').exists())

    def test_signup_rate_limit_blocks_after_ten_attempts_per_ip(self):
        """signup_page rate-limits POST by 'ip' at 10/m."""
        signup_url = reverse('user_signup')

        for attempt in range(10):
            suffix = secrets.token_hex(4)
            response = self.client.post(signup_url, {
                'username': f'spamuser_{attempt}_{suffix}',
                'email': f'spamuser_{attempt}_{suffix}@example.com',
                'password': 'SomeReasonablyStrongPassword987',
                'birthday': '2000-01-01',
            })
            self.assertEqual(
                response.status_code, 201,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )

        blocked_suffix = secrets.token_hex(4)
        blocked_response = self.client.post(signup_url, {
            'username': f'spamuser_blocked_{blocked_suffix}',
            'email': f'spamuser_blocked_{blocked_suffix}@example.com',
            'password': 'SomeReasonablyStrongPassword987',
            'birthday': '2000-01-01',
        })
        self.assertEqual(
            blocked_response.status_code, 403,
            "11th signup attempt within a minute from the same IP should be rate-limited (ip, 10/m)"
        )

    def test_signup_rate_limit_is_scoped_per_ip_not_global(self):
        """
        Exhausting the 10/m limit for one IP must not affect a different IP -
        the 'ip' key should isolate counters per address, not share a single
        global counter across every signup attempt.
        """
        signup_url = reverse('user_signup')

        for attempt in range(10):
            suffix = secrets.token_hex(4)
            response = self.client.post(
                signup_url,
                {
                    'username': f'ipscope_a_{attempt}_{suffix}',
                    'email': f'ipscope_a_{attempt}_{suffix}@example.com',
                    'password': 'SomeReasonablyStrongPassword987',
                    'birthday': '2000-01-01',
                },
                REMOTE_ADDR='10.1.0.1',
            )
            self.assertEqual(response.status_code, 201)

        exhausted_response = self.client.post(
            signup_url,
            {
                'username': f'ipscope_a_blocked_{secrets.token_hex(4)}',
                'email': f'ipscope_a_blocked_{secrets.token_hex(4)}@example.com',
                'password': 'SomeReasonablyStrongPassword987',
                'birthday': '2000-01-01',
            },
            REMOTE_ADDR='10.1.0.1',
        )
        self.assertEqual(exhausted_response.status_code, 403, "the first IP should now be exhausted")

        other_ip_response = self.client.post(
            signup_url,
            {
                'username': f'ipscope_b_{secrets.token_hex(4)}',
                'email': f'ipscope_b_{secrets.token_hex(4)}@example.com',
                'password': 'SomeReasonablyStrongPassword987',
                'birthday': '2000-01-01',
            },
            REMOTE_ADDR='10.1.0.2',
        )
        self.assertEqual(
            other_ip_response.status_code, 201,
            "a different IP must have its own independent counter, not inherit the first IP's exhausted limit"
        )

    def test_signup_get_is_never_rate_limited(self):
        """
        The 'ip' ratelimit on signup_page is scoped to method='POST' - GET
        requests (loading the signup form) should never be blocked, no
        matter how many times they're made.
        """
        signup_url = reverse('user_signup')
        for attempt in range(25):
            response = self.client.get(signup_url)
            self.assertEqual(
                response.status_code, 200,
                f"GET attempt {attempt + 1} should never be rate-limited, got {response.status_code}"
            )


class ProfileAccessTests(TestCase):
    def setUp(self):
        # same reasoning as UsersTests.setUp: ratelimit counters live outside
        # the DB transaction rollback, so clear them for a clean slate.
        cache.clear()
        self.owner = self._make_user('profileowner')
        self.viewer = self._make_user('profileviewer')
        self.stranger = self._make_user('bystander')

    @staticmethod
    def _make_user(name):
        suffix = secrets.token_hex(4)
        return User.objects.create_user(
            username=f'{name}_{suffix}',
            email=f'{name}_{suffix}@example.com',
            password='CorrectHorseBatteryStaple123',
            birthday=date(2000, 1, 1),
        )

    @staticmethod
    def _profile_url(username):
        return reverse('users:profile-path', kwargs={'username': username})

    # ---- hidden sections: visible to the owner only ----

    def test_own_profile_includes_hidden_sections(self):
        UserProfileSection.objects.create(
            user=self.owner, name='Secret Notes', content='only I should see this', hidden=True
        )
        self.client.force_login(self.owner)
        response = self.client.get(self._profile_url(self.owner.username))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['is_owner'])
        self.assertTrue(
            any(s['name'] == 'Secret Notes' and s['hidden'] for s in data['profile_sections']),
            "the owner viewing their own profile must see their own hidden sections"
        )

    def test_foreign_profile_excludes_hidden_sections(self):
        UserProfileSection.objects.create(
            user=self.owner, name='Secret Notes', content='only I should see this', hidden=True
        )
        self.client.force_login(self.viewer)
        response = self.client.get(self._profile_url(self.owner.username))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['is_owner'])
        self.assertFalse(
            any(s['name'] == 'Secret Notes' for s in data['profile_sections']),
            "a visitor must never see another user's hidden sections"
        )

    def test_foreign_profile_still_includes_visible_default_sections(self):
        """The default sections created at signup (About me, Skills, ...) are all hidden=False."""
        self.client.force_login(self.viewer)
        response = self.client.get(self._profile_url(self.owner.username))
        sections = response.json()['profile_sections']
        self.assertTrue(len(sections) > 0)
        self.assertTrue(all(not s['hidden'] for s in sections))

    # ---- friendship/request state populated into the JSON payload ----

    def test_profile_with_no_friendship_relation(self):
        self.client.force_login(self.viewer)
        response = self.client.get(self._profile_url(self.owner.username))
        data = response.json()
        self.assertFalse(data['sent_to_him'])
        self.assertFalse(data['received_from_him'])
        self.assertFalse(data['friends'])
        self.assertIsNone(data['friendship_request_id'])

    def test_profile_shows_request_sent_by_viewer(self):
        req = UserRequest.objects.send_friend_request(self.viewer, self.owner)
        self.client.force_login(self.viewer)
        response = self.client.get(self._profile_url(self.owner.username))
        data = response.json()
        self.assertTrue(data['sent_to_him'])
        self.assertFalse(data['received_from_him'])
        self.assertFalse(data['friends'])
        self.assertEqual(data['friendship_request_id'], req.id)

    def test_profile_shows_request_received_from_profile_owner(self):
        req = UserRequest.objects.send_friend_request(self.owner, self.viewer)
        self.client.force_login(self.viewer)
        response = self.client.get(self._profile_url(self.owner.username))
        data = response.json()
        self.assertFalse(data['sent_to_him'])
        self.assertTrue(data['received_from_him'])
        self.assertFalse(data['friends'])
        self.assertEqual(data['friendship_request_id'], req.id)

    def test_profile_shows_friends_true_once_friendship_exists(self):
        Friendship.objects.create(sender=self.viewer, receiver=self.owner)
        self.client.force_login(self.viewer)
        response = self.client.get(self._profile_url(self.owner.username))
        data = response.json()
        self.assertTrue(data['friends'])
        self.assertFalse(data['sent_to_him'])
        self.assertFalse(data['received_from_him'])

    def test_profile_friendship_detection_is_symmetric(self):
        """
        find_friendship matches sender/receiver in either direction - being
        friends must show up the same way regardless of who sent the
        original request, i.e. regardless of who is 'sender' on the row.
        """
        Friendship.objects.create(sender=self.owner, receiver=self.viewer)
        self.client.force_login(self.viewer)
        response = self.client.get(self._profile_url(self.owner.username))
        self.assertTrue(response.json()['friends'])

    # ---- profile of a username that isn't a live account ----

    def test_profile_for_never_registered_username_returns_404_not_500(self):
        self.client.force_login(self.viewer)
        response = self.client.get(self._profile_url('this_username_was_never_registered'))
        self.assertEqual(response.status_code, 404)

    def test_profile_for_deleted_user_returns_404_not_500(self):
        """
        A competitor's account removed from the app (row actually deleted,
        not just deactivated) must produce a clean 404 - acces_profile relies
        on get_object_or_404, so a stale profile link/bookmark to a since-
        deleted account should never 500.
        """
        deleted_username = self.stranger.username
        self.stranger.delete()
        self.client.force_login(self.viewer)
        response = self.client.get(self._profile_url(deleted_username))
        self.assertEqual(response.status_code, 404)

    def test_profile_for_deactivated_but_undeleted_user_is_still_reachable(self):
        """
        Documents current behavior rather than asserting a requirement:
        acces_profile only calls get_object_or_404, it never checks
        is_active - a deactivated/banned account's row still exists, so its
        profile stays viewable by others even though that account itself can
        no longer log in.
        """
        self.stranger.is_active = False
        self.stranger.save(update_fields=['is_active'])
        self.client.force_login(self.viewer)
        response = self.client.get(self._profile_url(self.stranger.username))
        self.assertEqual(response.status_code, 200)

    def test_unauthenticated_visitor_is_redirected_not_shown_the_profile(self):
        response = self.client.get(self._profile_url(self.owner.username))
        self.assertEqual(response.status_code, 302)

    # ---- email is business data, not something every viewer should see ----

    def test_own_profile_still_includes_email(self):
        self.client.force_login(self.owner)
        response = self.client.get(self._profile_url(self.owner.username))
        self.assertEqual(response.json()['email'], self.owner.email)

    def test_foreign_profile_hides_email(self):
        """
        acces_profile used to put user.email in the context unconditionally,
        so any logged-in visitor could read another user's email just by
        opening their profile - only profile_sections was gated by
        is_owner, email wasn't. Now it must be None for non-owners.
        """
        self.client.force_login(self.viewer)
        response = self.client.get(self._profile_url(self.owner.username))
        self.assertIsNone(response.json()['email'])

    # ---- rate limiting ----

    def test_profile_rate_limit_blocks_after_120_requests_per_user(self):
        """acces_profile rate-limits by 'user' at 120/m."""
        self.client.force_login(self.viewer)
        url = self._profile_url(self.owner.username)

        for attempt in range(120):
            response = self.client.get(url)
            self.assertEqual(
                response.status_code, 200,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )

        blocked_response = self.client.get(url)
        self.assertEqual(
            blocked_response.status_code, 403,
            "121st request within a minute from the same user should be rate-limited (user, 120/m)"
        )


class SkillCrudTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user_a = self._make_user('skilluser_a')
        self.user_b = self._make_user('skilluser_b')
        # create_user() auto-creates the default techstack sections
        # (Frontend/Backend/Database/Tools) for every new account.
        self.section_a = UserTechnicalSkillSection.objects.filter(user=self.user_a).first()
        self.section_b = UserTechnicalSkillSection.objects.filter(user=self.user_b).first()

    @staticmethod
    def _make_user(name):
        suffix = secrets.token_hex(4)
        return User.objects.create_user(
            username=f'{name}_{suffix}',
            email=f'{name}_{suffix}@example.com',
            password='CorrectHorseBatteryStaple123',
            birthday=date(2000, 1, 1),
        )

    @staticmethod
    def _add_url():
        return reverse('users:api_add_skill')

    @staticmethod
    def _delete_url(skill_id):
        return reverse('users:api_delete_skill', kwargs={'skill_id': skill_id})

    # ---- add_skill: happy path ----

    def test_add_skill_succeeds_for_own_section(self):
        self.client.force_login(self.user_a)
        response = self.client.post(self._add_url(), {'name': 'Python', 'section_id': self.section_a.id})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            UserTechnicalSkill.objects.filter(name='Python', section_id=self.section_a.id).exists()
        )

    def test_add_skill_rejects_duplicate_in_same_section(self):
        self.client.force_login(self.user_a)
        self.client.post(self._add_url(), {'name': 'Python', 'section_id': self.section_a.id})
        second = self.client.post(self._add_url(), {'name': 'Python', 'section_id': self.section_a.id})
        self.assertEqual(second.status_code, 409)
        self.assertEqual(
            UserTechnicalSkill.objects.filter(name='Python', section_id=self.section_a.id).count(), 1,
            "a duplicate add attempt must not create a second row"
        )

    def test_add_skill_missing_name_returns_400(self):
        self.client.force_login(self.user_a)
        response = self.client.post(self._add_url(), {'section_id': self.section_a.id})
        self.assertEqual(response.status_code, 400)

    def test_add_skill_missing_section_id_returns_400(self):
        self.client.force_login(self.user_a)
        response = self.client.post(self._add_url(), {'name': 'Python'})
        self.assertEqual(response.status_code, 400)

    def test_add_skill_requires_authentication(self):
        response = self.client.post(self._add_url(), {'name': 'Python', 'section_id': self.section_a.id})
        self.assertEqual(response.status_code, 302)

    # ---- add_skill: bad/foreign section_id ----

    def test_add_skill_rejects_nonexistent_section_id(self):
        self.client.force_login(self.user_a)
        never_existed_id = UserTechnicalSkillSection.objects.order_by('-id').first().id + 10_000
        response = self.client.post(self._add_url(), {'name': 'Python', 'section_id': never_existed_id})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(UserTechnicalSkill.objects.filter(name='Python').exists())

    def test_add_skill_rejects_section_belonging_to_another_user(self):
        """
        A must not be able to add a skill under B's section just by knowing
        (or guessing) B's section_id - add_user_skill filters by
        (id=section_id, user=request.user), so a foreign section_id must
        produce the exact same 404 as a nonexistent one, otherwise A could
        use the status code to enumerate which section_ids exist.
        """
        self.client.force_login(self.user_a)
        response = self.client.post(self._add_url(), {'name': 'Python', 'section_id': self.section_b.id})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            UserTechnicalSkill.objects.filter(name='Python', section_id=self.section_b.id).exists(),
            "A's attempt must not plant a skill under B's section"
        )

    def test_add_skill_section_of_a_deleted_user_behaves_like_a_nonexistent_section(self):
        """
        UserTechnicalSkillSection.user is on_delete=CASCADE, so deleting the
        owning account also deletes their sections - a stale section_id kept
        around client-side (e.g. from a previous page load) must fail the
        same way a made-up id would, not 500 with a different error or leak
        that the section used to exist.
        """
        deleted_user = self._make_user('skilluser_c')
        stale_section_id = UserTechnicalSkillSection.objects.filter(user=deleted_user).first().id
        deleted_user.delete()

        self.client.force_login(self.user_a)
        response = self.client.post(self._add_url(), {'name': 'Python', 'section_id': stale_section_id})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(UserTechnicalSkill.objects.filter(name='Python').exists())

    def test_add_skill_rejects_non_numeric_section_id(self):
        self.client.force_login(self.user_a)
        response = self.client.post(self._add_url(), {'name': 'Python', 'section_id': 'not-a-number'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserTechnicalSkill.objects.filter(name='Python').exists())

    # ---- add_skill: rate limiting ----

    def test_add_skill_rate_limit_blocks_after_30_requests_per_user(self):
        """api_add_skill rate-limits POST by 'user' at 30/m."""
        self.client.force_login(self.user_a)

        for attempt in range(30):
            response = self.client.post(
                self._add_url(), {'name': f'Skill{attempt}', 'section_id': self.section_a.id}
            )
            self.assertEqual(
                response.status_code, 200,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )

        blocked_response = self.client.post(
            self._add_url(), {'name': 'SkillBlocked', 'section_id': self.section_a.id}
        )
        self.assertEqual(
            blocked_response.status_code, 403,
            "31st add-skill POST within a minute from the same user should be rate-limited (user, 30/m)"
        )

    # ---- delete_skill: happy path ----

    def test_delete_skill_succeeds_for_own_skill(self):
        skill = UserTechnicalSkill.objects.create(name='Python', section_id=self.section_a.id)
        self.client.force_login(self.user_a)
        response = self.client.delete(self._delete_url(skill.id))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserTechnicalSkill.objects.filter(id=skill.id).exists())

    def test_delete_skill_rejects_nonexistent_skill_id(self):
        self.client.force_login(self.user_a)
        never_existed_id = 999_999_999
        response = self.client.delete(self._delete_url(never_existed_id))
        self.assertEqual(response.status_code, 404)

    def test_delete_skill_requires_authentication(self):
        skill = UserTechnicalSkill.objects.create(name='Python', section_id=self.section_a.id)
        response = self.client.delete(self._delete_url(skill.id))
        self.assertEqual(response.status_code, 302)

    # ---- delete_skill: cross-user access ----

    def test_delete_skill_rejects_deleting_another_users_skill(self):
        """A must not be able to delete a skill that lives under B's section."""
        skill = UserTechnicalSkill.objects.create(name='Python', section_id=self.section_b.id)
        self.client.force_login(self.user_a)
        response = self.client.delete(self._delete_url(skill.id))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            UserTechnicalSkill.objects.filter(id=skill.id).exists(),
            "B's skill must survive A's unauthorized delete attempt"
        )

    def test_delete_skill_of_a_deleted_user_returns_404(self):
        """
        Deleting the account cascades User -> UserTechnicalSkillSection ->
        UserTechnicalSkill, so a skill_id from a since-deleted account must
        behave like it never existed, not 403/500.
        """
        deleted_user = self._make_user('skilluser_c')
        deleted_user_section = UserTechnicalSkillSection.objects.filter(user=deleted_user).first()
        skill = UserTechnicalSkill.objects.create(name='Python', section_id=deleted_user_section.id)
        skill_id = skill.id
        deleted_user.delete()

        self.assertFalse(UserTechnicalSkill.objects.filter(id=skill_id).exists(), "cascade should have removed it already")

        self.client.force_login(self.user_a)
        response = self.client.delete(self._delete_url(skill_id))
        self.assertEqual(response.status_code, 404)

    # ---- delete_skill: rate limiting ----

    def test_delete_skill_rate_limit_blocks_after_30_requests_per_user(self):
        """api_delete_skill rate-limits DELETE by 'user' at 30/m."""
        skills = UserTechnicalSkill.objects.bulk_create([
            UserTechnicalSkill(name=f'RateLimitSkill{i}', section_id=self.section_a.id) for i in range(31)
        ])
        self.client.force_login(self.user_a)

        for attempt, skill in enumerate(skills[:30]):
            response = self.client.delete(self._delete_url(skill.id))
            self.assertEqual(
                response.status_code, 200,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )

        blocked_response = self.client.delete(self._delete_url(skills[30].id))
        self.assertEqual(
            blocked_response.status_code, 403,
            "31st delete-skill DELETE within a minute from the same user should be rate-limited (user, 30/m)"
        )


class FriendRequestAndConnectionsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user_a = self._make_user('frienduser_a')
        self.user_b = self._make_user('frienduser_b')
        self.user_c = self._make_user('frienduser_c')

    @staticmethod
    def _make_user(name):
        suffix = secrets.token_hex(4)
        return User.objects.create_user(
            username=f'{name}_{suffix}',
            email=f'{name}_{suffix}@example.com',
            password='CorrectHorseBatteryStaple123',
            birthday=date(2000, 1, 1),
        )

    @staticmethod
    def _requests_url():
        return reverse('users:friend-requests')

    @staticmethod
    def _request_detail_url(request_id):
        return reverse('users:friend-request-detail', kwargs={'id': request_id})

    @staticmethod
    def _remove_friend_url(removed_id):
        return reverse('users:remove_friend', kwargs={'removed': removed_id})

    @staticmethod
    def _connections_url():
        return reverse('users:view_connections')

    def _post_json(self, url, payload):
        return self.client.post(url, data=json.dumps(payload), content_type='application/json')

    def _patch_json(self, url, payload):
        return self.client.patch(url, data=json.dumps(payload), content_type='application/json')

    # ================= api_friend_requests (send) =================

    def test_send_friend_request_succeeds(self):
        self.client.force_login(self.user_a)
        response = self._post_json(self._requests_url(), {'receiver_id': self.user_b.id})
        self.assertEqual(response.status_code, 200)
        req_id = response.json()['id']
        req = UserRequest.objects.get(id=req_id)
        self.assertEqual(req.sender_id, self.user_a.id)
        self.assertEqual(req.receiver_id, self.user_b.id)
        self.assertEqual(req.request_type, 'friend')
        self.assertEqual(req.status, 'pending')

    def test_send_friend_request_to_self_is_rejected(self):
        self.client.force_login(self.user_a)
        response = self._post_json(self._requests_url(), {'receiver_id': self.user_a.id})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserRequest.objects.filter(sender=self.user_a, receiver=self.user_a).exists())

    def test_send_friend_request_to_nonexistent_user_returns_404(self):
        self.client.force_login(self.user_a)
        never_existed_id = User.objects.order_by('-id').first().id + 10_000
        response = self._post_json(self._requests_url(), {'receiver_id': never_existed_id})
        self.assertEqual(response.status_code, 404)

    def test_send_friend_request_rejects_duplicate_same_direction(self):
        self.client.force_login(self.user_a)
        self._post_json(self._requests_url(), {'receiver_id': self.user_b.id})
        second = self._post_json(self._requests_url(), {'receiver_id': self.user_b.id})
        self.assertEqual(second.status_code, 400)
        self.assertEqual(
            UserRequest.objects.filter(sender=self.user_a, receiver=self.user_b).count(), 1
        )

    def test_send_friend_request_rejects_duplicate_reverse_direction(self):
        """B already sent A a pending request - A sending one back must be rejected as a duplicate, not create a second row."""
        self.client.force_login(self.user_b)
        self._post_json(self._requests_url(), {'receiver_id': self.user_a.id})

        self.client.force_login(self.user_a)
        response = self._post_json(self._requests_url(), {'receiver_id': self.user_b.id})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(UserRequest.objects.filter(request_type='friend').count(), 1)

    def test_send_friend_request_requires_authentication(self):
        response = self._post_json(self._requests_url(), {'receiver_id': self.user_b.id})
        self.assertEqual(response.status_code, 302)

    def test_send_friend_request_rate_limit_blocks_after_20_requests_per_user(self):
        """api_friend_requests rate-limits POST by 'user' at 20/m."""
        self.client.force_login(self.user_a)
        targets = [self._make_user(f'frienduser_target_{i}') for i in range(21)]

        for attempt, target in enumerate(targets[:20]):
            response = self._post_json(self._requests_url(), {'receiver_id': target.id})
            self.assertEqual(
                response.status_code, 200,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )

        blocked_response = self._post_json(self._requests_url(), {'receiver_id': targets[20].id})
        self.assertEqual(
            blocked_response.status_code, 403,
            "21st POST within a minute from the same user should be rate-limited (user, 20/m)"
        )

    # ================= api_friend_request_detail: PATCH (accept) =================

    def test_accept_friend_request_succeeds_and_creates_friendship(self):
        self.client.force_login(self.user_a)
        req_id = self._post_json(self._requests_url(), {'receiver_id': self.user_b.id}).json()['id']

        self.client.force_login(self.user_b)
        response = self._patch_json(self._request_detail_url(req_id), {'status': 'accepted'})
        self.assertEqual(response.status_code, 200)

        self.assertFalse(UserRequest.objects.filter(id=req_id).exists(), "the request row is consumed on acceptance")
        self.assertIsNotNone(
            Friendship.objects.find_friendship(self.user_a, self.user_b).first(),
            "accepting must create a Friendship row between the original sender and receiver"
        )

    def test_sender_cannot_accept_their_own_sent_request(self):
        self.client.force_login(self.user_a)
        req_id = self._post_json(self._requests_url(), {'receiver_id': self.user_b.id}).json()['id']

        response = self._patch_json(self._request_detail_url(req_id), {'status': 'accepted'})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(UserRequest.objects.filter(id=req_id, status='pending').exists())

    def test_non_participant_cannot_touch_the_request(self):
        self.client.force_login(self.user_a)
        req_id = self._post_json(self._requests_url(), {'receiver_id': self.user_b.id}).json()['id']

        self.client.force_login(self.user_c)
        response = self._patch_json(self._request_detail_url(req_id), {'status': 'accepted'})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(UserRequest.objects.filter(id=req_id, status='pending').exists())

    def test_accept_nonexistent_request_returns_404(self):
        self.client.force_login(self.user_a)
        response = self._patch_json(self._request_detail_url(999_999_999), {'status': 'accepted'})
        self.assertEqual(response.status_code, 404)

    def test_cannot_accept_an_already_handled_request(self):
        self.client.force_login(self.user_a)
        req_id = self._post_json(self._requests_url(), {'receiver_id': self.user_b.id}).json()['id']
        req = UserRequest.objects.get(id=req_id)
        UserRequest.objects.accept_request(req)  # status -> 'accepted' directly through the manager

        self.client.force_login(self.user_b)
        response = self._patch_json(self._request_detail_url(req_id), {'status': 'accepted'})
        self.assertEqual(response.status_code, 403)

    def test_accept_rejects_unsupported_status_value(self):
        self.client.force_login(self.user_a)
        req_id = self._post_json(self._requests_url(), {'receiver_id': self.user_b.id}).json()['id']

        self.client.force_login(self.user_b)
        response = self._patch_json(self._request_detail_url(req_id), {'status': 'declined'})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(UserRequest.objects.filter(id=req_id, status='pending').exists())

    # ================= api_friend_request_detail: DELETE (cancel/decline) =================

    def test_sender_can_cancel_their_own_pending_request(self):
        self.client.force_login(self.user_a)
        req_id = self._post_json(self._requests_url(), {'receiver_id': self.user_b.id}).json()['id']

        response = self.client.delete(self._request_detail_url(req_id))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserRequest.objects.filter(id=req_id).exists())

    def test_receiver_can_decline_a_pending_request(self):
        self.client.force_login(self.user_a)
        req_id = self._post_json(self._requests_url(), {'receiver_id': self.user_b.id}).json()['id']

        self.client.force_login(self.user_b)
        response = self.client.delete(self._request_detail_url(req_id))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserRequest.objects.filter(id=req_id).exists())

    def test_non_participant_cannot_delete_the_request(self):
        self.client.force_login(self.user_a)
        req_id = self._post_json(self._requests_url(), {'receiver_id': self.user_b.id}).json()['id']

        self.client.force_login(self.user_c)
        response = self.client.delete(self._request_detail_url(req_id))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(UserRequest.objects.filter(id=req_id).exists())

    def test_delete_nonexistent_request_returns_404(self):
        self.client.force_login(self.user_a)
        response = self.client.delete(self._request_detail_url(999_999_999))
        self.assertEqual(response.status_code, 404)

    def test_request_detail_requires_authentication(self):
        self.client.force_login(self.user_a)
        req_id = self._post_json(self._requests_url(), {'receiver_id': self.user_b.id}).json()['id']
        self.client.logout()

        response = self.client.delete(self._request_detail_url(req_id))
        self.assertEqual(response.status_code, 302)

    def test_request_detail_rate_limit_blocks_after_20_requests_per_user(self):
        """
        api_friend_request_detail rate-limits (PATCH+DELETE share the same
        'user' key) at 20/m. The 21 fixture requests are created directly
        through the ORM rather than via api_friend_requests, since that
        endpoint has its own 20/m limit that would otherwise trip first
        while just setting up the fixtures.
        """
        self.client.force_login(self.user_a)
        targets = [self._make_user(f'frienduser_ratelimit_{i}') for i in range(21)]
        request_ids = [
            UserRequest.objects.create(
                sender=self.user_a, receiver=target, request_type='friend', status='pending'
            ).id
            for target in targets
        ]

        for attempt, req_id in enumerate(request_ids[:20]):
            response = self.client.delete(self._request_detail_url(req_id))
            self.assertEqual(
                response.status_code, 200,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )

        blocked_response = self.client.delete(self._request_detail_url(request_ids[20]))
        self.assertEqual(
            blocked_response.status_code, 403,
            "21st request within a minute from the same user should be rate-limited (user, 20/m)"
        )

    # ================= api_remove_friend =================

    def _make_friends(self, user_x, user_y):
        self.client.force_login(user_x)
        req_id = self._post_json(self._requests_url(), {'receiver_id': user_y.id}).json()['id']
        self.client.force_login(user_y)
        self._patch_json(self._request_detail_url(req_id), {'status': 'accepted'})

    def test_remove_friend_succeeds(self):
        self._make_friends(self.user_a, self.user_b)

        self.client.force_login(self.user_a)
        response = self.client.delete(self._remove_friend_url(self.user_b.id))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(Friendship.objects.find_friendship(self.user_a, self.user_b).first())

    def test_remove_friend_also_cleans_up_a_leftover_pending_request(self):
        """
        Simulates a DB state where a Friendship exists alongside a still-open
        UserRequest between the same two users (e.g. a second request sent
        after the first was already accepted) - removing the friendship must
        also clear that leftover request instead of orphaning it.
        """
        self._make_friends(self.user_a, self.user_b)
        leftover_request = UserRequest.objects.create(
            sender=self.user_a, receiver=self.user_b, request_type='friend', status='pending'
        )

        self.client.force_login(self.user_a)
        response = self.client.delete(self._remove_friend_url(self.user_b.id))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserRequest.objects.filter(id=leftover_request.id).exists())

    def test_remove_friend_when_not_actually_friends_returns_404(self):
        self.client.force_login(self.user_a)
        response = self.client.delete(self._remove_friend_url(self.user_b.id))
        self.assertEqual(response.status_code, 404)

    def test_remove_friend_requires_authentication(self):
        self._make_friends(self.user_a, self.user_b)
        self.client.logout()

        response = self.client.delete(self._remove_friend_url(self.user_b.id))
        self.assertEqual(response.status_code, 302)

    def test_remove_friend_rate_limit_blocks_after_20_requests_per_user(self):
        """
        api_remove_friend rate-limits DELETE by 'user' at 20/m. Friendships
        are created directly through the ORM instead of via the send+accept
        HTTP flow, since api_friend_requests has its own 20/m limit that
        would otherwise trip first while just setting up 21 fixtures.
        """
        friends = [self._make_user(f'frienduser_removeratelimit_{i}') for i in range(21)]
        for friend in friends:
            Friendship.objects.create(sender=self.user_a, receiver=friend)

        self.client.force_login(self.user_a)
        for attempt, friend in enumerate(friends[:20]):
            response = self.client.delete(self._remove_friend_url(friend.id))
            self.assertEqual(
                response.status_code, 200,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )

        blocked_response = self.client.delete(self._remove_friend_url(friends[20].id))
        self.assertEqual(
            blocked_response.status_code, 403,
            "21st DELETE within a minute from the same user should be rate-limited (user, 20/m)"
        )

    # ================= connections_page =================

    def test_connections_page_shows_requests_where_user_is_receiver(self):
        self.client.force_login(self.user_a)
        self._post_json(self._requests_url(), {'receiver_id': self.user_b.id})

        self.client.force_login(self.user_b)
        response = self.client.get(self._connections_url())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['requests']), 1)
        self.assertEqual(data['requests'][0]['sender_id'], self.user_a.id)
        self.assertEqual(data['requests'][0]['receiver_id'], self.user_b.id)

    def test_connections_page_does_not_show_requests_where_user_is_only_sender(self):
        self.client.force_login(self.user_a)
        self._post_json(self._requests_url(), {'receiver_id': self.user_b.id})

        response = self.client.get(self._connections_url())
        self.assertEqual(response.json()['requests'], [])

    def test_connections_page_empty_when_no_requests(self):
        self.client.force_login(self.user_c)
        response = self.client.get(self._connections_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['requests'], [])

    def test_connections_page_requires_authentication(self):
        response = self.client.get(self._connections_url())
        self.assertEqual(response.status_code, 302)

    def test_connections_page_rate_limit_blocks_after_60_requests_per_user(self):
        """connections_page rate-limits GET by 'user' at 60/m."""
        self.client.force_login(self.user_a)

        for attempt in range(60):
            response = self.client.get(self._connections_url())
            self.assertEqual(
                response.status_code, 200,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )

        blocked_response = self.client.get(self._connections_url())
        self.assertEqual(
            blocked_response.status_code, 403,
            "61st GET within a minute from the same user should be rate-limited (user, 60/m)"
        )