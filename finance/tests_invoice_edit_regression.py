from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone

from academics.models import AcademicYear, Term
from core.models import Gender, Organization, PaymentMethod, PaymentSource, PaymentStatus, TermChoices
from finance.forms import InvoiceItemForm
from finance.models import Invoice, InvoiceItem
from finance.views import InvoiceEditView
from payments.models import Payment
from payments.services.invoice import InvoiceService
from students.models import Student, StudentTermState
from transport.models import TransportFee, TransportRoute


class InvoiceEditRegressionTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='PCEA Wendani Academy', code='PCEA_WENDANI')
        self.academic_year = AcademicYear.objects.create(
            organization=self.organization,
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            is_current=True,
        )
        self.term = Term.objects.create(
            organization=self.organization,
            academic_year=self.academic_year,
            term=TermChoices.TERM_2,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 8, 31),
            is_current=True,
        )
        self.route = TransportRoute.objects.create(
            organization=self.organization,
            name='Kahawa Sukari',
        )
        TransportFee.objects.create(
            organization=self.organization,
            route=self.route,
            academic_year=self.academic_year,
            term=TermChoices.TERM_2,
            amount=Decimal('8000.00'),
            half_amount=Decimal('4500.00'),
        )
        self.student = Student.objects.create(
            organization=self.organization,
            admission_number='PWA/EDNA',
            admission_date=date(2025, 1, 10),
            first_name='Edna',
            last_name='Njoki',
            gender=Gender.FEMALE,
            date_of_birth=date(2016, 5, 1),
            status='active',
            uses_school_transport=True,
            transport_route=self.route,
            balance_bf_original=Decimal('100.00'),
            prepayment_original=Decimal('50.00'),
        )
        StudentTermState.objects.create(
            organization=self.organization,
            student=self.student,
            term=self.term,
            status='active',
            uses_school_transport=True,
            transport_route=self.route,
            transport_trip_type='half',
        )
        self.invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number='INV-EDIT-001',
            student=self.student,
            term=self.term,
            balance_bf=Decimal('100.00'),
            prepayment=Decimal('50.00'),
            issue_date=self.term.start_date,
            due_date=self.term.end_date,
        )
        self.tuition = InvoiceItem.objects.create(
            invoice=self.invoice,
            description='Tuition',
            category='tuition',
            amount=Decimal('1000.00'),
        )
        self.transport = InvoiceItem.objects.create(
            invoice=self.invoice,
            description='Transport',
            category='transport',
            amount=Decimal('8000.00'),
            transport_route=self.route,
            transport_trip_type='half',
        )

    def test_discount_distribution_preserves_balance_and_prepayment_math(self):
        view = InvoiceEditView()

        view._prepare_invoice_item_for_save(self.transport, self.invoice)
        self.transport.save()
        view.recalculate_invoice_totals(self.invoice, discount_amount=Decimal('550.00'))
        self.invoice.save()

        self.invoice.refresh_from_db()
        self.transport.refresh_from_db()

        self.assertEqual(self.transport.amount, Decimal('4500.00'))
        self.assertEqual(self.invoice.subtotal, Decimal('5500.00'))
        self.assertEqual(self.invoice.discount_amount, Decimal('550.00'))
        self.assertEqual(self.invoice.total_amount, Decimal('4950.00'))
        self.assertEqual(self.invoice.balance, Decimal('5000.00'))
        self.assertEqual(
            self.invoice.items.filter(is_active=True).aggregate(total=Sum('discount_applied'))['total'],
            Decimal('550.00'),
        )

    def test_discount_cannot_exceed_positive_invoice_charges(self):
        view = InvoiceEditView()

        with self.assertRaises(ValueError):
            view.recalculate_invoice_totals(self.invoice, discount_amount=Decimal('10000.00'))

    def test_prepayment_item_allows_negative_amount_when_discount_is_applied(self):
        gift = Student.objects.create(
            organization=self.organization,
            admission_number='ADM.2408',
            admission_date=date(2025, 1, 10),
            first_name='Gift Alvin',
            last_name='Mwai',
            gender=Gender.MALE,
            date_of_birth=date(2016, 5, 1),
            status='active',
        )
        invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number='INV-GIFT-2408',
            student=gift,
            term=self.term,
            issue_date=self.term.start_date,
            due_date=self.term.end_date,
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            description='Tuition Fee',
            category='tuition',
            amount=Decimal('20000.00'),
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            description='Examination Fee',
            category='examination',
            amount=Decimal('1500.00'),
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            description='Meals',
            category='meals',
            amount=Decimal('6500.00'),
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            description='Activity Fee',
            category='activity',
            amount=Decimal('3000.00'),
        )
        prepayment = InvoiceItem.objects.create(
            invoice=invoice,
            description='Prepayment / Credit from previous term',
            category='prepayment',
            amount=Decimal('-10000.00'),
            net_amount=Decimal('-10000.00'),
        )

        form = InvoiceItemForm(
            data={
                'description': prepayment.description,
                'category': 'prepayment',
                'amount': '-10000.00',
                'discount_applied': '0.00',
            },
            instance=prepayment,
            invoice=invoice,
        )
        self.assertTrue(form.is_valid(), form.errors)

        view = InvoiceEditView()
        view._prepare_invoice_item_for_save(prepayment, invoice)
        prepayment.save()
        view.recalculate_invoice_totals(invoice, discount_amount=Decimal('15500.00'))
        invoice.save()

        invoice.refresh_from_db()
        prepayment.refresh_from_db()

        self.assertEqual(prepayment.amount, Decimal('-10000.00'))
        self.assertEqual(prepayment.discount_applied, Decimal('0.00'))
        self.assertEqual(prepayment.net_amount, Decimal('-10000.00'))
        self.assertEqual(invoice.subtotal, Decimal('31000.00'))
        self.assertEqual(invoice.discount_amount, Decimal('15500.00'))
        self.assertEqual(invoice.total_amount, Decimal('15500.00'))
        self.assertEqual(invoice.prepayment, Decimal('10000.00'))
        self.assertEqual(invoice.balance, Decimal('5500.00'))

    def test_discount_distribution_and_payment_allocations_stay_whole_kes(self):
        student = Student.objects.create(
            organization=self.organization,
            admission_number='PWA/WHOLE-KES',
            admission_date=date(2025, 1, 10),
            first_name='Victoria',
            last_name='Mutahi',
            gender=Gender.FEMALE,
            date_of_birth=date(2016, 5, 1),
            status='active',
        )
        invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number='INV-WHOLE-KES',
            student=student,
            term=self.term,
            issue_date=self.term.start_date,
            due_date=self.term.end_date,
        )
        for description, category, amount in [
            ('Tuition', 'tuition', Decimal('16500.00')),
            ('Meals', 'meals', Decimal('6500.00')),
            ('Examination', 'examination', Decimal('1500.00')),
            ('Activity', 'activity', Decimal('3000.00')),
            ('Transport', 'transport', Decimal('6500.00')),
        ]:
            InvoiceItem.objects.create(
                invoice=invoice,
                description=description,
                category=category,
                amount=amount,
            )

        view = InvoiceEditView()
        view.recalculate_invoice_totals(invoice, discount_amount=Decimal('1650.00'))
        invoice.save()
        invoice.refresh_from_db()

        self.assertEqual(invoice.subtotal, Decimal('34000.00'))
        self.assertEqual(invoice.discount_amount, Decimal('1650.00'))
        self.assertEqual(invoice.total_amount, Decimal('32350.00'))

        expected_net_amounts = {
            'tuition': Decimal('15699.00'),
            'meals': Decimal('6185.00'),
            'examination': Decimal('1427.00'),
            'activity': Decimal('2854.00'),
            'transport': Decimal('6185.00'),
        }
        for item in invoice.items.filter(is_active=True):
            self.assertEqual(item.net_amount, expected_net_amounts[item.category])
            self.assertEqual(item.net_amount, item.net_amount.quantize(Decimal('1')))
            self.assertEqual(item.discount_applied, item.discount_applied.quantize(Decimal('1')))

        payment = Payment.objects.create(
            organization=self.organization,
            student=student,
            invoice=invoice,
            amount=invoice.total_amount,
            payment_method=PaymentMethod.BANK_DEPOSIT,
            payment_source=PaymentSource.EQUITY_BANK,
            status=PaymentStatus.COMPLETED,
            payment_date=timezone.now(),
        )
        allocated = InvoiceService._allocate_amount_to_invoice_items(payment, invoice, invoice.total_amount)
        InvoiceService._recalculate_invoice_fields(invoice)

        self.assertEqual(allocated, Decimal('32350.00'))
        allocations = {
            allocation.invoice_item.category: allocation.amount
            for allocation in payment.allocations.filter(is_active=True).select_related('invoice_item')
        }
        self.assertEqual(allocations, expected_net_amounts)
        for amount in allocations.values():
            self.assertEqual(amount, amount.quantize(Decimal('1')))
