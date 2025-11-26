# portal/urls.py
from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/admin/", views.dashboard_admin, name="dashboard_admin"),
    path("dashboard/bursar/", views.dashboard_bursar, name="dashboard_bursar"),
    path("dashboard/teacher/", views.dashboard_teacher, name="dashboard_teacher"),
    path("dashboard/parent/", views.dashboard_parent, name="dashboard_parent"),
    path("sections/academics/", views.academics_overview, name="academics_overview"),
    path("sections/finance/", views.finance_overview, name="finance_overview"),
    path("sections/communications/", views.communications_overview, name="communications_overview"),
    path("sections/resources/", views.resources_overview, name="resources_overview"),
    path("sections/settings/", views.settings_overview, name="settings_overview"),
    path("pages/blank/", views.blank_page, name="blank_page"),
    path("auth/login/", views.login_page, name="login"),
    path("auth/register/", views.register_page, name="register"),
]