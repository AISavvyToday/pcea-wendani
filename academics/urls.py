# academics/urls.py

from django.urls import path
from . import views

app_name = 'academics'

urlpatterns = [
    # Academic Year
    path('academic-years/', views.AcademicYearListView.as_view(), name='academic_year_list'),
    path('academic-years/create/', views.AcademicYearCreateView.as_view(), name='academic_year_create'),
    path('academic-years/<uuid:pk>/edit/', views.AcademicYearUpdateView.as_view(), name='academic_year_edit'),

    # Term
    path('terms/', views.TermListView.as_view(), name='term_list'),
    path('terms/create/', views.TermCreateView.as_view(), name='term_create'),
    path('terms/<uuid:pk>/edit/', views.TermUpdateView.as_view(), name='term_edit'),

    # Subject
    path('subjects/', views.SubjectListView.as_view(), name='subject_list'),
    path('subjects/create/', views.SubjectCreateView.as_view(), name='subject_create'),
    path('subjects/<uuid:pk>/edit/', views.SubjectUpdateView.as_view(), name='subject_edit'),

    # Class
    path('classes/', views.ClassListView.as_view(), name='class_list'),
    path('classes/create/', views.ClassCreateView.as_view(), name='class_create'),
    path('classes/<uuid:pk>/edit/', views.ClassUpdateView.as_view(), name='class_edit'),

    # ClassSubject
    path('class-subjects/', views.ClassSubjectListView.as_view(), name='class_subject_list'),
    path('class-subjects/create/', views.ClassSubjectCreateView.as_view(), name='class_subject_create'),
    path('class-subjects/<uuid:pk>/edit/', views.ClassSubjectUpdateView.as_view(), name='class_subject_edit'),

    # Exam
    path('exams/', views.ExamListView.as_view(), name='exam_list'),
    path('exams/create/', views.ExamCreateView.as_view(), name='exam_create'),
    path('exams/<uuid:pk>/edit/', views.ExamUpdateView.as_view(), name='exam_edit'),

    # Attendance
    path('attendance/<uuid:class_pk>/<str:date>/', views.AttendanceCreateView.as_view(), name='attendance'),
    path('attendance/<uuid:class_pk>/', views.AttendanceCreateView.as_view(), name='attendance_today'),
    path('attendance/', views.AttendanceListView.as_view(), name='attendance_list'),

    # Grade Entry
    path('grades/<uuid:exam_pk>/<uuid:class_pk>/<uuid:subject_pk>/', views.GradeEntryView.as_view(), name='grade_entry'),

    # Reports
    path('reports/academic/', views.AcademicReportView.as_view(), name='academic_report'),
]