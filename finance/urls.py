# finance/urls.py
"""
Finance module URL configuration.
Handles fee structures, invoices, payments, and financial reports.
"""

from django.urls import path
from . import views

app_name = 'finance'

urlpatterns = [
    # Dashboard
    path('', views.FinanceDashboardView.as_view(), name='dashboard'),

    # Fee Structures
    path('fee-structures/', views.FeeStructureListView.as_view(), name='fee_structure_list'),
    path('fee-structures/create/', views.FeeStructureCreateView.as_view(), name='fee_structure_create'),
    path('fee-structures/<uuid:pk>/', views.FeeStructureDetailView.as_view(), name='fee_structure_detail'),
    path('fee-structures/<uuid:pk>/edit/', views.FeeStructureUpdateView.as_view(), name='fee_structure_update'),
    path('fee-structures/<uuid:pk>/delete/', views.FeeStructureDeleteView.as_view(), name='fee_structure_delete'),

    # Discounts
    path('discounts/', views.DiscountListView.as_view(), name='discount_list'),
    path('discounts/create/', views.DiscountCreateView.as_view(), name='discount_create'),
    path('discounts/<uuid:pk>/edit/', views.DiscountUpdateView.as_view(), name='discount_update'),
    path('discounts/<uuid:pk>/delete/', views.DiscountDeleteView.as_view(), name='discount_delete'),

    # Student Discounts
    path('student-discounts/', views.StudentDiscountListView.as_view(), name='student_discount_list'),
    path('student-discounts/assign/', views.StudentDiscountCreateView.as_view(), name='student_discount_create'),
    path('student-discounts/<uuid:pk>/approve/', views.StudentDiscountApproveView.as_view(),
         name='student_discount_approve'),

    # Invoices
    path('invoices/', views.InvoiceListView.as_view(), name='invoice_list'),
    path('invoices/generate/', views.InvoiceGenerateView.as_view(), name='invoice_generate'),
    path('invoice/<uuid:pk>/edit/', views.InvoiceEditView.as_view(), name='invoice_edit'),
    # path('invoices/<uuid:pk>/', views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/<uuid:pk>/view/', views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/<uuid:pk>/receipt/', views.InvoicePrintView.as_view(), name='invoice_receipt_print'),
    path('invoices/<uuid:pk>/cancel/', views.InvoiceCancelView.as_view(), name='invoice_cancel'),
    path('invoices/<uuid:pk>/delete/', views.InvoiceDeleteView.as_view(), name='invoice_delete'),

    # Payments
    path('payments/', views.PaymentListView.as_view(), name='payment_list'),
    path('payments/record/', views.PaymentRecordView.as_view(), name='payment_record'),
    path('payments/family/', views.FamilyPaymentView.as_view(), name='family_payment'),
    path('payments/<uuid:pk>/', views.PaymentDetailView.as_view(), name='payment_detail'),
    path('payments/<uuid:pk>/receipt/', views.PaymentReceiptView.as_view(), name='payment_receipt'),

    # Bank Transactions
    path('bank-transactions/', views.BankTransactionListView.as_view(), name='bank_transaction_list'),
    path('bank-transactions/<uuid:pk>/', views.BankTransactionDetailView.as_view(), name='bank_transaction_detail'),
    path('bank-transactions/<uuid:pk>/match/', views.BankTransactionMatchView.as_view(), name='bank_transaction_match'),

    # Student Finance
    path('student/<uuid:student_pk>/statement/', views.StudentStatementView.as_view(), name='student_statement'),
    path('student/<uuid:student_pk>/statement/print/', views.StudentStatementPrintView.as_view(),
         name='student_statement_print'),
    path('student/<uuid:student_pk>/generate-invoice/', views.SingleStudentInvoiceGenerateView.as_view(),
         name='student_generate_invoice'),

    # Reports
    path('reports/collections/', views.CollectionsReportView.as_view(), name='collections_report'),
    path('reports/outstanding/', views.OutstandingBalancesReportView.as_view(), name='outstanding_report'),
    path('reports/export/', views.FinanceExportView.as_view(), name='finance_export'),
]