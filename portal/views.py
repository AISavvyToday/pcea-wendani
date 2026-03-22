# portal/views.py
"""
Portal views for dashboards, sections, and authentication.

Finance dashboards now show REAL metrics from DB (invoices, payments, bank txns).

Definitions (as requested):
- billed (current term)     = SUM(Invoice.total_amount) for invoices in current term
- collected (current term)  = SUM(PaymentAllocation.amount) for allocations to current term invoices
                              + SUM(Payment.amount) for completed payments linked to current term invoices
                                that have NO allocations
- outstanding (current term)= billed - collected

Unmatched bank transactions:
- count of BankTransaction records NOT matched to a student admission number
  (in your schema this means NOT linked to any Payment => payment IS NULL),
  excluding failed/duplicate.
"""

import logging
from decimal import Decimal
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from accounts.decorators import role_required
from academics.models import Term
from core.models import InvoiceStatus, PaymentStatus, UserRole
from finance.models import Invoice, InvoiceItem
from payments.models import BankTransaction, Payment, PaymentAllocation
from payments.services.resolution import ResolutionService
from students.metrics import get_student_base_queryset, get_student_status_counters

logger = logging.getLogger(__name__)


# =============================================================================
# INTERNAL HELPERS (safe, DB-driven metrics)
# =============================================================================

def _model_has_field(model, field_name: str) -> bool:
    try:
        return any(getattr(f, "name", None) == field_name for f in model._meta.get_fields())
    except Exception:
        return False


def _safe_reverse(name, default="#", kwargs=None):
    kwargs = kwargs or {}
    try:
        return reverse(name, kwargs=kwargs)
    except NoReverseMatch:
        return default


def _fmt_kes(amount) -> str:
    if amount is None:
        amount = 0
    try:
        amount = Decimal(str(amount))
    except Exception:
        amount = Decimal("0")
    return f"KES {amount:,.0f}"


def _get_current_term(organization=None):
    qs = Term.objects.filter(is_current=True).select_related("academic_year")
    if organization:
        qs = qs.filter(organization=organization)
    term = qs.first()
    if not term:
        qs = Term.objects.all().select_related("academic_year")
        if organization:
            qs = qs.filter(organization=organization)
        if _model_has_field(Term, "is_active"):
            qs = qs.filter(is_active=True)
        term = qs.order_by("-id").first()
    # Fallback: if org-filtered returns nothing, use global is_current (shared term)
    if not term and organization:
        term = Term.objects.filter(is_current=True).select_related("academic_year").first()
    return term


def _get_active_students_qs(organization=None):
    return get_student_base_queryset(organization=organization).filter(status='active')


def _get_staff_count(organization=None):
    User = get_user_model()
    qs = User.objects.all()
    if organization:
        qs = qs.filter(organization=organization)
    if _model_has_field(User, "is_active"):
        qs = qs.filter(is_active=True)

    staff_roles = [
        UserRole.SUPER_ADMIN,
        UserRole.SCHOOL_ADMIN,
        UserRole.ACCOUNTANT,
        UserRole.TEACHER,
    ]
    try:
        return qs.filter(role__in=staff_roles).count()
    except Exception:
        return qs.count()


def _invoice_base_qs(organization=None):
    qs = (
        Invoice.objects.filter(
            is_active=True, 
            student__status='active'
        )
        .exclude(status=InvoiceStatus.CANCELLED)
        .select_related("student", "term", "term__academic_year")
    )
    if organization:
        qs = qs.filter(organization=organization)
    return qs


def _completed_payments_base_qs(organization=None):
    qs = Payment.objects.filter(status=PaymentStatus.COMPLETED)
    if organization:
        # Filter by organization with backward compatibility
        qs = qs.filter(
            Q(organization=organization) | 
            Q(organization__isnull=True, student__organization=organization)
        )
    elif organization is None:
        # If explicitly None, only show payments without organization
        qs = qs.filter(organization__isnull=True)
    if _model_has_field(Payment, "is_active"):
        qs = qs.filter(is_active=True)
    return qs


def _completed_allocations_base_qs():
    """
    Allocations represent the most accurate way to count collections against invoices,
    especially when a payment is split across multiple invoice items.
    """
    qs = PaymentAllocation.objects.select_related(
        "payment", "invoice_item", "invoice_item__invoice"
    ).filter(payment__status=PaymentStatus.COMPLETED)

    if _model_has_field(PaymentAllocation, "is_active"):
        qs = qs.filter(is_active=True)

    if _model_has_field(Payment, "is_active"):
        qs = qs.filter(payment__is_active=True)

    return qs


def _sum_decimal(queryset, field_name):
    total = queryset.aggregate(total=Sum(field_name))["total"] or Decimal("0")
    return Decimal(str(total))


def _group_invoice_item_amounts(invoice_qs, amount_field="net_amount"):
    items = InvoiceItem.objects.filter(invoice__in=invoice_qs, is_active=True)
    return {
        "fees": _sum_decimal(
            items.exclude(category__in=["other", "transport", "balance_bf", "prepayment"]),
            amount_field,
        ),
        "other_items": _sum_decimal(items.filter(category="other"), amount_field),
        "transport": _sum_decimal(items.filter(category="transport"), amount_field),
        "balance_bf": _sum_decimal(items.filter(category="balance_bf"), amount_field),
    }


def _group_allocation_amounts(invoice_qs):
    allocations = _completed_allocations_base_qs().filter(invoice_item__invoice__in=invoice_qs)
    return {
        "fees": _sum_decimal(
            allocations.exclude(invoice_item__category__in=["other", "balance_bf", "prepayment"]),
            "amount",
        ),
        "other_items": _sum_decimal(allocations.filter(invoice_item__category="other"), "amount"),
        "balance_bf": _sum_decimal(allocations.filter(invoice_item__category="balance_bf"), "amount"),
    }


def _term_overpayments(term=None, organization=None):
    if not term:
        return Decimal("0")

    payments = _completed_payments_base_qs(organization=organization).filter(
        payment_date__date__gte=term.start_date,
        payment_date__date__lte=term.end_date,
    )
    return _sum_decimal(payments, "unallocated_amount")


def _collected_for_invoices(invoice_qs):
    """
    Calculate total collected amount from invoices in the queryset.
    
    collected = SUM(invoice.amount_paid) for invoices in invoice_qs
    
    This is the most accurate method because invoice.amount_paid includes:
    - Allocations to invoice items (via PaymentAllocation)
    - Payments to balance_bf (stored directly in amount_paid, no PaymentAllocation record)
    - All payments applied to the invoice, regardless of allocation method
    
    IMPORTANT: When a payment clears balance_bf, it is added to invoice.amount_paid
    (see payments/services/invoice.py apply_payment_to_student_arrears method).
    This ensures ALL payments are captured in the Collected stat, including those
    that clear balance_bf from previous terms.
    
    This ensures all payments are captured, including those that go to balance_bf.
    """
    # Sum amount_paid from all invoices in the queryset
    # amount_paid includes both item allocations and balance_bf payments
    # This means Collected stat will increment for ALL payments, including balance_bf payments
    collected = invoice_qs.aggregate(total=Sum("amount_paid"))["total"] or Decimal("0")
    return Decimal(str(collected))


def _filter_bank_transactions_by_organization(queryset, organization=None):
    """
    Filter bank transactions by organization.
    For PCEA Wendani Academy and Demo Organisation: show ALL bank transactions (matched + unmatched).
    """
    if not organization:
        return queryset
    
    # For these orgs, show ALL bank transactions (including unmatched for demo)
    if organization.name in ('PCEA Wendani Academy', 'Demo Organisation'):
        return queryset  # Show everything
    
    # For other organizations, filter normally
    return queryset.filter(
        Q(payment__organization=organization) | 
        Q(payment__isnull=False, payment__organization__isnull=True, payment__student__organization=organization)
    )


def _finance_kpis(term=None, organization=None):

    term = term or _get_current_term(organization=organization)
    academic_year = getattr(term, "academic_year", None) if term else None

    base = _invoice_base_qs(organization=organization)
    term_invoices = base.filter(term=term) if term else base.none()
    year_invoices = base.filter(term__academic_year=academic_year) if academic_year else base.none()
    active_students = _get_active_students_qs(organization=organization)

    balances_bf_total = _sum_decimal(active_students, 'balance_bf_original')
    prepayments_total = _sum_decimal(active_students, 'prepayment_original')

    def agg(invoice_qs, *, include_term_breakdowns=False):
        collected = _collected_for_invoices(invoice_qs)
        billed = _sum_decimal(invoice_qs, 'total_amount')
        outstanding = billed - collected

        stats = {
            "billed": billed,
            "collected": collected,
            "outstanding": outstanding,
            "invoice_count": invoice_qs.count(),
            "balances_bf": balances_bf_total,
            "prepayments": prepayments_total,
        }

        if include_term_breakdowns:
            billed_breakdown = _group_invoice_item_amounts(invoice_qs)
            collected_breakdown = _group_allocation_amounts(invoice_qs)
            balance_bf_cleared = collected_breakdown["balance_bf"]
            prepayments_consumed = _sum_decimal(invoice_qs, 'prepayment')
            overpayments = _term_overpayments(term=term, organization=organization)

            stats.update({
                "billed_breakdown": {
                    "fees": billed_breakdown["fees"],
                    "other_items": billed_breakdown["other_items"],
                    "transport": billed_breakdown["transport"],
                },
                "balance_bf_breakdown": {
                    "total": balances_bf_total,
                    "cleared": balance_bf_cleared,
                    "uncleared": max(Decimal("0"), balances_bf_total - balance_bf_cleared),
                },
                "prepayments_breakdown": {
                    "total": prepayments_total,
                    "consumed": prepayments_consumed,
                    "unconsumed": max(Decimal("0"), prepayments_total - prepayments_consumed),
                },
                "collected_breakdown": {
                    "fees": collected_breakdown["fees"],
                    "other_items": collected_breakdown["other_items"],
                    "overpayments": overpayments,
                },
            })

        return stats

    term_stats = agg(term_invoices, include_term_breakdowns=True)
    year_stats = agg(year_invoices)

    # Unmatched bank txns = NOT linked to a Payment (therefore not linked to any student admission number)
    bank_qs = BankTransaction.objects.all()
    if _model_has_field(BankTransaction, "is_active"):
        bank_qs = bank_qs.filter(is_active=True)
    
    # Filter by organization (matched + unmatched with matching admission numbers)
    bank_qs = _filter_bank_transactions_by_organization(bank_qs, organization=organization)

    unmatched_bank = (
        bank_qs.filter(payment__isnull=True)
        .exclude(processing_status__in=["failed", "duplicate"])
        .count()
    )

    # Payments today (completed)
    today = timezone.localdate()
    pay_qs = _completed_payments_base_qs(organization=organization)
    payments_today_total = pay_qs.filter(payment_date__date=today).aggregate(x=Sum("amount"))["x"] or 0
    payments_today_count = pay_qs.filter(payment_date__date=today).count()

    return {
        "term": term,
        "academic_year": academic_year,
        "term_stats": term_stats,
        "year_stats": year_stats,
        "unmatched_bank_transactions": unmatched_bank,
        "payments_today_total": payments_today_total,
        "payments_today_count": payments_today_count,
    }


# =============================================================================
# AUTHENTICATION VIEWS
# =============================================================================

@never_cache
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        # If already authenticated, redirect admins directly to admin dashboard
        if request.user.role in [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]:
            return redirect("portal:dashboard_admin")
        return redirect("portal:role_redirect")

    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        remember_me = request.POST.get("remember_me")

        if not email or not password:
            messages.error(request, "Please enter both email and password.")
            return render(request, "auth/login.html")

        user = authenticate(request, username=email, password=password)

        if user is not None:
            if hasattr(user, "is_locked") and user.is_locked():
                messages.error(
                    request,
                    "Your account is temporarily locked. Please try again later or contact support.",
                )
                return render(request, "auth/login.html")

            if not user.is_active:
                messages.error(request, "Your account is inactive. Please contact the administrator.")
                return render(request, "auth/login.html")

            login(request, user)

            if hasattr(user, "reset_failed_login"):
                user.reset_failed_login()

            if not remember_me:
                request.session.set_expiry(0)

            messages.success(request, f"Welcome back, {user.get_short_name()}!")

            next_url = request.GET.get("next") or request.POST.get("next")
            if next_url:
                return redirect(next_url)
            
            # Redirect admin users directly to admin dashboard
            if user.role in [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]:
                return redirect("portal:dashboard_admin")
            
            # Non-admin users go through role_redirect
            return redirect("portal:role_redirect")

        messages.error(request, "Invalid email or password. Please try again.")

    return render(request, "auth/login.html")


@login_required
@require_http_methods(["GET", "POST"])
def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect("portal:login")


@never_cache
@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.user.is_authenticated:
        return redirect("portal:role_redirect")

    if request.method == "POST":
        messages.info(
            request,
            "Registration is currently handled by school administrators. Please contact the school office.",
        )
        return render(request, "auth/register.html")

    return render(request, "auth/register.html")


@login_required
def role_redirect(request):
    user = request.user
    role = user.role

    dashboard_map = {
        UserRole.SUPER_ADMIN: "portal:dashboard_admin",
        UserRole.SCHOOL_ADMIN: "portal:dashboard_admin",
        UserRole.ACCOUNTANT: "portal:dashboard_admin",  # Accountants use admin dashboard
        UserRole.TEACHER: "portal:dashboard_teacher",
        UserRole.PARENT: "portal:dashboard_parent",
        UserRole.STUDENT: "portal:dashboard_parent",
    }

    return redirect(dashboard_map.get(role, "portal:home"))


# =============================================================================
# DASHBOARD VIEWS
# =============================================================================

@login_required
def home(request):
    user = request.user
    # Redirect admin users to admin dashboard instead of showing home page
    if user.role in [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]:
        return redirect("portal:dashboard_admin")
    
    context = {
        "quick_stats": _get_quick_stats(user),
        "quick_actions": _get_quick_actions(user),
        "notices": _get_notices(user),
        "summaries": _get_summaries(user),
    }
    return render(request, "portal/home.html", context)


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN])
def dashboard_admin(request):
    """
    Administrator dashboard with full system overview.
    Finance stats are pulled from DB for current term + academic year.
    """
    organization = getattr(request, 'organization', None)
    # Allow superusers/staff to access even without organization (for setup/migration)
    if not organization:
        if request.user.is_superuser or request.user.is_staff:
            messages.warning(request, 'Your account is not assigned to an organization. Please assign one in Django admin.')
            # Show empty dashboard or redirect to admin
            from core.models import Organization
            orgs = Organization.objects.all()
            if orgs.exists():
                messages.info(request, f'Available organizations: {", ".join([o.name for o in orgs])}')
            return render(request, "dashboard/admin.html", {
                "current_term": None,
                "current_academic_year": None,
                "stat_cards": [],
            })
        else:
            messages.error(request, 'Your account is not assigned to an organization.')
            return redirect('portal:login')
    
    kpis = _finance_kpis(organization=organization)

    term = kpis["term"]
    academic_year = kpis["academic_year"]
    term_stats = kpis["term_stats"]
    year_stats = kpis["year_stats"]

    student_base_qs = get_student_base_queryset(organization=organization)
    student_counts = get_student_status_counters(student_base_qs, term=term)
    total_students = student_counts['active']
    new_students = student_counts['new']
    graduated_students = student_counts['graduated']
    transferred_students = student_counts['transferred']

    staff_count = _get_staff_count(organization=organization)

    # Finance URLs (REAL from your finance/urls.py)
    finance_dashboard_url = _safe_reverse("finance:dashboard", default=_safe_reverse("portal:finance_overview"))
    invoices_url = _safe_reverse("finance:invoice_list", default=finance_dashboard_url)
    payments_url = _safe_reverse("finance:payment_list", default=finance_dashboard_url)
    bank_url = _safe_reverse("finance:bank_transaction_list", default=finance_dashboard_url)
    outstanding_url = _safe_reverse("finance:invoice_list", default=invoices_url)

    # Add term filter to some links
    term_qs = f"?term={term.pk}" if term else ""
    invoices_term_url = f"{invoices_url}"
    outstanding_term_url = f"{outstanding_url}"

    billed = Decimal(str(term_stats["billed"] or 0))
    collected = Decimal(str(term_stats["collected"] or 0))
    prepayments = Decimal(str(term_stats["prepayments"] or 0))
    balances_bf = Decimal(str(term_stats["balances_bf"] or 0))
    billed_breakdown = term_stats.get("billed_breakdown", {})
    balance_bf_breakdown = term_stats.get("balance_bf_breakdown", {})
    prepayments_breakdown = term_stats.get("prepayments_breakdown", {})
    collected_breakdown = term_stats.get("collected_breakdown", {})
    
    # IMPORTANT: Balance B/F stat behavior
    # - balances_bf is the sum of frozen balance_bf_original values from current term invoices
    # - These values are set at invoice creation and NEVER change during the term
    # - When payments are made, they increment 'collected' but do NOT change 'balances_bf' (which uses balance_bf_original)
    # - Balance B/F stat only changes when a new term starts and new invoices are generated
    # - Note: balance_bf field decreases as payments are made (for student accounts), but balance_bf_original stays frozen (for dashboard)
    
    # IMPORTANT: Collected stat behavior
    # - collected includes ALL payments: both to invoice items AND to balance_bf
    # - When a student pays 20k to clear balance_bf, Collected increases by 20k
    # - Balance B/F stat remains unchanged (frozen value)
    
    total_expected = (balances_bf + billed) - prepayments
    # Outstanding should be Total Expected - Collected (not just billed - collected)
    outstanding = total_expected - collected
    rate = (collected / billed * 100) if billed > 0 else Decimal("0")

    year_billed = Decimal(str(year_stats["billed"] or 0))
    year_collected = Decimal(str(year_stats["collected"] or 0))
    year_rate = (year_collected / year_billed * 100) if year_billed > 0 else Decimal("0")

    # Dashboard cards arranged in requested order:
    # 1. Total Students -> 2. Bal B/F -> 3. Total Prepayments -> 4. Billed -> 5. Collected -> 6. Outstanding Bal -> 7. Unmatched Bank Txns
    context = {
        "current_term": term,
        "current_academic_year": academic_year,
        "stat_cards": [
            {
                "title": "Total Students(Active only)",
                "value": f"{total_students:,}",
                "icon": "mdi-account-group",
                "bg": "bg-gradient-primary",
                "url": _safe_reverse("students:list"),
                "helper_lines": [
                    f"New-{new_students}",
                    f"Graduated-{graduated_students}, Transferred-{transferred_students}",
                ],
            },
            {
                "title": "Bal B/F",
                "value": _fmt_kes(balances_bf),
                "icon": "mdi-history",
                "bg": "bg-gradient-warning",
                "url": invoices_term_url,
                "helper_lines": [
                    f"Total: {_fmt_kes(balance_bf_breakdown.get('total'))}",
                    f"Cleared: {_fmt_kes(balance_bf_breakdown.get('cleared'))}",
                    f"Uncleared: {_fmt_kes(balance_bf_breakdown.get('uncleared'))}",
                ],
            },
            {
                "title": "Total Prepayments",
                "value": _fmt_kes(prepayments),
                "icon": "mdi-cash-plus",
                "bg": "bg-gradient-success",
                "url": invoices_term_url,
                "helper_lines": [
                    f"Consumed: {_fmt_kes(prepayments_breakdown.get('consumed'))}",
                    f"Unconsumed: {_fmt_kes(prepayments_breakdown.get('unconsumed'))}",
                ],
            },
            {
                "title": "Billed",
                "value": _fmt_kes(billed),
                "icon": "mdi-file-document",
                "bg": "bg-gradient-info",
                "url": invoices_term_url,
                "helper_lines": [
                    f"Fees: {_fmt_kes(billed_breakdown.get('fees'))}",
                    f"Other items: {_fmt_kes(billed_breakdown.get('other_items'))}",
                    f"Transport: {_fmt_kes(billed_breakdown.get('transport'))}",
                ],
            },
            {
                "title": "Total Expected",
                "value": _fmt_kes(total_expected),
                "icon": "mdi-calculator",
                "bg": "bg-gradient-primary",
                "url": invoices_term_url,
                "helper": "Bal B/F + Billed - Prepayments",
            },
            {
                "title": "Collected",
                "value": _fmt_kes(collected),
                "icon": "mdi-cash-check",
                "bg": "bg-gradient-success",
                "url": payments_url,
                "helper_lines": [
                    f"Collection rate: {rate:.1f}%",
                    f"Fees: {_fmt_kes(collected_breakdown.get('fees'))}",
                    f"Other items: {_fmt_kes(collected_breakdown.get('other_items'))}",
                    f"Overpayments: {_fmt_kes(collected_breakdown.get('overpayments'))}",
                ],
            },
            {
                "title": "Outstanding Bal",
                "value": _fmt_kes(outstanding),
                "icon": "mdi-alert-circle",
                "bg": "bg-gradient-warning",
                "url": outstanding_term_url,
                "helper": "Unpaid balance",
            },
            {
                "title": "Unmatched Bank Txns",
                "value": f"{kpis['unmatched_bank_transactions']:,}",
                "icon": "mdi-bank-transfer",
                "bg": "bg-gradient-danger",
                "url": bank_url,
                "helper": "Needs reconciliation",
            },
        ],
    }

    return render(request, "dashboard/admin.html", context)


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT])
def dashboard_bursar(request):
    """
    DEPRECATED: Bursar dashboard - redirects to admin dashboard.
    Accountants should use admin dashboard.
    """
    return redirect('portal:dashboard_admin')


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.TEACHER])
def dashboard_teacher(request):
    """
    Teacher dashboard with real data.
    Shows assigned classes, pending grade entries, today's schedule, attendance to take.
    """
    organization = getattr(request, 'organization', None)
    if not organization:
        messages.error(request, 'Your account is not assigned to an organization.')
        return redirect('portal:login')
    
    from academics.models import Staff, ClassSubject, Timetable, Exam, Grade, Attendance
    from students.models import Student
    from academics.models import Subject
    from django.utils import timezone
    from datetime import date
    
    try:
        staff = Staff.objects.get(user=request.user, organization=organization)
    except Staff.DoesNotExist:
        messages.error(request, "You don't have a staff profile.")
        return render(request, 'portal/dashboard_teacher.html', {
            'title': 'Teacher Dashboard',
            'staff': None,
        })
    
    # Get assigned classes
    from academics.models import Class as ClassModel
    assigned_classes = ClassModel.objects.filter(
        class_subjects__teacher=staff,
        organization=organization
    ).distinct()
    
    # Get today's schedule
    today = date.today()
    day_of_week = today.weekday()  # 0=Monday, 4=Friday
    current_term = _get_current_term(organization=organization)
    
    today_schedule = []
    if current_term:
        today_schedule = Timetable.objects.filter(
            teacher=staff,
            term=current_term,
            day_of_week=day_of_week,
            organization=organization
        ).select_related('class_obj', 'subject').order_by('start_time')
    
    # Get pending grade entries (exams with no grades for assigned classes)
    pending_grade_entries = []
    if current_term:
        exams = Exam.objects.filter(
            term=current_term,
            classes__in=assigned_classes,
            organization=organization
        ).distinct()
        
        for exam in exams:
            for class_obj in assigned_classes:
                if exam.classes.filter(id=class_obj.id).exists():
                    students = Student.objects.filter(
                        current_class=class_obj,
                        status='active',
                        organization=organization
                    )
                    for student in students:
                        # Check if any grades missing for this exam
                        subjects = Subject.objects.filter(
                            class_subjects__class_obj=class_obj,
                            class_subjects__teacher=staff,
                            organization=organization
                        )
                        for subject in subjects:
                            if not Grade.objects.filter(
                                student=student,
                                exam=exam,
                                subject=subject,
                                organization=organization
                            ).exists():
                                pending_grade_entries.append({
                                    'exam': exam,
                                    'class': class_obj,
                                    'student': student,
                                    'subject': subject,
                                })
                                break
    
    # Get attendance to take (today's date, assigned classes)
    attendance_to_take = []
    for class_obj in assigned_classes:
        students_count = Student.objects.filter(
            current_class=class_obj,
            status='active',
            organization=organization
        ).count()
        attendance_taken = Attendance.objects.filter(
            class_obj=class_obj,
            date=today,
            organization=organization
        ).count()
        if attendance_taken < students_count:
            attendance_to_take.append({
                'class': class_obj,
                'students_count': students_count,
                'attendance_taken': attendance_taken,
            })
    
    context = {
        'title': 'Teacher Dashboard',
        'staff': staff,
        'assigned_classes': assigned_classes,
        'today_schedule': today_schedule,
        'pending_grade_entries': pending_grade_entries[:10],  # Limit to 10
        'attendance_to_take': attendance_to_take,
        'current_term': current_term,
    }
    return render(request, 'portal/dashboard_teacher.html', context)


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.PARENT, UserRole.STUDENT])
def dashboard_parent(request):
    """
    Parent dashboard with real data.
    Shows children list, fee balances, recent announcements, attendance summary, grades.
    """
    organization = getattr(request, 'organization', None)
    if not organization:
        messages.error(request, 'Your account is not assigned to an organization.')
        return redirect('portal:login')
    
    from students.models import Parent, Student, StudentParent
    from finance.models import Invoice
    from communications.models import Announcement
    from academics.models import Attendance, Grade, Exam, ReportCard
    from django.db.models import Sum, Q
    from django.utils import timezone
    from datetime import timedelta
    from core.models import InvoiceStatus
    
    try:
        parent = Parent.objects.get(user=request.user, organization=organization)
    except Parent.DoesNotExist:
        messages.error(request, "You don't have a parent profile.")
        return render(request, 'portal/dashboard_parent.html', {
            'title': 'Parent Dashboard',
            'parent': None,
        })
    
    # Get children
    children = Student.objects.filter(
        student_parents__parent=parent,
        student_parents__is_active=True,
        organization=organization
    ).select_related('current_class').distinct()
    
    # Get fee balances for each child
    children_data = []
    current_term = _get_current_term(organization=organization)
    
    for child in children:
        # Get outstanding balance
        outstanding = Decimal('0.00')
        if current_term:
            invoices = Invoice.objects.filter(
                student=child,
                term=current_term,
                organization=organization,
                is_active=True
            ).exclude(status=InvoiceStatus.CANCELLED)
            outstanding = invoices.aggregate(total=Sum('balance'))['total'] or Decimal('0.00')
        
        # Get recent attendance (last 7 days)
        recent_attendance = Attendance.objects.filter(
            student=child,
            date__gte=timezone.now().date() - timedelta(days=7),
            organization=organization
        ).order_by('-date')[:7]
        
        # Get recent grades
        recent_grades = []
        if current_term:
            exams = Exam.objects.filter(
                term=current_term,
                organization=organization,
                is_published=True
            )
            recent_grades = Grade.objects.filter(
                student=child,
                exam__in=exams,
                organization=organization
            ).select_related('subject', 'exam').order_by('-created_at')[:5]
        
        children_data.append({
            'student': child,
            'outstanding_balance': outstanding,
            'recent_attendance': recent_attendance,
            'recent_grades': recent_grades,
        })
    
    # Get recent announcements
    recent_announcements = Announcement.objects.filter(
        organization=organization,
        is_sent=True,
        target_audience__in=['all', 'parents']
    ).order_by('-sent_at')[:5]
    
    # Get published report cards
    published_report_cards = ReportCard.objects.filter(
        student__in=children,
        is_published=True,
        organization=organization
    ).select_related('student', 'term').order_by('-published_at')[:5]
    
    context = {
        'title': 'Parent Dashboard',
        'parent': parent,
        'children_data': children_data,
        'recent_announcements': recent_announcements,
        'published_report_cards': published_report_cards,
        'current_term': current_term,
    }
    return render(request, 'portal/dashboard_parent.html', context)


# =============================================================================
# SECTION VIEWS
# =============================================================================

@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.TEACHER])
def academics_overview(request):
    # sample
    widgets = [
        {"icon": "mdi-calendar-clock", "label": "Timetables", "description": "Manage class schedules"},
        {"icon": "mdi-clipboard-check", "label": "Attendance", "description": "Daily attendance tracking"},
        {"icon": "mdi-file-document-edit", "label": "Examinations", "description": "Exams and assessments"},
        {"icon": "mdi-certificate", "label": "Report Cards", "description": "Generate student reports"},
    ]
    return render(request, "sections/academics.html", {"academic_widgets": widgets})


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT])
def finance_overview(request):
    """
    Finance section overview.
    Uses real DB counts for invoice/payment/bank queues.
    """
    organization = getattr(request, 'organization', None)
    if not organization:
        messages.error(request, 'Your account is not assigned to an organization.')
        return redirect('portal:login')
    
    term = _get_current_term()
    students_count = _get_active_students_qs(organization=organization).count()

    invoices_qs = _invoice_base_qs(organization=organization)
    if term:
        invoices_qs = invoices_qs.filter(term=term)

    # Students that already have an invoice this term
    invoiced_students = invoices_qs.values("student_id").distinct().count()
    pending_invoices = max(0, students_count - invoiced_students)

    bank_qs = BankTransaction.objects.all()
    if _model_has_field(BankTransaction, "is_active"):
        bank_qs = bank_qs.filter(is_active=True)
    
    # Filter by organization (matched + unmatched with matching admission numbers)
    bank_qs = _filter_bank_transactions_by_organization(bank_qs, organization=organization)

    unmatched_bank = (
        bank_qs.filter(payment__isnull=True)
        .exclude(processing_status__in=["failed", "duplicate"])
        .count()
    )

    outstanding_invoices_qs = invoices_qs.filter(balance__gt=0)
    outstanding_students = outstanding_invoices_qs.values("student_id").distinct().count()

    overdue_count = 0
    overdue_label = "Overdue Accounts"
    overdue_subtitle = "Past due date"
    if _model_has_field(Invoice, "due_date"):
        overdue_count = (
            outstanding_invoices_qs.filter(due_date__lt=timezone.localdate())
            .values("student_id").distinct().count()
        )
    else:
        overdue_count = outstanding_students
        overdue_label = "Outstanding Accounts"
        overdue_subtitle = "Balance > 0"

    def pct(x):
        return int((x / students_count * 100)) if students_count else 0

    term_qs = f"?term={term.pk}" if term else ""
    queues = [
        {
            "title": "Pending Invoices",
            "subtitle": "Awaiting generation (students without invoice this term)",
            "count": pending_invoices,
            "percent": pct(pending_invoices),
            "badge_class": "warning",
            "url": f"{_safe_reverse('finance:invoice_generate', default=_safe_reverse('finance:dashboard'))}",
        },
        {
            "title": "Unmatched Bank Transactions",
            "subtitle": "Not linked to payment/student admission number",
            "count": unmatched_bank,
            "percent": 0,
            "badge_class": "danger",
            "url": f"{_safe_reverse('finance:bank_transaction_list', default=_safe_reverse('finance:dashboard'))}",
        },
        {
            "title": overdue_label,
            "subtitle": overdue_subtitle,
            "count": overdue_count,
            "percent": pct(overdue_count),
            "badge_class": "info",
            "url": f"{_safe_reverse('finance:outstanding_report', default=_safe_reverse('finance:invoice_list'))}{term_qs}",
        },
    ]

    return render(request, "sections/finance.html", {"queues": queues, "current_term": term})


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN])
def communications_overview(request):
    # sample
    broadcasts = [
        {"title": "Term 3 Fee Reminder", "summary": "Sent to all parents with outstanding balances", "timestamp": "2 hours ago"},
        {"title": "Sports Day Announcement", "summary": "Event details for Dec 8th", "timestamp": "1 day ago"},
        {"title": "Holiday Schedule", "summary": "School closing dates", "timestamp": "3 days ago"},
    ]

    approvals = [
        {"title": "Fee Waiver Request", "owner": "Mary Kamau (Parent)", "state": "Pending", "badge_class": "warning"},
        {"title": "Leave Application", "owner": "John Odhiambo (Teacher)", "state": "Pending", "badge_class": "warning"},
    ]

    return render(request, "sections/communications.html", {"broadcasts": broadcasts, "approvals": approvals})


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.TEACHER])
def resources_overview(request):
    # sample
    resources = [
        {"title": "CBC Curriculum Guide", "type": "PDF Document", "icon": "mdi-file-pdf-box", "description": "Official CBC implementation guide"},
        {"title": "Assessment Templates", "type": "Excel Templates", "icon": "mdi-file-excel", "description": "Standardized assessment forms"},
        {"title": "Teaching Resources", "type": "Resource Pack", "icon": "mdi-folder-multiple", "description": "Subject-specific materials"},
    ]
    return render(request, "sections/resources.html", {"resources": resources})


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN])
def settings_overview(request):
    # Get all terms for selection
    organization = getattr(request, 'organization', None)
    terms = Term.objects.all().select_related("academic_year")
    if organization:
        terms = terms.filter(organization=organization)
    terms = terms.order_by("-academic_year__year", "-term")
    current_term = _get_current_term(organization=organization)
    
    links = [
        {"title": "School Profile", "description": "Update school information", "url": "#", "cta": "Configure"},
        {"title": "Academic Years", "description": "Manage academic years and terms", "url": "#", "cta": "Manage"},
        {"title": "User Management", "description": "Manage staff and user accounts", "url": "#", "cta": "Manage"},
        {"title": "SMS Credits", "description": "View SMS balance and purchase credits", "url": reverse('communications:sms_settings'), "cta": "Manage"},
        {"title": "System Configuration", "description": "General system settings", "url": "#", "cta": "Configure"},
    ]
    return render(request, "sections/settings.html", {
        "settings_links": links,
        "terms": terms,
        "current_term": current_term,
    })


@login_required
def blank_page(request):
    return render(request, "pages/blank.html")


# =============================================================================
# HOME HELPERS (keep sample except accountant quick stats)
# =============================================================================

def _get_quick_stats(user):
    role = user.role

    if role == UserRole.ACCOUNTANT:
        # Note: request is not available in this helper function
        # This would need to be passed or accessed differently
        organization = None  # Will be set by middleware
        kpis = _finance_kpis(organization=organization) if organization else None
        if not kpis:
            return []
        term_stats = kpis["term_stats"]
        billed = Decimal(str(term_stats["billed"] or 0))
        collected = Decimal(str(term_stats["collected"] or 0))
        outstanding = Decimal(str(term_stats["outstanding"] or 0))
        rate = (collected / billed * 100) if billed > 0 else Decimal("0")

        return [
            {
                "label": "Today's Collections",
                "value": _fmt_kes(kpis["payments_today_total"]),
                "icon": "mdi-cash-plus",
                "color": "success",
                "delta": f"{kpis['payments_today_count']} payment(s)",
            },
            {
                "label": "Collection Rate",
                "value": f"{rate:.1f}%",
                "icon": "mdi-chart-line",
                "color": "primary",
                "delta": f"Term collected {_fmt_kes(collected)}",
            },
            {
                "label": "Outstanding",
                "value": _fmt_kes(outstanding),
                "icon": "mdi-alert-circle",
                "color": "danger",
                "delta": f"{term_stats['students_outstanding']} student(s)",
            },
            {
                "label": "Unmatched Bank Txns",
                "value": f"{kpis['unmatched_bank_transactions']:,}",
                "icon": "mdi-bank",
                "color": "warning",
                "delta": "Needs reconciliation",
            },
        ]

    # sample for others (as you requested)
    if role in [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]:
        return [
            {"label": "Total Students", "value": "1,247", "icon": "mdi-account-group", "color": "primary", "delta": "+12 this term"},
            {"label": "Staff Members", "value": "86", "icon": "mdi-account-tie", "color": "success", "delta": "4 on leave"},
            {"label": "Fee Collection", "value": "78%", "icon": "mdi-cash", "color": "warning", "delta": "KES 9.8M collected"},
            {"label": "Attendance Today", "value": "94%", "icon": "mdi-clipboard-check", "color": "info", "delta": "1,172 present"},
        ]
    elif role == UserRole.TEACHER:
        return [
            {"label": "My Classes", "value": "4", "icon": "mdi-google-classroom", "color": "primary", "delta": "156 students"},
            {"label": "Today's Lessons", "value": "5", "icon": "mdi-book-open", "color": "success", "delta": "2 completed"},
            {"label": "Pending Marks", "value": "2", "icon": "mdi-file-edit", "color": "warning", "delta": "Assessments due"},
            {"label": "Attendance", "value": "96%", "icon": "mdi-clipboard-check", "color": "info", "delta": "My classes avg"},
        ]
    else:
        return [
            {"label": "Children", "value": "2", "icon": "mdi-account-child", "color": "primary", "delta": "Enrolled"},
            {"label": "Fee Balance", "value": "KES 15K", "icon": "mdi-cash", "color": "warning", "delta": "Due Dec 15"},
            {"label": "Attendance", "value": "96%", "icon": "mdi-clipboard-check", "color": "success", "delta": "This term"},
            {"label": "Avg Grade", "value": "B+", "icon": "mdi-certificate", "color": "info", "delta": "All subjects"},
        ]


def _get_quick_actions(user):
    role = user.role

    if role == UserRole.ACCOUNTANT:
        # real finance actions
        return [
            {"label": "Record Payment", "icon": "mdi-cash-plus", "url_name": "finance:payment_record", "helper": "Manual payment entry"},
            {"label": "Generate Invoices", "icon": "mdi-file-document-edit", "url_name": "finance:invoice_generate", "helper": "Bulk invoice generation"},
            {"label": "Bank Reconciliation", "icon": "mdi-bank-transfer", "url_name": "finance:bank_transaction_list", "helper": "Match transactions"},
            {"label": "Collections Report", "icon": "mdi-chart-bar", "url_name": "finance:collections_report", "helper": "Collections summary"},
        ]

    # keep sample for other roles for now
    if role in [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]:
        return [
            {"label": "Add Student", "icon": "mdi-account-plus", "url_name": "portal:blank_page", "helper": "Register new student"},
            {"label": "Generate Invoices", "icon": "mdi-file-document-edit", "url_name": "finance:invoice_generate", "helper": "Bulk invoice generation"},
            {"label": "Send Announcement", "icon": "mdi-bullhorn", "url_name": "portal:blank_page", "helper": "Broadcast to parents"},
            {"label": "View Reports", "icon": "mdi-chart-bar", "url_name": "finance:collections_report", "helper": "Finance analytics"},
        ]
    elif role == UserRole.TEACHER:
        return [
            {"label": "Take Attendance", "icon": "mdi-clipboard-check", "url_name": "portal:blank_page", "helper": "Daily attendance"},
            {"label": "Enter Marks", "icon": "mdi-file-document-edit", "url_name": "portal:blank_page", "helper": "Assessment scores"},
            {"label": "View Timetable", "icon": "mdi-calendar-clock", "url_name": "portal:blank_page", "helper": "My schedule"},
            {"label": "Class List", "icon": "mdi-account-group", "url_name": "portal:blank_page", "helper": "Student roster"},
        ]
    else:
        return [
            {"label": "View Results", "icon": "mdi-certificate", "url_name": "portal:blank_page", "helper": "Academic performance"},
            {"label": "Fee Statement", "icon": "mdi-file-chart", "url_name": "portal:blank_page", "helper": "Payment history"},
            {"label": "Announcements", "icon": "mdi-bullhorn", "url_name": "portal:blank_page", "helper": "School notices"},
            {"label": "Contact School", "icon": "mdi-email", "url_name": "portal:blank_page", "helper": "Send message"},
        ]


def _get_notices(user):
    return [
        {"title": "End of Term Exams", "timeframe": "Dec 10-14", "badge": "warning"},
        {"title": "Sports Day", "timeframe": "Dec 8", "badge": "info"},
        {"title": "School Closes", "timeframe": "Dec 15", "badge": "success"},
    ]


def _get_summaries(user):
    role = user.role
    if role in [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]:
        return [
            {"title": "Enrollment", "description": "Current term", "value": "1,247", "trend": "+2.4%", "trend_class": "success"},
            {"title": "Collection Rate", "description": "Fee recovery", "value": "78%", "trend": "+5%", "trend_class": "success"},
            {"title": "Attendance", "description": "Term average", "value": "94%", "trend": "-1%", "trend_class": "warning"},
        ]
    elif role == UserRole.ACCOUNTANT:
        return [
            {"title": "Monthly Target", "description": "December", "value": "KES 3.2M", "trend": "65% achieved", "trend_class": "warning"},
            {"title": "Overdue Amount", "description": "Past 30 days", "value": "KES 890K", "trend": "45 accounts", "trend_class": "danger"},
            {"title": "Today's Receipts", "description": "All channels", "value": "KES 245K", "trend": "12 payments", "trend_class": "success"},
        ]
    else:
        return [
            {"title": "Term Progress", "description": "Academic calendar", "value": "85%", "trend": "2 weeks left", "trend_class": "info"},
            {"title": "Upcoming Events", "description": "This month", "value": "3", "trend": "View calendar", "trend_class": "primary"},
            {"title": "Unread Messages", "description": "From school", "value": "2", "trend": "New", "trend_class": "warning"},
        ]


# =============================================================================
# TERM TRANSITION
# =============================================================================

@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN])
def term_transition(request):
    """
    Handle term transition - carry forward balances from one term to the next.
    
    This view allows admins to:
    1. Select previous and new term
    2. Preview changes (dry run)
    3. Execute the transition
    """
    from finance.services import transition_frozen_balances
    
    organization = getattr(request, 'organization', None)
    if organization:
        terms = Term.objects.filter(organization=organization).select_related("academic_year").order_by("-academic_year__year", "-term")
    else:
        terms = Term.objects.none()
    current_term = _get_current_term(organization=organization)
    
    # Default to selecting the previous term
    previous_terms = terms.exclude(id=current_term.id) if current_term else terms
    
    context = {
        "terms": terms,
        "current_term": current_term,
        "previous_terms": previous_terms,
    }
    
    if request.method == "POST":
        previous_term_id = request.POST.get("previous_term")
        new_term_id = request.POST.get("new_term")
        action = request.POST.get("action", "preview")  # "preview" or "execute"
        
        try:
            if organization:
                previous_term = Term.objects.get(pk=previous_term_id, organization=organization)
                new_term = Term.objects.get(pk=new_term_id, organization=organization)
            else:
                previous_term = Term.objects.get(pk=previous_term_id)
                new_term = Term.objects.get(pk=new_term_id)
            
            if previous_term.id == new_term.id:
                messages.error(request, "Previous term and new term cannot be the same.")
                return render(request, "sections/term_transition.html", context)
            
            # Run transition (dry_run for preview, actual for execute)
            is_dry_run = (action == "preview")
            stats = transition_frozen_balances(previous_term, new_term, dry_run=is_dry_run)
            
            context["previous_term_selected"] = previous_term
            context["new_term_selected"] = new_term
            context["stats"] = stats
            context["is_preview"] = is_dry_run
            
            if is_dry_run:
                messages.info(
                    request,
                    f"Preview complete. {stats['updated']} student(s) would be updated. "
                    f"Review the summary below and click 'Execute Transition' to apply changes."
                )
            else:
                messages.success(
                    request,
                    f"Term transition completed successfully! "
                    f"{stats['updated']} student(s) updated. "
                    f"{stats['with_outstanding']} with outstanding balances, "
                    f"{stats['with_overpayment']} with overpayments, "
                    f"{stats['fully_paid']} fully paid."
                )
                
        except Term.DoesNotExist:
            messages.error(request, "Invalid term selection. Please try again.")
        except Exception as e:
            logger.exception(f"Error during term transition: {e}")
            messages.error(request, f"An error occurred during transition: {str(e)}")
    
    return render(request, "sections/term_transition.html", context)