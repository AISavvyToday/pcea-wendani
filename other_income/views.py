# other_income/views.py
from decimal import Decimal
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, View, TemplateView, FormView
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.db.models import Q

from core.mixins import RoleRequiredMixin, OrganizationFilterMixin
from accounts.models import UserRole
from .models import OtherIncomeInvoice, OtherIncomeItem, OtherIncomePayment
from .forms import (
    OtherIncomeInvoiceForm,
    OtherIncomeItemFormSet,
    OtherIncomePaymentForm,
    OtherIncomeReportStagingFilterForm,
)
from .reporting import (
    OtherIncomeReportFilters,
    build_other_income_report_dataset,
    build_other_income_report_inventory,
)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings


def _other_income_invoice_queryset(organization):
    """Queryset for OtherIncomeInvoice with org filter and backward compatibility for null org."""
    qs = OtherIncomeInvoice.objects.filter(is_active=True)
    if organization:
        qs = qs.filter(Q(organization=organization) | Q(organization__isnull=True))
    return qs


class OtherIncomeListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, TemplateView):
    template_name = 'other_income/invoice_list.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get active tab from query param
        active_tab = self.request.GET.get('tab', 'invoices')
        context['active_tab'] = active_tab
        
        # Search query
        q = self.request.GET.get('q', '')
        context['search_query'] = q
        
        # Get invoices - apply organization filter (with backward compat for null org)
        organization = getattr(self.request, 'organization', None)
        invoices = _other_income_invoice_queryset(organization)
        if q:
            invoices = invoices.filter(client_name__icontains=q)
        context['invoices'] = invoices.order_by('-issue_date')[:50]
        
        # Get payments - apply organization filter (with backward compat)
        payments = OtherIncomePayment.objects.filter(is_active=True).select_related('invoice')
        if organization:
            payments = payments.filter(
                Q(invoice__organization=organization) | Q(invoice__organization__isnull=True)
            )
        if q:
            payments = payments.filter(
                invoice__client_name__icontains=q
            ) | payments.filter(
                payer_name__icontains=q
            ) | payments.filter(
                payment_reference__icontains=q
            )
        context['payments'] = payments.order_by('-payment_date')[:50]
        
        return context


class OtherIncomeCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = OtherIncomeInvoice
    form_class = OtherIncomeInvoiceForm
    template_name = 'other_income/invoice_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['formset'] = OtherIncomeItemFormSet(self.request.POST)
        else:
            context['formset'] = OtherIncomeItemFormSet()
        return context

    def form_valid(self, form):
        formset = OtherIncomeItemFormSet(self.request.POST)
        if not formset.is_valid():
            messages.error(self.request, "Please correct the item errors.")
            return self.render_to_response(self.get_context_data(form=form))

        try:
            with transaction.atomic():
                self.object = form.save(commit=False)
                # Set organization for multi-tenancy (critical - was missing, caused 404 on view)
                organization = getattr(self.request, 'organization', None)
                if organization:
                    self.object.organization = organization
                self.object.generated_by = self.request.user
                self.object.status = 'unpaid'
                self.object.save()
                formset.instance = self.object
                formset.save()

                # recalc totals
                self.object.recalc_totals()
                self.object.save(update_fields=['subtotal', 'total_amount', 'balance', 'updated_at'])

            messages.success(self.request, f"Invoice {self.object.invoice_number} created.")
            return redirect('other_income:invoice_detail', pk=self.object.pk)
        except Exception as e:
            messages.error(self.request, f"Error creating invoice: {e}")
            return self.render_to_response(self.get_context_data(form=form))


class OtherIncomeDetailView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, DetailView):
    model = OtherIncomeInvoice
    template_name = 'other_income/invoice_detail.html'
    context_object_name = 'invoice'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_queryset(self):
        return _other_income_invoice_queryset(getattr(self.request, 'organization', None))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object
        context['items'] = invoice.items.filter(is_active=True)
        context['payments'] = invoice.payments.filter(is_active=True).order_by('-payment_date')
        return context


class OtherIncomeEditView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    """Edit other income invoice header and items."""
    model = OtherIncomeInvoice
    form_class = OtherIncomeInvoiceForm
    template_name = 'other_income/invoice_form.html'
    context_object_name = 'invoice'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_queryset(self):
        return _other_income_invoice_queryset(getattr(self.request, 'organization', None))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['formset'] = OtherIncomeItemFormSet(self.request.POST, instance=self.object)
        else:
            context['formset'] = OtherIncomeItemFormSet(instance=self.object)
        context['is_edit'] = True
        return context

    def form_valid(self, form):
        formset = OtherIncomeItemFormSet(self.request.POST, instance=self.object)
        if not formset.is_valid():
            messages.error(self.request, "Please correct the item errors.")
            return self.render_to_response(self.get_context_data(form=form))

        try:
            with transaction.atomic():
                form.save()
                formset.save()
                self.object.recalc_totals()
                self.object.save(update_fields=['subtotal', 'total_amount', 'balance', 'updated_at'])
            messages.success(self.request, f"Invoice {self.object.invoice_number} updated.")
            return redirect('other_income:invoice_detail', pk=self.object.pk)
        except Exception as e:
            messages.error(self.request, f"Error updating invoice: {e}")
            return self.render_to_response(self.get_context_data(form=form))


class OtherIncomeInvoiceDeleteView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """
    Soft-delete an other income invoice.
    Shows confirmation page on GET, performs soft delete on POST.
    """
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_invoice(self):
        queryset = _other_income_invoice_queryset(getattr(self.request, 'organization', None))
        return get_object_or_404(queryset, pk=self.kwargs.get('pk'))

    def get(self, request, *args, **kwargs):
        invoice = self.get_invoice()
        return render(request, 'other_income/invoice_confirm_delete.html', {'invoice': invoice})

    def post(self, request, *args, **kwargs):
        invoice = self.get_invoice()
        invoice_number = invoice.invoice_number
        invoice.is_active = False
        invoice.deleted_at = timezone.now()
        invoice.deleted_by = request.user
        invoice.save(update_fields=['is_active', 'deleted_at', 'deleted_by', 'updated_at'])
        messages.success(request, f'Other income invoice {invoice_number} has been deleted successfully.')
        return redirect('other_income:invoice_list')


class OtherIncomeInvoicePrintView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, DetailView):
    model = OtherIncomeInvoice
    template_name = 'other_income/invoice_print.html'
    context_object_name = 'invoice'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_queryset(self):
        return _other_income_invoice_queryset(getattr(self.request, 'organization', None))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object

        # notes & copies
        notes = self.request.GET.get('notes', '')
        try:
            copies = int(self.request.GET.get('copies', '1'))
        except Exception:
            copies = 1
        copies = max(1, min(copies, 4))
        copies_range = range(copies)

        printed_by = getattr(self.request.user, 'get_full_name', lambda: str(self.request.user))()
        print_datetime = timezone.now()

        organization = getattr(self.request, 'organization', None)
        is_demo = organization and organization.name == 'Demo Organisation'
        if is_demo:
            school_logo_url = '/static/assets/images/placeholder_logo.png'
            sponsor_logo_url = '/static/assets/images/placeholder_logo2.png'
        else:
            school_logo_url = getattr(settings, 'SCHOOL_LOGO_URL', '/static/img/school_logo.png')
            sponsor_logo_url = getattr(settings, 'SPONSOR_LOGO_URL', '/static/img/sponsor_logo.png')
        
        context.update({
            'notes': notes,
            'copies': copies,
            'copies_range': copies_range,
            'printed_by': printed_by,
            'print_datetime': print_datetime,
            'school_name': getattr(settings, 'SCHOOL_NAME', 'P.C.E.A Wendani Academy'),
            'school_logo_url': school_logo_url,
            'sponsor_logo_url': sponsor_logo_url,
            'bank_details': getattr(settings, 'SCHOOL_BANK_DETAILS', {}),
        })
        return context


class OtherIncomeRecordPaymentView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, FormView):
    template_name = 'other_income/payment_record.html'
    form_class = OtherIncomePaymentForm
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def dispatch(self, request, *args, **kwargs):
        queryset = _other_income_invoice_queryset(getattr(request, 'organization', None))
        self.invoice = get_object_or_404(queryset, pk=self.kwargs.get('pk'))
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial['payment_date'] = timezone.now()
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['invoice'] = self.invoice
        return ctx

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            with transaction.atomic():
                payment = OtherIncomePayment.objects.create(
                    invoice=self.invoice,
                    amount=data['amount'],
                    payment_method=data.get('payment_method', ''),
                    payment_date=data.get('payment_date') or timezone.now(),
                    payer_name=data.get('payer_name', ''),
                    payer_contact=data.get('payer_contact', ''),
                    transaction_reference=data.get('transaction_reference', ''),
                    received_by=self.request.user
                )
            messages.success(self.request, f"Payment recorded: KES {payment.amount}")
            return redirect('other_income:invoice_detail', pk=self.invoice.pk)
        except Exception as e:
            messages.error(self.request, f"Error recording payment: {e}")
            return self.render_to_response(self.get_context_data(form=form))


class OtherIncomeReportStagingView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, TemplateView):
    """
    Planning/staging page for the upcoming other-income reports.

    This deliberately stops short of the final HTML/Excel/PDF outputs until the
    Wendani team confirms the exact report template, but it centralizes the
    shared filters and data inventory so those outputs can be added quickly.
    """
    template_name = 'other_income/report_staging.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = OtherIncomeReportStagingFilterForm(self.request.GET or None)
        form.is_valid()
        cleaned = getattr(form, 'cleaned_data', {})

        filters = OtherIncomeReportFilters(
            search=cleaned.get('search', ''),
            status=cleaned.get('status', ''),
            issue_date_from=cleaned.get('issue_date_from'),
            issue_date_to=cleaned.get('issue_date_to'),
            due_date_from=cleaned.get('due_date_from'),
            due_date_to=cleaned.get('due_date_to'),
            payment_date_from=cleaned.get('payment_date_from'),
            payment_date_to=cleaned.get('payment_date_to'),
            payment_method=cleaned.get('payment_method', ''),
        )
        organization = getattr(self.request, 'organization', None)

        context.update({
            'form': form,
            'pending_template_questions': [
                'Which columns should appear in the final report?',
                'Should rows be grouped by invoice, client, payment date, payment method, or another business dimension?',
                'Which totals/subtotals are required in the body and footer?',
                'Which date filters should drive the report: issue date, due date, payment date, or a combination?',
                'Which invoice/payment dimensions must remain filterable across HTML, Excel, and PDF outputs?',
                'Should the export layouts be identical across HTML, Excel, and PDF, or tailored per format?',
            ],
            'report_inventory': build_other_income_report_inventory(
                organization=organization,
                filters=filters,
            ),
            'preview_rows': build_other_income_report_dataset(
                organization=organization,
                filters=filters,
                limit=5,
            ),
            'future_implementation_notes': [
                'Use the shared dataset in other_income.reporting for the final HTML view.',
                'Mirror the same filters in Excel/PDF exports so every output uses one ruleset.',
                'Reuse report formatting helpers from reports/views.py and reports/views_exports.py for headers, totals, and export response handling.',
            ],
        })
        return context


class OtherIncomePaymentReceiptView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, DetailView):
    """Print-friendly receipt for other income payments."""
    model = OtherIncomePayment
    template_name = 'other_income/payment_receipt.html'
    context_object_name = 'payment'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_queryset(self):
        queryset = OtherIncomePayment.objects.filter(is_active=True)
        organization = getattr(self.request, 'organization', None)
        if organization:
            queryset = queryset.filter(
                Q(invoice__organization=organization) | Q(invoice__organization__isnull=True)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = self.object

        # notes & copies
        notes = self.request.GET.get('notes', '')
        try:
            copies = int(self.request.GET.get('copies', '2'))
        except Exception:
            copies = 2
        copies = max(1, min(copies, 4))
        copies_range = range(copies)

        printed_by = getattr(self.request.user, 'get_full_name', lambda: str(self.request.user))()
        print_datetime = timezone.now()

        organization = getattr(self.request, 'organization', None)
        is_demo = organization and organization.name == 'Demo Organisation'
        if is_demo:
            school_logo_url = '/static/assets/images/placeholder_logo.png'
            sponsor_logo_url = '/static/assets/images/placeholder_logo2.png'
        else:
            school_logo_url = getattr(settings, 'SCHOOL_LOGO_URL', '/static/img/school_logo.png')
            sponsor_logo_url = getattr(settings, 'SPONSOR_LOGO_URL', '/static/img/sponsor_logo.png')

        context.update({
            'invoice': payment.invoice,
            'notes': notes,
            'copies': copies,
            'copies_range': copies_range,
            'printed_by': printed_by,
            'print_datetime': print_datetime,
            'school_name': getattr(settings, 'SCHOOL_NAME', 'P.C.E.A Wendani Academy'),
            'school_logo_url': school_logo_url,
            'sponsor_logo_url': sponsor_logo_url,
            'bank_details': getattr(settings, 'SCHOOL_BANK_DETAILS', {}),
        })
        return context
