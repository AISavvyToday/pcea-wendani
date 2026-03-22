# students/urls.py
from django.urls import path
from . import views
from . import views_exports

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