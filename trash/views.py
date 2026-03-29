from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView, View

from core.mixins import OrganizationFilterMixin, RoleRequiredMixin
from core.models import UserRole
from finance.models import Invoice
from finance.services import InvoiceService as FinanceInvoiceService
from other_income.models import OtherIncomeInvoice
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import TemplateView, View

from accounts.models import UserRole
from core.mixins import OrganizationFilterMixin, RoleRequiredMixin
from finance.models import Invoice
from payments.models import Payment
from payments.services.invoice import InvoiceService as PaymentsInvoiceService
from students.models import Student


def _org_filter(queryset, organization):
    if organization is None:
        return queryset
    if hasattr(queryset.model, 'organization_id'):
        return queryset.filter(organization=organization)
    return queryset


class TrashListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, TemplateView):
    template_name = 'trash/list.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = getattr(self.request, 'organization', None)
        selected = self.request.GET.get('entity', 'invoice')

        entities = {
            'invoice': _org_filter(Invoice.objects.filter(is_active=False).select_related('student', 'deleted_by'), organization),
            'payment': _org_filter(Payment.objects.filter(is_active=False).select_related('student', 'deleted_by'), organization),
            'student': _org_filter(Student.objects.filter(is_active=False).select_related('deleted_by'), organization),
            'other_income_invoice': _org_filter(OtherIncomeInvoice.objects.filter(is_active=False).select_related('deleted_by'), organization),
        }

        context['entity'] = selected
        context['entities'] = list(entities.keys())
        context['rows'] = entities.get(selected, Invoice.objects.none()).order_by('-deleted_at', '-updated_at')[:200]
ENTITY_MODELS = {
    "invoice": Invoice,
    "payment": Payment,
    "student": Student,
}


class TrashDashboardView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, TemplateView):
    template_name = "trash/dashboard.html"
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = getattr(self.request, "organization", None)
        entity_type = (self.request.GET.get("type") or "all").lower()

        records = []
        for key, model in ENTITY_MODELS.items():
            if entity_type != "all" and key != entity_type:
                continue

            qs = model.objects.filter(is_active=False, deleted_at__isnull=False).select_related("deleted_by")
            if organization and hasattr(model, "organization"):
                qs = qs.filter(organization=organization)
            elif organization and key in {"invoice", "payment"}:
                qs = qs.filter(student__organization=organization)

            for obj in qs.order_by("-deleted_at")[:100]:
                records.append(
                    {
                        "type": key,
                        "pk": obj.pk,
                        "label": str(obj),
                        "deleted_at": obj.deleted_at,
                        "deleted_by": obj.deleted_by,
                    }
                )

        records = sorted(records, key=lambda r: r["deleted_at"], reverse=True)

        context.update(
            {
                "records": records,
                "selected_type": entity_type,
                "entity_types": ["all", "invoice", "payment", "student"],
            }
        )
        return context


class TrashRestoreView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def post(self, request, entity, pk):
        if entity == 'invoice':
            obj = Invoice.objects.filter(pk=pk, is_active=False).first()
            if not obj:
                raise Http404
            FinanceInvoiceService.restore_invoice(obj)
        elif entity == 'payment':
            obj = Payment.objects.filter(pk=pk, is_active=False).first()
            if not obj:
                raise Http404
            PaymentsInvoiceService.restore_payment(obj)
        elif entity == 'student':
            obj = Student.objects.filter(pk=pk, is_active=False).first()
            if not obj:
                raise Http404
            obj.is_active = True
            obj.deleted_at = None
            obj.deleted_by = None
            if obj.status == 'inactive':
                obj.status = 'active'
            obj.save(update_fields=['is_active', 'deleted_at', 'deleted_by', 'status', 'updated_at'])
        elif entity == 'other_income_invoice':
            obj = OtherIncomeInvoice.objects.filter(pk=pk, is_active=False).first()
            if not obj:
                raise Http404
            obj.is_active = True
            obj.deleted_at = None
            obj.deleted_by = None
            obj.save(update_fields=['is_active', 'deleted_at', 'deleted_by', 'updated_at'])
        else:
            raise Http404

        messages.success(request, f'{entity.replace("_", " ").title()} restored successfully.')
        return redirect(f'{reverse("trash:list")}?entity={entity}')


class TrashPurgeView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def post(self, request, entity, pk):
        if entity == 'invoice':
            obj = Invoice.objects.filter(pk=pk, is_active=False).first()
            if not obj:
                raise Http404
            FinanceInvoiceService.purge_invoice(obj)
        elif entity == 'payment':
            obj = Payment.objects.filter(pk=pk, is_active=False).first()
            if not obj:
                raise Http404
            PaymentsInvoiceService.purge_payment(obj)
        elif entity == 'student':
            Student.objects.filter(pk=pk, is_active=False).delete()
        elif entity == 'other_income_invoice':
            OtherIncomeInvoice.objects.filter(pk=pk, is_active=False).delete()
        else:
            raise Http404

        messages.success(request, f'{entity.replace("_", " ").title()} permanently purged.')
        return redirect(f'{reverse("trash:list")}?entity={entity}')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    @transaction.atomic
    def post(self, request, entity_type, pk, *args, **kwargs):
        model = ENTITY_MODELS.get(entity_type)
        if not model:
            messages.error(request, "Unknown record type.")
            return redirect("trash:dashboard")

        obj = get_object_or_404(model.objects, pk=pk, is_active=False)
        obj.is_active = True
        obj.deleted_at = None
        obj.deleted_by = None

        update_fields = ["is_active", "deleted_at", "deleted_by", "updated_at"]
        if isinstance(obj, Student):
            obj.status = "active"
            obj.status_date = timezone.now()
            update_fields.extend(["status", "status_date"])

        obj.save(update_fields=update_fields)

        if isinstance(obj, Invoice):
            obj.student.recompute_outstanding_balance()
        elif isinstance(obj, Payment):
            PaymentsInvoiceService.apply_payment_to_student_arrears(obj)
            obj.student.recompute_outstanding_balance()
        elif isinstance(obj, Student):
            obj.recompute_outstanding_balance()

        messages.success(request, f"Restored {entity_type} record successfully.")
        return redirect("trash:dashboard")


class TrashPurgeView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.ACCOUNTANT]

    @transaction.atomic
    def post(self, request, entity_type, pk, *args, **kwargs):
        model = ENTITY_MODELS.get(entity_type)
        if not model:
            messages.error(request, "Unknown record type.")
            return redirect("trash:dashboard")

        obj = get_object_or_404(model.objects, pk=pk, is_active=False)

        if isinstance(obj, Payment):
            PaymentsInvoiceService.delete_payment(obj)
        elif isinstance(obj, Invoice):
            student = obj.student
            obj.delete()
            student.recompute_outstanding_balance()
        else:
            obj.delete()

        messages.success(request, f"Purged {entity_type} record permanently.")
        return redirect("trash:dashboard")
