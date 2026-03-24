from django.contrib import admin

from .models import ReportRequest


@admin.register(ReportRequest)
class ReportRequestAdmin(admin.ModelAdmin):
    list_display = ('report_type', 'organization', 'academic_year', 'term', 'created_by', 'created_at', 'note')
    list_filter = ('organization', 'report_type', 'academic_year', 'term', 'created_at')
    search_fields = ('note', 'created_by__email', 'organization__name')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('organization', 'created_by', 'academic_year')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
