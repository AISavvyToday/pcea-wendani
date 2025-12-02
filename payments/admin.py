# payments/admin.py

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import Payment, BankTransaction, PaymentAllocation, PaymentReminder


class PaymentAllocationInline(admin.TabularInline):
    model = PaymentAllocation
    extra = 0
    autocomplete_fields = ['invoice_item']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'payment_reference', 'student', 'amount_display', 'payment_method',
        'status', 'payment_date', 'transaction_reference', 'is_reconciled'
    )
    list_filter = ('status', 'payment_method', 'is_reconciled', 'payment_date')
    search_fields = (
        'payment_reference', 'receipt_number', 'transaction_reference',
        'student__admission_number', 'student__first_name', 'student__last_name',
        'payer_name', 'payer_phone'
    )
    autocomplete_fields = ['student', 'invoice']
    readonly_fields = (
        'payment_reference', 'receipt_number', 'receipt_sent_at',
        'reconciled_at', 'created_at', 'updated_at'
    )
    date_hierarchy = 'payment_date'
    inlines = [PaymentAllocationInline]
    
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
            'fields': ('received_by', 'notes'),
            'classes': ('collapse',)
        }),
        ('Reconciliation', {
            'fields': ('is_reconciled', 'reconciled_by', 'reconciled_at'),
            'classes': ('collapse',)
        }),
    )
    
    def amount_display(self, obj):
        return format_html('KES {:,.0f}', obj.amount)
    amount_display.short_description = 'Amount'
    
    def save_model(self, request, obj, form, change):
        if not change and not obj.received_by:
            obj.received_by = request.user
        if obj.is_reconciled and not obj.reconciled_by:
            obj.reconciled_by = request.user
            obj.reconciled_at = timezone.now()
        super().save_model(request, obj, form, change)
    
    actions = ['mark_as_reconciled', 'send_receipts']
    
    @admin.action(description='Mark selected payments as reconciled')
    def mark_as_reconciled(self, request, queryset):
        updated = queryset.filter(is_reconciled=False).update(
            is_reconciled=True,
            reconciled_by=request.user,
            reconciled_at=timezone.now()
        )
        self.message_user(request, f'{updated} payments marked as reconciled.')
    
    @admin.action(description='Send receipts for selected payments')
    def send_receipts(self, request, queryset):
        # TODO: Implement receipt sending
        count = queryset.filter(status='completed', receipt_sent=False).count()
        self.message_user(request, f'{count} receipts queued for sending.')


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'transaction_id', 'gateway', 'amount_display', 'payer_account',
        'payer_name', 'bank_status', 'processing_status', 'callback_received_at'
    )
    list_filter = ('gateway', 'processing_status', 'bank_status', 'callback_received_at')
    search_fields = ('transaction_id', 'transaction_reference', 'payer_account', 'payer_name')
    readonly_fields = (
        'transaction_id', 'gateway', 'amount', 'currency', 'payer_account', 'payer_name',
        'bank_status', 'bank_status_description', 'bank_timestamp',
        'raw_request', 'raw_response', 'callback_url', 'callback_received_at'
    )
    date_hierarchy = 'callback_received_at'
    autocomplete_fields = ['payment']
    
    fieldsets = (
        ('Transaction Info', {
            'fields': ('transaction_id', 'gateway', 'transaction_reference', 'amount', 'currency')
        }),
        ('Payer Details', {
            'fields': ('payer_account', 'payer_name')
        }),
        ('Bank Response', {
            'fields': ('bank_status', 'bank_status_description', 'bank_timestamp')
        }),
        ('Processing', {
            'fields': ('payment', 'processing_status', 'processing_notes')
        }),
        ('Raw Data', {
            'fields': ('raw_request', 'raw_response', 'callback_url', 'callback_received_at'),
            'classes': ('collapse',)
        }),
    )
    
    def amount_display(self, obj):
        return format_html('{} {:,.0f}', obj.currency, obj.amount)
    amount_display.short_description = 'Amount'
    
    def has_add_permission(self, request):
        return False  # Bank transactions are created via API only
    
    def has_delete_permission(self, request, obj=None):
        return False  # Never delete bank transactions


@admin.register(PaymentAllocation)
class PaymentAllocationAdmin(admin.ModelAdmin):
    list_display = ('payment', 'invoice_item', 'amount')
    search_fields = ('payment__payment_reference', 'invoice_item__description')
    autocomplete_fields = ['payment', 'invoice_item']


@admin.register(PaymentReminder)
class PaymentReminderAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'reminder_type', 'created_at')
    list_filter = ('reminder_type', 'created_at')
    search_fields = ('invoice__invoice_number', 'invoice__student__admission_number')
    autocomplete_fields = ['invoice']
    date_hierarchy = 'created_at'