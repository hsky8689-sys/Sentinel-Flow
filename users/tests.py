import secrets
from datetime import date

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from users.models import User


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