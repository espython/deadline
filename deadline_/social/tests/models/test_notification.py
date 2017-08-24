from unittest.mock import patch

from django.test import TestCase

from challenges.tests.base import TestHelperMixin
from challenges.tests.factories import UserFactory, SubmissionFactory, ChallengeFactory, SubmissionCommentFactory
from social.constants import RECEIVE_FOLLOW_NOTIFICATION, RECEIVE_SUBMISSION_UPVOTE_NOTIFICATION, \
    RECEIVE_NW_ITEM_LIKE_NOTIFICATION, NEW_CHALLENGE_NOTIFICATION, RECEIVE_NW_ITEM_COMMENT_NOTIFICATION, \
    RECEIVE_NW_ITEM_COMMENT_REPLY_NOTIFICATION, RECEIVE_SUBMISSION_COMMENT_NOTIFICATION
from social.errors import InvalidNotificationType, MissingNotificationContentField, InvalidNotificationContentField, \
    InvalidFollowError
from social.models import Notification, NewsfeedItem, NewsfeedItemComment


class NotifiationItemTests(TestCase, TestHelperMixin):
    def setUp(self):
        self.create_user_and_auth_token()

    def test_model_save_raises_if_invalid_notification_type(self):
        """ An error should be raised if we enter an invalid newsfeeditem type """
        with self.assertRaises(InvalidNotificationType):
            Notification.objects.create(recipient=self.auth_user, type='TANK',
                                        content={'content': 'Hello I like turtles'})

    @patch('social.models.VALID_NOTIFICATION_TYPES', ['test_type'])
    @patch('social.models.NOTIFICATION_TYPE_CONTENT_FIELDS', {'test_type': ['1', '2']})
    def test_model_save_raises_if_missing_newsfeed_content_field(self):
        """ Given a valid Newsfeed Type, an error should be raised if a required field is missing """
        with self.assertRaises(MissingNotificationContentField):
            Notification.objects.create(recipient=self.auth_user, type='test_type',
                                        content={})

    @patch('social.models.VALID_NOTIFICATION_TYPES', ['test_type'])
    @patch('social.models.NOTIFICATION_TYPE_CONTENT_FIELDS', {'test_type': ['1', '2']})
    def test_model_save_raises_if_invalid_newsfeed_content_field(self):
        """ Given a valid Newsfeed Type, an error should be raised if an invalid field is added,
                regardless if all the right ones are supplied (memory is expensive) """
        with self.assertRaises(InvalidNotificationContentField):
            Notification.objects.create(recipient=self.auth_user, type='test_type',
                                        content={'1': 'Hello I like turtles', '2': 'pf', 'tank': 'yo'})

    def test_create_receive_follow_notification(self):
        sec_user = UserFactory()
        notif = Notification.objects.create_receive_follow_notification(recipient=self.auth_user, follower=sec_user)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(notif.type, RECEIVE_FOLLOW_NOTIFICATION)
        self.assertEqual(notif.recipient, self.auth_user)
        self.assertEqual(notif.content, {'follower_id': sec_user.id, 'follower_name': sec_user.username})

    def test_create_receive_follow_notification_raises_invalid_follow_if_same_follower(self):
        with self.assertRaises(InvalidFollowError):
            Notification.objects.create_receive_follow_notification(recipient=self.auth_user, follower=self.auth_user)

    def test_create_receive_submission_upvote_notification(self):
        sec_user = UserFactory()
        submission = SubmissionFactory(author=self.auth_user)
        notif = Notification.objects.create_receive_submission_upvote_notification(submission=submission, liker=sec_user)
        expected_content = {
            'submission_id': submission.id,
            'challenge_id': submission.challenge.id,
            'challenge_name': submission.challenge.name,
            'liker_id': sec_user.id,
            'liker_name': sec_user.username
        }
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(notif.type, RECEIVE_SUBMISSION_UPVOTE_NOTIFICATION)
        self.assertEqual(notif.recipient, self.auth_user)
        self.assertEqual(expected_content, notif.content)

    def test_create_receive_submission_upvote_notification_doesnt_create_if_same_user(self):
        submission = SubmissionFactory(author=self.auth_user)
        notif = Notification.objects.create_receive_submission_upvote_notification(submission=submission, liker=self.auth_user)
        self.assertIsNone(notif)
        self.assertEqual(Notification.objects.count(), 0)

    def test_create_receive_nw_item_like_notification(self):
        sec_user = UserFactory()
        nw_item = NewsfeedItem.objects.create_challenge_link(challenge=ChallengeFactory(), author=self.auth_user)
        expected_content = {'nw_content': nw_item.content,
                            'nw_type': nw_item.type, 'liker_id': sec_user.id, 'liker_name': sec_user.username}

        notif = Notification.objects.create_receive_nw_item_like_notification(nw_item=nw_item, liker=sec_user)

        self.assertEqual(notif.type, RECEIVE_NW_ITEM_LIKE_NOTIFICATION)
        self.assertEqual(notif.content, expected_content)
        self.assertEqual(notif.recipient, self.auth_user)

    def test_create_receive_nw_item_like_notification_doesnt_create_if_liker_is_recipient(self):
        nw_item = NewsfeedItem.objects.create_challenge_link(challenge=ChallengeFactory(), author=self.auth_user)
        notif = Notification.objects.create_receive_nw_item_like_notification(nw_item=nw_item, liker=self.auth_user)
        self.assertIsNone(notif)
        self.assertEqual(Notification.objects.count(), 0)

    def test_create_new_challenge_notification(self):
        chal = ChallengeFactory()
        expected_content = {
            'challenge_name': chal.name,
            'challenge_id': chal.id,
            'challenge_subcategory_name': chal.category.name
        }
        notif = Notification.objects.create_new_challenge_notification(recipient=self.auth_user, challenge=chal)

        self.assertEqual(notif.type, NEW_CHALLENGE_NOTIFICATION)
        self.assertEqual(notif.recipient, self.auth_user)
        self.assertEqual(expected_content, notif.content)

    def test_create_nw_item_comment_notification(self):
        sec_user = UserFactory()
        nw_item = NewsfeedItem.objects.create_challenge_link(challenge=ChallengeFactory(), author=self.auth_user)
        expected_content = {'commenter_name': sec_user.username, 'commenter_id': sec_user.id,
                            'nw_item_content': nw_item.content, 'nw_item_id': nw_item.id, 'nw_item_type': nw_item.type}
        notif = Notification.objects.create_nw_item_comment_notification(nw_item=nw_item, commenter=sec_user)

        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Notification.objects.first(), notif)
        self.assertEqual(notif.type, RECEIVE_NW_ITEM_COMMENT_NOTIFICATION)
        self.assertEqual(notif.recipient, nw_item.author)
        self.assertEqual(notif.content, expected_content)

    def test_create_nw_item_comment_notification_doesnt_create_if_commenter_is_recipient(self):
        nw_item = NewsfeedItem.objects.create_challenge_link(challenge=ChallengeFactory(), author=self.auth_user)
        notif = Notification.objects.create_nw_item_comment_notification(nw_item=nw_item, commenter=self.auth_user)
        self.assertIsNone(notif)
        self.assertEqual(Notification.objects.count(), 0)

    def test_create_nw_item_comment_reply_notif(self):
        sec_user = UserFactory()
        nw_item = NewsfeedItem.objects.create_challenge_link(challenge=ChallengeFactory(), author=self.auth_user)
        nw_comment: NewsfeedItemComment = nw_item.add_comment(author=self.auth_user, content='travis scott',
                                                              to_notify=False)
        reply = NewsfeedItemComment.objects.create(newsfeed_item=nw_item,
                                                   parent=nw_comment, author=sec_user,
                                                   content='secured')
        expected_content = {
            'nw_comment_id': nw_comment.id, 'commenter_id': reply.author.id,
            'commenter_name': reply.author.username, 'comment_content': reply.content
        }

        notif = Notification.objects.create_nw_item_comment_reply_notification(nw_comment=nw_comment, reply=reply)

        self.assertEqual(notif.type, RECEIVE_NW_ITEM_COMMENT_REPLY_NOTIFICATION)
        self.assertEqual(notif.recipient, nw_comment.author)
        self.assertEqual(notif.content, expected_content)

    def test_create_nw_item_comment_reply_notif_doesnt_create_if_recipient_is_replier(self):
        nw_item = NewsfeedItem.objects.create_challenge_link(challenge=ChallengeFactory(), author=self.auth_user)
        nw_comment: NewsfeedItemComment = nw_item.add_comment(author=self.auth_user, content='travis scott',
                                                              to_notify=False)
        reply = NewsfeedItemComment.objects.create(newsfeed_item=nw_item,
                                                   parent=nw_comment, author=self.auth_user,
                                                   content='secured')
        notif = Notification.objects.create_nw_item_comment_reply_notification(nw_comment=nw_comment, reply=reply)

        self.assertIsNone(notif)
        self.assertEqual(Notification.objects.count(), 0)

    def test_create_submission_comment_notification(self):
        self.setup_proficiencies()
        subm = SubmissionFactory(author_id=self.auth_user.id)
        subm_comment = SubmissionCommentFactory(submission=subm)
        expected_content = {
            'submission_id': subm.id, 'challenge_id': subm.challenge.id, 'challenge_name': subm.challenge.name,
            'commenter_name': subm_comment.author.username, 'comment_content': subm_comment.content,
            'comment_id': subm_comment.id, 'commenter_id': subm_comment.author.id,
        }

        notif = Notification.objects.create_submission_comment_notification(comment=subm_comment)
        self.assertEqual(notif.type, RECEIVE_SUBMISSION_COMMENT_NOTIFICATION)
        self.assertEqual(notif.recipient, subm.author)
        self.assertEqual(notif.content, expected_content)

    def test_create_submission_comment_notification_not_created_if_author_comments_himself(self):
        self.setup_proficiencies()
        subm = SubmissionFactory(author_id=self.auth_user.id)
        subm_comment = SubmissionCommentFactory(submission=subm, author=self.auth_user)
        notif = Notification.objects.create_submission_comment_notification(comment=subm_comment)
        self.assertIsNone(notif)
        self.assertEqual(Notification.objects.count(), 0)
