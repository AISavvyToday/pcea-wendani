# students/admin.py

from decimal import Decimal
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Club, ClubMembership, Parent, Student, StudentParent, StudentDocument,
    DisciplineRecord, MedicalRecord
)


class StudentParentInline(admin.TabularInline):
    model = StudentParent
    extra = 1
    autocomplete_fields = ['parent']


class ClubMembershipInline(admin.TabularInline):
    model = ClubMembership
    extra = 0
    autocomplete_fields = ['club']


class StudentDocumentInline(admin.TabularInline):
    model = StudentDocument
    extra = 0
    readonly_fields = ('uploaded_by', 'created_at')


class DisciplineRecordInline(admin.TabularInline):
    model = DisciplineRecord
    extra = 0
    readonly_fields = ('reported_by', 'created_at')
    fields = ('incident_type', 'incident_date', 'description', 'action_taken', 'parent_notified')


class MedicalRecordInline(admin.TabularInline):
    model = MedicalRecord
    extra = 0
    readonly_fields = ('recorded_by', 'created_at')
    fields = ('record_type', 'record_date', 'description', 'treatment')


@admin.register(Parent)
class ParentAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone_primary', 'email', 'relationship', 'children_count', 'is_active')
    list_filter = ('relationship', 'is_active', 'gender')
    search_fields = ('first_name', 'last_name', 'phone_primary', 'phone_secondary', 'email', 'id_number')
    ordering = ('last_name', 'first_name')
    
    fieldsets = (
        ('Personal Information', {
            'fields': ('first_name', 'last_name', 'gender', 'id_number', 'relationship')
        }),
        ('Contact Information', {
            'fields': ('phone_primary', 'phone_secondary', 'email', 'address', 'town')
        }),
        ('Employment', {
            'fields': ('occupation', 'employer'),
            'classes': ('collapse',)
        }),
        ('Portal Access', {
            'fields': ('user',),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )
    
    def children_count(self, obj):
        return obj.children.count()
    children_count.short_description = 'Children'


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ['admission_number', 'full_name', 'current_class', 'uses_school_transport', 'transport_route']
    list_filter = ['uses_school_transport', 'transport_route', 'current_class__grade_level', 'current_class__stream']
    search_fields = ('admission_number', 'first_name', 'middle_name', 'last_name', 'birth_certificate_number')
    ordering = ('admission_number',)
    autocomplete_fields = ['current_class', 'transport_route']
    date_hierarchy = 'admission_date'
    readonly_fields = ('age',)
    
    fieldsets = (
        ('Admission', {
            'fields': ('admission_number', 'admission_date')
        }),
        ('Personal Information', {
            'fields': ('first_name', 'middle_name', 'last_name', 'gender', 'date_of_birth', 'age', 'birth_certificate_number', 'photo')
        }),
        ('Academic', {
            'fields': ('current_class', 'previous_school', 'previous_class')
        }),
        ('Medical', {
            'fields': ('blood_group', 'medical_conditions', 'has_special_needs', 'special_needs_details'),
            'classes': ('collapse',)
        }),
        ('Emergency Contact', {
            'fields': ('emergency_contact_name', 'emergency_contact_phone'),
            'classes': ('collapse',)
        }),
        ('Transport Information', {
            'fields': ('uses_school_transport', 'transport_route')
        }),
        ('Portal Access', {
            'fields': ('user',),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )
    
    inlines = [StudentParentInline, ClubMembershipInline, StudentDocumentInline, DisciplineRecordInline, MedicalRecordInline]
    
    def primary_parent_display(self, obj):
        parent = obj.primary_parent
        if parent:
            return f"{parent.full_name} ({parent.phone_primary})"
        return "-"
    primary_parent_display.short_description = 'Primary Parent'
    
    def balance_display(self, obj):
        # Get latest invoice balance
        latest_invoice = obj.invoices.order_by('-term__academic_year__year', '-term__term').first()
        if latest_invoice and latest_invoice.balance is not None:
            try:
                balance = Decimal(str(latest_invoice.balance))
                formatted = f"{abs(balance):,.0f}"
                if balance > 0:
                    return format_html('<span style="color: red;">KES {}</span>', formatted)
                elif balance < 0:
                    return format_html('<span style="color: green;">KES {} CR</span>', formatted)
                return format_html('<span style="color: green;">Paid</span>')
            except (ValueError, TypeError):
                return "-"
        return "-"
    balance_display.short_description = 'Balance'


@admin.register(StudentParent)
class StudentParentAdmin(admin.ModelAdmin):
    list_display = ('student', 'parent', 'relationship', 'is_primary', 'is_emergency_contact', 'receives_notifications')
    list_filter = ('relationship', 'is_primary', 'is_emergency_contact')
    search_fields = ('student__admission_number', 'student__first_name', 'parent__first_name', 'parent__phone_primary')
    autocomplete_fields = ['student', 'parent']


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'patron', 'member_count', 'is_active')
    list_filter = ('organization', 'is_active')
    search_fields = ('name', 'description', 'patron__user__first_name', 'patron__user__last_name')
    autocomplete_fields = ['patron']

    def member_count(self, obj):
        return obj.students.count()


@admin.register(ClubMembership)
class ClubMembershipAdmin(admin.ModelAdmin):
    list_display = ('student', 'club', 'joined_on', 'is_active')
    list_filter = ('club', 'joined_on', 'is_active')
    search_fields = ('student__admission_number', 'student__first_name', 'club__name')
    autocomplete_fields = ['student', 'club']


@admin.register(StudentDocument)
class StudentDocumentAdmin(admin.ModelAdmin):
    list_display = ('student', 'document_type', 'title', 'uploaded_by', 'created_at')
    list_filter = ('document_type', 'created_at')
    search_fields = ('student__admission_number', 'student__first_name', 'title')
    autocomplete_fields = ['student']
    readonly_fields = ('uploaded_by', 'created_at', 'updated_at')


@admin.register(DisciplineRecord)
class DisciplineRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'incident_type', 'incident_date', 'parent_notified', 'follow_up_required')
    list_filter = ('incident_type', 'parent_notified', 'follow_up_required', 'incident_date')
    search_fields = ('student__admission_number', 'student__first_name', 'description')
    autocomplete_fields = ['student']
    date_hierarchy = 'incident_date'


@admin.register(MedicalRecord)
class MedicalRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'record_type', 'record_date', 'doctor_name', 'follow_up_date')
    list_filter = ('record_type', 'record_date')
    search_fields = ('student__admission_number', 'student__first_name', 'description')
    autocomplete_fields = ['student']
    date_hierarchy = 'record_date'
