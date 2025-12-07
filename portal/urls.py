# portal/urls.py
"""
Portal URL configuration.
Handles dashboards, sections, and authentication routes.
"""

from django.urls import path
from django.contrib.auth import views as auth_views

from . import views

app_name = 'portal'

urlpatterns = [
    # =========================================================================
    # HOME & DASHBOARDS
    # =========================================================================
    path('', views.home, name='home'),
    path('dashboard/admin/', views.dashboard_admin, name='dashboard_admin'),
    path('dashboard/bursar/', views.dashboard_bursar, name='dashboard_bursar'),
    path('dashboard/teacher/', views.dashboard_teacher, name='dashboard_teacher'),
    path('dashboard/parent/', views.dashboard_parent, name='dashboard_parent'),

    # =========================================================================
    # SECTIONS (placeholder pages for now)
    # =========================================================================
    path('sections/academics/', views.academics_overview, name='academics_overview'),
    path('sections/finance/', views.finance_overview, name='finance_overview'),
    path('sections/communications/', views.communications_overview, name='communications_overview'),
    path('sections/resources/', views.resources_overview, name='resources_overview'),
    path('sections/settings/', views.settings_overview, name='settings_overview'),
    path('pages/blank/', views.blank_page, name='blank_page'),

    # =========================================================================
    # AUTHENTICATION
    # =========================================================================
    path('auth/login/', views.login_view, name='login'),
    path('auth/logout/', views.logout_view, name='logout'),
    path('auth/register/', views.register_view, name='register'),
    path('auth/route/', views.role_redirect, name='role_redirect'),

    # =========================================================================
    # PASSWORD RESET (using Django's built-in views with custom templates)
    # =========================================================================
    path('auth/password-reset/',
         auth_views.PasswordResetView.as_view(
             template_name='auth/password_reset.html',
             email_template_name='auth/password_reset_email.html',
             subject_template_name='auth/password_reset_subject.txt',
             success_url='/auth/password-reset/done/'
         ),
         name='password_reset'),

    path('auth/password-reset/done/',
         auth_views.PasswordResetDoneView.as_view(
             template_name='auth/password_reset_done.html'
         ),
         name='password_reset_done'),

    path('auth/password-reset-confirm/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(
             template_name='auth/password_reset_confirm.html',
             success_url='/auth/password-reset-complete/'
         ),
         name='password_reset_confirm'),

    path('auth/password-reset-complete/',
         auth_views.PasswordResetCompleteView.as_view(
             template_name='auth/password_reset_complete.html'
         ),
         name='password_reset_complete'),
]