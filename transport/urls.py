# transport/urls.py
from django.urls import path
from . import views

app_name = 'transport'

urlpatterns = [
    path('', views.TransportRouteListView.as_view(), name='route_list'),
    
    # Route CRUD
    path('routes/create/', views.TransportRouteCreateView.as_view(), name='route_create'),
    path('routes/<uuid:pk>/update/', views.TransportRouteUpdateView.as_view(), name='route_update'),
    path('routes/<uuid:pk>/delete/', views.TransportRouteDeleteView.as_view(), name='route_delete'),
    path('routes/<uuid:pk>/detail/', views.TransportRouteDetailView.as_view(), name='route_detail'),
    
    # Fee CRUD
    path('fees/create/', views.TransportFeeCreateView.as_view(), name='fee_create'),
    path('fees/<uuid:pk>/update/', views.TransportFeeUpdateView.as_view(), name='fee_update'),
    path('fees/<uuid:pk>/delete/', views.TransportFeeDeleteView.as_view(), name='fee_delete'),
    path('fees/<uuid:pk>/detail/', views.TransportFeeDetailView.as_view(), name='fee_detail'),
]

