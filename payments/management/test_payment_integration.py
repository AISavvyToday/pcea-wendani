# File: payments/management/commands/test_payment_integration.py
# ============================================================
# RATIONALE: Management command to test payment integration locally
# ============================================================

import json
import requests
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = 'Test payment integration endpoints locally'

    def add_arguments(self, parser):
        parser.add_argument(
            '--endpoint',
            type=str,
            choices=['equity-validation', 'equity-notification', 'coop-ipn', 'all'],
            default='all',
            help='Which endpoint to test'
        )
        parser.add_argument(
            '--base-url',
            type=str,
            default='http://localhost:8000',
            help='Base URL for the API'
        )
        parser.add_argument(
            '--bill-number',
            type=str,
            default='PWA1001',
            help='Bill number to use for testing'
        )

    def handle(self, *args, **options):
        base_url = options['base_url']
        endpoint = options['endpoint']
        bill_number = options['bill_number']

        self.stdout.write(self.style.NOTICE(f'Testing against: {base_url}'))
        self.stdout.write('')

        if endpoint in ['equity-validation', 'all']:
            self.test_equity_validation(base_url, bill_number)

        if endpoint in ['equity-notification', 'all']:
            self.test_equity_notification(base_url, bill_number)

        if endpoint in ['coop-ipn', 'all']:
            self.test_coop_ipn(base_url, bill_number)

    def test_equity_validation(self, base_url, bill_number):
        self.stdout.write(self.style.HTTP_INFO('=== Testing Equity Validation ==='))
        
        url = f'{base_url}/api/payments/equity/validation/'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Api-Key {settings.EQUITY_API_KEY}'
        }
        payload = {'billNumber': bill_number}

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            self.stdout.write(f'Status: {response.status_code}')
            self.stdout.write(f'Response: {json.dumps(response.json(), indent=2)}')
            
            if response.status_code == 200:
                self.stdout.write(self.style.SUCCESS('✓ Equity Validation: PASSED'))
            else:
                self.stdout.write(self.style.WARNING(f'✗ Equity Validation: {response.status_code}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Equity Validation: {str(e)}'))
        
        self.stdout.write('')

    def test_equity_notification(self, base_url, bill_number):
        self.stdout.write(self.style.HTTP_INFO('=== Testing Equity Notification ==='))
        
        url = f'{base_url}/api/payments/equity/notification/'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Api-Key {settings.EQUITY_API_KEY}'
        }
        
        import uuid
        payload = {
            'billNumber': bill_number,
            'amount': '1000.00',
            'bankReference': f'EQ-TEST-{uuid.uuid4().hex[:8].upper()}',
            'transactionDate': '2025-01-15T14:30:00',
            'customerName': 'Test Parent',
            'phoneNumber': '254712345678',
            'paymentChannel': 'TEST'
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            self.stdout.write(f'Status: {response.status_code}')
            self.stdout.write(f'Response: {json.dumps(response.json(), indent=2)}')
            
            if response.status_code == 200:
                self.stdout.write(self.style.SUCCESS('✓ Equity Notification: PASSED'))
            else:
                self.stdout.write(self.style.WARNING(f'✗ Equity Notification: {response.status_code}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Equity Notification: {str(e)}'))
        
        self.stdout.write('')

    def test_coop_ipn(self, base_url, bill_number):
        self.stdout.write(self.style.HTTP_INFO('=== Testing Co-op IPN ==='))
        
        url = f'{base_url}/api/payments/coop/ipn/'
        
        import base64
        credentials = base64.b64encode(
            f'{settings.COOP_IPN_USERNAME}:{settings.COOP_IPN_PASSWORD}'.encode()
        ).decode()
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Basic {credentials}'
        }
        
        import uuid
        payload = {
            'MessageReference': f'COOP-TEST-{uuid.uuid4().hex[:8].upper()}',
            'TransactionId': f'TXN-TEST-{uuid.uuid4().hex[:8].upper()}',
            'AcctNo': settings.SCHOOL_COOP_ACCOUNT_NO,
            'TxnAmount': '1000.00',
            'TxnDate': '2025-01-15',
            'Currency': 'KES',
            'DrCr': 'C',
            'CustMemo': 'Test payment',
            'Narration1': 'FT from Test Parent',
            'Narration2': f'{bill_number} Term 1 fees',
            'Narration3': '',
            'EventType': 'CREDIT',
            'Balance': '1000000.00',
            'ValueDate': '2025-01-15',
            'PostingDate': '2025-01-15',
            'BranchCode': '001'
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            self.stdout.write(f'Status: {response.status_code}')
            self.stdout.write(f'Response: {json.dumps(response.json(), indent=2)}')
            
            if response.status_code == 200:
                self.stdout.write(self.style.SUCCESS('✓ Co-op IPN: PASSED'))
            else:
                self.stdout.write(self.style.WARNING(f'✗ Co-op IPN: {response.status_code}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Co-op IPN: {str(e)}'))
        
        self.stdout.write('')