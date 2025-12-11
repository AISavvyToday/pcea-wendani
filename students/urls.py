# students/urls.py
from django.urls import path
from . import views

app_name = 'students'

urlpatterns = [
    path('', views.StudentListView.as_view(), name='list'),
    path('create/', views.StudentCreateView.as_view(), name='create'),
    path('<uuid:pk>/', views.StudentDetailView.as_view(), name='detail'),  # ✅ Changed from int to uuid
    path('<uuid:pk>/edit/', views.StudentUpdateView.as_view(), name='update'),  # ✅ Changed from int to uuid
    path('promote/', views.StudentPromotionView.as_view(), name='promote'),
]