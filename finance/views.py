# finance/views.py
"""
Finance module views for fee management, invoicing, and payments.

Standalone invoices policy:
- Do NOT manually adjust invoice balances in views.
- All payments (manual + bank match) are allocated oldest-invoice-first via payments.services.payment.PaymentService
- Invoice detail shows payments via allocations (and also legacy Payment.invoice links if present).

Invoice generation policy (NO OVERWRITE):
- Bulk invoice generation should NOT overwrite existing invoices.
- If an invoice already exists for a student+term, it is skipped (service returns created count only).
"""

import logging
from decimal import Decimal
from datetime import date

from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView,
    TemplateView, FormView, View
)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.db.models import Q, Sum, Count
from django.db import transaction as db_transaction
from django.utils import timezone

from core.mixins import RoleRequiredMixin
from accounts.models import UserRole
from .models import (
    FeeStructure, FeeItem, Discount, StudentDiscount,
    Invoice, InvoiceItem
)
from .forms import (
    FeeStructureForm, FeeItemFormSet, DiscountForm, StudentDiscountForm,
    InvoiceGenerateForm, PaymentRecordForm, BankTransactionMatchForm, DateRangeFilterForm
)
from .services import (
    FeeStructureService, DiscountService, InvoiceService, FinanceReportService
)
from students.models import Student
from academics.models import Term
from payments.models import Payment, BankTransaction
from payments.services.payment import PaymentService as PaymentsPaymentService
from core.models import InvoiceStatus, PaymentMethod, PaymentStatus

logger = logging.getLogger(__name__)


# =============================================================================
# Dashboard
# =============================================================================

class FinanceDashboardView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    """Finance dashboard with key metrics and quick actions."""

    template_name = 'finance/dashboard.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get current term
        current_term = Term.objects.filter(is_current=True).first()

        # Dashboard stats
        context['stats'] = FinanceReportService.get_dashboard_stats(current_term)

        # Recent payments
        context['recent_payments'] = Payment.objects.filter(
            is_active=True,
            status=PaymentStatus.COMPLETED
        ).select_related('student').order_by('-payment_date')[:10]

        # Unmatched bank transactions (recent)
        context['unmatched_transactions'] = BankTransaction.objects.filter(
            is_active=True,
            payment__isnull=True
        ).order_by('-callback_received_at')[:5]

        # Top outstanding balances
        context['top_balances'] = Invoice.objects.filter(
            is_active=True,
            balance__gt=0
        ).exclude(
            status=InvoiceStatus.CANCELLED
        ).select_related('student', 'term').order_by('-balance')[:10]

        context['current_term'] = current_term
        return context


# =============================================================================
# Fee Structures
# =============================================================================

class FeeStructureListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    """List all fee structures."""

    model = FeeStructure
    template_name = 'finance/fee_structure_list.html'
    context_object_name = 'fee_structures'
    paginate_by = 20
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_queryset(self):
        queryset = FeeStructure.objects.filter(is_active=True).select_related('academic_year')

        # Filter by academic year
        year = self.request.GET.get('year')
        if year:
            queryset = queryset.filter(academic_year_id=year)

        # Filter by term (if you have term relation)
        term = self.request.GET.get('term')
        if term:
            queryset = queryset.filter(term=term)

        return queryset.order_by('-academic_year__year', 'term', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from academics.models import AcademicYear
        context['academic_years'] = AcademicYear.objects.filter(is_active=True)
        context['selected_year'] = self.request.GET.get('year', '')
        context['selected_term'] = self.request.GET.get('term', '')
        return context


class FeeStructureDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    """View fee structure details with items."""

    model = FeeStructure
    template_name = 'finance/fee_structure_detail.html'
    context_object_name = 'fee_structure'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['fee_items'] = self.object.items.filter(is_active=True).order_by('category')
        context['total_amount'] = getattr(self.object, 'total_amount', None)
        return context


class FeeStructureCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    """Create a new fee structure with items."""

    model = FeeStructure
    form_class = FeeStructureForm
    template_name = 'finance/fee_structure_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Fee Structure'
        context['button_text'] = 'Create Fee Structure'

        if self.request.POST:
            context['formset'] = FeeItemFormSet(self.request.POST)
        else:
            context['formset'] = FeeItemFormSet()

        return context

    def form_valid(self, form):
        context = self.get_context_data()
        formset = context['formset']

        if formset.is_valid():
            with db_transaction.atomic():
                self.object = form.save()
                formset.instance = self.object
                formset.save()

            messages.success(self.request, f'Fee structure "{self.object.name}" created successfully!')
            return redirect('finance:fee_structure_detail', pk=self.object.pk)
        else:
            return self.render_to_response(self.get_context_data(form=form))

    def get_success_url(self):
        return reverse('finance:fee_structure_detail', kwargs={'pk': self.object.pk})


class FeeStructureUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    """Edit an existing fee structure."""

    model = FeeStructure
    form_class = FeeStructureForm
    template_name = 'finance/fee_structure_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Fee Structure: {self.object.name}'
        context['button_text'] = 'Update Fee Structure'
        context['is_edit'] = True

        if self.request.POST:
            context['formset'] = FeeItemFormSet(self.request.POST, instance=self.object)
        else:
            context['formset'] = FeeItemFormSet(instance=self.object)

        return context

    def form_valid(self, form):
        context = self.get_context_data()
        formset = context['formset']

        if formset.is_valid():
            with db_transaction.atomic():
                self.object = form.save()
                formset.save()

            messages.success(self.request, 'Fee structure updated successfully!')
            return redirect('finance:fee_structure_detail', pk=self.object.pk)
        else:
            return self.render_to_response(self.get_context_data(form=form))

    def get_success_url(self):
        return reverse('finance:fee_structure_detail', kwargs={'pk': self.object.pk})


class FeeStructureDeleteView(LoginRequiredMixin, RoleRequiredMixin, DeleteView):
    """Delete a fee structure."""

    model = FeeStructure
    template_name = 'finance/fee_structure_confirm_delete.html'
    success_url = reverse_lazy('finance:fee_structure_list')
    allowed_roles = [UserRole.SUPER_ADMIN]

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()

        invoice_count = Invoice.objects.filter(
            items__fee_item__fee_structure=self.object
        ).distinct().count()

        if invoice_count > 0:
            messages.error(
                request,
                f'Cannot delete fee structure. It is used in {invoice_count} invoice(s).'
            )
            return redirect('finance:fee_structure_detail', pk=self.object.pk)

        self.object.is_active = False
        self.object.save()

        messages.success(request, 'Fee structure deleted successfully.')
        return HttpResponseRedirect(self.success_url)


# =============================================================================
# Discounts
# =============================================================================

class DiscountListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    """List all discounts."""

    model = Discount
    template_name = 'finance/discount_list.html'
    context_object_name = 'discounts'
    paginate_by = 20
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_queryset(self):
        return Discount.objects.filter(is_active=True).order_by('name')


class DiscountCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    """Create a new discount."""

    model = Discount
    form_class = DiscountForm
    template_name = 'finance/discount_form.html'
    success_url = reverse_lazy('finance:discount_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Discount'
        context['button_text'] = 'Create Discount'
        return context

    def form_valid(self, form):
        messages.success(self.request, f'Discount "{form.instance.name}" created successfully!')
        return super().form_valid(form)


class DiscountUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    """Edit an existing discount."""

    model = Discount
    form_class = DiscountForm
    template_name = 'finance/discount_form.html'
    success_url = reverse_lazy('finance:discount_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Discount: {self.object.name}'
        context['button_text'] = 'Update Discount'
        context['is_edit'] = True
        return context

    def form_valid(self, form):
        messages.success(self.request, 'Discount updated successfully!')
        return super().form_valid(form)


class DiscountDeleteView(LoginRequiredMixin, RoleRequiredMixin, DeleteView):
    """Delete a discount."""

    model = Discount
    template_name = 'finance/discount_confirm_delete.html'
    success_url = reverse_lazy('finance:discount_list')
    allowed_roles = [UserRole.SUPER_ADMIN]

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.is_active = False
        self.object.save()
        messages.success(request, 'Discount deleted successfully.')
        return HttpResponseRedirect(self.success_url)


# =============================================================================
# Student Discounts
# =============================================================================

class StudentDiscountListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    """List student discount assignments."""

    model = StudentDiscount
    template_name = 'finance/student_discount_list.html'
    context_object_name = 'student_discounts'
    paginate_by = 20
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_queryset(self):
        queryset = StudentDiscount.objects.filter(
            is_active=True
        ).select_related('student', 'discount', 'approved_by')

        status = self.request.GET.get('status')
        if status == 'pending':
            queryset = queryset.filter(is_approved=False)
        elif status == 'approved':
            queryset = queryset.filter(is_approved=True)

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['pending_count'] = StudentDiscount.objects.filter(
            is_active=True, is_approved=False
        ).count()
        context['selected_status'] = self.request.GET.get('status', '')
        return context


class StudentDiscountCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    """Assign a discount to a student."""

    model = StudentDiscount
    form_class = StudentDiscountForm
    template_name = 'finance/student_discount_form.html'
    success_url = reverse_lazy('finance:student_discount_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Assign Discount to Student'
        context['button_text'] = 'Assign Discount'
        return context

    def form_valid(self, form):
        if not form.instance.discount.requires_approval:
            form.instance.is_approved = True
            form.instance.approved_by = self.request.user
            form.instance.approved_at = timezone.now()

        messages.success(
            self.request,
            f'Discount assigned to {form.instance.student.full_name} successfully!'
        )
        return super().form_valid(form)


class StudentDiscountApproveView(LoginRequiredMixin, RoleRequiredMixin, View):
    """Approve a student discount."""

    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def post(self, request, pk):
        student_discount = get_object_or_404(StudentDiscount, pk=pk)

        student_discount.is_approved = True
        student_discount.approved_by = request.user
        student_discount.approved_at = timezone.now()
        student_discount.save()

        messages.success(
            request,
            f'Discount for {student_discount.student.full_name} approved successfully!'
        )
        return redirect('finance:student_discount_list')


# =============================================================================
# Invoices
# =============================================================================

class InvoiceListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    """List all invoices with filters."""

    model = Invoice
    template_name = 'finance/invoice_list.html'
    context_object_name = 'invoices'
    paginate_by = 25
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_queryset(self):
        queryset = Invoice.objects.filter(
            is_active=True
        ).select_related('student', 'term', 'term__academic_year')

        query = self.request.GET.get('query', '')
        if query:
            queryset = queryset.filter(
                Q(invoice_number__icontains=query) |
                Q(student__admission_number__icontains=query) |
                Q(student__first_name__icontains=query) |
                Q(student__last_name__icontains=query)
            )

        term = self.request.GET.get('term')
        if term:
            queryset = queryset.filter(term_id=term)

        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        grade = self.request.GET.get('grade')
        if grade:
            queryset = queryset.filter(student__grade_level=grade)

        return queryset.order_by('-issue_date', '-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['terms'] = Term.objects.filter(is_active=True).select_related('academic_year')
        context['statuses'] = InvoiceStatus.choices
        context['query'] = self.request.GET.get('query', '')
        context['selected_term'] = self.request.GET.get('term', '')
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_grade'] = self.request.GET.get('grade', '')

        invoices = self.get_queryset()
        context['total_billed'] = invoices.aggregate(total=Sum('total_amount'))['total'] or 0
        context['total_outstanding'] = invoices.aggregate(total=Sum('balance'))['total'] or 0
        context['invoice_count'] = invoices.count()

        return context


class InvoiceDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    """View invoice details."""

    model = Invoice
    template_name = 'finance/invoice_detail.html'
    context_object_name = 'invoice'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['items'] = self.object.items.filter(is_active=True).order_by('category')

        # IMPORTANT:
        # Payments are no longer reliably tied to invoice via Payment.invoice
        # because one payment can clear multiple invoices (allocations).
        context['payments'] = Payment.objects.filter(
            is_active=True,
            status=PaymentStatus.COMPLETED
        ).filter(
            Q(invoice=self.object) | Q(allocations__invoice_item__invoice=self.object)
        ).distinct().order_by('-payment_date')

        return context


class InvoiceGenerateView(LoginRequiredMixin, RoleRequiredMixin, FormView):
    """Bulk generate invoices (NO OVERWRITE)."""

    template_name = 'finance/invoice_generate.html'
    form_class = InvoiceGenerateForm
    success_url = reverse_lazy('finance:invoice_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Generate Invoices'
        return context

    def form_valid(self, form):
        term = form.cleaned_data['term']
        grade_levels = form.cleaned_data.get('grade_levels', [])

        logger.info(f"Invoice generation started for term: {term}, grade levels: {grade_levels}")

        try:
            # DEBUG: Check if students exist
            from students.models import Student
            students = Student.objects.filter(is_active=True, status='active')
            if grade_levels:
                students = students.filter(grade_level__in=grade_levels)

            logger.info(f"Found {students.count()} active students")

            if students.count() == 0:
                messages.warning(self.request, "No active students found for the selected criteria.")
                return super().form_invalid(form)

            # DEBUG: Check fee structures
            from finance.models import FeeStructure
            fee_structures = FeeStructure.objects.filter(
                academic_year=term.academic_year,
                term=term.term,
                is_active=True
            )
            logger.info(f"Found {fee_structures.count()} fee structures for {term.academic_year.year} {term.term}")

            for fs in fee_structures:
                logger.info(f"  - {fs.name}: grade_levels={fs.grade_levels}")

            # TEST: Try generating invoice for first student to see error
            if students.exists():
                test_student = students.first()
                logger.info(
                    f"Testing with student: {test_student.admission_number} (Grade: {test_student.grade_level})")

                try:
                    from .services import InvoiceService
                    invoice, created = InvoiceService.generate_invoice(
                        student=test_student,
                        term=term,
                        generated_by=self.request.user,
                    )
                    if created:
                        logger.info(f"✓ Test invoice created: {invoice.invoice_number}")
                    else:
                        logger.info(f"⚠ Test invoice already exists: {invoice.invoice_number}")
                except Exception as test_error:
                    logger.error(f"✗ Test invoice generation failed: {str(test_error)}", exc_info=True)
                    messages.error(self.request, f"Test failed: {str(test_error)}")
                    # Continue with bulk generation anyway

            # Now run the bulk generation
            logger.info("Starting bulk invoice generation...")
            results = InvoiceService.bulk_generate_invoices(
                term=term,
                grade_levels=grade_levels if grade_levels else None,
                generated_by=self.request.user,
            )

            logger.info(f"Bulk generation results: {results}")

        except Exception as e:
            logger.exception("Invoice bulk generation failed with exception")
            messages.error(self.request, f"Invoice generation failed: {str(e)}")
            return super().form_invalid(form)

        # Parse results with better error handling
        generated = skipped = errors = 0
        error_details = []

        if isinstance(results, dict):
            generated = results.get('generated', results.get('created', 0))
            skipped = results.get('skipped', 0)
            errors = results.get('errors', 0)
            error_details = results.get('error_details', [])
        elif isinstance(results, (list, tuple)):
            if len(results) == 2:
                # (created_count, error_list) format
                created_count, error_list = results
                generated = created_count
                if isinstance(error_list, (list, tuple)):
                    errors = len(error_list)
                    error_details = error_list[:10]  # Get first 10 errors for display
                else:
                    errors = 1 if error_list else 0
                    error_details = [str(error_list)] if error_list else []
            else:
                try:
                    generated = int(results[0]) if results else 0
                except Exception:
                    generated = 0

        # Log detailed errors
        if error_details:
            logger.error(f"Generation errors ({len(error_details)}):")
            for i, err in enumerate(error_details[:5]):  # Log first 5 errors
                logger.error(f"  Error {i + 1}: {err}")

        # Create success message
        message = f"Invoice generation complete: {generated} generated, {skipped} skipped, {errors} errors."
        messages.success(self.request, message)

        # Show first few errors in message if present
        if error_details:
            error_preview = "<br>".join([f"• {err}" for err in error_details[:3]])
            if len(error_details) > 3:
                error_preview += f"<br>• ... and {len(error_details) - 3} more errors"

            messages.error(
                self.request,
                f"{errors} errors occurred during generation:<br>{error_preview}",
                extra_tags='safe'
            )
        elif errors > 0:
            messages.warning(
                self.request,
                f"{errors} errors occurred. Check server logs for details."
            )

        # Also add context for debugging
        context = self.get_context_data()
        context['generated_invoices'] = Invoice.objects.filter(
            term=term,
            generated_by=self.request.user
        ).order_by('-created_at')[:50]  # Show recent 50 invoices

        # Add error details to context for template
        if error_details:
            context['error_details'] = error_details[:10]

        return self.render_to_response(context)

class InvoicePrintView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    """Print-friendly invoice view."""

    model = Invoice
    template_name = 'finance/invoice_print.html'
    context_object_name = 'invoice'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['items'] = self.object.items.filter(is_active=True).order_by('category')
        context['school_name'] = 'PCEA Wendani Academy'
        return context


class InvoiceCancelView(LoginRequiredMixin, RoleRequiredMixin, View):
    """Cancel an invoice."""

    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def post(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk)

        if invoice.amount_paid > 0:
            messages.error(
                request,
                'Cannot cancel invoice with payments. Please reverse payments first.'
            )
            return redirect('finance:invoice_detail', pk=pk)

        invoice.status = InvoiceStatus.CANCELLED
        invoice.save()

        messages.success(request, f'Invoice {invoice.invoice_number} cancelled.')
        return redirect('finance:invoice_list')


# =============================================================================
# Payments
# =============================================================================

class PaymentListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    """List all payments."""

    model = Payment
    template_name = 'finance/payment_list.html'
    context_object_name = 'payments'
    paginate_by = 25
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_queryset(self):
        queryset = Payment.objects.filter(
            is_active=True
        ).select_related('student', 'invoice')

        query = self.request.GET.get('query', '')
        if query:
            queryset = queryset.filter(
                Q(payment_reference__icontains=query) |
                Q(receipt_number__icontains=query) |
                Q(transaction_reference__icontains=query) |
                Q(student__admission_number__icontains=query) |
                Q(student__first_name__icontains=query) |
                Q(student__last_name__icontains=query)
            )

        method = self.request.GET.get('method')
        if method:
            queryset = queryset.filter(payment_method=method)

        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        if start_date:
            queryset = queryset.filter(payment_date__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(payment_date__date__lte=end_date)

        return queryset.order_by('-payment_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['payment_methods'] = PaymentMethod.choices
        context['statuses'] = PaymentStatus.choices
        context['query'] = self.request.GET.get('query', '')
        context['selected_method'] = self.request.GET.get('method', '')
        context['selected_status'] = self.request.GET.get('status', '')
        context['start_date'] = self.request.GET.get('start_date', '')
        context['end_date'] = self.request.GET.get('end_date', '')

        payments = self.get_queryset().filter(status=PaymentStatus.COMPLETED)
        context['total_amount'] = payments.aggregate(total=Sum('amount'))['total'] or 0
        context['payment_count'] = payments.count()

        return context


class PaymentDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    """View payment details."""

    model = Payment
    template_name = 'finance/payment_detail.html'
    context_object_name = 'payment'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Helpful in UI: show allocations (if template uses it)
        context['allocations'] = self.object.allocations.select_related(
            'invoice_item', 'invoice_item__invoice'
        ).all()

        # If there are bank transactions linked
        context['bank_transactions'] = self.object.bank_transactions.all()

        return context


class PaymentRecordView(LoginRequiredMixin, RoleRequiredMixin, FormView):
    """Manually record a payment.

    NOTE: PaymentRecordForm is a forms.Form, not a ModelForm, so do NOT call form.save().
    """

    template_name = 'finance/payment_record.html'
    form_class = PaymentRecordForm
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['student_id'] = self.request.GET.get('student')
        kwargs['invoice_id'] = self.request.GET.get('invoice')
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Record Payment'
        return context

    def form_valid(self, form):
        cd = form.cleaned_data

        student = cd['student']
        amount = cd['amount']
        payment_method = cd['payment_method']
        payment_date = cd.get('payment_date') or timezone.now()

        selected_invoice = cd.get('invoice')  # optional; policy is still oldest-first
        notes = cd.get('notes') or ''
        transaction_reference = cd.get('transaction_reference') or ''
        payer_name = cd.get('payer_name') or ''
        payer_phone = cd.get('payer_phone') or ''

        if selected_invoice:
            extra = f"Selected invoice: {selected_invoice.invoice_number} (allocation policy: oldest-first)"
            notes = (notes + (" | " if notes else "") + extra)

        payment = PaymentsPaymentService.create_manual_payment(
            student=student,
            amount=amount,
            payment_method=payment_method,
            received_by=self.request.user,
            payment_date=payment_date,
            payer_name=payer_name,
            payer_phone=payer_phone,
            notes=notes,
            transaction_reference=transaction_reference,
        )

        messages.success(self.request, f'Payment of KES {payment.amount:,.2f} recorded successfully.')
        return redirect('finance:payment_detail', pk=payment.pk)


class PaymentReceiptView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    """Print-friendly payment receipt."""

    model = Payment
    template_name = 'finance/payment_receipt.html'
    context_object_name = 'payment'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['school_name'] = 'PCEA Wendani Academy'
        return context


# =============================================================================
# Bank Transaction Matching & Details
# =============================================================================

class BankTransactionListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    """List unmatched bank transactions."""

    model = BankTransaction
    template_name = 'finance/bank_transaction_list.html'
    context_object_name = 'bank_transactions'
    paginate_by = 25
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_queryset(self):
        queryset = BankTransaction.objects.filter(is_active=True)

        status = self.request.GET.get('status', 'unmatched')
        if status == 'unmatched':
            queryset = queryset.filter(payment__isnull=True)
        elif status == 'matched':
            queryset = queryset.filter(payment__isnull=False)

        return queryset.order_by('-callback_received_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['selected_status'] = self.request.GET.get('status', 'unmatched')
        context['unmatched_count'] = BankTransaction.objects.filter(
            is_active=True, payment__isnull=True
        ).count()
        return context


class BankTransactionMatchView(LoginRequiredMixin, RoleRequiredMixin, FormView):
    """Match a bank transaction to a student (invoice selection is optional, but allocation is oldest-first)."""

    template_name = 'finance/bank_transaction_match.html'
    form_class = BankTransactionMatchForm
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['transaction'] = get_object_or_404(BankTransaction, pk=self.kwargs['pk'])
        return context

    def form_valid(self, form):
        transaction = get_object_or_404(BankTransaction, pk=self.kwargs['pk'])
        student = form.cleaned_data['student']
        selected_invoice = form.cleaned_data.get('invoice')  # optional; do not force allocation to it
        notes = form.cleaned_data.get('notes') or ''

        if transaction.payment_id:
            messages.error(self.request, "This transaction is already matched to a payment.")
            return redirect('finance:bank_transaction_list')

        # Add operator note (optional)
        if selected_invoice:
            extra = f"Selected invoice: {selected_invoice.invoice_number} (allocation policy: oldest-first)"
            notes = (notes + (" | " if notes else "") + extra)

        if notes:
            transaction.processing_notes = (transaction.processing_notes or "")
            transaction.processing_notes = (
                transaction.processing_notes
                + (" | " if transaction.processing_notes else "")
                + notes
            )
            transaction.save(update_fields=["processing_notes", "updated_at"])

        # Create payment from this BankTransaction and allocate oldest-first
        payment = PaymentsPaymentService.create_payment_from_bank_transaction(
            bank_tx=transaction,
            student=student,
            invoice=None,
            payer_name=transaction.payer_name or "",
            payer_phone=transaction.payer_account or "",
            reconciled_by=self.request.user,
        )

        messages.success(self.request, f'Transaction matched to {student.full_name} successfully.')
        return redirect('finance:bank_transaction_list')


class BankTransactionDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    """View bank transaction details."""

    model = BankTransaction
    template_name = 'finance/bank_transaction_detail.html'
    context_object_name = 'transaction'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object.payment:
            context['payment'] = self.object.payment
        return context


# =============================================================================
# Reports
# =============================================================================

class FinanceReportView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    """Finance reports dashboard."""

    template_name = 'finance/reports.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_term'] = Term.objects.filter(is_current=True).first()
        return context


class CollectionReportView(LoginRequiredMixin, RoleRequiredMixin, FormView):
    """Fee collection report."""

    template_name = 'finance/report_collection.html'
    form_class = DateRangeFilterForm
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')

        if start_date and end_date:
            context['report_data'] = FinanceReportService.get_collection_report(
                start_date=start_date,
                end_date=end_date
            )
            context['start_date'] = start_date
            context['end_date'] = end_date

        return context


class CollectionsReportView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    """Fee collections report with date filtering (alternate view)."""

    template_name = 'finance/report_collections.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        term_id = self.request.GET.get('term')

        term = None
        if term_id:
            term = Term.objects.filter(pk=term_id).first()

        if start_date or end_date or term:
            context['report_data'] = FinanceReportService.get_collections_summary(
                start_date=start_date,
                end_date=end_date,
                term=term
            )

        context['terms'] = Term.objects.filter(is_active=True).select_related('academic_year')
        context['start_date'] = start_date or ''
        context['end_date'] = end_date or ''
        context['selected_term'] = term_id or ''
        return context


class OutstandingBalancesReportView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    """Outstanding balances report."""

    template_name = 'finance/report_outstanding.html'
    context_object_name = 'invoices'
    paginate_by = 50
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_queryset(self):
        queryset = Invoice.objects.filter(
            is_active=True,
            balance__gt=0
        ).exclude(
            status=InvoiceStatus.CANCELLED
        ).select_related('student', 'term')

        term = self.request.GET.get('term')
        if term:
            queryset = queryset.filter(term_id=term)

        grade = self.request.GET.get('grade')
        if grade:
            queryset = queryset.filter(student__grade_level=grade)

        return queryset.order_by('-balance')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['terms'] = Term.objects.filter(is_active=True)
        context['total_outstanding'] = self.get_queryset().aggregate(
            total=Sum('balance')
        )['total'] or 0
        context['selected_term'] = self.request.GET.get('term', '')
        context['selected_grade'] = self.request.GET.get('grade', '')
        return context


# =============================================================================
# API Views (for AJAX)
# =============================================================================

class StudentInvoicesAPIView(LoginRequiredMixin, View):
    """Get invoices for a student (AJAX)."""

    def get(self, request, student_id):
        invoices = Invoice.objects.filter(
            student_id=student_id,
            is_active=True,
            balance__gt=0
        ).exclude(status=InvoiceStatus.CANCELLED).values(
            'id', 'invoice_number', 'total_amount', 'balance', 'term__name'
        )
        return JsonResponse(list(invoices), safe=False)


class StudentBalanceAPIView(LoginRequiredMixin, View):
    """Get total balance for a student (AJAX)."""

    def get(self, request, student_id):
        total_balance = Invoice.objects.filter(
            student_id=student_id,
            is_active=True
        ).exclude(
            status=InvoiceStatus.CANCELLED
        ).aggregate(total=Sum('balance'))['total'] or 0

        return JsonResponse({'balance': float(total_balance)})


# =============================================================================
# Student Statement Views
# =============================================================================

class StudentStatementView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    """View student financial statement."""

    model = Student
    template_name = 'finance/student_statement.html'
    context_object_name = 'student'
    pk_url_kwarg = 'student_pk'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT, UserRole.PARENT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        term_id = self.request.GET.get('term')
        term = None
        if term_id:
            term = Term.objects.filter(pk=term_id).first()

        statement = InvoiceService.get_student_statement(self.object, term)
        context.update(statement)
        context['terms'] = Term.objects.filter(is_active=True).select_related('academic_year')
        context['selected_term'] = term_id or ''
        return context


class StudentStatementPrintView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    """Print-friendly student statement."""

    model = Student
    template_name = 'finance/student_statement_print.html'
    context_object_name = 'student'
    pk_url_kwarg = 'student_pk'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        term_id = self.request.GET.get('term')
        term = Term.objects.filter(pk=term_id).first() if term_id else None

        statement = InvoiceService.get_student_statement(self.object, term)
        context.update(statement)
        context['school_name'] = 'PCEA Wendani Academy'
        context['print_date'] = timezone.now()
        return context


# =============================================================================
# Export (CSV)
# =============================================================================

class FinanceExportView(LoginRequiredMixin, RoleRequiredMixin, View):
    """Export financial data to CSV."""

    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get(self, request):
        import csv
        from django.http import HttpResponse

        export_type = request.GET.get('type', 'invoices')
        term_id = request.GET.get('term')

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{export_type}_{timezone.now().date()}.csv"'
        writer = csv.writer(response)

        if export_type == 'invoices':
            writer.writerow(['Invoice #', 'Student', 'Admission #', 'Term', 'Total', 'Paid', 'Balance', 'Status'])

            invoices = Invoice.objects.filter(is_active=True).select_related('student', 'term')
            if term_id:
                invoices = invoices.filter(term_id=term_id)

            for inv in invoices:
                writer.writerow([
                    inv.invoice_number,
                    getattr(inv.student, 'full_name', ''),
                    getattr(inv.student, 'admission_number', ''),
                    str(inv.term) if inv.term else '',
                    inv.total_amount,
                    inv.amount_paid,
                    inv.balance,
                    inv.status
                ])

        elif export_type == 'payments':
            writer.writerow(['Date', 'Receipt #', 'Student', 'Amount', 'Method', 'Reference', 'Status'])

            payments = Payment.objects.filter(is_active=True).select_related('student')
            for pmt in payments:
                writer.writerow([
                    pmt.payment_date.strftime('%Y-%m-%d %H:%M') if pmt.payment_date else '',
                    pmt.receipt_number or '',
                    getattr(pmt.student, 'full_name', ''),
                    pmt.amount,
                    pmt.payment_method,
                    pmt.transaction_reference or '',
                    pmt.status
                ])

        elif export_type == 'outstanding':
            writer.writerow(['Student', 'Admission #', 'Grade', 'Invoice #', 'Total', 'Balance'])

            invoices = Invoice.objects.filter(
                is_active=True, balance__gt=0
            ).exclude(status=InvoiceStatus.CANCELLED).select_related('student')

            if term_id:
                invoices = invoices.filter(term_id=term_id)

            for inv in invoices:
                writer.writerow([
                    getattr(inv.student, 'full_name', ''),
                    getattr(inv.student, 'admission_number', ''),
                    getattr(inv.student, 'grade_level', ''),
                    inv.invoice_number,
                    inv.total_amount,
                    inv.balance
                ])

        return response