# File: payments/tests/conftest.py
# ============================================================
# RATIONALE: Pytest fixtures for payment tests (if using pytest)
# ============================================================

import pytest
from decimal import Decimal
from datetime import date
from django.contrib.auth import get_user_model

from students.models import Student, Grade
from fees.models import Invoice

User = get_user_model()


@pytest.fixture
def test_grade(db):
    """Create a test grade"""
    return Grade.objects.create(
        name='Test Grade',
        code='TG',
        level='primary'
    )


@pytest.fixture
def test_student(db, test_grade):
    """Create a test student"""
    return Student.objects.create(
        admission_number='PWA9999',
        first_name='Test',
        last_name='Student',
        date_of_birth=date(2015, 1, 1),
        gender='M',
        current_grade=test_grade,
        status='active',
        parent_phone='254700000000',
        parent_email='test@example.com'
    )


@pytest.fixture
def test_invoice(db, test_student):
    """Create a test invoice"""
    return Invoice.objects.create(
        student=test_student,
        invoice_number='INV-TEST-001',
        academic_year=2025,
        term=1,
        total_amount=Decimal('50000.00'),
        amount_paid=Decimal('0.00'),
        balance=Decimal('50000.00'),
        status='unpaid',
        due_date=date(2025, 12, 31)
    )


@pytest.fixture
def equity_api_key(settings):
    """Set Equity API key for tests"""
    settings.EQUITY_API_KEY = 'test-equity-key'
    return 'test-equity-key'


@pytest.fixture
def coop_credentials(settings):
    """Set Co-op credentials for tests"""
    settings.COOP_IPN_USERNAME = 'testuser'
    settings.COOP_IPN_PASSWORD = 'testpass'
    settings.SCHOOL_COOP_ACCOUNT_NO = '01234567890100'
    return ('testuser', 'testpass')