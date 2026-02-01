# payroll/urls.py

from django.urls import path
from . import views

app_name = 'payroll'

urlpatterns = [
    # Salary Structure
    path('salary-structures/', views.SalaryStructureListView.as_view(), name='salary_structure_list'),
    path('salary-structures/create/', views.SalaryStructureCreateView.as_view(), name='salary_structure_create'),
    path('salary-structures/<uuid:pk>/edit/', views.SalaryStructureUpdateView.as_view(), name='salary_structure_edit'),
    
    # Allowances
    path('allowances/', views.AllowanceListView.as_view(), name='allowance_list'),
    path('allowances/create/', views.AllowanceCreateView.as_view(), name='allowance_create'),
    path('allowances/<uuid:pk>/edit/', views.AllowanceUpdateView.as_view(), name='allowance_edit'),
    
    # Deductions
    path('deductions/', views.DeductionListView.as_view(), name='deduction_list'),
    path('deductions/create/', views.DeductionCreateView.as_view(), name='deduction_create'),
    path('deductions/<uuid:pk>/edit/', views.DeductionUpdateView.as_view(), name='deduction_edit'),
    
    # Staff Salary
    path('staff-salaries/', views.StaffSalaryListView.as_view(), name='staff_salary_list'),
    path('staff-salaries/create/', views.StaffSalaryCreateView.as_view(), name='staff_salary_create'),
    path('staff-salaries/<uuid:pk>/edit/', views.StaffSalaryUpdateView.as_view(), name='staff_salary_edit'),
    
    # Payroll Periods
    path('periods/', views.PayrollPeriodListView.as_view(), name='payroll_period_list'),
    path('periods/create/', views.PayrollPeriodCreateView.as_view(), name='payroll_period_create'),
    
    # Payroll Generation
    path('generate/', views.PayrollGenerateView.as_view(), name='payroll_generate'),
    path('list/', views.PayrollListView.as_view(), name='payroll_list'),
    path('list/<uuid:period_id>/', views.PayrollListView.as_view(), name='payroll_list_period'),
    path('detail/<uuid:pk>/', views.PayrollDetailView.as_view(), name='payroll_detail'),
    
    # Payslips
    path('payslips/', views.PayslipListView.as_view(), name='payslip_list'),
    path('payslips/generate/<uuid:period_id>/', views.PayslipGenerateView.as_view(), name='payslip_generate'),
    path('payslips/<uuid:pk>/', views.PayslipDetailView.as_view(), name='payslip_detail'),
    
    # Reports
    path('reports/', views.PayrollReportView.as_view(), name='payroll_report'),
]

