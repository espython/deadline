from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APITestCase

from challenges.tests.base import TestHelperMixin
from challenges.tests.factories import UserFactory
from social.constants import RECEIVE_CHALLENGE_COMMENT_REPLY_NOTIFICATION
from social.models.notification import Notification


class ChallengeCommentModelTests(TestCase, TestHelperMixin):
    def setUp(self):
        self.base_set_up()

    def test_add_comment(self):
        new_comment = self.challenge.add_comment(author=self.auth_user, content='Frozen')
        self.assertEqual(self.challenge.comments.count(), 1)
        self.assertEqual(self.challenge.comments.first(), new_comment)
        self.assertEqual(new_comment.replies.count(), 0)
        self.assertEqual(new_comment.author, self.auth_user)
        self.assertEqual(new_comment.content, 'Frozen')
        self.assertIsNone(new_comment.parent)
        self.assertEqual(new_comment.replies.count(), 0)

    def test_add_reply(self):
        sec_user = UserFactory()
        new_comment = self.challenge.add_comment(author=sec_user, content='Frozen')
        new_reply = new_comment.add_reply(author=self.auth_user, content='Stone')
        self.assertEqual(new_reply.replies.count(), 0)
        self.assertEqual(new_comment.replies.count(), 1)
        self.assertEqual(new_comment.replies.first(), new_reply)
        self.assertEqual(new_reply.content, 'Stone')
        self.assertEqual(new_reply.parent, new_comment)
        self.assertEqual(new_reply.author, self.auth_user)
        # assert it creates a notification
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Notification.objects.first().type, RECEIVE_CHALLENGE_COMMENT_REPLY_NOTIFICATION)
        self.assertEqual(Notification.objects.first().recipient, sec_user)

    def test_add_reply_doesnt_create_notification_if_commenter_replies_himself(self):
        new_comment = self.challenge.add_comment(author=self.auth_user, content='Frozen')
        new_comment.add_reply(author=self.auth_user, content='Stone', to_notify=True)
        self.assertEqual(Notification.objects.count(), 0)

    def test_add_reply_doest_create_notification_if_explicitly_stated(self):
        sec_user = UserFactory()
        new_comment = self.challenge.add_comment(author=sec_user, content='Frozen')
        new_comment.add_reply(author=self.auth_user, content='Stone', to_notify=False)
        self.assertEqual(Notification.objects.count(), 0)

    def test_get_absolute_url(self):
        new_comment = self.challenge.add_comment(author=self.auth_user, content='Frozen')
        expected_url = f'/challenges/{self.challenge.id}/comments/{new_comment.id}'
        self.assertEqual(new_comment.get_absolute_url(), expected_url)


class ChallengeCommentViewTest(APITestCase, TestHelperMixin):
    def setUp(self):
        self.base_set_up()
        self.c1 = self.challenge

    # Comment Create Tests
    def test_create_comment(self):
        response = self.client.post(f'/challenges/{self.c1.id}/comments',
                                    HTTP_AUTHORIZATION=self.auth_token,
                                    data={'content': 'Hello World'})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.c1.comments.count(), 1)
        self.assertEqual(self.c1.comments.first().author, self.auth_user)
        self.assertEqual(self.c1.comments.first().content, 'Hello World')

    def test_returns_400_if_comment_is_not_str(self):
        response = self.client.post(f'/challenges/{self.c1.id}/comments',
                                    HTTP_AUTHORIZATION=self.auth_token,
                                    data={'content': 123456}, content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_returns_400_if_comment_is_too_short(self):
        response = self.client.post(f'/challenges/{self.c1.id}/comments',
                                    HTTP_AUTHORIZATION=self.auth_token,
                                    data={'content': 'wh'})
        self.assertEqual(response.status_code, 400)

    def test_returns_400_if_comment_is_too_long(self):
        response = self.client.post(f'/challenges/{self.c1.id}/comments',
                                    HTTP_AUTHORIZATION=self.auth_token,
                                    data={'content': 'Hello World'*500})
        self.assertEqual(response.status_code, 400)

    def test_non_existent_challenge_returns_404(self):
        response = self.client.post(f'/challenges/111/comments',
                                    HTTP_AUTHORIZATION=self.auth_token,
                                    data={'content': 'Hello World'})
        self.assertEqual(response.status_code, 404)

    def test_requires_authentication(self):
        response = self.client.post(f'/challenges/111/comments',
                                    data={'content': 'Hello World'})
        self.assertEqual(response.status_code, 401)

        # Comment Create Tests


@patch('challenges.models.Challenge.add_comment')
class ChallengeCommentCreateViewTest(APITestCase, TestHelperMixin):
    def setUp(self):
        self.base_set_up()

    def test_creates_comment(self, mock_add_comment):
        # the add_comment method creates a comment
        resp = self.client.post(f'/challenges/{self.challenge.id}/comments',
                                HTTP_AUTHORIZATION=self.auth_token,
                                data={'content': 'White rapper not rocking a buzz cut'})
        mock_add_comment.assert_called_once_with(author=self.auth_user, content='White rapper not rocking a buzz cut')
        self.assertEqual(resp.status_code, 201)

    def test_returns_400_if_comment_is_not_str(self, mock_add_comment):
        resp = self.client.post(f'/challenges/{self.challenge.id}/comments',
                                HTTP_AUTHORIZATION=self.auth_token,
                                data={'content': 1})
        mock_add_comment.assert_not_called()
        self.assertEqual(resp.status_code, 400)

    def test_returns_400_if_comment_too_long(self, mock_add_comment):
        resp = self.client.post(f'/challenges/{self.challenge.id}/comments',
                                HTTP_AUTHORIZATION=self.auth_token,
                                data={'content': 'ab' * 300})
        mock_add_comment.assert_not_called()
        self.assertEqual(resp.status_code, 400)

    def test_returns_400_if_comment_too_sort(self, mock_add_comment):
        resp = self.client.post(f'/challenges/{self.challenge.id}/comments',
                                HTTP_AUTHORIZATION=self.auth_token,
                                data={'content': 'ab'})
        mock_add_comment.assert_not_called()
        self.assertEqual(resp.status_code, 400)

    def test_requires_auth(self, mock_add_comment):
        resp = self.client.post(f'/challenges/{self.challenge.id}/comments',
                                data={'content': 'e-dubble, happy friday'})
        mock_add_comment.assert_not_called()
        self.assertEqual(resp.status_code, 401)


@patch('challenges.models.ChallengeComment.add_reply')
class ChallengeCommentReplyCreateViewTest(APITestCase, TestHelperMixin):
    def setUp(self):
        self.base_set_up()
        self.comment = self.challenge.add_comment(author=self.auth_user, content='One Life, One Shot')
        self.comment_url = self.comment.get_absolute_url()

    def test_creates_reply(self, mock_add_reply):
        response = self.client.post(self.comment_url, HTTP_AUTHORIZATION=self.auth_token,
                                    data={'content': 'No, it is not!'})
        self.assertEqual(response.status_code, 201)
        mock_add_reply.assert_called_once_with(author=self.auth_user, content='No, it is not!', to_notify=True)

    def test_invalid_challenge_id_returns_404(self, mock_add_reply):
        response = self.client.post(f'/challenges/111/comments/{self.comment.id}',
                                    HTTP_AUTHORIZATION=self.auth_token,
                                    data={'content': 'No, it is not!'})
        self.assertEqual(response.status_code, 404)
        mock_add_reply.assert_not_called()

    def test_invalid_comment_id_returns_404(self, mock_add_reply):
        response = self.client.post(f'/challenges/{self.challenge.id}/comments/111',
                                    HTTP_AUTHORIZATION=self.auth_token,
                                    data={'content': 'No, it is not!'})
        self.assertEqual(response.status_code, 404)
        mock_add_reply.assert_not_called()

    def test_invalid_relationship_between_challenge_comment_returns_400(self, mock_add_reply):
        new_comment = self.create_challenge().add_comment(author=self.auth_user, content='No rest for the')
        response = self.client.post(f'/challenges/{self.challenge.id}/comments/{new_comment.id}',
                                    HTTP_AUTHORIZATION=self.auth_token,
                                    data={'content': 'No, it is not!'})
        self.assertEqual(response.status_code, 400)
        mock_add_reply.assert_not_called()

    def test_invalid_content_type_returns_400(self, mock_add_reply):
        # content should be a string, not a number
        response = self.client.post(self.comment_url, HTTP_AUTHORIZATION=self.auth_token,
                                    data={'content': 123}, content_type='application/json')
        self.assertEqual(response.status_code, 400)

        mock_add_reply.assert_not_called()

    def test_no_content_returns_400(self, mock_add_reply):
        response = self.client.post(self.comment_url, HTTP_AUTHORIZATION=self.auth_token)
        self.assertEqual(response.status_code, 400)
        mock_add_reply.assert_not_called()

    def test_short_content_returns_400(self, mock_add_reply):
        response = self.client.post(self.comment_url, HTTP_AUTHORIZATION=self.auth_token,
                                    data={'content': 'he'}, format='json')
        self.assertEqual(response.status_code, 400)
        mock_add_reply.assert_not_called()

    def test_long_content_returns_400(self, mock_add_reply):
        response = self.client.post(self.comment_url, HTTP_AUTHORIZATION=self.auth_token,
                                    data={'content': 'he' * 500}, format='json')
        self.assertEqual(response.status_code, 400)
        mock_add_reply.assert_not_called()

    def test_requires_auth(self, mock_add_reply):
        response = self.client.post(self.comment_url, data={'content': 'he' * 5})
        self.assertEqual(response.status_code, 401)
        mock_add_reply.assert_not_called()
