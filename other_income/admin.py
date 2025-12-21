# other_income/admin.py
from django.contrib import admin
from .models import OtherIncomeInvoice, OtherIncomeItem, OtherIncomePayment


class ItemInline(admin.TabularInline):
    model = OtherIncomeItem
    extra = 0


@admin.register(OtherIncomeInvoice)
class OtherIncomeInvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'client_name', 'total_amount', 'amount_paid', 'balance', 'status', 'issue_date')
    inlines = [ItemInline]


@admin.register(OtherIncomePayment)
class OtherIncomePaymentAdmin(admin.ModelAdmin):
    list_display = ('payment_reference', 'invoice', 'amount', 'payment_date', 'received_by')