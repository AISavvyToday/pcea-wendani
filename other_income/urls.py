# other_income/urls.py
from django.urls import path
from . import views

app_name = 'other_income'

urlpatterns = [
    path('', views.OtherIncomeListView.as_view(), name='invoice_list'),
    path('create/', views.OtherIncomeCreateView.as_view(), name='invoice_create'),
    path('<uuid:pk>/', views.OtherIncomeDetailView.as_view(), name='invoice_detail'),
    path('<uuid:pk>/print/', views.OtherIncomeInvoicePrintView.as_view(), name='invoice_print'),
    path('<uuid:pk>/payments/record/', views.OtherIncomeRecordPaymentView.as_view(), name='invoice_record_payment'),
]