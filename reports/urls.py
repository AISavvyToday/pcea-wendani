# reports/urls.py
from django.urls import path
from . import views
from . import views_exports

app_name = 'reports'

urlpatterns = [
    # Invoice Summary Report (category-based summary)
    path('invoice-summary-report/', views.InvoiceReportView.as_view(), name='invoice_summary_report'),
    path('invoice-summary-report/export/xlsx/', views_exports.InvoiceSummaryReportExcelView.as_view(), name='invoice_summary_report_export_excel'),
    path('invoice-summary-report/export/pdf/', views_exports.InvoiceSummaryReportPDFView.as_view(), name='invoice_summary_report_export_pdf'),
    
    # Invoice Detailed Report (student-level detail)
    path('invoice-detailed-report/', views.InvoiceDetailedReportView.as_view(), name='invoice_detailed_report'),
    path('invoice-detailed-report/export/xlsx/', views_exports.InvoiceDetailedReportExcelView.as_view(), name='invoice_detailed_report_export_excel'),
    path('invoice-detailed-report/export/pdf/', views_exports.InvoiceDetailedReportPDFView.as_view(), name='invoice_detailed_report_export_pdf'),

    path('fees-collection/', views.FeesCollectionReportView.as_view(), name='fees_collection_report'),
    path('fees-collection/export/xlsx/', views_exports.FeesCollectionExcelView.as_view(), name='fees_collection_export_excel'),
    path('fees-collection/export/pdf/', views_exports.FeesCollectionPDFView.as_view(), name='fees_collection_export_pdf'),

    path('outstanding-balances/', views.OutstandingBalancesReportView.as_view(), name='outstanding_report'),
    path('outstanding-balances/export/xlsx/', views_exports.OutstandingBalancesExcelView.as_view(), name='outstanding_report_export_excel'),
    path('outstanding-balances/export/pdf/', views_exports.OutstandingBalancesPDFView.as_view(), name='outstanding_report_export_pdf'),

    path('transport-report/', views.TransportReportView.as_view(), name='transport_report'),
    path('transport-report/export/xlsx/', views_exports.TransportReportExcelView.as_view(), name='transport_report_export_excel'),
    path('transport-report/export/pdf/', views_exports.TransportReportPDFView.as_view(), name='transport_report_export_pdf'),

    path('other-items/', views.OtherItemsReportView.as_view(), name='other_items_report'),
    path('other-items/export/xlsx/', views_exports.OtherItemsReportExcelView.as_view(), name='other_items_report_export_excel'),
    path('other-items/export/pdf/', views_exports.OtherItemsReportPDFView.as_view(), name='other_items_report_export_pdf'),

    # Invoice List Exports (for invoice list page)
    path('invoice-list/export/xlsx/', views_exports.InvoiceListExcelView.as_view(), name='invoice_xlsx'),
    path('invoice-list/export/pdf/', views_exports.InvoiceListPDFView.as_view(), name='invoice_pdf'),

    # Transferred Students Report
    path('transferred-students/', views.TransferredStudentsReportView.as_view(), name='transferred_students_report'),
    path('transferred-students/export/xlsx/', views_exports.TransferredStudentsExcelView.as_view(), name='transferred_students_export_excel'),
    path('transferred-students/export/pdf/', views_exports.TransferredStudentsPDFView.as_view(), name='transferred_students_export_pdf'),

    # Graduated Students Report
    path('graduated-students/', views.GraduatedStudentsReportView.as_view(), name='graduated_students_report'),

    # Admitted Students Report
    path('admitted-students/', views.AdmittedStudentsReportView.as_view(), name='admitted_students_report'),
    path('admitted-students/export/xlsx/', views_exports.AdmittedStudentsExcelView.as_view(), name='admitted_students_export_excel'),
    path('admitted-students/export/pdf/', views_exports.AdmittedStudentsPDFView.as_view(), name='admitted_students_export_pdf'),
]