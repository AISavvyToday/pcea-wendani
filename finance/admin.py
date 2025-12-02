# finance/admin.py

from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum
from .models import (
    FeeStructure, FeeItem, Discount, StudentDiscount,
    Invoice, InvoiceItem
)


class FeeItemInline(admin.TabularInline):
    model = FeeItem
    extra = 1


@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ('name', 'academic_year', 'term', 'is_boarding', 'total_amount_display', 'is_active')
    list_filter = ('academic_year', 'term', 'is_boarding', 'is_active')
    search_fields = ('name',)
    ordering = ('-academic_year__year', 'term')
    inlines = [FeeItemInline]
    
    def total_amount_display(self, obj):
        return format_html('KES {:,.0f}', obj.total_amount)
    total_amount_display.short_description = 'Total Amount'


@admin.register(FeeItem)
class FeeItemAdmin(admin.ModelAdmin):
    list_display = ('fee_structure', 'category', 'description', 'amount', 'is_optional')
    list_filter = ('fee_structure__academic_year', 'category', 'is_optional')
    search_fields = ('description', 'fee_structure__name')


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = ('name', 'discount_type', 'value_display', 'academic_year', 'requires_approval', 'is_active')
    list_filter = ('discount_type', 'academic_year', 'requires_approval', 'is_active')
    search_fields = ('name',)
    
    def value_display(self, obj):
        if obj.discount_type == 'percentage':
            return f"{obj.value}%"
        return f"KES {obj.value:,.0f}"
    value_display.short_description = 'Value'


@admin.register(StudentDiscount)
class StudentDiscountAdmin(admin.ModelAdmin):
    list_display = ('student', 'discount', 'custom_value', 'start_date', 'end_date', 'is_approved', 'approved_by')
    list_filter = ('discount', 'is_approved', 'start_date')
    search_fields = ('student__admission_number', 'student__first_name', 'student__last_name')
    autocomplete_fields = ['student', 'discount', 'approved_by']
    readonly_fields = ('approved_at',)
    
    def save_model(self, request, obj, form, change):
        if obj.is_approved and not obj.approved_by:
            obj.approved_by = request.user
            from django.utils import timezone
            obj.approved_at = timezone.now()
        super().save_model(request, obj, form, change)


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0
    readonly_fields = ('net_amount',)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        'invoice_number', 'student', 'term', 'subtotal_display',
        'discount_display', 'total_display', 'paid_display', 'balance_display', 'status'
    )
    list_filter = ('status', 'term__academic_year', 'term', 'issue_date')
    search_fields = ('invoice_number', 'student__admission_number', 'student__first_name', 'student__last_name')
    autocomplete_fields = ['student', 'term']
    readonly_fields = ('invoice_number', 'balance', 'generated_by', 'created_at', 'updated_at')
    date_hierarchy = 'issue_date'
    inlines = [InvoiceItemInline]
    
    fieldsets = (
        ('Invoice Info', {
            'fields': ('invoice_number', 'student', 'term', 'status')
        }),
        ('Amounts', {
            'fields': ('subtotal', 'discount_amount', 'total_amount', 'balance_bf', 'prepayment', 'amount_paid', 'balance')
        }),
        ('Dates', {
            'fields': ('issue_date', 'due_date')
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        ('Tracking', {
            'fields': ('generated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def subtotal_display(self, obj):
        return format_html('KES {:,.0f}', obj.subtotal)
    subtotal_display.short_description = 'Subtotal'
    
    def discount_display(self, obj):
        if obj.discount_amount > 0:
            return format_html('<span style="color: green;">-KES {:,.0f}</span>', obj.discount_amount)
        return '-'
    discount_display.short_description = 'Discount'
    
    def total_display(self, obj):
        return format_html('KES {:,.0f}', obj.total_amount)
    total_display.short_description = 'Total'
    
    def paid_display(self, obj):
        return format_html('KES {:,.0f}', obj.amount_paid)
    paid_display.short_description = 'Paid'
    
    def balance_display(self, obj):
        if obj.balance > 0:
            return format_html('<span style="color: red; font-weight: bold;">KES {:,.0f}</span>', obj.balance)
        elif obj.balance < 0:
            return format_html('<span style="color: green;">KES {:,.0f} CR</span>', abs(obj.balance))
        return format_html('<span style="color: green;">✓ Paid</span>')
    balance_display.short_description = 'Balance'
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.generated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'category', 'description', 'amount', 'discount_applied', 'net_amount')
    list_filter = ('category', 'invoice__term')
    search_fields = ('invoice__invoice_number', 'description')
    autocomplete_fields = ['invoice']