# students/urls.py
from django.urls import path
from . import views

app_name = 'students'

urlpatterns = [
    path('', views.StudentListView.as_view(), name='list'),
    path('create/', views.StudentCreateView.as_view(), name='create'),
    path('<uuid:pk>/', views.StudentDetailView.as_view(), name='detail'),  # ✅ Changed from int to uuid
    path('<uuid:pk>/edit/', views.StudentUpdateView.as_view(), name='update'),  # ✅ Changed from int to uuid
    path('<uuid:pk>/delete/', views.StudentDeleteView.as_view(), name='delete'),
    path('promote/', views.StudentPromotionView.as_view(), name='promote'),

# Parent/Guardian URLs
    path('parents/', views.ParentListView.as_view(), name='parent_list'),
    path('parents/create/', views.ParentCreateView.as_view(), name='parent_create'),
    path('parents/<uuid:pk>/', views.ParentDetailView.as_view(), name='parent_detail'),
    path('parents/<uuid:pk>/edit/', views.ParentUpdateView.as_view(), name='parent_update'),
    path('parents/<uuid:pk>/delete/', views.ParentDeleteView.as_view(), name='parent_delete'),


]