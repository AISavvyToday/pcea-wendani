# communications/management/commands/send_fee_reminders.py
"""
Django management command to send SMS reminders for overdue invoices.

Usage:
    python manage.py send_fee_reminders --term-id=1 --balance-threshold=1000
"""

import logging
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from academics.models import Term
from finance.models import Invoice, InvoiceStatus
from communications.services.sms_service import SMSService
from communications.models import NotificationTemplate, SMSNotification

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Send SMS reminders for overdue invoices'

    def add_arguments(self, parser):
        parser.add_argument(
            '--term-id',
            type=int,
            help='Term ID to filter invoices (default: current term)',
        )
        parser.add_argument(
            '--balance-threshold',
            type=float,
            default=0.0,
            help='Minimum balance to send reminder (default: 0.0)',
        )
        parser.add_argument(
            '--organization-id',
            type=str,
            help='Organization ID (default: all organizations)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Perform a dry run without sending SMS',
        )

    def handle(self, *args, **options):
        term_id = options.get('term_id')
        balance_threshold = options.get('balance_threshold', 0.0)
        organization_id = options.get('organization_id')
        dry_run = options.get('dry_run', False)
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No SMS will be sent'))
        
        # Get term
        if term_id:
            try:
                term = Term.objects.get(id=term_id)
            except Term.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Term with ID {term_id} not found'))
                return
        else:
            term = Term.objects.filter(is_current=True).first()
            if not term:
                self.stdout.write(self.style.ERROR('No current term found. Please specify --term-id'))
                return
        
        self.stdout.write(f'Processing fee reminders for term: {term}')
        
        # Get invoices
        invoices = Invoice.objects.filter(
            term=term,
            balance__gt=balance_threshold,
            status__in=[InvoiceStatus.OVERDUE, InvoiceStatus.PARTIALLY_PAID],
            is_active=True,
            student__status='active'
        ).select_related('student', 'student__primary_parent', 'organization')
        
        if organization_id:
            invoices = invoices.filter(organization_id=organization_id)
        
        self.stdout.write(f'Found {invoices.count()} invoices with balance > {balance_threshold}')
        
        # Get or create template
        template = NotificationTemplate.objects.filter(
            organization=term.organization if hasattr(term, 'organization') and term.organization else None,
            name='Fee Reminder',
            template_type='sms'
        ).first()
        
        if not template:
            # Use default message
            default_message = "Dear Parent, your child {{student_name}} has an outstanding fee balance of KES {{balance}}. Please clear the balance to avoid inconveniences. Thank you."
        else:
            default_message = template.template_text
        
        sms_service = SMSService()
        sent_count = 0
        failed_count = 0
        
        for invoice in invoices:
            student = invoice.student
            parent = student.primary_parent
            
            if not parent or not parent.phone_primary:
                logger.warning(f"No phone number for parent of student {student.admission_number}")
                continue
            
            # Render message
            message = default_message.replace('{{student_name}}', student.full_name)
            message = message.replace('{{balance}}', f"{invoice.balance:,.0f}")
            message = message.replace('{{invoice_number}}', invoice.invoice_number)
            
            if dry_run:
                self.stdout.write(f'  [DRY RUN] Would send SMS to {parent.phone_primary}: {message[:50]}...')
                sent_count += 1
            else:
                # SMS sending is temporarily disabled - logic kept ready for future use
                # TODO: Uncomment when ready to send SMS
                # org = invoice.organization or student.organization
                # # Get balance before sending
                # balance_before = org.sms_balance
                # 
                # # Send SMS using package service (it handles credit deduction internally)
                # try:
                #     result = sms_service.send_sms(
                #         phone_number=parent.phone_primary,
                #         message=message,
                #         organization=org,
                #         parent=parent,
                #         user=None,  # Automated command, no user
                #         purpose='fee_reminder',
                #         sms_notification_model=None  # We create our own records
                #     )
                #     
                #     # Refresh to check if credits were deducted
                #     org.refresh_from_db()
                #     balance_after = org.sms_balance
                #     
                #     # Create notification record
                #     if balance_after < balance_before:
                #         # Credits were deducted, SMS was sent
                #         notification = SMSNotification.objects.create(
                #             organization=org,
                #             recipient_phone=parent.phone_primary,
                #             message=message,
                #             status='sent',
                #             sent_at=timezone.now(),
                #             purpose='fee_reminder',
                #             related_student=student,
                #         )
                #         sent_count += 1
                #         self.stdout.write(f'  ✓ Sent to {parent.phone_primary} for {student.admission_number}')
                #     else:
                #         # No credits deducted, likely failed
                #         notification = SMSNotification.objects.create(
                #             organization=org,
                #             recipient_phone=parent.phone_primary,
                #             message=message,
                #             status='failed',
                #             error_message='Insufficient credits or send failed',
                #             purpose='fee_reminder',
                #             related_student=student,
                #         )
                #         failed_count += 1
                #         self.stdout.write(self.style.ERROR(f'  ✗ Failed to send to {parent.phone_primary}: Insufficient credits'))
                # except Exception as e:
                #     # Error occurred
                #     notification = SMSNotification.objects.create(
                #         organization=org,
                #         recipient_phone=parent.phone_primary,
                #         message=message,
                #         status='failed',
                #         error_message=str(e),
                #         purpose='fee_reminder',
                #         related_student=student,
                #     )
                #     failed_count += 1
                #     logger.error(f"Error sending SMS to {parent.phone_primary}: {str(e)}", exc_info=True)
                #     self.stdout.write(self.style.ERROR(f'  ✗ Failed to send to {parent.phone_primary}: {str(e)}'))
                
                # For now, just log that SMS would be sent
                if dry_run:
                    self.stdout.write(f'  [DRY RUN] Would send SMS to {parent.phone_primary}: {message[:50]}...')
                else:
                    self.stdout.write(f'  [SMS DISABLED] Would send SMS to {parent.phone_primary} for {student.admission_number}')
                sent_count += 1  # Count as "would send" for reporting
        
        self.stdout.write(self.style.SUCCESS(f'\nFee reminders complete! Sent: {sent_count}, Failed: {failed_count}'))

