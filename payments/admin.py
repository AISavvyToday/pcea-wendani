# File: payments/admin.py
# ============================================================
# RATIONALE: Admin configuration matching actual model fields
# ============================================================

from django.contrib import admin
from django.utils.html import format_html
from .models import Payment, BankTransaction, PaymentAllocation, PaymentReminder


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_select_related = ('student', 'invoice', 'received_by', 'reconciled_by')
    list_display = [
        'payment_reference',
        'student',
        'amount',
        'payment_method',
        'payment_source',
        'payment_date',
        'status',
        'receipt_number',
    ]
    list_filter = ['status', 'payment_method', 'payment_source', 'payment_date', 'is_reconciled']
    search_fields = [
        'payment_reference', 
        'receipt_number',
        'transaction_reference',
        'student__admission_number', 
        'student__first_name', 
        'student__last_name',
        'payer_name',
        'payer_phone',
    ]
    date_hierarchy = 'payment_date'
    readonly_fields = ['payment_reference', 'receipt_number', 'created_at', 'updated_at']
    raw_id_fields = ['student', 'invoice', 'received_by', 'reconciled_by']
    
    fieldsets = (
        ('Payment Info', {
            'fields': ('payment_reference', 'student', 'invoice', 'amount', 'payment_method', 'status')
        }),
        ('Transaction Details', {
            'fields': ('payment_date', 'transaction_reference', 'payer_name', 'payer_phone')
        }),
        ('Receipt', {
            'fields': ('receipt_number', 'receipt_sent', 'receipt_sent_at')
        }),
        ('Processing', {
            'fields': ('received_by', 'notes')
        }),
        ('Reconciliation', {
            'fields': ('is_reconciled', 'reconciled_by', 'reconciled_at'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'transaction_id',
        'gateway',
        'amount',
        'payer_name',
        'callback_received_at',
        'processing_status',
        'is_matched_display',
    ]
    list_filter = ['processing_status', 'gateway', 'callback_received_at']
    search_fields = [
        'transaction_id', 
        'transaction_reference',
        'payer_name', 
        'payer_account',
    ]
    date_hierarchy = 'callback_received_at'
    readonly_fields = [
        'created_at', 
        'updated_at', 
        'raw_request', 
        'raw_response',
        'callback_received_at',
    ]
    raw_id_fields = ['payment']
    
    fieldsets = (
        ('Transaction Info', {
            'fields': ('transaction_id', 'transaction_reference', 'gateway', 'amount', 'currency')
        }),
        ('Payer Details', {
            'fields': ('payer_name', 'payer_account')
        }),
        ('Bank Status', {
            'fields': ('bank_status', 'bank_status_description', 'bank_timestamp')
        }),
        ('Processing', {
            'fields': ('processing_status', 'processing_notes', 'payment')
        }),
        ('Callback Info', {
            'fields': ('callback_url', 'callback_received_at')
        }),
        ('Raw Data', {
            'fields': ('raw_request', 'raw_response'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    @admin.display(boolean=True, description='Matched')
    def is_matched_display(self, obj):
        return obj.payment is not None

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('payment')


@admin.register(PaymentAllocation)
class PaymentAllocationAdmin(admin.ModelAdmin):
    list_select_related = ('payment', 'invoice_item')
    list_display = ['payment', 'invoice_item', 'amount', 'created_at']
    list_filter = ['created_at']
    search_fields = ['payment__payment_reference', 'invoice_item__description']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['payment', 'invoice_item']


@admin.register(PaymentReminder)
class PaymentReminderAdmin(admin.ModelAdmin):
    list_select_related = ('invoice',)
    list_display = ['invoice', 'reminder_type', 'created_at']
    list_filter = ['reminder_type', 'created_at']
    search_fields = ['invoice__invoice_number']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['invoice']