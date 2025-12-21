# finance/api_views.py

from django.http import JsonResponse
from payments.services.payment import PaymentService
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import json
import logging

from .models import Invoice
from payments.services import PaymentService
from students.models import Student

logger = logging.getLogger(__name__)


class StudentInvoicesAPIView(View):
    def get(self, request, student_pk):
        invoices = Invoice.objects.filter(
            student_id=student_pk, is_active=True, balance__gt=0
        ).exclude(status='cancelled').values('id', 'invoice_number', 'balance', 'term__name')

        return JsonResponse(list(invoices), safe=False)


@method_decorator(csrf_exempt, name='dispatch')
class CoopBankIPNView(View):

    def post(self, request):
        try:
            data = json.loads(request.body)
            logger.info(f"Co-op Bank IPN received: {data}")

            payment, bank_txn = PaymentService.process_bank_callback(data, 'coop')

            if payment:
                return JsonResponse({'status': 'success', 'message': 'Payment processed'})
            else:
                return JsonResponse({'status': 'pending', 'message': 'Transaction recorded, awaiting manual matching'})

        except Exception as e:
            logger.error(f"Co-op Bank IPN error: {str(e)}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class EquityBankIPNView(View):

    def post(self, request):
        try:
            data = json.loads(request.body)
            logger.info(f"Equity Bank IPN received: {data}")

            payment, bank_txn = PaymentService.process_bank_callback(data, 'equity')

            if payment:
                return JsonResponse({'status': 'success', 'message': 'Payment processed'})
            else:
                return JsonResponse({'status': 'pending', 'message': 'Transaction recorded, awaiting manual matching'})

        except Exception as e:
            logger.error(f"Equity Bank IPN error: {str(e)}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class MpesaIPNView(View):

    def post(self, request):
        try:
            data = json.loads(request.body)
            logger.info(f"M-PESA IPN received: {data}")

            # Extract M-PESA specific fields
            transaction_data = {
                'reference': data.get('TransID'),
                'amount': data.get('TransAmount'),
                'account_reference': data.get('BillRefNumber'),
                'sender_name': data.get('FirstName', '') + ' ' + data.get('LastName', ''),
                'sender_phone': data.get('MSISDN'),
            }

            payment, bank_txn = PaymentService.process_bank_callback(transaction_data, 'mpesa')

            if payment:
                return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Success'})
            else:
                return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

        except Exception as e:
            logger.error(f"M-PESA IPN error: {str(e)}")
            return JsonResponse({'ResultCode': 1, 'ResultDesc': str(e)})