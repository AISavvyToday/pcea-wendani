from django.contrib import admin
from django.utils.html import format_html

from .models import OtherIncomeInvoice, OtherIncomeItem, OtherIncomePayment


class ItemInline(admin.TabularInline):
    model = OtherIncomeItem
    extra = 0
    fields = ('description', 'amount')


class PaymentInline(admin.TabularInline):
    model = OtherIncomePayment
    extra = 0
    fields = ('payment_reference', 'amount', 'payment_method', 'payment_date', 'received_by')
    readonly_fields = ('payment_reference', 'payment_date')


@admin.register(OtherIncomeInvoice)
class OtherIncomeInvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'client_name', 'total_amount_display', 'amount_paid_display', 'balance_display', 'status', 'issue_date', 'organization')
    list_filter = ('organization', 'status', 'issue_date', 'due_date')
    search_fields = ('invoice_number', 'client_name', 'client_contact', 'description')
    readonly_fields = ('invoice_number', 'subtotal', 'total_amount', 'amount_paid', 'balance', 'created_at', 'updated_at')
    autocomplete_fields = ('organization', 'generated_by')
    inlines = [ItemInline, PaymentInline]
    date_hierarchy = 'issue_date'
    ordering = ('-issue_date', '-created_at')

    def total_amount_display(self, obj):
        return f"KES {obj.total_amount:,.0f}"

    def amount_paid_display(self, obj):
        return f"KES {obj.amount_paid:,.0f}"

    def balance_display(self, obj):
        color = 'green' if obj.balance <= 0 else 'red'
        return format_html('<span style="color: {}; font-weight: bold;">KES {:,.0f}</span>', color, abs(obj.balance))


@admin.register(OtherIncomePayment)
class OtherIncomePaymentAdmin(admin.ModelAdmin):
    list_display = ('payment_reference', 'invoice', 'amount', 'payment_method', 'payment_date', 'payer_name', 'received_by')
    list_filter = ('payment_method', 'payment_date', 'invoice__organization')
    search_fields = ('payment_reference', 'receipt_number', 'transaction_reference', 'payer_name', 'payer_contact', 'invoice__invoice_number', 'invoice__client_name')
    readonly_fields = ('payment_reference', 'receipt_number', 'created_at', 'updated_at')
    autocomplete_fields = ('invoice', 'received_by')
    date_hierarchy = 'payment_date'
    ordering = ('-payment_date',)
