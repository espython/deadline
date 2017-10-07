from django.contrib.postgres.fields import JSONField
from django.db import models
from django_hstore import hstore
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from accounts.models import User
from challenges.models import SubCategory, UserSubcategoryProficiency, SubmissionComment, ChallengeComment, SubmissionVote
from errors import ForbiddenMethodError
from social.constants import NEWSFEED_ITEM_TYPE_CONTENT_FIELDS, VALID_NEWSFEED_ITEM_TYPES, \
    NW_ITEM_SUBCATEGORY_BADGE_POST, NW_ITEM_SHARE_POST, NW_ITEM_SUBMISSION_LINK_POST, NW_ITEM_CHALLENGE_LINK_POST, \
    NW_ITEM_CHALLENGE_COMPLETION_POST, VALID_NOTIFICATION_TYPES, NOTIFICATION_TYPE_CONTENT_FIELDS, \
    RECEIVE_FOLLOW_NOTIFICATION, RECEIVE_SUBMISSION_UPVOTE_NOTIFICATION, RECEIVE_NW_ITEM_LIKE_NOTIFICATION, \
    NEW_CHALLENGE_NOTIFICATION, RECEIVE_NW_ITEM_COMMENT_NOTIFICATION, RECEIVE_NW_ITEM_COMMENT_REPLY_NOTIFICATION, \
    RECEIVE_SUBMISSION_COMMENT_NOTIFICATION, RECEIVE_SUBMISSION_COMMENT_REPLY_NOTIFICATION, \
    RECEIVE_CHALLENGE_COMMENT_REPLY_NOTIFICATION, RECEIVE_SUBMISSION_UPVOTE_NOTIFICATION_SQUASHED, \
    RECEIVE_FOLLOW_NOTIFICATION_SQUASHED, RECEIVE_NW_ITEM_LIKE_NOTIFICATION_SQUASHED, \
    RECEIVE_NW_ITEM_COMMENT_NOTIFICATION_SQUASHED
from social.errors import InvalidNewsfeedItemType, MissingNewsfeedItemContentField, InvalidNewsfeedItemContentField, \
    LikeAlreadyExistsError, NonExistentLikeError, InvalidNotificationType, MissingNotificationContentField, \
    InvalidNotificationContentField, InvalidFollowError


class NewsfeedItemManager(models.Manager):
    """
    Use a custom NewsfeedItem manager for specific type of NewsfeedItem creation
    """

    def create_subcategory_badge_post(self, user_subcat_prof: UserSubcategoryProficiency):
        """
        Creates a SubcategoryBadgePost

        A SubcategoryBadgePost is a NewsfeedItem which has the following fields as content:
            proficiency_name: - the name of the proficiency (or badge) the user has attained
            subcategory_name: - the name of the subcategory this badge is for
            subcategory_id:   - the id of the subcategory

        ex: Stanislav just earned the Master badge for Graph Algorithms!
        """
        return self.create(author_id=user_subcat_prof.user_id, type=NW_ITEM_SUBCATEGORY_BADGE_POST,
                           content={
                               'proficiency_name': user_subcat_prof.proficiency.name,
                               'subcategory_name': user_subcat_prof.subcategory.name,
                               'subcategory_id': user_subcat_prof.subcategory.id
                           })

    def create_share_post(self, shared_item: 'NewsfeedItem', author: User):
        """
        Creates a 'share' of a NewsfeedItem or in other words, a NewsfeedItem that points to another
        """
        # TODO: Add validation for not creating a share of a share
        return self.create(author_id=author.id, type=NW_ITEM_SHARE_POST, content={'newsfeed_item_id': shared_item.id})

    def create_submission_link(self, submission: 'Submission', author: User):
        """
        Creates a 'link' NewsfeedItem type of a Submission
        """
        return self.create(author_id=author.id, type=NW_ITEM_SUBMISSION_LINK_POST,
                           content={
                               'submission_id': submission.id,
                               'submission_author_id': submission.author.id,
                               'submission_author_name': submission.author.username,
                               'submission_code_snippet': submission.code[:200],  # for now up until 200 characters, we'll see how this works
                               'submission_language_name': submission.language.name,
                               'submission_language_loc': 0  # temporary, as we do not store this anywhere
                           })

    def create_challenge_link(self, challenge: 'Challenge', author: User):
        """
        Creates a 'link' NewsfeedItem type of a Submission
        """
        return self.create(author_id=author.id, type=NW_ITEM_CHALLENGE_LINK_POST,
                           content={
                               'challenge_id': challenge.id,
                               'challenge_name': challenge.name,
                               'challenge_subcategory_name': challenge.category.name,
                               'challenge_difficulty': challenge.difficulty
                           })

    def create_challenge_completion_post(self, submission: 'Submission'):
        """
        Creates a NewsfeedItem of type ChallengeCompletion
            ex: Stanislav has completed challenge Firefox with 100/100 score after 30 attempts
        """
        challenge = submission.challenge
        author: User = submission.author
        if not submission.has_solved_challenge():
            raise Exception(f'Submission has not solved the challenge!')

        return self.create(author_id=author.id, type=NW_ITEM_CHALLENGE_COMPLETION_POST,
                           content={
                               'challenge_id': challenge.id,
                               'challenge_name': challenge.name,
                               'submission_id': submission.id,
                               'challenge_score': challenge.score,
                               'attempts_count': author.fetch_unsuccessful_challenge_attempts_count(challenge)
                           })


class NewsfeedItem(models.Model):
    """
    NewsfeedItem is a model that holds a single item in the facebook-esque NewsFeed (or Activity Feed)
        of the website.
    Since the content here is dynamic (you can share a submission, display you've complete a challenge, etc),
        we need an HStore field to store data related to the type of the post.
    e.g
    {
        type: "completed_challenge"
        content: {
            "challenge_id": 1,
            "submission_id": 1
        }
    },
    {
        type: "created_course"
        content: {
            "course_id": 1
        }
    }
    """
    author = models.ForeignKey(User)
    type = models.CharField(max_length=30)  # no other table for now
    content = JSONField()  # varies depending on the type
    is_private = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = NewsfeedItemManager()

    def get_absolute_url(self):
        return f'/social/feed/items/{self.id}'

    def like(self, user: User, create_notif=True):
        if NewsfeedItemLike.objects.filter(newsfeed_item=self, author=user).exists():
            raise LikeAlreadyExistsError(f'The Like from User {user.id} for Item {self.id} does already exists!')

        nw_like = NewsfeedItemLike.objects.create(author=user, newsfeed_item=self)

        if create_notif and user != self.author:
            Notification.objects.create_receive_nw_item_like_notification(nw_item=self, liker=user)

        return nw_like

    def remove_like(self, user: User):
        like = NewsfeedItemLike.objects.filter(newsfeed_item=self, author=user).first()
        if like is None:
            raise NonExistentLikeError(f'The Like from User {user.id} for Item {self.id} does not exist!')

        like.delete()

    def add_comment(self, author: User, content: str, to_notify: bool=True):
        if to_notify and self.author != author:
            Notification.objects.create_nw_item_comment_notification(commenter=author, nw_item=self)
        return NewsfeedItemComment.objects.create(author=author, content=content, newsfeed_item=self)


@receiver(pre_save, sender=NewsfeedItem)
def nw_item_validation(sender, instance, *args, **kwargs):
    # Validate that the type is valid and contains what we expect exactly
    if instance.type not in VALID_NEWSFEED_ITEM_TYPES:
        raise InvalidNewsfeedItemType(f'{instance.type} is not a valid NewsfeedItem type!')

    # Assert that each field is present
    required_fields = NEWSFEED_ITEM_TYPE_CONTENT_FIELDS[instance.type]
    for field in required_fields:
        if field not in instance.content:
            raise MissingNewsfeedItemContentField(
                f'The field {field} must be in the content of NewsfeedItem of type {instance.type}.')

    # Assert that no other unnecessary fields are present
    if len(required_fields) < len(instance.content.keys()):
        # Some unnecessary field is present
        for field in instance.content.keys():
            if field not in required_fields:
                raise InvalidNewsfeedItemContentField(
                    f'The field {field} is not part of the expected content for {instance.type} and is unnecessary!')


class NewsfeedItemComment(models.Model):
    newsfeed_item = models.ForeignKey(NewsfeedItem, related_name='comments')
    author = models.ForeignKey(User)
    content = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    parent = models.ForeignKey('self', null=True, related_name='replies', default=None)

    def add_reply(self, author, content, to_notify=True):
        reply = NewsfeedItemComment.objects.create(newsfeed_item=self.newsfeed_item, parent=self, author=author, content=content)
        if to_notify and author != self.author:
            Notification.objects.create_nw_item_comment_reply_notification(nw_comment=self, reply=reply)
        return reply


class NewsfeedItemLike(models.Model):
    newsfeed_item = models.ForeignKey(NewsfeedItem, related_name='likes')
    author = models.ForeignKey(User)
    unique_together = ('newsfeed_item', 'author')

# TODO: Move these Notifications to another place
# TODO: Figure out what a CommentReply notification should look like, as currently
# TODO:     some hold the content of the replier's comment and some hold the content of the original comment
class NotificationManager(hstore.HStoreManager):
    """
    Use a custom Notification manager for specific type of Notification creation
    """
    def create(self, *args, **kwargs):
        raise ForbiddenMethodError('This method is not intended to be used. '
                                   'Please use any of the create_xxx methods to create a specific type of notification')

    def _create(self, *args, **kwargs):
        """
        The create() method, intentionally marked as private as it is not intended for usage at all,
            except for testing purposes
        """
        return super().create(*args, **kwargs)

    def create_receive_follow_notification(self, recipient: User, follower: User):
        """
        Creates a Notification that a User has been followed
        ex: Stanislav has followed you!
        """
        return ReceiveFollowNotificationManager(self, recipient=recipient, follower=follower).create()

    def create_receive_submission_upvote_notification(self, submission: 'Submission', liker: User):
        """
        Creates a Notification that a User has liked your submission
        ex: Stanislav has liked your Submission for Challenge Robert's Pass
        """
        return ReceiveSubmissionUpvoteNotificationManager(self, submission=submission, liker=liker).create()

    def create_receive_nw_item_like_notification(self, nw_item: NewsfeedItem, liker: User):
        return ReceiveNWItemLikeNotificationManager(self, nw_item=nw_item, liker=liker).create()

    def create_new_challenge_notification(self, recipient: User, challenge: 'Challenge'):
        """ A notification which notifies the user that a new challenge has appeared on the site"""
        # TODO: Figure out a way to add new challenges and create notifications.

        return self._create(recipient=recipient, type=NEW_CHALLENGE_NOTIFICATION,
                            content={'challenge_name': challenge.name, 'challenge_id': challenge.id,
                                     'challenge_subcategory_name': challenge.category.name})

    def create_nw_item_comment_notification(self, nw_item: NewsfeedItem, commenter: User):
        """ A notification which notifies the user that somebody has commented on his NewsfeedItem """
        return ReceiveNWItemCommentNotificationManager(self, nw_item=nw_item, commenter=commenter).create()

    def create_nw_item_comment_reply_notification(self, nw_comment: NewsfeedItemComment, reply: NewsfeedItemComment):
        if nw_comment.author == reply.author:
            return

        return self._create(recipient=nw_comment.author, type=RECEIVE_NW_ITEM_COMMENT_REPLY_NOTIFICATION,
                            content={
                                'nw_comment_id': nw_comment.id,
                                'commenter_id': reply.author.id,
                                'commenter_name': reply.author.username,
                                'comment_content': reply.content
                            })

    def create_submission_comment_notification(self, comment: SubmissionComment):
        if comment.author == comment.submission.author:
            return

        return self._create(recipient=comment.submission.author, type=RECEIVE_SUBMISSION_COMMENT_NOTIFICATION,
                            content={
                                'submission_id': comment.submission.id,
                                'challenge_id': comment.submission.challenge.id,
                                'challenge_name': comment.submission.challenge.name,
                                'commenter_name': comment.author.username,
                                'commenter_id': comment.author.id,
                                'comment_content': comment.content,
                                'comment_id': comment.id
                            })

    def create_submission_comment_reply_notification(self, comment: SubmissionComment):
        if comment.parent.author == comment.author:
            return

        return self._create(recipient=comment.parent.author, type=RECEIVE_SUBMISSION_COMMENT_REPLY_NOTIFICATION,
                           content={
                               'submission_id': comment.submission.id,
                               'challenge_id': comment.submission.challenge.id,
                               'challenge_name': comment.submission.challenge.name,
                               'commenter_name': comment.author.username,
                               'commenter_id': comment.author.id,
                               'comment_content': comment.content,
                               'comment_id': comment.id
                           })

    def create_challenge_comment_reply_notification(self, reply: ChallengeComment):
        if reply.parent.author == reply.author:
            return

        return self._create(recipient=reply.parent.author, type=RECEIVE_CHALLENGE_COMMENT_REPLY_NOTIFICATION,
                            content={
                                'challenge_id': reply.challenge.id,
                                'challenge_name': reply.challenge.name,
                                'comment_id': reply.id,
                                'comment_content': reply.content,
                                'commenter_id': reply.author.id,
                                'commenter_name': reply.author.username
                            })


class ReceiveFollowNotificationManager():
    """
    Raises InvalidFollowError
    """
    TYPE = RECEIVE_FOLLOW_NOTIFICATION
    SQUASHED_TYPE = RECEIVE_FOLLOW_NOTIFICATION_SQUASHED

    def __init__(self, notification_manager: NotificationManager, recipient: User, follower: User):
        self.notification_manager: NotificationManager= notification_manager
        self.recipient = recipient
        self.follower = follower

    def create(self):
        """
        Creates a Notification that a User has been followed
        ex: Stanislav has followed you!
        """
        if self.follower == self.recipient:
            raise InvalidFollowError('You cannot follow yourself!')

        if self.should_squash():
            return self.squash()
        else:
            return self.notification_manager._create(recipient=self.recipient, type=RECEIVE_FOLLOW_NOTIFICATION,
                                                     content={
                                                         'follower_id': self.follower.id,
                                                         'follower_name': self.follower.username
                                                     })

    def find_last_squashable_notification(self) -> 'Notification':
        """
        This method should get the last Notification that is not read and is the same as our type
        """
        last_notification = self.notification_manager.filter(
            type__in=[self.TYPE, self.SQUASHED_TYPE],
            is_read=False,
            recipient=self.recipient).last()

        return last_notification

    def should_squash(self) -> bool:
        self.last_notification = self.find_last_squashable_notification()
        return self.last_notification is not None

    def squash(self) -> 'Notification':
        """ Squashes the notification we're about to create with another one """
        if self.last_notification.type == self.TYPE:
            notification = self.convert_to_squashed_type()
        else:
            notification = self.add_to_squashed_type()

        return notification

    def convert_to_squashed_type(self) -> 'Notification':
        """
        Converts the latest squashable notification into a SQUASHED type
            and combines it with the one being created
        """
        self.last_notification.type = self.SQUASHED_TYPE
        new_content = {
            'followers': [
                self.last_notification.content,
                {'follower_id': self.follower.id, 'follower_name': self.follower.username}
            ]
        }
        self.last_notification.content = new_content
        self.last_notification.save()
        return self.last_notification

    def add_to_squashed_type(self) -> 'Notification':
        """
        Adds to the latest notification (which should be a SQUASHED type)
        """
        new_entry = {'follower_id': self.follower.id, 'follower_name': self.follower.username}
        self.last_notification.content['followers'].append(new_entry)
        self.last_notification.save()
        return self.last_notification


class ReceiveSubmissionUpvoteNotificationManager():
    TYPE = RECEIVE_SUBMISSION_UPVOTE_NOTIFICATION
    SQUASHED_TYPE = RECEIVE_SUBMISSION_UPVOTE_NOTIFICATION_SQUASHED

    def __init__(self, notification_manager: NotificationManager, submission: 'Submission', liker: User):
        self.notification_manager: NotificationManager = notification_manager
        self.submission = submission
        self.liker = liker

    def create(self):
        """
        Creates a Notification that a User has liked your submission
        ex: Stanislav has liked your Submission for Challenge Robert's Pass
        """
        if self.liker == self.submission.author:
            return

        if self.should_squash():
            return self.squash()
        else:
            return self.notification_manager._create(recipient=self.submission.author, type=self.TYPE,
                                                     content={
                                                         'submission_id': self.submission.id,
                                                         'challenge_id': self.submission.challenge.id,
                                                         'challenge_name': self.submission.challenge.name,
                                                         'liker_id': self.liker.id,
                                                         'liker_name': self.liker.username
                                                     })

    def should_squash(self) -> bool:
        """ Returns a boolean, indicating if we should squash this notification with another one """
        self.last_notification = self.find_last_squashable_notification()
        return self.last_notification is not None

    def squash(self) -> 'Notification':
        """ Squashes the notification we're about to create with another one """
        if self.last_notification.type == self.TYPE:
            notification = self.convert_to_squashed_type()
        else:
            notification = self.add_to_squashed_type()

        return notification

    def convert_to_squashed_type(self) -> 'Notification':
        """
        Converts the latest squashable notification into a SQUASHED type
            and combines it with the one being created
        """
        self.last_notification.type = self.SQUASHED_TYPE
        new_content = {
            'submission_id': self.submission.id,
            'challenge_id': self.submission.challenge.id,
            'challenge_name': self.submission.challenge.name,
            'likers': [
                {
                    'liker_id': self.last_notification.content['liker_id'],
                    'liker_name': self.last_notification.content['liker_name']
                },
                {'liker_id': self.liker.id, 'liker_name': self.liker.username}
            ]
        }
        self.last_notification.content = new_content
        self.last_notification.save()
        return self.last_notification

    def add_to_squashed_type(self) -> 'Notification':
        """
        Adds to the latest notification (which should be a SQUASHED type)
        """
        new_entry = {'liker_id': self.liker.id, 'liker_name': self.liker.username}
        self.last_notification.content['likers'].append(new_entry)
        self.last_notification.save()
        return self.last_notification

    def find_last_squashable_notification(self) -> 'Notification':
        """
        This method should get the last Notification that is not read and is the same as our type
            (e.g same submission was upvoted)
        """
        return self.notification_manager.filter(
            type__in=[self.TYPE, self.SQUASHED_TYPE],
            is_read=False,
            content__contains={'submission_id': self.submission.id},
            recipient=self.submission.author
        ).last()


class ReceiveNWItemLikeNotificationManager:
    """
    A notification that a user has liked your NewsfeedItem
    """
    TYPE = RECEIVE_NW_ITEM_LIKE_NOTIFICATION
    SQUASHED_TYPE = RECEIVE_NW_ITEM_LIKE_NOTIFICATION_SQUASHED

    def __init__(self, notification_manager: NotificationManager, nw_item: NewsfeedItem, liker: User):
        self.notification_manager: NotificationManager = notification_manager
        self.liker = liker
        self.nw_item = nw_item

    def create(self):
        if self.liker == self.nw_item.author:
            return
        if self.should_squash():
            return self.squash()
        else:
            # TODO: Change nw_item_content, nw_item_type to nw_content, nw_type or vice-versa. but be consistent!
            return self.notification_manager._create(recipient=self.nw_item.author, type=RECEIVE_NW_ITEM_LIKE_NOTIFICATION,
                                                     content={'nw_content': self.nw_item.content,
                                                              'liker_id': self.liker.id, 'liker_name': self.liker.username,
                                                              'nw_type': self.nw_item.type, 'nw_item_id': self.nw_item.id})

    def should_squash(self) -> bool:
        self.last_notification = self.find_last_squashable_notification()
        return self.last_notification is not None

    def squash(self) -> 'Notification':
        """ Squashes the notification we're about to create with another one """
        if self.last_notification.type == self.TYPE:
            notification = self.convert_to_squashed_type()
        else:
            notification = self.add_to_squashed_type()

        return notification

    def convert_to_squashed_type(self) -> 'Notification':
        """
        Converts the latest squashable notification into a SQUASHED type
            and combines it with the one being created
        """
        self.last_notification.type = self.SQUASHED_TYPE

        new_content = {
            'nw_content': self.nw_item.content,
            'nw_type': self.nw_item.type,
            'nw_item_id': self.nw_item.id,
            'likers': [
                {'liker_id': self.last_notification.content['liker_id'], 'liker_name': self.last_notification.content['liker_name']},
                {'liker_id': self.liker.id, 'liker_name': self.liker.username}
            ]
        }
        self.last_notification.content = new_content
        self.last_notification.save()
        return self.last_notification

    def add_to_squashed_type(self):
        """
        Adds to the latest notification (which should be a SQUASHED type)
        """
        self.last_notification.content['likers'].append({'liker_id': self.liker.id, 'liker_name': self.liker.username})
        self.last_notification.save()
        return self.last_notification

    def find_last_squashable_notification(self) -> 'Notification':
        """
        This method should get the last Notification that is not read and is the same as our type
            (e.g same submission was upvoted)
        """
        return self.notification_manager.filter(
            type__in=[self.TYPE, self.SQUASHED_TYPE],
            is_read=False,
            content__contains={'nw_item_id': self.nw_item.id},
            recipient=self.nw_item.author
        ).last()


class ReceiveNWItemCommentNotificationManager:
    """
    A notification that a user has liked your NewsfeedItem
    """
    TYPE = RECEIVE_NW_ITEM_COMMENT_NOTIFICATION
    SQUASHED_TYPE = RECEIVE_NW_ITEM_COMMENT_NOTIFICATION_SQUASHED

    def __init__(self, notification_manager: NotificationManager, nw_item: NewsfeedItem, commenter: User):
        self.notification_manager: NotificationManager = notification_manager
        self.commenter = commenter
        self.nw_item = nw_item

    def create(self):
        if self.commenter == self.nw_item.author:
            return
        if self.should_squash():
            return self.squash()
        else:
            return self.notification_manager._create(recipient=self.nw_item.author, type=self.TYPE,
                                                     content={'nw_item_content': self.nw_item.content,
                                                              'commenter_id': self.commenter.id, 'commenter_name': self.commenter.username,
                                                              'nw_item_type': self.nw_item.type, 'nw_item_id': self.nw_item.id})

    def should_squash(self) -> bool:
        self.last_notification = self.find_last_squashable_notification()
        return self.last_notification is not None

    def squash(self) -> 'Notification':
        """ Squashes the notification we're about to create with another one """
        if self.last_notification.type == self.TYPE:
            notification = self.convert_to_squashed_type()
        else:
            notification = self.add_to_squashed_type()

        return notification

    def convert_to_squashed_type(self) -> 'Notification':
        """
        Converts the latest squashable notification into a SQUASHED type
            and combines it with the one being created
        """
        self.last_notification.type = self.SQUASHED_TYPE

        new_content = {
            'nw_item_content': self.nw_item.content,
            'nw_item_type': self.nw_item.type,
            'nw_item_id': self.nw_item.id,
            'commenters': [
                {'commenter_id': self.last_notification.content['commenter_id'], 'commenter_name': self.last_notification.content['commenter_name']},
                {'commenter_id': self.commenter.id, 'commenter_name': self.commenter.username}
            ]
        }
        self.last_notification.content = new_content
        self.last_notification.save()
        return self.last_notification

    def add_to_squashed_type(self):
        """
        Adds to the latest notification (which should be a SQUASHED type)
        """
        self.last_notification.content['commenters'].append({'commenter_id': self.commenter.id, 'commenter_name': self.commenter.username})
        self.last_notification.save()
        return self.last_notification

    def find_last_squashable_notification(self) -> 'Notification':
        """
        This method should get the last Notification that is not read and is the same as our type
            (e.g same submission was upvoted)
        """
        return self.notification_manager.filter(
            type__in=[self.TYPE, self.SQUASHED_TYPE],
            is_read=False,
            content__contains={'nw_item_id': self.nw_item.id},
            recipient=self.nw_item.author
        ).last()


class Notification(models.Model):
    """
    A Notification is a simple notification that a user receives, again facebook-esque
    Since the content here is dynamic (somebody liked your post, new challenge appears in the site, etc),
        we need an HStore field to store data related to the type of the notification.
    """
    recipient = models.ForeignKey(User)
    type = models.CharField(max_length=60)  # no other table for now
    content = JSONField()  # varies depending on the type
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = NotificationManager()

    # TODO: Implement some logic to squash multiple notifications into one
    # TODO: And have it be marked as unread again,
    # e.g One user likes your photo, another does again, another again, and when you login you'll get 3 different notifications? No thanks.

    class Meta:
        ordering = ('updated_at', )  # order by updated_at, as we might update notifications to simulate squashing

    @staticmethod
    def is_valid_submission_upvote_notification(submission_vote: SubmissionVote):
        return submission_vote.is_upvote and submission_vote.author != submission_vote.submission.author

    @staticmethod
    def fetch_unread_notifications_for_user(user: User):
        return Notification.objects.filter(recipient=user, is_read=False).order_by('updated_at')

    def is_recipient(self, user: User):
        return self.recipient_id == user.id


from deadline.celery import send_notification


@receiver(pre_save, sender=Notification)
def notification_type_validation(sender, instance, *args, **kwargs):
    # Validate that the type is valid and contains what we expect exactly
    if instance.type not in VALID_NOTIFICATION_TYPES:
        raise InvalidNotificationType(f'{instance.type} is not a valid Notification type!')

    # Assert that each field is present
    required_fields = NOTIFICATION_TYPE_CONTENT_FIELDS[instance.type]
    for field in required_fields:
        if field not in instance.content:
            raise MissingNotificationContentField(
                f'The field {field} must be in the content of Notification of type {instance.type}.')

    # Assert that no other unnecessary fields are present
    if len(required_fields) < len(instance.content.keys()):
        # Some unnecessary field is present
        for field in instance.content.keys():
            if field not in required_fields:
                raise InvalidNotificationContentField(
                    f'The field {field} is not part of the expected content for {instance.type} and is unnecessary!')
    # TODO: Raise Squashable exception


@receiver(post_save, sender=Notification)
def notif_post_save_send(sender, instance, created, *args, **kwargs):
    if created:
        send_notification(instance.id)
