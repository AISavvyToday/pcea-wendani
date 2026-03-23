# students/urls.py
from django.urls import path
from . import views
from . import views_exports
from . import views_enhancements

app_name = 'students'

urlpatterns = [
    path('', views.StudentListView.as_view(), name='list'),
    path('my-students/', views.StudentListView.as_view(), name='my_students'),
    path('create/', views.StudentCreateView.as_view(), name='create'),
    path('<uuid:pk>/', views.StudentDetailView.as_view(), name='detail'),
    path('<uuid:pk>/detail/', views.StudentDetailView.as_view(), name='student_detail'),
    path('<uuid:pk>/edit/', views.StudentUpdateView.as_view(), name='update'),
    path('<uuid:pk>/delete/', views.StudentDeleteView.as_view(), name='delete'),
    path('promote/', views.StudentPromotionView.as_view(), name='promote'),

    path('bulk-stream-transfer/', views_enhancements.BulkStreamTransferView.as_view(), name='bulk_stream_transfer'),

    # Clubs
    path('clubs/', views_enhancements.ClubListView.as_view(), name='club_list'),
    path('clubs/create/', views_enhancements.ClubCreateView.as_view(), name='club_create'),
    path('clubs/<uuid:pk>/', views_enhancements.ClubDetailView.as_view(), name='club_detail'),
    path('clubs/<uuid:pk>/edit/', views_enhancements.ClubUpdateView.as_view(), name='club_update'),
    path('clubs/<uuid:pk>/members/add/', views_enhancements.ClubMembershipUpdateView.as_view(), name='club_members_add'),
    path('clubs/<uuid:pk>/members/<uuid:membership_pk>/remove/', views_enhancements.ClubMembershipRemoveView.as_view(), name='club_member_remove'),

    # Export URLs
    path('export/xlsx/', views_exports.StudentListExcelView.as_view(), name='export_excel'),
    path('export/pdf/', views_exports.StudentListPDFView.as_view(), name='export_pdf'),
    
    # Import URLs
    path('import/', views.StudentImportView.as_view(), name='import'),
    path('import/template/', views.StudentTemplateDownloadView.as_view(), name='import_template'),

# Parent/Guardian URLs
    path('parents/', views.ParentListView.as_view(), name='parent_list'),
    path('parents/create/', views.ParentCreateView.as_view(), name='parent_create'),
    path('parents/<uuid:pk>/', views.ParentDetailView.as_view(), name='parent_detail'),
    path('parents/<uuid:pk>/edit/', views.ParentUpdateView.as_view(), name='parent_update'),
    path('parents/<uuid:pk>/delete/', views.ParentDeleteView.as_view(), name='parent_delete'),

    # API endpoints
    path('api/parents/<uuid:pk>/children/', views.ParentChildrenAPIView.as_view(), name='api_parent_children'),
]