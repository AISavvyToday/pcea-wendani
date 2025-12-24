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
from academics.models import Term

import logging


from django.conf import settings
from .forms import InvoiceEditForm, InvoiceItemFormSet
from decimal import Decimal
from academics.models import TransportFee

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
from django.db import transaction as db_transaction, models
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
from decimal import Decimal
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

# local service imports
from payments.services.invoice import InvoiceService as PaymentsInvoiceService
from payments.models import Payment, PaymentAllocation
from core.models import PaymentStatus
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

        # Debug logging
        logger.info(f"FeeStructureCreateView.form_valid - Form valid: {form.is_valid()}")
        logger.info(f"FeeStructureCreateView.form_valid - Formset valid: {formset.is_valid()}")

        if not formset.is_valid():
            logger.error(f"Formset has errors: {formset.errors}")
            for i, f in enumerate(formset.forms):
                if f.errors:
                    logger.error(f"Form {i} has errors: {f.errors}")
                    # Log the POST data for this form
                    for field_name in ['category', 'description', 'amount']:
                        field_key = f'{formset.prefix}-{i}-{field_name}'
                        field_value = self.request.POST.get(field_key)
                        logger.error(f"  Field {field_name}: {field_value}")

        if formset.is_valid():
            try:
                with db_transaction.atomic():
                    self.object = form.save()
                    formset.instance = self.object

                    # Save formset items
                    instances = formset.save(commit=False)
                    for instance in instances:
                        # Set the fee structure for each item
                        instance.fee_structure = self.object
                        instance.save()

                    # Delete any marked for deletion
                    for instance in formset.deleted_objects:
                        instance.delete()

                    logger.info(f"Fee structure created successfully: {self.object.pk}")
                    logger.info(f"Fee items created: {self.object.items.count()}")

                    # Log all created items
                    for item in self.object.items.all():
                        logger.info(f"  - {item.category}: {item.description} = {item.amount}")

                messages.success(self.request, f'Fee structure "{self.object.name}" created successfully!')
                return redirect('finance:fee_structure_detail', pk=self.object.pk)

            except Exception as e:
                logger.exception(f"Error saving fee structure: {str(e)}")
                messages.error(self.request, f'Error saving fee structure: {str(e)}')
                return self.render_to_response(self.get_context_data(form=form))
        else:
            # Compile error messages for user
            error_summary = []
            for i, form in enumerate(formset.forms):
                if form.errors:
                    for field, errors in form.errors.items():
                        # Get the field label or use field name
                        field_label = form.fields[field].label if field in form.fields else field
                        for error in errors:
                            error_summary.append(f"Item {i + 1}, {field_label}: {error}")

            if error_summary:
                messages.error(self.request, "Please correct the following errors:")
                for error in error_summary[:5]:  # Show first 5 errors
                    messages.error(self.request, f"• {error}")
                if len(error_summary) > 5:
                    messages.error(self.request, f"... and {len(error_summary) - 5} more errors")

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
            # Log errors for debugging
            for i, f in enumerate(formset.forms):
                if f.errors:
                    logger.error(f"Form {i} errors in update: {f.errors}")
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
            queryset = queryset.filter(student__current_class__grade_level=grade)

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
    """View invoice details with comprehensive allocation breakdown."""

    model = Invoice
    template_name = 'finance/invoice_detail.html'
    context_object_name = 'invoice'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object

        # Get invoice items with their allocations, ordered by priority (same as allocation logic)
        items_qs = invoice.items.filter(is_active=True)

        # Build priority mapping from InvoiceService
        priority_order = {cat: i for i, cat in enumerate(PaymentsInvoiceService.PRIORITY_ORDER)}

        def priority_key(it):
            return (priority_order.get(it.category, 999), it.id)

        items = sorted(list(items_qs), key=priority_key)

        # Enhanced items with allocation details
        enhanced_items = []
        for item in items:
            total_allocated = PaymentAllocation.objects.filter(
                invoice_item=item,
                is_active=True,
                payment__is_active=True,
                payment__status=PaymentStatus.COMPLETED
            ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')

            allocations = PaymentAllocation.objects.filter(
                invoice_item=item,
                is_active=True,
                payment__is_active=True,
                payment__status=PaymentStatus.COMPLETED
            ).select_related('payment').order_by('-created_at')

            enhanced_items.append({
                'item': item,
                'total_allocated': total_allocated,
                'balance': (item.net_amount or Decimal('0.00')) - total_allocated,
                'is_fully_paid': total_allocated >= (item.net_amount or Decimal('0.00')),
                'allocations': allocations,
                'payment_count': allocations.count(),
            })

        context['enhanced_items'] = enhanced_items

        # Get all payments for this invoice (via allocations or legacy Payment.invoice link)
        payments_qs = Payment.objects.filter(
            is_active=True,
            status=PaymentStatus.COMPLETED
        ).filter(
            Q(invoice=invoice) | Q(allocations__invoice_item__invoice=invoice)
        ).distinct().select_related('student').prefetch_related('allocations').order_by('-payment_date')

        # Enhance payments with allocation details for THIS invoice
        enhanced_payments = []
        for p in payments_qs:
            payment_allocations = p.allocations.filter(
                is_active=True,
                invoice_item__invoice=invoice
            ).select_related('invoice_item')

            total_from_payment = payment_allocations.aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')

            enhanced_payments.append({
                'payment': p,
                'allocations': payment_allocations,
                'total_allocated': total_from_payment,
            })

        context['enhanced_payments'] = enhanced_payments

        # Calculate totals for display
        total_invoiced = invoice.total_amount or Decimal('0.00')
        total_paid = sum(i['total_allocated'] for i in enhanced_items) if enhanced_items else Decimal('0.00')
        total_balance = total_invoiced - total_paid

        # paid percentage
        paid_percentage = 0
        try:
            if total_invoiced > 0:
                paid_percentage = (total_paid / total_invoiced) * 100
        except Exception:
            paid_percentage = 0

        context.update({
            'total_invoiced': total_invoiced,
            'total_paid': total_paid,
            'total_balance': total_balance,
            'payment_count': len(enhanced_payments),
            'paid_percentage': paid_percentage,
            'today': timezone.now().date(),
        })

        return context

# class InvoiceDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
#     """View invoice details with comprehensive allocation breakdown."""
#
#     model = Invoice
#     template_name = 'finance/invoice_detail.html'
#     context_object_name = 'invoice'
#     allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]
#
#     def get_context_data(self, **kwargs):
#         context = super().get_context_data(**kwargs)
#
#         # Get invoice items with their allocations
#         items = self.object.items.filter(is_active=True).order_by('category')
#
#         # Enhanced items with allocation details
#         enhanced_items = []
#         for item in items:
#             # Get total allocated amount for this item from all payments
#             from payments.models import PaymentAllocation
#             total_allocated = PaymentAllocation.objects.filter(
#                 invoice_item=item,
#                 is_active=True,
#                 payment__is_active=True,
#                 payment__status=PaymentStatus.COMPLETED
#             ).aggregate(total=models.Sum('amount'))['total'] or 0
#
#             # Get individual allocations for this item
#             allocations = PaymentAllocation.objects.filter(
#                 invoice_item=item,
#                 is_active=True,
#                 payment__is_active=True,
#                 payment__status=PaymentStatus.COMPLETED
#             ).select_related('payment').order_by('-created_at')
#
#             enhanced_items.append({
#                 'item': item,
#                 'total_allocated': total_allocated,
#                 'balance': item.net_amount - total_allocated,
#                 'is_fully_paid': total_allocated >= item.net_amount,
#                 'allocations': allocations,
#                 'payment_count': allocations.count(),
#             })
#
#         context['enhanced_items'] = enhanced_items
#
#         # Get all payments for this invoice (via allocations)
#         from django.db.models import Q
#         payments = Payment.objects.filter(
#             is_active=True,
#             status=PaymentStatus.COMPLETED
#         ).filter(
#             Q(invoice=self.object) | Q(allocations__invoice_item__invoice=self.object)
#         ).distinct().select_related('student').prefetch_related('allocations').order_by('-payment_date')
#
#         # Enhance payments with allocation details for this invoice
#         enhanced_payments = []
#         for payment in payments:
#             # Get allocations for this payment that belong to this invoice
#             payment_allocations = payment.allocations.filter(
#                 is_active=True,
#                 invoice_item__invoice=self.object
#             ).select_related('invoice_item')
#
#             # Calculate total allocated from this payment to this invoice
#             total_from_payment = payment_allocations.aggregate(
#                 total=models.Sum('amount')
#             )['total'] or 0
#
#             enhanced_payments.append({
#                 'payment': payment,
#                 'allocations': payment_allocations,
#                 'total_allocated': total_from_payment,
#             })
#
#         context['enhanced_payments'] = enhanced_payments
#
#         # Calculate totals for display
#         total_invoiced = self.object.total_amount
#         total_paid = sum(item['total_allocated'] for item in enhanced_items)
#         total_balance = total_invoiced - total_paid
#
#         # Calculate paid percentage
#         paid_percentage = 0
#         if total_invoiced > 0:
#             paid_percentage = (total_paid / total_invoiced) * 100
#
#         context.update({
#             'total_invoiced': total_invoiced,
#             'total_paid': total_paid,
#             'total_balance': total_balance,
#             'payment_count': len(enhanced_payments),
#             'paid_percentage': paid_percentage,
#             'today': timezone.now().date(),
#         })
#
#         return context


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

            # FIXED: Use current_class__grade_level
            if grade_levels:
                students = students.filter(current_class__grade_level__in=grade_levels)

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

                # FIXED: Use current_class__grade_level
                grade_display = test_student.current_class.grade_level if test_student.current_class else "No class"
                logger.info(f"Testing with student: {test_student.admission_number} (Grade: {grade_display})")

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
                    error_details = error_list[:10]
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
            for i, err in enumerate(error_details[:5]):
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
        ).order_by('-created_at')[:50]

        # Add error details to context for template
        if error_details:
            context['error_details'] = error_details[:10]

        return self.render_to_response(context)


class InvoicePrintView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    """Print-friendly invoice/receipt view."""

    model = Invoice
    template_name = 'finance/invoice_print.html'
    context_object_name = 'invoice'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object

        # Determine mode: explicit ?mode=invoice|receipt else infer by amount_paid
        mode = self.request.GET.get('mode')
        if mode not in ('invoice', 'receipt'):
            mode = 'receipt' if (invoice.amount_paid and invoice.amount_paid > Decimal('0.00')) else 'invoice'

        # notes from querystring (optional)
        notes = self.request.GET.get('notes', '').strip()

        # copies parameter for printing multiple receipts on one page (default 2 for Epson LX350 A4)
        try:
            copies = int(self.request.GET.get('copies', '2'))
        except Exception:
            copies = 2
        copies = max(1, min(copies, 4))  # limit to 1..4

        copies_range = range(copies)

        # printed metadata
        printed_by = getattr(self.request.user, 'get_full_name', lambda: str(self.request.user))()
        print_datetime = timezone.now()

        # Items sorted by allocation priority
        items_qs = invoice.items.filter(is_active=True)
        priority_order = {cat: i for i, cat in enumerate(PaymentsInvoiceService.PRIORITY_ORDER)}

        def priority_key(it):
            return (priority_order.get(it.category, 999), it.id)

        items = sorted(list(items_qs), key=priority_key)

        # Build enhanced_items (with allocation totals)
        enhanced_items = []
        for item in items:
            total_allocated = PaymentAllocation.objects.filter(
                invoice_item=item,
                is_active=True,
                payment__is_active=True,
                payment__status=PaymentStatus.COMPLETED
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

            enhanced_items.append({
                'item': item,
                'total_allocated': total_allocated,
                'balance': (item.net_amount or Decimal('0.00')) - total_allocated,
            })

        # Payments for this invoice (distinct)
        payments_qs = Payment.objects.filter(
            is_active=True,
            status=PaymentStatus.COMPLETED
        ).filter(
            Q(invoice=invoice) | Q(allocations__invoice_item__invoice=invoice)
        ).distinct().select_related('student').prefetch_related('allocations').order_by('-payment_date')

        # Build enhanced_payments (with allocated_total for this invoice)
        enhanced_payments = []
        for p in payments_qs:
            allocs = p.allocations.filter(is_active=True, invoice_item__invoice=invoice).select_related('invoice_item')
            allocated_total = allocs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            enhanced_payments.append({
                'payment': p,
                'allocations': allocs,
                'allocated_total': allocated_total,
            })

        # Totals
        total_invoiced = invoice.total_amount or Decimal('0.00')
        # total_paid for this invoice computed from enhanced_items (sum of allocated amounts)
        total_paid = sum(x['total_allocated'] for x in enhanced_items) if enhanced_items else Decimal('0.00')

        # Important: follow same formula as Invoice.save/update -- include balance_bf and prepayment
        balance_bf = invoice.balance_bf or Decimal('0.00')
        prepayment = invoice.prepayment or Decimal('0.00')
        total_balance = (total_invoiced + balance_bf - prepayment) - total_paid

        # Bank details & logos from settings (fallback to hardcoded)
        bank_details = getattr(settings, 'SCHOOL_BANK_DETAILS', {
            'equity': {'name': 'EQUITY BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '1130280029105'},
            'coop': {'name': 'CO-OPERATIVE BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '01129158350600'},
            'paybill_1': {'label': 'PAYBILL (247247)', 'acc_format': '80029#<admission_number>'},
            'paybill_2': {'label': 'PAYBILL (400222)', 'acc_format': '393939#<admission_number>'},
        })

        school_logo_url = getattr(settings, 'SCHOOL_LOGO_URL', '/static/img/school_logo.png')
        sponsor_logo_url = getattr(settings, 'SPONSOR_LOGO_URL', '/static/img/sponsor_logo.png')

        context.update({
            'mode': mode,
            'notes': notes,
            'copies': copies,
            'copies_range': copies_range,
            'printed_by': printed_by,
            'print_datetime': print_datetime,
            'enhanced_items': enhanced_items,
            'enhanced_payments': enhanced_payments,
            'total_invoiced': total_invoiced,
            'total_paid': total_paid,
            'total_balance': total_balance,
            'bank_details': bank_details,
            'school_logo_url': school_logo_url,
            'sponsor_logo_url': sponsor_logo_url,
            'school_name': getattr(settings, 'SCHOOL_NAME', 'P.C.E.A Wendani Academy'),
        })

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
        payment_source = cd['payment_source']
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
            payment_source=payment_source,
            received_by=self.request.user,
            payment_date=payment_date,
            payer_name=payer_name,
            payer_phone=payer_phone,
            notes=notes,
            transaction_reference=transaction_reference,
        )

        messages.success(self.request, f'Payment of KES {payment.amount:,.2f} recorded successfully.')
        return redirect('finance:payment_list')


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
    """
    Print-friendly student statement.
    Accepts optional query params:
      - term=<term_pk> (filter statement by term)
      - notes=<text> (optional notes to put on printout)
      - copies=<n> (how many copies to render on same A4; default 2)
    """

    model = Student
    template_name = 'finance/student_statement_print.html'
    context_object_name = 'student'
    pk_url_kwarg = 'student_pk'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        student = self.object

        # Term filter
        term_id = self.request.GET.get('term')
        term = Term.objects.filter(pk=term_id).first() if term_id else None

        # Prepare statement using existing InvoiceService helper
        statement = InvoiceService.get_student_statement(student, term)

        # Notes and copies
        notes = self.request.GET.get('notes', '').strip()
        try:
            copies = int(self.request.GET.get('copies', '2'))
        except Exception:
            copies = 2
        copies = max(1, min(copies, 4))
        copies_range = range(copies)

        # printed metadata
        printed_by = getattr(self.request.user, 'get_full_name', None)
        if callable(printed_by):
            printed_by = printed_by()
        else:
            printed_by = str(self.request.user)

        print_datetime = timezone.now()

        # School branding & bank details from settings (fallback defaults)
        bank_details = getattr(settings, 'SCHOOL_BANK_DETAILS', {
            'equity': {'name': 'EQUITY BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '1130280029105'},
            'coop': {'name': 'CO-OPERATIVE BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '01129158350600'},
            'paybill_1': {'label': 'PAYBILL (247247)', 'acc_format': '80029#<admission_number>'},
            'paybill_2': {'label': 'PAYBILL (400222)', 'acc_format': '393939#<admission_number>'},
        })
        school_logo_url = getattr(settings, 'SCHOOL_LOGO_URL', '/static/img/school_logo.png')
        sponsor_logo_url = getattr(settings, 'SPONSOR_LOGO_URL', '/static/img/sponsor_logo.png')
        school_name = getattr(settings, 'SCHOOL_NAME', 'P.C.E.A Wendani Academy')

        # Put everything in context
        context.update({
            'statement': statement,
            'term': term,
            'notes': notes,
            'copies': copies,
            'copies_range': copies_range,
            'printed_by': printed_by,
            'print_datetime': print_datetime,
            'bank_details': bank_details,
            'school_logo_url': school_logo_url,
            'sponsor_logo_url': sponsor_logo_url,
            'school_name': school_name,
        })

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


class InvoiceEditView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    """
    Edit invoice header and items (inline). Staff can add/remove items,
    including transport items with route & half/full trip selection.
    """
    model = Invoice
    form_class = InvoiceEditForm
    template_name = 'finance/invoice_edit.html'
    context_object_name = 'invoice'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object

        if self.request.POST:
            context['formset'] = InvoiceItemFormSet(
                self.request.POST,
                instance=self.object,
                form_kwargs={'invoice': invoice}
            )
        else:
            context['formset'] = InvoiceItemFormSet(
                instance=self.object,
                form_kwargs={'invoice': invoice}
            )

        # Add fee map for JavaScript
        if invoice and invoice.term:
            from academics.models import TransportFee
            import json
            from decimal import Decimal

            transport_fees = TransportFee.objects.filter(
                academic_year=invoice.term.academic_year,
                term=invoice.term.term,
                is_active=True
            ).select_related('route')

            fee_map = {}
            for tf in transport_fees:
                half_amount = tf.half_amount if tf.half_amount is not None else tf.amount / 2
                fee_map[str(tf.route.id)] = {
                    'full': float(tf.amount),
                    'half': float(half_amount)
                }

            context['fee_map_json'] = json.dumps(fee_map)
            
            # Add student's transport info for auto-population
            student = invoice.student
            if student and student.uses_school_transport and student.transport_route:
                student_transport_info = {
                    'route_id': str(student.transport_route.id),
                    'route_name': student.transport_route.name,
                    'trip_type': 'full'  # Default to full trip
                }
                context['student_transport_json'] = json.dumps(student_transport_info)
            else:
                context['student_transport_json'] = json.dumps(None)
        else:
            context['fee_map_json'] = json.dumps({})
            context['student_transport_json'] = json.dumps(None)

        # Add initial totals for display
        context['current_subtotal'] = invoice.subtotal or Decimal('0.00')
        context['current_discount'] = invoice.discount_amount or Decimal('0.00')
        context['current_total'] = invoice.total_amount or Decimal('0.00')

        return context

    def form_valid(self, form):
        invoice = form.instance
        formset = InvoiceItemFormSet(
            self.request.POST,
            instance=invoice,
            form_kwargs={'invoice': invoice}
        )

        if not formset.is_valid():
            # Log formset errors for debugging
            for i, f in enumerate(formset.forms):
                if f.errors:
                    logger.error(f"Form {i} errors in invoice edit: {f.errors}")

            messages.error(self.request, "There are errors in the invoice items. Please fix them.")
            return self.render_to_response(self.get_context_data(form=form))

        try:
            with db_transaction.atomic():
                # Save invoice header (notes/due_date)
                self.object = form.save()

                # Process each form in formset to handle transport amounts
                instances = formset.save(commit=False)

                for inst in instances:
                    # If this item is transport and route is selected, auto-calculate amount
                    if inst.category == 'transport' and inst.transport_route:
                        # If transport_route and trip_type provided, fetch transport fee
                        if inst.transport_route and inst.transport_trip_type:
                            try:
                                tf = TransportFee.objects.get(
                                    route=inst.transport_route,
                                    academic_year=invoice.term.academic_year,
                                    term=invoice.term.term,
                                    is_active=True
                                )
                                # Calculate amount based on trip type
                                if inst.transport_trip_type == 'half':
                                    amount = tf.half_amount if tf.half_amount is not None else tf.amount / 2
                                else:
                                    amount = tf.amount

                                inst.amount = amount

                                # Update description if empty
                                if not inst.description or inst.description.strip() == '':
                                    trip_display = "Half Trip" if inst.transport_trip_type == 'half' else "Full Trip"
                                    inst.description = f"Transport ({inst.transport_route.name} - {trip_display})"

                            except TransportFee.DoesNotExist:
                                # No configured fee: keep existing amount or set to 0
                                if not inst.amount or inst.amount == Decimal('0.00'):
                                    inst.amount = Decimal('0.00')
                                    inst.description = inst.description or f"Transport ({inst.transport_route.name} - Fee not configured)"
                        else:
                            # If route selected but no trip type, default to full trip
                            if inst.transport_route and not inst.transport_trip_type:
                                inst.transport_trip_type = 'full'
                                try:
                                    tf = TransportFee.objects.get(
                                        route=inst.transport_route,
                                        academic_year=invoice.term.academic_year,
                                        term=invoice.term.term,
                                        is_active=True
                                    )
                                    inst.amount = tf.amount
                                    if not inst.description or inst.description.strip() == '':
                                        inst.description = f"Transport ({inst.transport_route.name} - Full Trip)"
                                except TransportFee.DoesNotExist:
                                    if not inst.amount or inst.amount == Decimal('0.00'):
                                        inst.amount = Decimal('0.00')
                    elif inst.category == 'transport' and not inst.transport_route:
                        # Transport item without route - ensure amount is set
                        if not inst.amount or inst.amount == Decimal('0.00'):
                            inst.amount = Decimal('0.00')

                    # Ensure net_amount is calculated properly
                    if inst.discount_applied is None:
                        inst.discount_applied = Decimal('0.00')
                    if inst.amount is None:
                        inst.amount = Decimal('0.00')

                    inst.net_amount = (inst.amount or Decimal('0.00')) - (inst.discount_applied or Decimal('0.00'))
                    inst.save()

                # Handle deleted forms
                for inst in formset.deleted_objects:
                    inst.delete()

                # Recalculate invoice totals from all items
                self.recalculate_invoice_totals(invoice)

                # Update payment status
                invoice.update_payment_status()

            messages.success(self.request, f"Invoice {invoice.invoice_number} updated successfully.")
            return redirect('finance:invoice_detail', pk=invoice.pk)

        except Exception as e:
            logger.exception("Failed to update invoice")
            messages.error(self.request, f"Error updating invoice: {str(e)}")
            return self.render_to_response(self.get_context_data(form=form))

    def recalculate_invoice_totals(self, invoice):
        """Recalculate invoice totals from items."""
        from decimal import Decimal

        # Get all active items for this invoice
        items = invoice.items.all()

        # Calculate totals
        subtotal = Decimal('0.00')
        total_discount = Decimal('0.00')

        for item in items:
            subtotal += item.amount or Decimal('0.00')
            total_discount += item.discount_applied or Decimal('0.00')

        # Update invoice fields
        invoice.subtotal = subtotal
        invoice.discount_amount = total_discount
        invoice.total_amount = subtotal - total_discount

        # Recompute balance using the correct formula
        balance_bf = invoice.balance_bf or Decimal('0.00')
        prepayment = invoice.prepayment or Decimal('0.00')
        amount_paid = invoice.amount_paid or Decimal('0.00')

        # Formula: (total + balance_bf - prepayment) - amount_paid
        invoice.balance = (invoice.total_amount + balance_bf - prepayment) - amount_paid

        # Ensure balance is not negative due to overpayment
        if invoice.balance < Decimal('0.00'):
            # If overpaid, set balance to 0 and adjust prepayment
            invoice.prepayment = abs(invoice.balance)
            invoice.balance = Decimal('0.00')

        invoice.save(update_fields=[
            'subtotal', 'discount_amount', 'total_amount',
            'balance', 'prepayment', 'updated_at'
        ])

        logger.info(f"Recalculated totals for invoice {invoice.invoice_number}: "
                    f"Subtotal={subtotal}, Discount={total_discount}, "
                    f"Total={invoice.total_amount}, Balance={invoice.balance}")


# =============================================================================
# Single Student Invoice Generation
# =============================================================================

class SingleStudentInvoiceGenerateView(LoginRequiredMixin, RoleRequiredMixin, View):
    """Generate invoice for a single student via AJAX."""

    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def post(self, request, student_pk):
        """Handle AJAX POST request to generate invoice for a single student."""
        import json

        try:
            student = get_object_or_404(Student, pk=student_pk)
            term_id = request.POST.get('term_id')

            if not term_id:
                return JsonResponse({
                    'success': False,
                    'error': 'Please select a term.'
                }, status=400)

            term = get_object_or_404(Term, pk=term_id)

            # Generate invoice using the same service as bulk generation
            invoice, created = InvoiceService.generate_invoice(
                student=student,
                term=term,
                generated_by=request.user
            )

            if created:
                return JsonResponse({
                    'success': True,
                    'message': f'Invoice {invoice.invoice_number} generated successfully for {student.full_name}.',
                    'invoice_id': str(invoice.pk),
                    'invoice_number': invoice.invoice_number,
                    'total_amount': str(invoice.total_amount),
                    'redirect_url': reverse('finance:invoice_detail', kwargs={'pk': invoice.pk})
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': f'Invoice already exists for {student.full_name} in {term}.',
                    'invoice_id': str(invoice.pk),
                    'invoice_number': invoice.invoice_number,
                    'redirect_url': reverse('finance:invoice_detail', kwargs={'pk': invoice.pk})
                }, status=400)

        except ValueError as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
        except Exception as e:
            logger.exception(f"Failed to generate invoice for student {student_pk}")
            return JsonResponse({
                'success': False,
                'error': f'Error generating invoice: {str(e)}'
            }, status=500)

    def get(self, request, student_pk):
        """Return available terms for invoice generation."""
        student = get_object_or_404(Student, pk=student_pk)

        # Get available terms (active terms)
        terms = Term.objects.filter(is_active=True).select_related('academic_year').order_by(
            '-academic_year__year', '-term'
        )

        # Check which terms already have invoices for this student
        existing_invoices = Invoice.objects.filter(
            student=student,
            is_active=True
        ).exclude(status='cancelled').values_list('term_id', flat=True)

        terms_data = []
        for term in terms:
            has_invoice = term.pk in existing_invoices
            terms_data.append({
                'id': str(term.pk),
                'label': f"{term.academic_year.year} - {term.get_term_display()}",
                'has_invoice': has_invoice
            })

        return JsonResponse({
            'success': True,
            'student_name': student.full_name,
            'terms': terms_data
        })