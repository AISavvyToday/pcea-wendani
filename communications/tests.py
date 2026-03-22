import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, TestCase, override_settings

from communications.models import SMSNotification
from communications.services.sms_api_client import SMSAPIClient
from communications.views import SMSSettingsView
from core.models import Organization


class SMSAPIClientTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(
            name='PCEA Wendani',
            code='PWA',
            sms_account_number='SMS001',
            sms_balance=17,
        )

    @override_settings(
        SMS_SERVICE_API_TOKEN='test-token',
        SMS_SERVICE_API_URL='https://sms.example/api/v1',
    )
    @patch('communications.services.sms_api_client.requests.get')
    def test_get_balance_success(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                'success': True,
                'balance': 42,
                'price_per_sms': 1.25,
            }),
        )

        client = SMSAPIClient()
        result = client.get_balance(self.organization)

        self.assertEqual(
            result,
            {'success': True, 'balance': 42, 'price_per_sms': 1.25},
        )
        mock_get.assert_called_once()

    @override_settings(
        SMS_SERVICE_API_TOKEN='test-token',
        SMS_SERVICE_API_URL='https://sms.example/api/v1',
    )
    @patch('communications.services.sms_api_client.requests.get')
    def test_get_balance_failure(self, mock_get):
        mock_get.return_value = Mock(
            status_code=503,
            json=Mock(return_value={'success': False, 'error': 'Service unavailable'}),
            text='Service unavailable',
        )

        client = SMSAPIClient()
        result = client.get_balance(self.organization)

        self.assertFalse(result['success'])
        self.assertIn('503', result['error'])

    @override_settings(
        SMS_SERVICE_API_TOKEN='test-token',
        SMS_SERVICE_API_URL='https://sms.example/api/v1',
    )
    @patch('communications.services.sms_api_client.requests.post')
    def test_send_sms_success(self, mock_post):
        mock_post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                'success': True,
                'message_id': 'remote-123',
            }),
        )

        client = SMSAPIClient()
        notification = client.send_sms(
            '0712345678',
            'Hello Jane',
            self.organization,
            purpose='greeting',
        )

        notification.refresh_from_db()
        self.assertEqual(notification.recipient_phone, '254712345678')
        self.assertEqual(notification.status, 'sent')
        self.assertIsNotNone(notification.sent_at)
        self.assertEqual(notification.purpose, 'greeting')
        self.assertFalse(hasattr(notification, 'message_id'))
        mock_post.assert_called_once()

    @override_settings(
        SMS_SERVICE_API_TOKEN='test-token',
        SMS_SERVICE_API_URL='https://sms.example/api/v1',
    )
    @patch('communications.services.sms_api_client.requests.post')
    def test_send_bulk_sms_success(self, mock_post):
        mock_post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                'success': True,
                'results': [
                    {'phone_number': '254712345678', 'status': 'sent', 'message_id': '1'},
                    {'phone_number': '254722222222', 'status': 'failed', 'error': 'Insufficient credits'},
                ],
            }),
        )

        client = SMSAPIClient()
        notifications = client.send_bulk_sms(
            [
                {'phone': '0712345678', 'message': 'Hi Jane'},
                {'phone': '0722222222', 'message': 'Hi John'},
            ],
            'Default message',
            self.organization,
            purpose='bulk_notice',
        )

        self.assertEqual(len(notifications), 2)
        self.assertEqual(notifications[0].recipient_phone, '254712345678')
        self.assertEqual(notifications[0].message, 'Hi Jane')
        self.assertEqual(notifications[0].status, 'sent')
        self.assertEqual(notifications[1].recipient_phone, '254722222222')
        self.assertEqual(notifications[1].message, 'Hi John')
        self.assertEqual(notifications[1].status, 'failed')
        self.assertEqual(notifications[1].error_message, 'Insufficient credits')
        self.assertEqual(SMSNotification.objects.count(), 2)

    @override_settings(
        SMS_SERVICE_API_TOKEN='test-token',
        SMS_SERVICE_API_URL='https://sms.example/api/v1',
    )
    @patch('communications.services.sms_api_client.requests.post')
    def test_send_sms_missing_sms_account_number(self, mock_post):
        organization = Organization.objects.create(
            name='No SMS Account',
            code='NOSMS',
            sms_account_number='',
        )

        client = SMSAPIClient()
        notification = client.send_sms(
            '0712345678',
            'Hello',
            organization,
            purpose='missing_account',
        )

        self.assertEqual(notification.status, 'failed')
        self.assertIn('missing SMS account number', notification.error_message)
        mock_post.assert_not_called()

    @override_settings(
        SMS_SERVICE_API_TOKEN='test-token',
        SMS_SERVICE_API_URL='https://sms.example/api/v1',
    )
    @patch('communications.services.sms_api_client.requests.post')
    def test_send_sms_invalid_phone_normalization(self, mock_post):
        client = SMSAPIClient()
        notification = client.send_sms(
            '12345',
            'Hello',
            self.organization,
            purpose='invalid_phone',
        )

        self.assertEqual(notification.status, 'failed')
        self.assertIn('Invalid phone number format', notification.error_message)
        self.assertEqual(notification.recipient_phone, '12345')
        mock_post.assert_not_called()


class SMSSettingsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(
            name='PCEA Wendani',
            code='VIEW',
            sms_account_number='SMS777',
            sms_balance=12,
            sms_price_per_unit=1.75,
        )

    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(SWIFT_RESIDE_PAYBILL='522533', SWIFT_RESIDE_TILL='SWIFTTECH')
    @patch('communications.services.sms_api_client.sms_api_client.get_balance')
    def test_sms_settings_balance_success_uses_central_api(self, mock_get_balance):
        mock_get_balance.return_value = {
            'success': True,
            'balance': 88,
            'price_per_sms': 2.5,
        }
        request = self.factory.get('/communications/sms-settings/')
        request.organization = self.organization
        request.user = SimpleNamespace(is_authenticated=True, role='super_admin')

        view = SMSSettingsView()
        view.request = request
        context = view.get_context_data()

        self.assertTrue(context['balance_api_available'])
        self.assertEqual(context['sms_balance'], 88)
        self.assertEqual(context['sms_price'], 2.5)
        self.assertEqual(context['payment_account'], 'SWIFTTECH#SMS777')
        self.assertIsNone(context['balance_error'])

    @override_settings(SWIFT_RESIDE_PAYBILL='522533', SWIFT_RESIDE_TILL='SWIFTTECH')
    @patch('communications.services.sms_api_client.sms_api_client.get_balance')
    def test_sms_settings_balance_failure_shows_operator_friendly_fallback(self, mock_get_balance):
        mock_get_balance.return_value = {
            'success': False,
            'error': 'Central service timeout',
        }
        request = self.factory.get('/communications/sms-settings/')
        request.organization = self.organization
        request.user = SimpleNamespace(is_authenticated=True, role='super_admin')

        view = SMSSettingsView()
        view.request = request
        context = view.get_context_data()

        self.assertFalse(context['balance_api_available'])
        self.assertEqual(context['sms_balance'], 12)
        self.assertEqual(context['sms_price'], self.organization.sms_price_per_unit)
        self.assertEqual(context['payment_account'], 'SWIFTTECH#SMS777')
        self.assertEqual(context['balance_error'], 'Central service timeout')


class StartupCleanlinessTests(TestCase):
    def test_manage_check_is_clean(self):
        repo_root = Path(__file__).resolve().parent.parent

        result = subprocess.run(
            [sys.executable, 'manage.py', 'check'],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

        combined_output = f"{result.stdout}\n{result.stderr}"

        self.assertEqual(result.returncode, 0, combined_output)
        self.assertNotIn('templates.E003', combined_output)
        self.assertNotIn('custom_filters', combined_output)
        self.assertNotIn('SMS_SERVICE_API_TOKEN not configured', combined_output)
        self.assertNotIn('imarabiz SMS API credentials not configured', combined_output)
