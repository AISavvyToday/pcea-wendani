from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import AcademicYear, Class, Term
from communications.models import SMSNotification
from communications.services.sms_template_service import SMSTemplateService
from communications.services.sms_workflow_service import SMSWorkflowService
from core.models import Organization, PaymentMethod, PaymentSource, PaymentStatus
from finance.models import Invoice
from payments.models import Payment
from payments.services.notifications import NotificationService
from students.models import Parent, Student, StudentParent

User = get_user_model()


class SMSWorkflowBaseTestCase(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name='PCEA Wendani Academy',
            code='PWA',
            sms_account_number='SMS001',
        )
        self.user = User.objects.create_user(
            email='admin@example.com',
            password='secret123',
            first_name='Admin',
            last_name='User',
            organization=self.organization,
        )
        self.academic_year = AcademicYear.objects.create(
            organization=self.organization,
            year=2026,
            start_date=date(2026, 1, 5),
            end_date=date(2026, 12, 1),
            is_current=True,
        )
        self.term = Term.objects.create(
            organization=self.organization,
            academic_year=self.academic_year,
            term='term_1',
            start_date=date(2026, 1, 5),
            end_date=date(2026, 4, 10),
            fee_deadline=date(2026, 2, 15),
            is_current=True,
        )
        self.class_grade_5 = Class.objects.create(
            organization=self.organization,
            name='Grade 5 East',
            grade_level='grade_5',
            stream='EAST',
            academic_year=self.academic_year,
        )
        self.class_grade_6 = Class.objects.create(
            organization=self.organization,
            name='Grade 6 East',
            grade_level='grade_6',
            stream='EAST',
            academic_year=self.academic_year,
        )
        self.primary_parent = Parent.objects.create(
            organization=self.organization,
            first_name='Mary',
            last_name='Wanjiru',
            phone_primary='0712345678',
            email='mary@example.com',
            relationship='mother',
        )
        self.secondary_parent = Parent.objects.create(
            organization=self.organization,
            first_name='John',
            last_name='Wanjiru',
            phone_primary='0798765432',
            email='john@example.com',
            relationship='father',
        )
        self.student = Student.objects.create(
            organization=self.organization,
            admission_number='PWA1001',
            admission_date=date(2026, 1, 5),
            first_name='Jane',
            last_name='Doe',
            gender='F',
            date_of_birth=date(2015, 5, 10),
            current_class=self.class_grade_5,
            status='active',
            outstanding_balance=Decimal('35000.00'),
        )
        StudentParent.objects.create(
            student=self.student,
            parent=self.secondary_parent,
            relationship='father',
            is_primary=False,
        )
        StudentParent.objects.create(
            student=self.student,
            parent=self.primary_parent,
            relationship='mother',
            is_primary=True,
        )
        self.invoice = Invoice.objects.create(
            organization=self.organization,
            student=self.student,
            term=self.term,
            invoice_number='INV-2026-00001',
            subtotal=Decimal('40000.00'),
            total_amount=Decimal('40000.00'),
            amount_paid=Decimal('5000.00'),
            balance_bf=Decimal('5000.00'),
            prepayment=Decimal('1000.00'),
            balance=Decimal('35000.00'),
            status='partially_paid',
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 2, 15),
        )
        self.payment = Payment.objects.create(
            organization=self.organization,
            payment_reference='PAY-20260320-00001',
            student=self.student,
            invoice=self.invoice,
            amount=Decimal('10000.00'),
            payment_method=PaymentMethod.MOBILE_MONEY,
            payment_source=PaymentSource.MPESA,
            status=PaymentStatus.COMPLETED,
            payment_date=timezone.make_aware(datetime(2026, 3, 20, 14, 30)),
            payer_name='Mary Wanjiru',
            payer_phone='254712345678',
            transaction_reference='MPE123ABC',
        )


class SMSTemplateServiceTests(SMSWorkflowBaseTestCase):
    def test_placeholder_rendering_preview_and_send_modes(self):
        template = (
            'Hello {parent.first_name}, {student.name} ({student.admission_number}) in '
            '{student.class} owes {student.outstanding_balance}. Total due is {invoice.total_due} '
            'by {invoice.due_date}. Invoice: {invoice.link}. Unknown: {custom.token}'
        )

        context = SMSWorkflowService.build_context(self.student, invoice=self.invoice, payment=self.payment)
        preview = SMSTemplateService.render(template, context=context, preview=True)
        send = SMSTemplateService.render(template, context=context, preview=False)

        self.assertIn('Mary', preview['message'])
        self.assertIn('Jane Doe', preview['message'])
        self.assertIn('PWA1001', preview['message'])
        self.assertIn('KES 39,000.00', preview['message'])
        self.assertIn('15 Feb 2026', preview['message'])
        self.assertIn('{custom.token}', preview['message'])
        self.assertIn('custom.token', preview['unresolved_placeholders'])

        self.assertNotIn('{custom.token}', send['message'])
        self.assertIn(reverse('finance:invoice_detail', kwargs={'pk': self.invoice.pk}), send['message'])


class SMSWorkflowServiceTests(SMSWorkflowBaseTestCase):
    def setUp(self):
        super().setUp()
        self.student_without_phone = Student.objects.create(
            organization=self.organization,
            admission_number='PWA1002',
            admission_date=date(2026, 1, 5),
            first_name='Brian',
            last_name='Maina',
            gender='M',
            date_of_birth=date(2015, 6, 12),
            current_class=self.class_grade_5,
            status='active',
            outstanding_balance=Decimal('12000.00'),
        )
        Invoice.objects.create(
            organization=self.organization,
            student=self.student_without_phone,
            term=self.term,
            invoice_number='INV-2026-00002',
            subtotal=Decimal('12000.00'),
            total_amount=Decimal('12000.00'),
            amount_paid=Decimal('0.00'),
            balance_bf=Decimal('0.00'),
            prepayment=Decimal('0.00'),
            balance=Decimal('12000.00'),
            status='overdue',
            issue_date=date(2026, 1, 10),
            due_date=date(2026, 2, 15),
        )

    @patch('communications.services.sms_workflow_service.sms_api_client.send_bulk_sms')
    def test_balance_workflow_builds_bulk_payload_and_tracks_failures(self, mock_send_bulk_sms):
        def fake_send_bulk_sms(*, recipients, message, organization, purpose, triggered_by=None):
            self.assertEqual(message, '')
            self.assertEqual(purpose, 'balance_reminder')
            self.assertEqual(len(recipients), 1)
            self.assertEqual(recipients[0]['phone'], '0712345678')
            self.assertIn('KES 39,000.00', recipients[0]['message'])
            return [
                SMSNotification.objects.create(
                    organization=organization,
                    recipient_phone='254712345678',
                    message=recipients[0]['message'],
                    status='sent',
                    purpose=purpose,
                    related_student=recipients[0]['student'],
                    triggered_by=triggered_by,
                )
            ]

        mock_send_bulk_sms.side_effect = fake_send_bulk_sms

        result = SMSWorkflowService.send_balance_reminders(
            organization=self.organization,
            template='Reminder: {student.name} balance is {student.outstanding_balance}.',
            grade_levels=['grade_5'],
            triggered_by=self.user,
        )

        self.assertEqual(result['sent_count'], 1)
        self.assertEqual(result['failed_count'], 1)
        self.assertEqual(result['audit_rows_created'], 2)
        self.assertIn('Student primary parent has no phone number.', result['error_messages'])
        self.assertTrue(
            SMSNotification.objects.filter(
                related_student=self.student_without_phone,
                status='failed',
                purpose='balance_reminder',
            ).exists()
        )

    def test_invoice_preview_includes_paybill_accounts_and_print_url(self):
        previews = SMSWorkflowService.preview_invoice_notifications(
            organization=self.organization,
            template='Pay via {invoice.paybill_account_1}. Print {invoice.print_url}',
            grade_levels=['grade_5'],
            student_ids=[self.student.id],
        )

        self.assertEqual(len(previews), 1)
        self.assertIn('280029#PWA1001', previews[0].message)
        self.assertIn(reverse('finance:invoice_receipt_print', kwargs={'pk': self.invoice.pk}), previews[0].message)


class PaymentReceiptNotificationTests(SMSWorkflowBaseTestCase):
    @patch('payments.services.notifications.sms_api_client.send_sms')
    def test_payment_receipt_uses_primary_parent_and_includes_requested_fields(self, mock_send_sms):
        mock_send_sms.return_value = SMSNotification.objects.create(
            organization=self.organization,
            recipient_phone='254712345678',
            message='sent',
            status='sent',
            purpose='payment_receipt',
            related_student=self.student,
        )

        result = NotificationService.send_payment_receipt(self.payment)
        self.payment.refresh_from_db()

        self.assertTrue(result)
        self.assertTrue(self.payment.receipt_sent)
        kwargs = mock_send_sms.call_args.kwargs
        self.assertEqual(kwargs['phone_number'], '0712345678')
        self.assertEqual(kwargs['purpose'], 'payment_receipt')
        self.assertEqual(kwargs['related_student'], self.student)
        self.assertIn('MPE123ABC', kwargs['message'])
        self.assertIn('20 Mar 2026', kwargs['message'])
        self.assertIn('KES 39,000.00', kwargs['message'])
        self.assertIn(self.payment.receipt_number, kwargs['message'])
        self.assertIn(reverse('finance:payment_receipt', kwargs={'pk': self.payment.pk}), kwargs['message'])
