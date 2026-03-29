# finance/services.py
"""
Finance module services for invoice generation, payment processing, and reporting.
"""

from decimal import Decimal
from typing import List, Optional

from django.db import transaction
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta, date

from payments.services.payment import logger
from .models import (
    FeeStructure,
    FeeItem,
    Invoice,
    InvoiceItem,
    StudentDiscount,
)

from payments.models import Payment, PaymentAllocation, BankTransaction
from students.models import Student
from academics.models import Term
from core.models import PaymentStatus, PaymentSource
from other_income.models import OtherIncomeInvoice


class InvoiceService:
    """Service for invoice operations."""

    
    @staticmethod
    @transaction.atomic
    def generate_invoice(student, term, generated_by=None):
        """
        Generate invoice for a student for a term.

        Financial rules enforced:
        - Opening balance comes ONLY from student.balance_bf_original
        - Opening credit comes ONLY from student.prepayment_original
        - Live credit_balance may further reduce exposure ONCE
        - Frozen fields are NEVER modified here
        """

        # --------------------------------------------------
        # Prevent duplicate invoice
        # --------------------------------------------------
        existing = Invoice.objects.filter(
            student=student,
            term=term,
            is_active=True
        ).exclude(status='cancelled').first()

        if existing:
            return existing, False

        # --------------------------------------------------
        # Resolve fee structure
        # --------------------------------------------------
        grade_level = getattr(student, 'grade_level', None)
        if not grade_level and getattr(student, 'current_class', None):
            grade_level = student.current_class.grade_level

        fee_structures = FeeStructure.objects.filter(
            academic_year=term.academic_year,
            term=term.term,
            is_active=True
        )

        fee_structure = None
        for fs in fee_structures:
            if not fs.grade_levels or grade_level in fs.grade_levels:
                fee_structure = fs
                break

        if not fee_structure:
            raise ValueError(
                f"No fee structure for {student.admission_number} (Grade: {grade_level})"
            )

        # --------------------------------------------------
        # Create invoice shell
        # --------------------------------------------------
        invoice = Invoice.objects.create(
            student=student,
            term=term,
            fee_structure=fee_structure,
            issue_date=timezone.now().date(),
            due_date=(
                term.start_date + timedelta(days=30)
                if term.start_date
                else timezone.now().date() + timedelta(days=30)
            ),
            generated_by=generated_by,
            status='overdue'
        )

        # --------------------------------------------------
        # Add fee items
        # --------------------------------------------------
        subtotal = Decimal('0.00')
        fee_items = FeeItem.objects.filter(
            fee_structure=fee_structure,
            is_active=True
        )

        for item in fee_items:
            item_amount = Decimal('0.00')
            description = item.description

            if item.category == 'transport':
                if student.uses_school_transport and student.transport_route:
                    from transport.models import TransportFee
                    try:
                        tf = TransportFee.objects.get(
                            route=student.transport_route,
                            academic_year=term.academic_year,
                            term=term.term,
                            is_active=True
                        )
                        item_amount = tf.amount
                        description = f"Transport ({student.transport_route.name})"
                    except TransportFee.DoesNotExist:
                        logger.warning(
                            f"No transport fee for {student.transport_route}"
                        )
            else:
                item_amount = item.amount

            discount_amount = Decimal('0.00')
            student_discounts = StudentDiscount.objects.filter(
                student=student,
                is_active=True,
                is_approved=True,
                discount__academic_year=term.academic_year
            ).filter(
                Q(start_date__lte=timezone.now().date()) | Q(start_date__isnull=True),
                Q(end_date__gte=timezone.now().date()) | Q(end_date__isnull=True),
            )

            for sd in student_discounts:
                discount = sd.discount
                if not discount.applicable_categories or item.category in discount.applicable_categories:
                    if discount.discount_type == 'percentage':
                        discount_amount += item_amount * (discount.value / 100)
                    else:
                        discount_amount += discount.value

            net_amount = item_amount - discount_amount

            InvoiceItem.objects.create(
                invoice=invoice,
                fee_item=item,
                category=item.category,
                description=description,
                amount=item_amount,
                discount_applied=discount_amount,
                net_amount=net_amount
            )

            subtotal += item_amount

        # --------------------------------------------------
        # Finalize term-fee totals (EXCLUDES B/F & prepayment)
        # --------------------------------------------------
        invoice.subtotal = subtotal
        invoice.discount_amount = (
            invoice.items.aggregate(total=Sum("discount_applied"))["total"]
            or Decimal("0.00")
        )
        invoice.total_amount = invoice.subtotal - invoice.discount_amount

        # --------------------------------------------------
        # Opening balances (frozen fields) mirrored on invoice
        # --------------------------------------------------
        opening_balance = student.balance_bf_original or Decimal("0.00")
        opening_prepayment = student.prepayment_original or Decimal("0.00")

        # These header fields remain as immutable snapshots for the term
        invoice.balance_bf = opening_balance
        invoice.prepayment = opening_prepayment  # stored as POSITIVE credit
        invoice.balance_bf_original = opening_balance

        # --------------------------------------------------
        # Represent B/F and Prepayment as synthetic invoice items
        # --------------------------------------------------
        # NOTE:
        # - Balance B/F item is a positive debit line.
        # - Prepayment item is a negative credit line (amount < 0),
        #   so allocation engine naturally ignores it (no positive due).
        #
        # These items are NOT included in subtotal/discount_amount/total_amount
        # which remain term-fee-only; they exist for allocation + statement
        # purposes so all exposure is itemised.
        bf_item = None
        if opening_balance > 0:
            bf_item = InvoiceItem.objects.create(
                invoice=invoice,
                fee_item=None,
                category="balance_bf",
                description="Balance B/F from previous term",
                amount=opening_balance,
                discount_applied=Decimal("0.00"),
                net_amount=opening_balance,
            )

        prepay_item = None
        if opening_prepayment > 0:
            prepay_item = InvoiceItem.objects.create(
                invoice=invoice,
                fee_item=None,
                category="prepayment",
                description="Prepayment / Credit from previous term",
                # Negative amount so net_amount < 0 (credit)
                amount=-opening_prepayment,
                discount_applied=Decimal("0.00"),
                net_amount=-opening_prepayment,
            )

        # --------------------------------------------------
        # Persist base invoice before any credit allocations
        # --------------------------------------------------
        invoice.save()

        # --------------------------------------------------
        # Consume live Student.credit_balance via INTERNAL payment
        # --------------------------------------------------
        from payments.services.invoice import InvoiceService as PaymentsInvoiceService

        available_credit = student.credit_balance or Decimal("0.00")

        # Exposure here is the full invoice balance (term fees + B/F - prepayments)
        # as currently calculated by the Invoice model.
        invoice.refresh_from_db()
        exposure = max(Decimal("0.00"), invoice.balance or Decimal("0.00"))
        credit_to_apply = min(available_credit, exposure)

        internal_allocated = Decimal("0.00")
        internal_payment = None

        if credit_to_apply > 0:
            internal_payment = Payment.objects.create(
                student=student,
                invoice=invoice,
                amount=credit_to_apply,
                payment_method="bank_deposit",  # reuse existing method enum
                payment_source=PaymentSource.CREDIT,
                status=PaymentStatus.COMPLETED,
                payment_date=timezone.now(),
                payer_name="System Credit",
                payer_phone="",
                transaction_reference="CREDIT-AUTO",
                received_by=generated_by,
                notes="Auto-applied from existing credit balance",
                is_reconciled=True,
                reconciled_by=generated_by,
                reconciled_at=timezone.now(),
            )

            internal_allocated = PaymentsInvoiceService.allocate_payment_to_single_invoice(
                payment=internal_payment,
                invoice=invoice,
                amount_to_apply=credit_to_apply,
            )

        # Decrement student's live credit BALANCE ONLY by what was actually applied
        if internal_allocated > 0:
            new_credit = (student.credit_balance or Decimal("0.00")) - internal_allocated
            student.credit_balance = max(Decimal("0.00"), new_credit)
        # Persist student changes (even if no internal allocation, updated_at is still useful)
        student.save(update_fields=["credit_balance", "updated_at"])

        # Recompute outstanding balance snapshot on the student
        student.recompute_outstanding_balance()

        return invoice, True



    @staticmethod
    @transaction.atomic
    def bulk_generate_invoices(term, grade_levels=None, generated_by=None):
        """Generate invoices for multiple students."""

        students = Student.objects.filter(is_active=True, status='active')

        if grade_levels:
            students = students.filter(current_class__grade_level__in=grade_levels)

        created_count = 0
        error_details = []

        for student in students:
            try:
                _, created = InvoiceService.generate_invoice(
                    student=student,
                    term=term,
                    generated_by=generated_by
                )
                if created:
                    created_count += 1
            except Exception as e:
                error_msg = f"{student.admission_number} ({student.full_name}): {str(e)}"
                error_details.append(error_msg)
                logger.error(f"Failed to generate invoice for {student.admission_number}: {str(e)}", exc_info=True)

        return created_count, error_details

    @staticmethod
    def get_student_statement(student, term=None):
        """Get student financial statement."""
        from datetime import date as date_cls
        from django.db.models import Q

        from core.models import InvoiceStatus
        invoices = Invoice.objects.filter(
            student=student, is_active=True
        ).exclude(status=InvoiceStatus.CANCELLED)

        if term:
            invoices = invoices.filter(term=term)

        # Get payments - if term is specified, only get payments allocated to invoices in that term
        if term:
            # Get payments that have allocations to invoice items in invoices for this term
            from payments.models import PaymentAllocation
            payment_ids = PaymentAllocation.objects.filter(
                is_active=True,
                invoice_item__invoice__in=invoices,
                payment__is_active=True,
                payment__status='completed'
            ).values_list('payment_id', flat=True).distinct()
            
            payments = Payment.objects.filter(
                id__in=payment_ids,
                student=student,
                is_active=True,
                status='completed'
            )
        else:
            payments = Payment.objects.filter(
                student=student, is_active=True, status='completed'
            )

        total_invoiced = invoices.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        
        # Calculate total paid - use invoice.amount_paid which includes both item allocations and balance_bf payments
        # This is more accurate than just summing allocations
        total_paid = invoices.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
        
        # Check for deleted invoices
        deleted_invoices = Invoice.objects.filter(
            student=student, is_active=False
        )
        
        # Calculate total balance_bf and prepayment
        # If deleted invoices exist or no active invoices, use student-level frozen fields
        if deleted_invoices.exists() or not invoices.exists():
            # Use student frozen fields for balance_bf and prepayment
            total_balance_bf = student.balance_bf_original or Decimal('0.00')
            total_prepayment = student.prepayment_original or Decimal('0.00')
        else:
            # Use values from active invoices
            total_balance_bf = invoices.aggregate(total=Sum('balance_bf'))['total'] or Decimal('0.00')
            total_prepayment = invoices.aggregate(total=Sum('prepayment'))['total'] or Decimal('0.00')

        # Build transaction list
        transactions = []
        running_balance = Decimal('0.00')
        balance_bf_shown = False

        # If deleted invoices exist or no active invoices, add balance_bf/prepayment from student level first
        if (deleted_invoices.exists() or not invoices.exists()) and (total_balance_bf > 0 or total_prepayment > 0):
            # Use earliest invoice date or current date for opening balances
            earliest_date = None
            if invoices.exists():
                earliest_inv = invoices.order_by('issue_date', 'created_at').first()
                earliest_date = earliest_inv.issue_date or (earliest_inv.created_at.date() if hasattr(earliest_inv.created_at, 'date') else earliest_inv.created_at)
            else:
                from datetime import date
                earliest_date = date.today()
            
            # Add balance_bf as opening balance
            if total_balance_bf > 0:
                running_balance += total_balance_bf
                balance_bf_shown = True
                transactions.append({
                    'date': earliest_date,
                    'description': 'Balance B/F from previous term',
                    'reference': 'Opening Balance',
                    'debit': total_balance_bf,
                    'credit': None,
                    'running_balance': running_balance
                })
            
            # Add prepayment as opening credit
            if total_prepayment > 0:
                running_balance -= total_prepayment
                transactions.append({
                    'date': earliest_date,
                    'description': 'Prepayment/Advance Payment',
                    'reference': 'Opening Credit',
                    'debit': None,
                    'credit': total_prepayment,
                    'running_balance': running_balance
                })

        all_items = []
        for inv in invoices:
            # Handle None issue_date - use created_at as fallback
            inv_date = inv.issue_date or (inv.created_at.date() if hasattr(inv.created_at, 'date') else inv.created_at)
            all_items.append({
                'date': inv_date,
                'type': 'invoice',
                'obj': inv
            })
        
        for pmt in payments:
            pmt_date = pmt.payment_date.date() if hasattr(pmt.payment_date, 'date') else pmt.payment_date
            all_items.append({
                'date': pmt_date,
                'type': 'payment',
                'obj': pmt
            })

        # Sort by date, handling None dates by putting them at the end
        all_items.sort(key=lambda x: x['date'] if x['date'] is not None else date_cls(9999, 12, 31))

        for item in all_items:
            if item['type'] == 'invoice':
                inv = item['obj']
                inv_date = inv.issue_date or (inv.created_at.date() if hasattr(inv.created_at, 'date') else inv.created_at)
                
                # Show balance_bf first if it exists and hasn't been shown yet (only for active invoices)
                if inv.balance_bf and inv.balance_bf > 0 and not balance_bf_shown:
                    running_balance += inv.balance_bf
                    balance_bf_shown = True
                    transactions.append({
                        'date': inv_date,
                        'description': f"Balance B/F (Invoice {inv.invoice_number})",
                        'reference': inv.invoice_number,
                        'debit': inv.balance_bf,
                        'credit': None,
                        'running_balance': running_balance
                    })
                
                # Add invoice total amount
                running_balance += inv.total_amount
                transactions.append({
                    'date': inv_date,
                    'description': f"Invoice {inv.invoice_number}",
                    'reference': inv.invoice_number,
                    'debit': inv.total_amount,
                    'credit': None,
                    'running_balance': running_balance
                })
                
                # If invoice has prepayment, show it as a credit entry (reduces balance)
                if inv.prepayment and inv.prepayment != 0:
                    # Prepayment is stored as positive, so subtract it to reduce balance
                    running_balance -= inv.prepayment
                    transactions.append({
                        'date': inv_date,
                        'description': f"Prepayment Applied (Invoice {inv.invoice_number})",
                        'reference': inv.invoice_number,
                        'debit': None,
                        'credit': inv.prepayment,
                        'running_balance': running_balance
                    })
            else:
                pmt = item['obj']
                running_balance -= pmt.amount
                pmt_date = pmt.payment_date.date() if hasattr(pmt.payment_date, 'date') else pmt.payment_date
                transactions.append({
                    'date': pmt_date,
                    'description': f"Payment - {pmt.get_payment_source_display()}",
                    'reference': pmt.receipt_number or pmt.payment_reference or '-',
                    'debit': None,
                    'credit': pmt.amount,
                    'running_balance': running_balance
                })

        balance_due = (total_invoiced + total_balance_bf) - (total_prepayment + total_paid)


        return {
            'total_invoiced': total_invoiced,
            'total_paid': total_paid,
            'balance_bf': total_balance_bf,
            'prepayment': abs(total_prepayment),
            'balance': balance_due,
            'transactions': transactions,
            'invoices': invoices,
            'payments': payments
        }

    
        
    @staticmethod
    @transaction.atomic
    def delete_invoice(invoice):
        """
        Safely delete an invoice.

        Rules:
        - Block deletion if payments exist
        - Restore any prepayment back to student's credit balance
        - Recompute outstanding balance AFTER restoration
        
        Note: balance_bf is a frozen field that was never modified, so it doesn't need restoration.
        """

        if invoice.amount_paid > 0:
            raise ValueError(
                f"Cannot delete invoice {invoice.invoice_number}: it has payments applied."
            )

        student = invoice.student
        restored_credit = invoice.prepayment or Decimal("0.00")

        invoice.delete()

        if restored_credit > 0:
            student.credit_balance = (student.credit_balance or Decimal("0.00")) + restored_credit
            student.save(update_fields=["credit_balance", "updated_at"])

        student.recompute_outstanding_balance()




class FinanceReportService:
    """Service for financial reports."""

    @staticmethod
    def _build_dashboard_kpis(term=None, organization=None):
        """
        Build reconciled dashboard KPIs from invoice items and other income invoices.

        Buckets:
        - fees (tuition + meals + activity + examination)
        - transport
        - admission
        - educational_activities (legacy invoice-item category='other')
        - other_income (from other_income.OtherIncomeInvoice)
        """
        zero = Decimal('0.00')
        buckets = {
            'fees': {'billed': zero, 'collected': zero, 'outstanding': zero},
            'transport': {'billed': zero, 'collected': zero, 'outstanding': zero},
            'admission': {'billed': zero, 'collected': zero, 'outstanding': zero},
            'educational_activities': {'billed': zero, 'collected': zero, 'outstanding': zero},
            'other_income': {'billed': zero, 'collected': zero, 'outstanding': zero},
        }

        item_bucket_map = {
            'tuition': 'fees',
            'meals': 'fees',
            'activity': 'fees',
            'examination': 'fees',
            'transport': 'transport',
            'admission': 'admission',
            'other': 'educational_activities',
        }

        invoice_items = InvoiceItem.objects.filter(
            is_active=True,
            invoice__is_active=True,
            invoice__student__status='active',
        ).exclude(
            invoice__status='cancelled'
        ).exclude(
            category__in=['balance_bf', 'prepayment']
        )
        if term:
            invoice_items = invoice_items.filter(invoice__term=term)
        if organization:
            invoice_items = invoice_items.filter(invoice__organization=organization)

        item_totals = invoice_items.values('category').annotate(
            billed=Sum('net_amount'),
            collected=Sum('allocations__amount'),
        )
        for row in item_totals:
            bucket_key = item_bucket_map.get(row['category'])
            if not bucket_key:
                continue
            billed = row['billed'] or zero
            collected = row['collected'] or zero
            outstanding = billed - collected
            buckets[bucket_key]['billed'] += billed
            buckets[bucket_key]['collected'] += collected
            buckets[bucket_key]['outstanding'] += outstanding

        other_income_invoices = OtherIncomeInvoice.objects.filter(
            is_active=True
        ).exclude(status='cancelled')
        if term:
            other_income_invoices = other_income_invoices.filter(
                issue_date__gte=term.start_date,
                issue_date__lte=term.end_date,
            )
        if organization:
            other_income_invoices = other_income_invoices.filter(organization=organization)

        other_income_totals = other_income_invoices.aggregate(
            billed=Sum('total_amount'),
            collected=Sum('amount_paid'),
            outstanding=Sum('balance'),
        )
        buckets['other_income']['billed'] = other_income_totals['billed'] or zero
        buckets['other_income']['collected'] = other_income_totals['collected'] or zero
        buckets['other_income']['outstanding'] = other_income_totals['outstanding'] or zero

        total_billed = sum((entry['billed'] for entry in buckets.values()), zero)
        total_collected = sum((entry['collected'] for entry in buckets.values()), zero)
        total_outstanding = sum((entry['outstanding'] for entry in buckets.values()), zero)

        return {
            'buckets': buckets,
            'total_billed': total_billed,
            'total_collected': total_collected,
            'total_outstanding': total_outstanding,
        }

    @staticmethod
    def get_dashboard_stats(term=None, organization=None):
        """Get finance dashboard statistics for active students only."""

        # Filter payments to active students only
        payments = Payment.objects.filter(
            is_active=True,
            status='completed',
            student__status='active'
        )
        if organization:
            payments = payments.filter(
                Q(organization=organization) |
                Q(organization__isnull=True, student__organization=organization)
            )

        kpis = FinanceReportService._build_dashboard_kpis(term=term, organization=organization)
        total_billed = kpis['total_billed']
        total_collected = kpis['total_collected']
        total_outstanding = kpis['total_outstanding']

        collection_rate = (total_collected / total_billed * 100) if total_billed > 0 else 0

        recent_payments = payments.select_related('student').order_by('-payment_date')[:10]
        pending_transactions = BankTransaction.objects.filter(processing_status='pending').order_by(
            '-callback_received_at')[:5]

        return {
            'total_billed': total_billed,
            # Backward-compatible key used in template JS and cards.
            'total_invoiced': total_billed,
            'total_collected': total_collected,
            'total_outstanding': total_outstanding,
            'collection_rate': collection_rate,
            'kpi_buckets': kpis['buckets'],
            'recent_payments': recent_payments,
            'pending_transactions': pending_transactions
        }

    @staticmethod
    def get_outstanding_report(term=None, grade_level=None):
        """Get outstanding fees report."""

        invoices = Invoice.objects.filter(
            is_active=True, balance__gt=0
        ).exclude(status='cancelled').select_related('student', 'student__current_class')

        if term:
            invoices = invoices.filter(term=term)
        if grade_level:
            invoices = invoices.filter(student__current_class__grade_level=grade_level)

        student_balances = {}
        for inv in invoices:
            sid = inv.student.pk
            if sid not in student_balances:
                student_balances[sid] = {
                    'student': inv.student,
                    'total_invoiced': Decimal('0.00'),
                    'total_paid': Decimal('0.00'),
                    'balance': Decimal('0.00')
                }
            student_balances[sid]['total_invoiced'] += inv.total_amount
            student_balances[sid]['total_paid'] += inv.amount_paid
            student_balances[sid]['balance'] += inv.balance

        outstanding_list = sorted(student_balances.values(), key=lambda x: x['balance'], reverse=True)
        total_outstanding = sum(s['balance'] for s in outstanding_list)
        students_with_balance = len(outstanding_list)
        average_balance = total_outstanding / students_with_balance if students_with_balance > 0 else 0

        return {
            'outstanding_list': outstanding_list,
            'total_outstanding': total_outstanding,
            'students_with_balance': students_with_balance,
            'average_balance': average_balance
        }

    @staticmethod
    def get_collections_summary(start_date=None, end_date=None, term=None):
        """Get collections summary report."""

        payments = Payment.objects.filter(is_active=True, status='completed')

        if start_date:
            payments = payments.filter(payment_date__date__gte=start_date)
        if end_date:
            payments = payments.filter(payment_date__date__lte=end_date)

        total_collected = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        transaction_count = payments.count()

        by_method = payments.values('payment_method').annotate(
            count=Count('id'), total=Sum('amount')
        ).order_by('-total')

        method_display = {
            'mpesa': 'M-PESA',
            'bank': 'Bank Transfer',
            'bank_transfer': 'Bank Transfer',
            'cash': 'Cash',
            'cheque': 'Cheque',
            'other': 'Other'
        }

        by_method_list = []
        for m in by_method:
            by_method_list.append({
                'method': method_display.get(m['payment_method'], m['payment_method']),
                'count': m['count'],
                'total': m['total'] or 0,
                'percentage': (m['total'] / total_collected * 100) if total_collected > 0 else 0
            })

        daily = payments.extra(
            select={'date': 'DATE(payment_date)'}
        ).values('date').annotate(
            count=Count('id'), total=Sum('amount')
        ).order_by('-date')[:30]

        mpesa_total = payments.filter(payment_method='mpesa').aggregate(total=Sum('amount'))['total'] or 0
        bank_total = payments.filter(
            Q(payment_method='bank') | Q(payment_method='bank_transfer')
        ).aggregate(total=Sum('amount'))['total'] or 0

        return {
            'total_collected': total_collected,
            'transaction_count': transaction_count,
            'by_method': by_method_list,

            'daily': list(daily),
            'mpesa_total': mpesa_total,
            'bank_total': bank_total
        }


class FeeStructureService:
    """Service for managing fee structures."""

    @staticmethod
    def get_fee_structure_for_student(student: Student, term: Term) -> Optional[FeeStructure]:
        """
        Get the applicable fee structure for a student in a given term.

        Matches based on:
        - Academic year
        - Term
        - Grade level
        """
        grade_level = student.grade_level

        fee_structure = FeeStructure.objects.filter(
            academic_year=term.academic_year,
            term=term,
            is_active=True
        ).filter(
            grade_levels__contains=[grade_level]
        ).first()

        if not fee_structure:
            fee_structure = FeeStructure.objects.filter(
                academic_year=term.academic_year,
                term=term,
                is_active=True
            ).filter(
                grade_levels__contains=[grade_level]
            ).first()

        return fee_structure

    @staticmethod
    def calculate_total_fees(fee_structure: FeeStructure, include_optional: bool = False) -> Decimal:
        """Calculate total fees for a fee structure."""
        items = fee_structure.items.filter(is_active=True)
        if not include_optional:
            items = items.filter(is_optional=False)
        return items.aggregate(total=Sum('amount'))['total'] or Decimal('0')


class DiscountService:
    """Service for managing discounts."""

    @staticmethod
    def get_applicable_discounts(student: Student, term: Term) -> List[StudentDiscount]:
        """Get all applicable discounts for a student in a term."""
        today = date.today()

        return StudentDiscount.objects.filter(
            student=student,
            is_active=True,
            is_approved=True,
            start_date__lte=today
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today)
        ).filter(
            Q(discount__academic_year__isnull=True) | Q(discount__academic_year=term.academic_year)
        ).select_related('discount')

    @staticmethod
    def calculate_discount_amount(
            student_discount: StudentDiscount,
            fee_items: List[FeeItem]
    ) -> Decimal:
        """Calculate discount amount for given fee items."""
        discount = student_discount.discount
        value = student_discount.custom_value or discount.value

        # Filter items by applicable categories
        applicable_items = fee_items
        if discount.applicable_categories:
            applicable_items = [
                item for item in fee_items
                if item.category in discount.applicable_categories
            ]

        total_applicable = sum(item.amount for item in applicable_items)

        if discount.discount_type == 'percentage':
            return total_applicable * (value / 100)
        else:
            return min(value, total_applicable)


def transition_frozen_balances(previous_term, new_term, dry_run=False):
    """
    Calculate and update frozen balances for all active students
    based on their previous term invoice outcomes.
    
    When a new term starts, this recalculates balance_bf_original and
    prepayment_original for all active students based on their previous term
    invoice outcomes.
    
    Args:
        previous_term: The Term object for the previous term
        new_term: The Term object for the new current term
        dry_run: If True, don't save changes, just log what would happen
        
    Returns:
        dict: Statistics about the transition
    """
    stats = {
        'total_students': 0,
        'with_outstanding': 0,
        'with_overpayment': 0,
        'fully_paid': 0,
        'no_invoice': 0,
        'updated': 0,
        'errors': 0,
    }
    
    logger.info(f"Starting term transition from {previous_term} to {new_term}")
    if dry_run:
        logger.info("DRY RUN MODE - No changes will be saved")
    
    active_students = Student.objects.filter(status='active')
    stats['total_students'] = active_students.count()
    
    for student in active_students:
        try:
            # Get previous term's invoice (if any)
            prev_invoice = Invoice.objects.filter(
                student=student,
                term=previous_term,
                is_active=True
            ).first()
            
            old_balance_bf = student.balance_bf_original
            old_prepayment = student.prepayment_original
            old_credit = student.credit_balance
            old_outstanding = student.outstanding_balance
            
            if prev_invoice:
                # Use invoice balance as new term-start position
                if prev_invoice.balance > 0:
                    # Student owes money - carry forward as balance_bf_original
                    student.balance_bf_original = prev_invoice.balance
                    student.prepayment_original = Decimal('0.00')
                    student.credit_balance = Decimal('0.00')  # No credit if student owes
                    student.outstanding_balance = prev_invoice.balance  # Set outstanding to match
                    stats['with_outstanding'] += 1
                elif prev_invoice.balance < 0:
                    # Student overpaid - carry forward as prepayment/credit
                    student.balance_bf_original = Decimal('0.00')
                    student.prepayment_original = abs(prev_invoice.balance)
                    student.credit_balance = abs(prev_invoice.balance)  # Positive credit amount
                    student.outstanding_balance = Decimal('0.00')  # No outstanding if overpaid
                    stats['with_overpayment'] += 1
                else:
                    # Fully paid - reset all balances
                    student.balance_bf_original = Decimal('0.00')
                    student.prepayment_original = Decimal('0.00')
                    student.credit_balance = Decimal('0.00')
                    student.outstanding_balance = Decimal('0.00')
                    stats['fully_paid'] += 1
            else:
                # No invoice - check existing outstanding_balance and credit_balance
                stats['no_invoice'] += 1
                current_outstanding = student.outstanding_balance or Decimal('0.00')
                current_credit = student.credit_balance or Decimal('0.00')
                
                if current_outstanding > 0:
                    # Student has outstanding balance from previous term
                    student.balance_bf_original = current_outstanding
                    student.prepayment_original = Decimal('0.00')
                    student.credit_balance = Decimal('0.00')
                    # outstanding_balance stays as is
                elif current_credit > 0:
                    # Student has credit balance (overpayment)
                    student.balance_bf_original = Decimal('0.00')
                    student.prepayment_original = current_credit
                    # credit_balance stays as is
                    student.outstanding_balance = Decimal('0.00')
                else:
                    # Zero balance - reset frozen fields
                    student.balance_bf_original = Decimal('0.00')
                    student.prepayment_original = Decimal('0.00')
                    student.outstanding_balance = Decimal('0.00')
            
            # Check if values changed
            changed = (
                old_balance_bf != student.balance_bf_original or
                old_prepayment != student.prepayment_original or
                old_credit != student.credit_balance or
                old_outstanding != student.outstanding_balance
            )
            
            if changed:
                logger.debug(
                    f"{student.admission_number}: "
                    f"balance_bf_original: {old_balance_bf} -> {student.balance_bf_original}, "
                    f"prepayment_original: {old_prepayment} -> {student.prepayment_original}, "
                    f"credit_balance: {old_credit} -> {student.credit_balance}, "
                    f"outstanding_balance: {old_outstanding} -> {student.outstanding_balance}"
                )
                
                if not dry_run:
                    student.save(update_fields=[
                        'balance_bf_original', 'prepayment_original', 
                        'credit_balance', 'outstanding_balance'
                    ])
                stats['updated'] += 1
                
        except Exception as e:
            logger.error(f"Error processing student {student.admission_number}: {e}")
            stats['errors'] += 1
    
    logger.info(
        f"Term transition complete: "
        f"{stats['total_students']} students processed, "
        f"{stats['updated']} updated, "
        f"{stats['with_outstanding']} with outstanding balance, "
        f"{stats['with_overpayment']} with overpayment, "
        f"{stats['fully_paid']} fully paid, "
        f"{stats['no_invoice']} without previous invoice, "
        f"{stats['errors']} errors"
    )
    
    return stats
