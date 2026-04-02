from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import TemplateView, View
from django.template.defaultfilters import truncatechars

from core.mixins import OrganizationFilterMixin, RoleRequiredMixin
from core.models import UserRole
from finance.models import Invoice
from finance.services import InvoiceService as FinanceInvoiceService
from other_income.models import OtherIncomeInvoice
from payments.models import Payment
from payments.services.invoice import InvoiceService as PaymentsInvoiceService
from students.models import Student


ENTITY_MODELS = {
    "invoice": Invoice,
    "payment": Payment,
    "student": Student,
    "other_income_invoice": OtherIncomeInvoice,
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
                "entity_types": ["all", "invoice", "payment", "student", "other_income_invoice"],
            }
        )
        return context


class TrashDetailView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, TemplateView):
    template_name = "trash/detail.html"
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entity_type = self.kwargs['entity_type']
        pk = self.kwargs['pk']
        model = ENTITY_MODELS.get(entity_type)
        if not model:
            raise Http404

        obj = get_object_or_404(model.objects, pk=pk, is_active=False)
        fields = []
        for field in obj._meta.fields:
            name = field.name
            try:
                value = getattr(obj, name)
            except Exception:
                value = '—'
            if isinstance(value, dict):
                value = truncatechars(str(value), 500)
            fields.append({'name': name, 'value': value})

        context.update({
            'entity_type': entity_type,
            'record': obj,
            'record_label': str(obj),
            'fields': fields,
        })
        return context


class TrashRestoreView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    @transaction.atomic
    def post(self, request, entity_type, pk, *args, **kwargs):
        model = ENTITY_MODELS.get(entity_type)
        if not model:
            raise Http404

        obj = get_object_or_404(model.objects, pk=pk, is_active=False)

        if isinstance(obj, Invoice):
            FinanceInvoiceService.restore_invoice(obj)
        elif isinstance(obj, Payment):
            PaymentsInvoiceService.restore_payment(obj)
        elif isinstance(obj, Student):
            obj.is_active = True
            obj.deleted_at = None
            obj.deleted_by = None
            if obj.status == "inactive":
                obj.status = "active"
            obj.save(update_fields=["is_active", "deleted_at", "deleted_by", "status", "updated_at"])
            obj.recompute_outstanding_balance()
        elif isinstance(obj, OtherIncomeInvoice):
            obj.is_active = True
            obj.deleted_at = None
            obj.deleted_by = None
            obj.save(update_fields=["is_active", "deleted_at", "deleted_by", "updated_at"])
        else:
            raise Http404

        messages.success(request, f"Restored {entity_type.replace('_', ' ')} successfully.")
        return redirect("trash:dashboard")


class TrashPurgeView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.ACCOUNTANT]

    @transaction.atomic
    def post(self, request, entity_type, pk, *args, **kwargs):
        model = ENTITY_MODELS.get(entity_type)
        if not model:
            raise Http404

        obj = get_object_or_404(model.objects, pk=pk, is_active=False)

        if isinstance(obj, Payment):
            PaymentsInvoiceService.purge_payment(obj)
        elif isinstance(obj, Invoice):
            FinanceInvoiceService.purge_invoice(obj)
        else:
            obj.delete()

        messages.success(request, f"Purged {entity_type.replace('_', ' ')} permanently.")
        return redirect("trash:dashboard")
