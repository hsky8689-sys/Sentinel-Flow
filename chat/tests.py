import json
import secrets
from datetime import date

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from chat.models import Conversation, Message
from chat.service import ConversationService
from projects.models import Project, ProjectRole, UserProjectRole
from users.models import User


def make_user(name):
    suffix = secrets.token_hex(4)
    return User.objects.create_user(
        username=f'{name}_{suffix}',
        email=f'{name}_{suffix}@example.com',
        password='CorrectHorseBatteryStaple123',
        birthday=date(2000, 1, 1),
    )


class LoadUserConversationsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user_a = make_user('chatuser_a')
        self.user_b = make_user('chatuser_b')
        self.user_c = make_user('chatuser_c')

    @staticmethod
    def _url():
        return reverse('chat:load_conversations')

    # ---- business logic ----

    def test_missing_page_number_returns_400(self):
        self.client.force_login(self.user_a)
        response = self.client.get(self._url(), {'pageSize': 10})
        self.assertEqual(response.status_code, 400)

    def test_missing_page_size_returns_400(self):
        self.client.force_login(self.user_a)
        response = self.client.get(self._url(), {'pageNumber': 0})
        self.assertEqual(response.status_code, 400)

    def test_non_integer_page_params_return_400(self):
        self.client.force_login(self.user_a)
        response = self.client.get(self._url(), {'pageNumber': 'abc', 'pageSize': 10})
        self.assertEqual(response.status_code, 400)

    def test_only_returns_conversations_the_caller_participates_in(self):
        own_conv_id = ConversationService.create_conversation(self.user_a.id, self.user_b.id)
        ConversationService.create_conversation(self.user_b.id, self.user_c.id)  # A is not in this one

        self.client.force_login(self.user_a)
        response = self.client.get(self._url(), {'pageNumber': 0, 'pageSize': 10})
        self.assertEqual(response.status_code, 200)
        ids = [c['id'] for c in response.json()['content']]
        self.assertEqual(ids, [own_conv_id])

    # ---- security ----

    def test_requires_authentication(self):
        response = self.client.get(self._url(), {'pageNumber': 0, 'pageSize': 10})
        self.assertEqual(response.status_code, 302)

    # ---- rate limiting ----

    def test_rate_limit_blocks_after_5_requests_per_second(self):
        """load_user_conversations rate-limits GET by 'user_or_ip' at 5/s."""
        self.client.force_login(self.user_a)
        for attempt in range(5):
            response = self.client.get(self._url(), {'pageNumber': 0, 'pageSize': 10})
            self.assertEqual(
                response.status_code, 200,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )
        blocked = self.client.get(self._url(), {'pageNumber': 0, 'pageSize': 10})
        self.assertEqual(blocked.status_code, 403, "6th GET within the same second should be rate-limited (user_or_ip, 5/s)")


class LoadChatByIdTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user_a = make_user('chatuser_a')
        self.user_b = make_user('chatuser_b')
        self.outsider = make_user('chatuser_notmember')
        self.conv_id = ConversationService.create_conversation(self.user_a.id, self.user_b.id)
        Message.objects.send_message(self.user_a.id, self.conv_id, 'hello there')

    @staticmethod
    def _url(conversation_id):
        return reverse('chat:load_chat', kwargs={'conversation_id': conversation_id})

    # ---- business logic ----

    def test_missing_page_number_returns_400(self):
        self.client.force_login(self.user_a)
        response = self.client.get(self._url(self.conv_id), {'pageSize': 10})
        self.assertEqual(response.status_code, 400)

    def test_missing_page_size_returns_400(self):
        self.client.force_login(self.user_a)
        response = self.client.get(self._url(self.conv_id), {'pageNumber': 0})
        self.assertEqual(response.status_code, 400)

    def test_non_integer_page_params_return_400(self):
        self.client.force_login(self.user_a)
        response = self.client.get(self._url(self.conv_id), {'pageNumber': 0, 'pageSize': 'abc'})
        self.assertEqual(response.status_code, 400)

    def test_participant_can_read_messages(self):
        self.client.force_login(self.user_a)
        response = self.client.get(self._url(self.conv_id), {'pageNumber': 0, 'pageSize': 10})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['content']), 1)
        self.assertEqual(response.json()['content'][0]['content'], 'hello there')

    def test_nonexistent_conversation_id_returns_404(self):
        self.client.force_login(self.user_a)
        never_existed_id = self.conv_id + 100_000
        response = self.client.get(self._url(never_existed_id), {'pageNumber': 0, 'pageSize': 10})
        self.assertEqual(response.status_code, 404)

    # ---- security ----

    def test_requires_authentication(self):
        response = self.client.get(self._url(self.conv_id), {'pageNumber': 0, 'pageSize': 10})
        self.assertEqual(response.status_code, 302)

    def test_non_participant_cannot_read_someone_elses_conversation(self):
        """
        load_chat_by_id must reject a reader who isn't in conversation_id's
        participant list - previously this had no check at all, so anyone
        could read any conversation's full history just by knowing (or
        brute-forcing, since ids are sequential integers) its id. Returns
        the same 404 as a nonexistent conversation, deliberately, so the
        status code can't be used to enumerate which ids are real.
        """
        self.client.force_login(self.outsider)
        response = self.client.get(self._url(self.conv_id), {'pageNumber': 0, 'pageSize': 10})
        self.assertEqual(response.status_code, 404)

    # ---- rate limiting ----

    def test_rate_limit_blocks_after_5_requests_per_second(self):
        """load_chat_by_id rate-limits GET by 'user_or_ip' at 5/s."""
        self.client.force_login(self.user_a)
        for attempt in range(5):
            response = self.client.get(self._url(self.conv_id), {'pageNumber': 0, 'pageSize': 10})
            self.assertEqual(
                response.status_code, 200,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )
        blocked = self.client.get(self._url(self.conv_id), {'pageNumber': 0, 'pageSize': 10})
        self.assertEqual(blocked.status_code, 403, "6th GET within the same second should be rate-limited (user_or_ip, 5/s)")


class OpenChatRoomTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user_a = make_user('chatuser_a')
        self.user_b = make_user('chatuser_b')

    @staticmethod
    def _url():
        return reverse('chat:chat_room')

    # ---- business logic ----

    def test_no_params_returns_neutral_state(self):
        self.client.force_login(self.user_a)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['chat_id'], -1)
        self.assertEqual(data['user_101'], -1)

    def test_conv_id_param_is_echoed_back(self):
        self.client.force_login(self.user_a)
        response = self.client.get(self._url(), {'conv_id': '42'})
        self.assertEqual(response.json()['chat_id'], '42')

    def test_user_1o1_with_no_existing_conversation_returns_minus_one(self):
        self.client.force_login(self.user_a)
        response = self.client.get(self._url(), {'user_1o1': self.user_b.id})
        data = response.json()
        self.assertEqual(data['chat_id'], -1)
        self.assertEqual(data['user_101'], self.user_b.id)

    def test_user_1o1_with_existing_conversation_returns_its_id(self):
        conv_id = ConversationService.create_conversation(self.user_a.id, self.user_b.id)
        self.client.force_login(self.user_a)
        response = self.client.get(self._url(), {'user_1o1': self.user_b.id})
        self.assertEqual(response.json()['chat_id'], conv_id)

    def test_user_1o1_literal_null_string_is_treated_as_absent(self):
        self.client.force_login(self.user_a)
        response = self.client.get(self._url(), {'user_1o1': 'null'})
        data = response.json()
        self.assertEqual(data['chat_id'], -1)
        self.assertEqual(data['user_101'], -1)

    # ---- security ----

    def test_requires_authentication(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)


class ChatMessageApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user_a = make_user('chatuser_a')
        self.user_b = make_user('chatuser_b')
        self.outsider = make_user('chatuser_notmember')

    @staticmethod
    def _url():
        return reverse('chat:send_message')

    def _post(self, payload):
        return self.client.post(self._url(), data=json.dumps(payload), content_type='application/json')

    # ---- business logic ----

    def test_send_via_user_1o1_creates_conversation_and_message(self):
        self.client.force_login(self.user_a)
        response = self._post({'user_1o1': self.user_b.id, 'content': 'hi B'})
        self.assertEqual(response.status_code, 200)
        conv_id = response.json()['conversation_id']
        self.assertTrue(Message.objects.filter(conversation_id=conv_id, content='hi B', user_id=self.user_a.id).exists())

    def test_send_via_existing_conversation_id(self):
        conv_id = ConversationService.create_conversation(self.user_a.id, self.user_b.id)
        self.client.force_login(self.user_a)
        response = self._post({'conversation_id': conv_id, 'content': 'second message'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Message.objects.filter(conversation_id=conv_id, content='second message').exists())

    def test_second_message_via_user_1o1_to_an_existing_conversation_succeeds(self):
        """
        Regression test for a real bug: send_message()'s conversation_id==-1
        branch used to assign check_if_1o1_conversation_exist()'s return
        value (a Conversation instance) directly as conversation_id, instead
        of its .id - which worked for a brand new 1-on-1 (routed through
        create_conversation(), which does return an id) but crashed on the
        second message to that same conversation, once it existed and
        check_if_1o1_conversation_exist() started finding it.
        """
        self.client.force_login(self.user_a)
        first = self._post({'user_1o1': self.user_b.id, 'content': 'first message'})
        self.assertEqual(first.status_code, 200)
        first_conv_id = first.json()['conversation_id']

        second = self._post({'user_1o1': self.user_b.id, 'content': 'second message'})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['conversation_id'], first_conv_id)
        self.assertTrue(Message.objects.filter(conversation_id=first_conv_id, content='second message').exists())

    def test_empty_content_is_rejected(self):
        self.client.force_login(self.user_a)
        response = self._post({'user_1o1': self.user_b.id, 'content': ''})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Message.objects.filter(user_id=self.user_a.id).exists())

    def test_missing_content_key_is_rejected(self):
        self.client.force_login(self.user_a)
        response = self._post({'user_1o1': self.user_b.id})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Message.objects.filter(user_id=self.user_a.id).exists())

    def test_missing_conversation_id_and_user_1o1_returns_400(self):
        self.client.force_login(self.user_a)
        response = self._post({'content': 'going nowhere'})
        self.assertEqual(response.status_code, 400)

    def test_nonexistent_conversation_id_returns_404(self):
        self.client.force_login(self.user_a)
        response = self._post({'conversation_id': 999_999_999, 'content': 'hello?'})
        self.assertEqual(response.status_code, 404)

    def test_malformed_json_body_returns_400(self):
        self.client.force_login(self.user_a)
        response = self.client.post(self._url(), data='not json at all', content_type='application/json')
        self.assertEqual(response.status_code, 400)

    # ---- security ----

    def test_requires_authentication(self):
        response = self._post({'user_1o1': self.user_b.id, 'content': 'hi'})
        self.assertEqual(response.status_code, 302)

    def test_user_1o1_path_cannot_be_used_to_inject_into_a_conversation_between_two_other_users(self):
        """
        Confirms the user_1o1 path is safe by construction: it only ever
        looks up/creates a 1-on-1 between request.user and the given
        user_1o1, so request.user is always one of the two parties - there's
        no way to use it to plant a message in a conversation you're not in.
        """
        conv_id = ConversationService.create_conversation(self.user_a.id, self.user_b.id)
        self.client.force_login(self.outsider)
        response = self._post({'user_1o1': self.user_b.id, 'content': 'trying to sneak in'})
        self.assertEqual(response.status_code, 200)
        new_conv_id = response.json()['conversation_id']
        self.assertNotEqual(
            new_conv_id, conv_id,
            "the outsider must get/create their OWN 1-on-1 with B, never reuse A and B's existing conversation"
        )

    def test_non_participant_cannot_inject_a_message_via_conversation_id(self):
        """
        Unlike the user_1o1 path above, the explicit conversation_id path had
        NO check that request.user is a participant of that conversation -
        ConversationService.send_message -> Message.objects.send_message just
        inserted a Message row with the given conversation_id, no matter who
        was actually in it. Anyone could post into ANY existing conversation
        (1-on-1, group, or project chat) just by knowing its id.
        """
        conv_id = ConversationService.create_conversation(self.user_a.id, self.user_b.id)
        self.client.force_login(self.outsider)
        response = self._post({'conversation_id': conv_id, 'content': 'I was never invited to this chat'})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            Message.objects.filter(conversation_id=conv_id, user_id=self.outsider.id).exists(),
            "the outsider's message must not land in A and B's conversation"
        )

    # ---- rate limiting ----

    def test_rate_limit_blocks_after_5_requests_per_second(self):
        """
        chat_message_api rate-limits POST by 'user_or_ip' at 5/s. Uses an
        explicit conversation_id for every attempt rather than repeated
        user_1o1 calls - seeing test_BUG_second_message_via_user_1o1_crashes
        below, a second user_1o1 call into the same 1-on-1 conversation
        currently crashes, which would make this test fail for an unrelated
        reason.
        """
        conv_id = ConversationService.create_conversation(self.user_a.id, self.user_b.id)
        self.client.force_login(self.user_a)
        for attempt in range(5):
            response = self._post({'conversation_id': conv_id, 'content': f'msg {attempt}'})
            self.assertEqual(
                response.status_code, 200,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )
        blocked = self._post({'user_1o1': self.user_b.id, 'content': 'msg blocked'})
        self.assertEqual(blocked.status_code, 403, "6th POST within the same second should be rate-limited (user_or_ip, 5/s)")


class ProjectConversationsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user('chatuser_owner')
        self.member = make_user('chatuser_member')
        self.outsider = make_user('chatuser_notmember')

        self.project = Project.objects.create_project(self.owner.id, f'chatproj_{secrets.token_hex(4)}', 'a project')
        developer_role = ProjectRole.objects.get(name='developer')
        UserProjectRole.objects.give_role_to_user(self.project.id, self.member.id, developer_role)

    @staticmethod
    def _url(project_id):
        return reverse('chat:project_conversations', kwargs={'project_id': project_id})

    def _post(self, project_id, payload):
        return self.client.post(self._url(project_id), data=json.dumps(payload), content_type='application/json')

    def _delete(self, project_id, payload):
        return self.client.delete(self._url(project_id), data=json.dumps(payload), content_type='application/json')

    # ---- business logic: GET (list) ----

    def test_get_missing_page_number_returns_400(self):
        self.client.force_login(self.owner)
        response = self.client.get(self._url(self.project.id), {'pageSize': 10})
        self.assertEqual(response.status_code, 400)

    def test_get_missing_page_size_returns_400(self):
        self.client.force_login(self.owner)
        response = self.client.get(self._url(self.project.id), {'pageNumber': 0})
        self.assertEqual(response.status_code, 400)

    def test_get_nonexistent_project_returns_404(self):
        self.client.force_login(self.owner)
        never_existed_id = self.project.id + 100_000
        response = self.client.get(self._url(never_existed_id), {'pageNumber': 0, 'pageSize': 10})
        self.assertEqual(response.status_code, 404)

    def test_post_nonexistent_project_returns_404(self):
        self.client.force_login(self.owner)
        never_existed_id = self.project.id + 100_000
        response = self._post(never_existed_id, {'member_ids': [self.member.id]})
        self.assertEqual(response.status_code, 404)

    def test_delete_nonexistent_project_returns_404(self):
        self.client.force_login(self.owner)
        never_existed_id = self.project.id + 100_000
        response = self._delete(never_existed_id, {'conversation_id': 1})
        self.assertEqual(response.status_code, 404)

    def test_get_lists_the_projects_conversations(self):
        conv_id = ConversationService.create_group_conversation(self.project, [self.owner.id, self.member.id])
        self.client.force_login(self.member)
        response = self.client.get(self._url(self.project.id), {'pageNumber': 0, 'pageSize': 10})
        self.assertEqual(response.status_code, 200)
        ids = [c['id'] for c in response.json()['content']]
        self.assertEqual(ids, [conv_id])

    # ---- business logic: POST (create) ----

    def test_post_creates_a_group_conversation_with_valid_members(self):
        self.client.force_login(self.owner)
        response = self._post(self.project.id, {'member_ids': [self.member.id]})
        self.assertEqual(response.status_code, 200)
        conv_id = response.json()['conversation_id']
        conv = Conversation.objects.get(id=conv_id)
        self.assertEqual(conv.project_id, self.project.id)
        self.assertTrue(conv.is_group)
        self.assertSetEqual(
            set(conv.participants.values_list('id', flat=True)), {self.owner.id, self.member.id}
        )

    def test_post_silently_drops_member_ids_that_are_not_project_members(self):
        self.client.force_login(self.owner)
        response = self._post(self.project.id, {'member_ids': [self.member.id, self.outsider.id]})
        self.assertEqual(response.status_code, 200)
        conv_id = response.json()['conversation_id']
        participant_ids = set(Conversation.objects.get(id=conv_id).participants.values_list('id', flat=True))
        self.assertNotIn(self.outsider.id, participant_ids)
        self.assertEqual(participant_ids, {self.owner.id, self.member.id})

    def test_post_requires_at_least_one_other_valid_member(self):
        self.client.force_login(self.owner)
        response = self._post(self.project.id, {'member_ids': [self.outsider.id]})  # not a project member
        self.assertEqual(response.status_code, 400)

    def test_post_invalid_json_returns_400(self):
        self.client.force_login(self.owner)
        response = self.client.post(self._url(self.project.id), data='not json', content_type='application/json')
        self.assertEqual(response.status_code, 400)

    # ---- business logic: DELETE ----

    def test_delete_removes_the_conversation(self):
        conv_id = ConversationService.create_group_conversation(self.project, [self.owner.id, self.member.id])
        self.client.force_login(self.owner)
        response = self._delete(self.project.id, {'conversation_id': conv_id})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Conversation.objects.filter(id=conv_id).exists())

    def test_delete_missing_conversation_id_returns_400(self):
        self.client.force_login(self.owner)
        response = self._delete(self.project.id, {})
        self.assertEqual(response.status_code, 400)

    def test_delete_conversation_not_belonging_to_project_returns_404(self):
        other_project = Project.objects.create_project(self.owner.id, f'chatproj_other_{secrets.token_hex(4)}', 'other')
        foreign_conv_id = ConversationService.create_group_conversation(other_project, [self.owner.id, self.member.id])

        self.client.force_login(self.owner)
        response = self._delete(self.project.id, {'conversation_id': foreign_conv_id})
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Conversation.objects.filter(id=foreign_conv_id).exists())

    # ---- security ----

    def test_get_requires_authentication(self):
        response = self.client.get(self._url(self.project.id), {'pageNumber': 0, 'pageSize': 10})
        self.assertEqual(response.status_code, 302)

    def test_non_member_cannot_list_conversations(self):
        self.client.force_login(self.outsider)
        response = self.client.get(self._url(self.project.id), {'pageNumber': 0, 'pageSize': 10})
        self.assertEqual(response.status_code, 403)

    def test_non_member_cannot_create_conversation(self):
        self.client.force_login(self.outsider)
        response = self._post(self.project.id, {'member_ids': [self.owner.id]})
        self.assertEqual(response.status_code, 403)

    def test_non_member_cannot_delete_conversation(self):
        conv_id = ConversationService.create_group_conversation(self.project, [self.owner.id, self.member.id])
        self.client.force_login(self.outsider)
        response = self._delete(self.project.id, {'conversation_id': conv_id})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Conversation.objects.filter(id=conv_id).exists())

    # ---- rate limiting ----

    def test_get_rate_limit_blocks_after_80_requests_per_user(self):
        """api_project_conversations rate-limits GET by 'user_or_ip' at 80/m."""
        self.client.force_login(self.owner)
        for attempt in range(80):
            response = self.client.get(self._url(self.project.id), {'pageNumber': 0, 'pageSize': 10})
            self.assertEqual(
                response.status_code, 200,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )
        blocked = self.client.get(self._url(self.project.id), {'pageNumber': 0, 'pageSize': 10})
        self.assertEqual(blocked.status_code, 403, "81st GET within a minute should be rate-limited (user_or_ip, 80/m)")

    def test_post_rate_limit_blocks_after_30_requests_per_user(self):
        """api_project_conversations rate-limits POST by 'user_or_ip' at 30/m."""
        self.client.force_login(self.owner)
        for attempt in range(30):
            response = self._post(self.project.id, {'member_ids': [self.member.id]})
            self.assertEqual(
                response.status_code, 200,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )
        blocked = self._post(self.project.id, {'member_ids': [self.member.id]})
        self.assertEqual(blocked.status_code, 403, "31st POST within a minute should be rate-limited (user_or_ip, 30/m)")

    def test_delete_rate_limit_blocks_after_30_requests_per_user(self):
        """api_project_conversations rate-limits DELETE by 'user_or_ip' at 30/m."""
        conv_ids = [
            ConversationService.create_group_conversation(self.project, [self.owner.id, self.member.id])
            for _ in range(31)
        ]
        self.client.force_login(self.owner)
        for attempt, conv_id in enumerate(conv_ids[:30]):
            response = self._delete(self.project.id, {'conversation_id': conv_id})
            self.assertEqual(
                response.status_code, 200,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )
        blocked = self._delete(self.project.id, {'conversation_id': conv_ids[30]})
        self.assertEqual(blocked.status_code, 403, "31st DELETE within a minute should be rate-limited (user_or_ip, 30/m)")
