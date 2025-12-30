# transport/admin.py
from django.contrib import admin
from .models import TransportRoute, TransportFee


@admin.register(TransportRoute)
class TransportRouteAdmin(admin.ModelAdmin):
    list_display = ['name', 'student_count']
    list_filter = ['is_active']
    search_fields = ['name']

    def student_count(self, obj):
        return obj.students.filter(is_active=True, uses_school_transport=True).count()

    student_count.short_description = 'Students on Route'


@admin.register(TransportFee)
class TransportFeeAdmin(admin.ModelAdmin):
    list_display = ['route', 'academic_year', 'term', 'amount', 'half_amount', 'is_active']
    list_filter = ['academic_year', 'term', 'route', 'is_active']
    search_fields = ['route__name']
    list_editable = ['amount', 'half_amount', 'is_active']

    fieldsets = (
        ('Basic Information', {
            'fields': ('route', 'academic_year', 'term')
        }),
        ('Fee Amounts', {
            'fields': ('amount', 'half_amount'),
            'description': 'Set the full trip amount. Half trip amount can be set explicitly or will be calculated as half of full amount.'
        }),
        ('Status', {
            'fields': ('is_active',)
        })
    )

