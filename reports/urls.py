# reports/urls.py
from django.urls import path
from . import views
from . import views_exports

app_name = 'reports'

urlpatterns = [
    path('invoice-report/', views.InvoiceReportView.as_view(), name='invoice_report'),
    path('invoice-report/export/xlsx/', views_exports.InvoiceReportExcelView.as_view(), name='invoice_report_export_excel'),
    path('invoice-report/export/pdf/', views_exports.InvoiceReportPDFView.as_view(), name='invoice_report_export_pdf'),

    path('fees-collection/', views.FeesCollectionReportView.as_view(), name='fees_collection_report'),
    path('fees-collection/export/xlsx/', views_exports.FeesCollectionExcelView.as_view(), name='fees_collection_export_excel'),
    path('fees-collection/export/pdf/', views_exports.FeesCollectionPDFView.as_view(), name='fees_collection_export_pdf'),

    path('outstanding-balances/', views.OutstandingBalancesReportView.as_view(), name='outstanding_report'),
    path('outstanding-balances/export/xlsx/', views_exports.OutstandingBalancesExcelView.as_view(), name='outstanding_report_export_excel'),
    path('outstanding-balances/export/pdf/', views_exports.OutstandingBalancesPDFView.as_view(), name='outstanding_report_export_pdf'),

    path('transport-report/', views.TransportReportView.as_view(), name='transport_report'),
    path('transport-report/export/xlsx/', views_exports.TransportReportExcelView.as_view(), name='transport_report_export_excel'),
    path('transport-report/export/pdf/', views_exports.TransportReportPDFView.as_view(), name='transport_report_export_pdf'),

    # Invoice List Exports (for invoice list page)
    path('invoice-list/export/xlsx/', views_exports.InvoiceListExcelView.as_view(), name='invoice_xlsx'),
    path('invoice-list/export/pdf/', views_exports.InvoiceListPDFView.as_view(), name='invoice_pdf'),
]