# other_income/urls.py
from django.urls import path
from . import views
from . import views_reports

app_name = 'other_income'

urlpatterns = [
    path('reports/', views_reports.OtherIncomeReportView.as_view(), name='report'),
    path('reports/export/xlsx/', views_reports.OtherIncomeReportExcelView.as_view(), name='report_export_excel'),
    path('reports/export/pdf/', views_reports.OtherIncomeReportPDFView.as_view(), name='report_export_pdf'),
    path('', views.OtherIncomeListView.as_view(), name='invoice_list'),
    path('reports/staging/', views.OtherIncomeReportStagingView.as_view(), name='report_staging'),
    path('create/', views.OtherIncomeCreateView.as_view(), name='invoice_create'),
    path('<uuid:pk>/', views.OtherIncomeDetailView.as_view(), name='invoice_detail'),
    path('<uuid:pk>/delete/', views.OtherIncomeInvoiceDeleteView.as_view(), name='invoice_delete'),
    path('<uuid:pk>/edit/', views.OtherIncomeEditView.as_view(), name='invoice_edit'),
    path('<uuid:pk>/print/', views.OtherIncomeInvoicePrintView.as_view(), name='invoice_print'),
    path('<uuid:pk>/payments/record/', views.OtherIncomeRecordPaymentView.as_view(), name='invoice_record_payment'),
    path('payment/<uuid:pk>/receipt/', views.OtherIncomePaymentReceiptView.as_view(), name='payment_receipt'),
]
