# academics/admin.py

from django.contrib import admin
from django.utils.html import format_html
from .models import (
    AcademicYear, Term, Department, Staff, Class, Subject,
    ClassSubject, Exam, Grade, Attendance, Timetable, TransportRoute
)


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('year', 'start_date', 'end_date', 'is_current', 'terms_count')
    list_filter = ('is_current',)
    search_fields = ('year',)  # ADD THIS LINE
    ordering = ('-year',)

    def terms_count(self, obj):
        return obj.terms.count()
    terms_count.short_description = 'Terms'





class TermInline(admin.TabularInline):
    model = Term
    extra = 0


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'start_date', 'end_date', 'fee_deadline', 'is_current')
    list_filter = ('academic_year', 'term', 'is_current')
    search_fields = ('academic_year__year', 'term')  # ADD THIS LINE
    ordering = ('-academic_year__year', 'term')


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'head', 'staff_count', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'code')
    autocomplete_fields = ['head']
    
    def staff_count(self, obj):
        return obj.staff_members.count()
    staff_count.short_description = 'Staff'


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ('staff_number', 'user', 'staff_type', 'department', 'phone_number', 'status')
    list_filter = ('staff_type', 'department', 'status', 'employment_type')
    search_fields = ('staff_number', 'user__first_name', 'user__last_name', 'user__email', 'id_number', 'tsc_number')
    autocomplete_fields = ['user', 'department']
    ordering = ('staff_number',)
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('user', 'staff_number', 'staff_type', 'department')
        }),
        ('Personal Details', {
            'fields': ('id_number', 'tsc_number', 'date_of_birth', 'gender', 'phone_number', 'address')
        }),
        ('Employment', {
            'fields': ('date_joined', 'employment_type', 'status', 'qualifications', 'specialization')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )


class ClassSubjectInline(admin.TabularInline):
    model = ClassSubject
    extra = 1
    autocomplete_fields = ['subject', 'teacher']


@admin.register(Class)
class ClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'grade_level', 'stream', 'academic_year', 'class_teacher', 'student_count', 'capacity', 'room')
    list_filter = ('academic_year', 'grade_level')
    search_fields = ('name', 'stream', 'room')
    autocomplete_fields = ['class_teacher', 'academic_year']
    ordering = ('academic_year', 'grade_level', 'stream')
    inlines = [ClassSubjectInline]
    
    def student_count(self, obj):
        count = obj.student_count
        capacity = obj.capacity
        if count >= capacity:
            return format_html('<span style="color: red;">{}/{}</span>', count, capacity)
        return f"{count}/{capacity}"
    student_count.short_description = 'Students'


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'subject_type', 'department', 'max_marks', 'pass_marks', 'is_active')
    list_filter = ('subject_type', 'department', 'is_active')
    search_fields = ('code', 'name')
    ordering = ('code',)


@admin.register(ClassSubject)
class ClassSubjectAdmin(admin.ModelAdmin):
    list_display = ('class_obj', 'subject', 'teacher', 'periods_per_week')
    list_filter = ('class_obj__academic_year', 'class_obj__grade_level', 'subject')
    search_fields = ('class_obj__name', 'subject__name', 'teacher__user__first_name')
    autocomplete_fields = ['class_obj', 'subject', 'teacher']


class GradeInline(admin.TabularInline):
    model = Grade
    extra = 0
    readonly_fields = ('grade_letter', 'points', 'entered_by', 'entered_at')
    autocomplete_fields = ['student', 'subject']


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ('name', 'term', 'exam_type', 'start_date', 'end_date', 'weight_percentage', 'is_published')
    list_filter = ('term__academic_year', 'term', 'exam_type', 'is_published')
    search_fields = ('name',)
    filter_horizontal = ('classes',)
    date_hierarchy = 'start_date'
    
    fieldsets = (
        ('Exam Details', {
            'fields': ('name', 'term', 'exam_type', 'weight_percentage')
        }),
        ('Schedule', {
            'fields': ('start_date', 'end_date')
        }),
        ('Classes', {
            'fields': ('classes',)
        }),
        ('Publication', {
            'fields': ('is_published',)
        }),
    )


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ('student', 'exam', 'subject', 'marks', 'grade_letter', 'points', 'entered_by')
    list_filter = ('exam__term', 'exam', 'subject', 'grade_letter')
    search_fields = ('student__admission_number', 'student__first_name', 'student__last_name')
    autocomplete_fields = ['student', 'exam', 'subject']
    readonly_fields = ('grade_letter', 'points', 'entered_by', 'entered_at', 'modified_by')
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.entered_by = request.user
        else:
            obj.modified_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'date', 'class_obj', 'status', 'arrival_time', 'recorded_by')
    list_filter = ('status', 'date', 'class_obj')
    search_fields = ('student__admission_number', 'student__first_name', 'student__last_name')
    autocomplete_fields = ['student', 'class_obj']
    date_hierarchy = 'date'
    readonly_fields = ('recorded_by',)
    
    def save_model(self, request, obj, form, change):
        if not obj.recorded_by:
            obj.recorded_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Timetable)
class TimetableAdmin(admin.ModelAdmin):
    list_display = ('class_obj', 'day_of_week', 'start_time', 'end_time', 'subject', 'teacher', 'room')
    list_filter = ('term', 'class_obj', 'day_of_week', 'subject')
    search_fields = ('class_obj__name', 'subject__name', 'teacher__user__first_name')
    autocomplete_fields = ['class_obj', 'subject', 'teacher', 'term']
    ordering = ('class_obj', 'day_of_week', 'start_time')


@admin.register(TransportRoute)
class TransportRouteAdmin(admin.ModelAdmin):
    list_display = ('name', 'driver_name', 'driver_phone', 'vehicle_registration', 'term_fee', 'students_count')
    search_fields = ('name', 'driver_name', 'vehicle_registration')
    
    def students_count(self, obj):
        return obj.students.count()
    students_count.short_description = 'Students'