# other_income/views.py
from decimal import Decimal
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, View, TemplateView, FormView
from django.contrib import messages
from django.db import transaction
from django.utils import timezone

from core.mixins import RoleRequiredMixin
from accounts.models import UserRole
from .models import OtherIncomeInvoice, OtherIncomeItem, OtherIncomePayment
from .forms import OtherIncomeInvoiceForm, OtherIncomeItemFormSet, OtherIncomePaymentForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings


class OtherIncomeListView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
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
        
        # Get invoices
        invoices = OtherIncomeInvoice.objects.filter(is_active=True)
        if q:
            invoices = invoices.filter(client_name__icontains=q)
        context['invoices'] = invoices.order_by('-issue_date')[:50]
        
        # Get payments
        payments = OtherIncomePayment.objects.filter(is_active=True).select_related('invoice')
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


class OtherIncomeCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
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


class OtherIncomeDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = OtherIncomeInvoice
    template_name = 'other_income/invoice_detail.html'
    context_object_name = 'invoice'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object
        context['items'] = invoice.items.filter(is_active=True)
        context['payments'] = invoice.payments.filter(is_active=True).order_by('-payment_date')
        return context


class OtherIncomeInvoicePrintView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = OtherIncomeInvoice
    template_name = 'other_income/invoice_print.html'
    context_object_name = 'invoice'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object

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

        context.update({
            'notes': notes,
            'copies': copies,
            'copies_range': copies_range,
            'printed_by': printed_by,
            'print_datetime': print_datetime,
            'school_name': getattr(settings, 'SCHOOL_NAME', 'P.C.E.A Wendani Academy'),
            'school_logo_url': getattr(settings, 'SCHOOL_LOGO_URL', '/static/img/school_logo.png'),
            'sponsor_logo_url': getattr(settings, 'SPONSOR_LOGO_URL', '/static/img/sponsor_logo.png'),
            'bank_details': getattr(settings, 'SCHOOL_BANK_DETAILS', {}),
        })
        return context


class OtherIncomeRecordPaymentView(LoginRequiredMixin, RoleRequiredMixin, FormView):
    template_name = 'other_income/payment_record.html'
    form_class = OtherIncomePaymentForm
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def dispatch(self, request, *args, **kwargs):
        self.invoice = get_object_or_404(OtherIncomeInvoice, pk=self.kwargs.get('pk'))
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