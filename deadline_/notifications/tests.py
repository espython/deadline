from unittest.mock import MagicMock, patch

import asyncio
from django.test import TestCase

from challenges.tests.base import TestHelperMixin
from notifications.errors import NotificationAlreadyRead, OfflineRecipientError, RecipientMismatchError, \
    InvalidNotificationToken
from notifications.handlers import NotificationsHandler, _read_notification
from social.models.notification import Notification
from social.serializers import NotificationSerializer


class NotificationsHandlerTests(TestCase, TestHelperMixin):
    def setUp(self):
        self.base_set_up(create_user=True)
        self.notification = Notification.objects.create_new_challenge_notification(recipient=self.auth_user, challenge=self.challenge)

    def test_receive_message_functions(self):
        with patch('notifications.handlers.ws_connections', {self.notification.recipient_id: MagicMock()}):
            self.assertTrue(NotificationsHandler.receive_message(str(self.notification.id)))

    @patch('notifications.handlers.NotificationsHandler.validate_notification')
    def test_fetch_notification_returns_notif_and_calls_validate(self, mock_validate_notif):
        received_notif = NotificationsHandler.fetch_notification(self.notification.id)
        self.assertEqual(received_notif, self.notification)
        mock_validate_notif.assert_called_once_with(self.notification)

    def test_validate_validates_successfully(self):
        with patch('notifications.handlers.ws_connections', {self.notification.recipient_id: MagicMock(is_valid=True)}):
            NotificationsHandler.validate_notification(self.notification)

    def test_validate_raises_already_read_if_notif_read(self):
        self.notification.is_read = True
        self.notification.save()

        with self.assertRaises(NotificationAlreadyRead):
            NotificationsHandler.validate_notification(self.notification)

    def test_validate_OfflineRecipientError_if_recipient_not_in_ws_conns(self):
        with patch('notifications.handlers.ws_connections', {}):
            with self.assertRaises(OfflineRecipientError):
                NotificationsHandler.validate_notification(self.notification)

    def test_validate_OfflineRecipientError_if_recipient_cons_not_validated(self):
        ws_conn_mock = {self.notification.recipient_id: MagicMock(is_valid=False)}
        with patch('notifications.handlers.ws_connections', ws_conn_mock):
            with self.assertRaises(OfflineRecipientError):
                NotificationsHandler.validate_notification(self.notification)

    @patch('notifications.handlers.NotificationsHandler.fetch_notification')
    @patch('notifications.handlers.NotificationsHandler.send_notification')
    @patch('notifications.handlers.asyncio.ensure_future')
    def test_receive_message_calls_expected_methods(self, mock_ensure_future, mock_send_notif, mock_fetch):
        mock_send_notif.return_value = 'fixThis'
        mock_fetch.return_value = 'HipHop'

        is_processed = NotificationsHandler.receive_message('1')

        self.assertTrue(is_processed)
        mock_fetch.assert_called_once_with(1)
        mock_send_notif.assert_called_once_with(mock_fetch.return_value)
        mock_ensure_future.assert_called_once_with(mock_send_notif.return_value)

    @patch('notifications.handlers.NotificationsHandler.fetch_notification')
    @patch('notifications.handlers.NotificationsHandler.send_notification')
    def test_receive_message_returns_true_on_notif_already_read_error(self, mock_send, mock_fetch):
        mock_fetch.side_effect = NotificationAlreadyRead()

        is_processed = NotificationsHandler.receive_message('1111')

        self.assertTrue(is_processed)
        mock_fetch.assert_called_once_with(1111)
        mock_send.assert_not_called()

    @patch('notifications.handlers.NotificationsHandler.fetch_notification')
    @patch('notifications.handlers.NotificationsHandler.send_notification')
    def test_receive_message_returns_true_on_notif_doesnt_exist_err(self, mock_send, mock_fetch):
        mock_fetch.side_effect = Notification.DoesNotExist()
        is_processed = NotificationsHandler.receive_message('1111')

        self.assertTrue(is_processed)
        mock_fetch.assert_called_once_with(1111)
        mock_send.assert_not_called()

    @patch('notifications.handlers.NotificationsHandler.fetch_notification')
    @patch('notifications.handlers.NotificationsHandler.send_notification')
    def test_receive_message_returns_true_on_offlineRecipientError(self, mock_send, mock_fetch):
        mock_fetch.side_effect = OfflineRecipientError()
        is_processed = NotificationsHandler.receive_message('1111')

        self.assertTrue(is_processed)
        mock_fetch.assert_called_once_with(1111)
        mock_send.assert_not_called()

    @patch('notifications.handlers.NotificationsHandler.send_notification')
    def test_receive_message_returns_false_on_invalid_message(self, mock_send):
        """ This is unexpected, as most probably the message structure is not as expected
        (not a valid int for the parsing), as such, it should not bep rocessed """
        is_processed = NotificationsHandler.receive_message('{"notif_id": "1"}')
        self.assertFalse(is_processed)
        mock_send.assert_not_called()

    @patch('notifications.handlers.NotificationsHandler.fetch_notification')
    @patch('notifications.handlers.NotificationsHandler.send_notification')
    def test_receive_message_returns_false_on_other_error(self, mock_send, mock_fetch):
        """ This is an unexpected error and as such the message should be marked as non-processed"""
        mock_fetch.side_effect = Exception()
        is_processed = NotificationsHandler.receive_message('1111')

        self.assertFalse(is_processed)
        mock_send.assert_not_called()

    @patch('notifications.handlers.asyncio.ensure_future')
    def test_send_notification_send_message(self, mock_ensure):
        @asyncio.coroutine
        def _test():
            send_message_mock = MagicMock()
            send_message_mock.return_value = 1
            expected_message = {
                "type": "NOTIFICATION",
                "notification": NotificationSerializer(self.notification).data
            }
            ws_conn_mock = MagicMock(send_message=send_message_mock, is_valid=True)
            with patch('notifications.handlers.ws_connections', {self.notification.recipient_id: ws_conn_mock}):
                yield from NotificationsHandler.send_notification(self.notification)

            send_message_mock.assert_called_once_with(expected_message)
            mock_ensure.assert_called_once_with(send_message_mock.return_value)
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)
        self.loop.run_until_complete(_test())

    @patch('notifications.handlers.asyncio.ensure_future')
    def test_send_notification_doesnt_send_if_recipient_not_in_ws(self, mock_ensure):
        @asyncio.coroutine
        def _test():
            with patch('notifications.handlers.ws_connections', {}):
                yield from NotificationsHandler.send_notification(self.notification)
                mock_ensure.assert_not_called()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)
        self.loop.run_until_complete(_test())

    @patch('notifications.handlers.asyncio.ensure_future')
    def test_send_notification_doesnt_send_if_recipient_not_validated(self, mock_ensure):
        @asyncio.coroutine
        def _test():
            send_message_mock = MagicMock()
            send_message_mock.return_value = 1

            ws_conn_mock = MagicMock(send_message=send_message_mock, is_valid=False)
            with patch('notifications.handlers.ws_connections', {self.notification.recipient_id: ws_conn_mock}):
                yield from NotificationsHandler.send_notification(self.notification)
            send_message_mock.assert_not_called()
            mock_ensure.assert_not_called()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)
        self.loop.run_until_complete(_test())


class ReadNotificationHandlerTests(TestCase, TestHelperMixin):
    def setUp(self):
        self.user_id = 1
        self.user_obj_mock = MagicMock(id=self.user_id)
        self.user_connection_mock = MagicMock(user=self.user_obj_mock, is_valid=True)
        self.ws_connections_mock = {self.user_id: self.user_connection_mock}

    def test_sets_notif_is_read(self):
        self.base_set_up(create_user=True)
        self.notification = Notification.objects.create_new_challenge_notification(recipient=self.auth_user,
                                                                                   challenge=self.challenge)
        self.user_obj_mock.id = self.auth_user.id
        with patch('notifications.handlers.ws_connections', {self.auth_user.id: self.user_connection_mock}) as mock_conn:
            _read_notification('notification_token', self.auth_user.id, self.notification.id)

            self.user_connection_mock.user.notification_token_is_valid.assert_called_once_with('notification_token')

            self.notification.refresh_from_db()
            self.assertTrue(self.notification.is_read)

    def test_raises_recipient_mismatch_error_if_user_is_not_recipient_of_notification(self):
        self.base_set_up(create_user=True)
        self.notification = Notification.objects.create_new_challenge_notification(recipient=self.auth_user, challenge=self.challenge)
        self.user_obj_mock.id = 111
        with patch('notifications.handlers.ws_connections', {111: self.user_connection_mock}) as mock_conn:
            with self.assertRaises(RecipientMismatchError):
                _read_notification('notification_token', 111, self.notification.id)
                self.user_connection_mock.user.notification_token_is_valid.assert_called_once_with('notification_token')

    def test_raises_offline_recipient_error_if_user_not_authenticated(self):
        with patch('notifications.handlers.ws_connections', self.ws_connections_mock):
            with self.assertRaises(OfflineRecipientError):
                _read_notification('', self.user_id + 1, 1)

    def test_raises_offline_recipient_error_if_user_not_connected(self):
        self.user_connection_mock.is_valid = False
        with patch('notifications.handlers.ws_connections', self.ws_connections_mock):
            with self.assertRaises(OfflineRecipientError):
                _read_notification('', self.user_id, 1)

    def test_invalid_token_raises_invalid_notification_token(self):
        self.user_obj_mock.notification_token_is_valid.return_value = False
        with patch('notifications.handlers.ws_connections', self.ws_connections_mock):
            with self.assertRaises(InvalidNotificationToken):
                _read_notification('', self.user_id, 1)
