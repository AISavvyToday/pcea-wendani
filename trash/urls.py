from django.urls import path

from . import views

app_name = 'trash'

urlpatterns = [
    path('', views.TrashListView.as_view(), name='list'),
    path('<str:entity>/<uuid:pk>/restore/', views.TrashRestoreView.as_view(), name='restore'),
    path('<str:entity>/<uuid:pk>/purge/', views.TrashPurgeView.as_view(), name='purge'),
app_name = "trash"

urlpatterns = [
    path("", views.TrashDashboardView.as_view(), name="dashboard"),
    path("restore/<str:entity_type>/<uuid:pk>/", views.TrashRestoreView.as_view(), name="restore"),
    path("purge/<str:entity_type>/<uuid:pk>/", views.TrashPurgeView.as_view(), name="purge"),
]
