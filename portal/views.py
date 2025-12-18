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

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from accounts.decorators import role_required
from academics.models import Term
from core.models import InvoiceStatus, PaymentStatus, UserRole
from finance.models import Invoice
from payments.models import BankTransaction, Payment, PaymentAllocation
from students.models import Student

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


def _get_current_term():
    term = Term.objects.filter(is_current=True).select_related("academic_year").first()
    if not term:
        qs = Term.objects.all().select_related("academic_year")
        if _model_has_field(Term, "is_active"):
            qs = qs.filter(is_active=True)
        term = qs.order_by("-id").first()
    return term


def _get_active_students_qs():
    qs = Student.objects.all()
    if _model_has_field(Student, "is_active"):
        qs = qs.filter(is_active=True)
    return qs


def _get_staff_count():
    User = get_user_model()
    qs = User.objects.all()
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


def _invoice_base_qs():
    return (
        Invoice.objects.filter(is_active=True)
        .exclude(status=InvoiceStatus.CANCELLED)
        .select_related("student", "term", "term__academic_year")
    )


def _completed_payments_base_qs():
    qs = Payment.objects.filter(status=PaymentStatus.COMPLETED)
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


def _collected_for_invoices(invoice_qs):
    """
    collected = allocated_total + direct_total_without_allocations
    - allocated_total:
        SUM(PaymentAllocation.amount) for allocations to invoice items whose invoice in invoice_qs
    - direct_total_without_allocations:
        SUM(Payment.amount) for completed payments linked to invoices in invoice_qs
        where the payment has NO allocations (to avoid double counting).
    """
    invoice_ids = list(invoice_qs.values_list("id", flat=True))
    if not invoice_ids:
        return Decimal("0")

    # 1) Allocated collections (best signal)
    alloc_qs = _completed_allocations_base_qs().filter(invoice_item__invoice_id__in=invoice_ids)
    allocated_total = alloc_qs.aggregate(x=Sum("amount"))["x"] or Decimal("0")

    # 2) Direct payment totals ONLY for payments that have no allocations at all
    pay_qs = _completed_payments_base_qs().filter(invoice_id__in=invoice_ids, allocations__isnull=True)
    direct_total = pay_qs.aggregate(x=Sum("amount"))["x"] or Decimal("0")

    return Decimal(str(allocated_total)) + Decimal(str(direct_total))


def _finance_kpis(term=None):
    """
    Returns KPIs for:
    - current term
    - current academic year (derived from term)

    DEFINITIONS:
    billed      = SUM(Invoice.total_amount)
    collected   = SUM(PaymentAllocation.amount for term invoices) + SUM(Payment.amount for term invoices with no allocations)
    outstanding = billed - collected
    """
    term = term or _get_current_term()
    academic_year = getattr(term, "academic_year", None) if term else None

    base = _invoice_base_qs()
    term_invoices = base.filter(term=term) if term else base.none()
    year_invoices = base.filter(term__academic_year=academic_year) if academic_year else base.none()

    def agg(invoice_qs):
        billed = invoice_qs.aggregate(x=Sum("total_amount"))["x"] or Decimal("0")
        billed = Decimal(str(billed))

        collected = _collected_for_invoices(invoice_qs)

        outstanding = billed - collected

        invoice_count = invoice_qs.count()
        students_outstanding = invoice_qs.filter(balance__gt=0).values("student_id").distinct().count()

        return {
            "billed": billed,
            "collected": collected,
            "outstanding": outstanding,
            "invoice_count": invoice_count,
            "students_outstanding": students_outstanding,
        }

    term_stats = agg(term_invoices)
    year_stats = agg(year_invoices)

    # Unmatched bank txns = NOT linked to a Payment (therefore not linked to any student admission number)
    bank_qs = BankTransaction.objects.all()
    if _model_has_field(BankTransaction, "is_active"):
        bank_qs = bank_qs.filter(is_active=True)

    unmatched_bank = (
        bank_qs.filter(payment__isnull=True)
        .exclude(processing_status__in=["failed", "duplicate"])
        .count()
    )

    # Payments today (completed)
    today = timezone.localdate()
    pay_qs = _completed_payments_base_qs()
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
        UserRole.ACCOUNTANT: "portal:dashboard_bursar",
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
    kpis = _finance_kpis()

    term = kpis["term"]
    academic_year = kpis["academic_year"]
    term_stats = kpis["term_stats"]
    year_stats = kpis["year_stats"]

    total_students = _get_active_students_qs().count()
    staff_count = _get_staff_count()

    # Finance URLs (REAL from your finance/urls.py)
    finance_dashboard_url = _safe_reverse("finance:dashboard", default=_safe_reverse("portal:finance_overview"))
    invoices_url = _safe_reverse("finance:invoice_list", default=finance_dashboard_url)
    payments_url = _safe_reverse("finance:payment_list", default=finance_dashboard_url)
    bank_url = _safe_reverse("finance:bank_transaction_list", default=finance_dashboard_url)
    outstanding_url = _safe_reverse("finance:outstanding_report", default=invoices_url)

    # Add term filter to some links
    term_qs = f"?term={term.pk}" if term else ""
    invoices_term_url = f"{invoices_url}{term_qs}"
    outstanding_term_url = f"{outstanding_url}{term_qs}"

    billed = Decimal(str(term_stats["billed"] or 0))
    collected = Decimal(str(term_stats["collected"] or 0))
    outstanding = Decimal(str(term_stats["outstanding"] or 0))
    rate = (collected / billed * 100) if billed > 0 else Decimal("0")

    year_billed = Decimal(str(year_stats["billed"] or 0))
    year_collected = Decimal(str(year_stats["collected"] or 0))
    year_rate = (year_collected / year_billed * 100) if year_billed > 0 else Decimal("0")

    context = {
        "current_term": term,
        "current_academic_year": academic_year,
        "stat_cards": [
            {
                "title": "Total Students",
                "value": f"{total_students:,}",
                "icon": "mdi-account-group",
                "bg": "bg-gradient-primary",
                "url": _safe_reverse("portal:academics_overview"),
                "helper": "Active/enrolled students",
            },
            {
                "title": "Staff Members",
                "value": f"{staff_count:,}",
                "icon": "mdi-account-tie",
                "bg": "bg-gradient-success",
                "url": _safe_reverse("portal:settings_overview"),
                "helper": "Admins · Teachers · Bursar",
            },
            {
                "title": "Billed (This Term)",
                "value": _fmt_kes(billed),
                "icon": "mdi-file-document",
                "bg": "bg-gradient-info",
                "url": invoices_term_url,
                "helper": f"Billed: {_fmt_kes(year_billed)}",
            },
            {
                "title": "Collected (This Term)",
                "value": _fmt_kes(collected),
                "icon": "mdi-cash",
                "bg": "bg-gradient-success",
                "url": payments_url,
                "helper": f"Term rate: {rate:.1f}% · Year rate: {year_rate:.1f}%",
            },
            # {
            #     "title": "Outstanding (This Term)",
            #     "value": _fmt_kes(outstanding),
            #     "icon": "mdi-alert-circle",
            #     "bg": "bg-gradient-warning",
            #     "url": outstanding_term_url,
            #     "helper": f"{term_stats['students_outstanding']} student(s) owing",
            # },
            {
                "title": "Bank Txns",
                "value": f"{kpis['unmatched_bank_transactions']:,}",
                "icon": "mdi-bank",
                "bg": "bg-gradient-danger",
                "url": bank_url,
                "helper": "Not linked to payment/student",
            },
        ],
    }

    return render(request, "dashboard/admin.html", context)


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT])
def dashboard_bursar(request):
    """
    Bursar/Accountant dashboard focused on finance.
    Uses DB data (invoices/payments/bank txns).
    """
    kpis = _finance_kpis()
    term = kpis["term"]
    term_stats = kpis["term_stats"]

    billed = Decimal(str(term_stats["billed"] or 0))
    collected = Decimal(str(term_stats["collected"] or 0))
    outstanding = Decimal(str(term_stats["outstanding"] or 0))
    students_outstanding = term_stats["students_outstanding"] or 0

    collection_rate = (collected / billed * 100) if billed > 0 else Decimal("0")

    invoices_url = _safe_reverse("finance:invoice_list", default=_safe_reverse("finance:dashboard"))
    payments_url = _safe_reverse("finance:payment_list", default=_safe_reverse("finance:dashboard"))
    bank_url = _safe_reverse("finance:bank_transaction_list", default=_safe_reverse("finance:dashboard"))
    record_payment_url = _safe_reverse("finance:payment_record", default=payments_url)
    outstanding_url = _safe_reverse("finance:outstanding_report", default=invoices_url)

    term_qs = f"?term={term.pk}" if term else ""
    invoices_term_url = f"{invoices_url}{term_qs}"
    outstanding_term_url = f"{outstanding_url}{term_qs}"

    # Top outstanding balances (current term) - based on Invoice.balance
    top_invoices = _invoice_base_qs()
    if term:
        top_invoices = top_invoices.filter(term=term)
    top_invoices = top_invoices.filter(balance__gt=0).order_by("-balance")[:10]

    def _priority(amount):
        amount = Decimal(str(amount or 0))
        if amount >= 50000:
            return ("High", "danger")
        if amount >= 20000:
            return ("Medium", "warning")
        return ("Low", "info")

    balances = []
    for inv in top_invoices:
        student = inv.student
        pr_label, pr_class = _priority(inv.balance)

        student_class = (
            getattr(student, "classroom", None)
            or getattr(student, "current_class", None)
            or getattr(student, "grade_level", None)
            or getattr(student, "grade", None)
            or ""
        )
        guardian = (
            getattr(student, "guardian_name", None)
            or getattr(student, "parent_name", None)
            or getattr(student, "contacts", None)
            or "-"
        )

        balances.append(
            {
                "student": getattr(student, "full_name", str(student)),
                "class": str(student_class),
                "guardian": str(guardian),
                "amount": _fmt_kes(inv.balance),
                "priority": pr_label,
                "priority_class": pr_class,
                "invoice_number": getattr(inv, "invoice_number", ""),
                "invoice_url": _safe_reverse("finance:invoice_detail", default="#", kwargs={"pk": inv.pk}),
            }
        )

    # Recent payments (latest)
    pay_qs = _completed_payments_base_qs()
    recent_payments = pay_qs.select_related("student", "invoice").order_by("-payment_date")[:10]

    context = {
        "current_term": term,
        "finance_widgets": [
            {
                "label": "Total Billed",
                "value": _fmt_kes(billed),
                "accent": "primary",
                "helper": "Current term invoices",
                "url": invoices_term_url,
            },
            {
                "label": "Collected",
                "value": _fmt_kes(collected),
                "accent": "success",
                "helper": f"{collection_rate:.1f}% collection rate",
                "url": payments_url,
            },
            {
                "label": "Outstanding",
                "value": _fmt_kes(outstanding),
                "accent": "warning",
                "helper": f"{students_outstanding} student(s)",
                "url": outstanding_term_url,
            },
            {
                "label": "Unmatched Bank Txns",
                "value": f"{kpis['unmatched_bank_transactions']:,}",
                "accent": "danger",
                "helper": "Not linked to any payment/student",
                "url": bank_url,
            },
            {
                "label": "Record Payment",
                "value": "",
                "accent": "info",
                "helper": "Manual payment entry",
                "url": record_payment_url,
            },
        ],
        "balances": balances,
        "recent_payments": recent_payments,
        # keep sample fee events (allowed)
        "fee_events": [
            {"title": "Term fees deadline", "date": "Dec 15, 2025"},
            {"title": "Transport fee review", "date": "Dec 20, 2025"},
            {"title": "Bursary applications close", "date": "Jan 5, 2026"},
        ],
    }

    return render(request, "dashboard/bursar.html", context)


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.TEACHER])
def dashboard_teacher(request):
    # sample
    context = {
        "teaching_cards": [
            {"label": "My Classes", "value": "4", "icon": "mdi-google-classroom", "trend": "Active", "trend_class": "success"},
            {"label": "Total Students", "value": "156", "icon": "mdi-account-group", "trend": "Across all classes", "trend_class": "muted"},
            {"label": "Pending Marks", "value": "2", "icon": "mdi-file-document-edit", "trend": "Assessments", "trend_class": "warning"},
        ],
        "schedule": [
            {"time": "8:00 - 8:40", "class_name": "Grade 8A", "room": "Room 12", "topic": "Mathematics"},
            {"time": "8:45 - 9:25", "class_name": "Grade 7B", "room": "Room 8", "topic": "Mathematics"},
            {"time": "10:00 - 10:40", "class_name": "Grade 9", "room": "Lab 2", "topic": "Science"},
            {"time": "11:00 - 11:40", "class_name": "Grade 6A", "room": "Room 5", "topic": "Mathematics"},
        ],
    }
    return render(request, "dashboard/teacher.html", context)


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.PARENT, UserRole.STUDENT])
def dashboard_parent(request):
    # sample
    context = {
        "children": [
            {
                "name": "James Mwangi",
                "classroom": "Grade 8A",
                "status": "Active",
                "badge_class": "success",
                "attendance": "94%",
                "average": "B+",
                "next_event": "End of Term Exams - Dec 10",
            },
            {
                "name": "Grace Mwangi",
                "classroom": "Grade 5B",
                "status": "Active",
                "badge_class": "success",
                "attendance": "98%",
                "average": "A-",
                "next_event": "Sports Day - Dec 8",
            },
        ],
    }
    return render(request, "dashboard/parent.html", context)


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
    term = _get_current_term()
    students_count = _get_active_students_qs().count()

    invoices_qs = _invoice_base_qs()
    if term:
        invoices_qs = invoices_qs.filter(term=term)

    # Students that already have an invoice this term
    invoiced_students = invoices_qs.values("student_id").distinct().count()
    pending_invoices = max(0, students_count - invoiced_students)

    bank_qs = BankTransaction.objects.all()
    if _model_has_field(BankTransaction, "is_active"):
        bank_qs = bank_qs.filter(is_active=True)

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
    # sample
    links = [
        {"title": "School Profile", "description": "Update school information", "url": "#"},
        {"title": "Academic Years", "description": "Manage academic years and terms", "url": "#"},
        {"title": "User Management", "description": "Manage staff and user accounts", "url": "#"},
        {"title": "System Configuration", "description": "General system settings", "url": "#"},
    ]
    return render(request, "sections/settings.html", {"settings_links": links})


@login_required
def blank_page(request):
    return render(request, "pages/blank.html")


# =============================================================================
# HOME HELPERS (keep sample except accountant quick stats)
# =============================================================================

def _get_quick_stats(user):
    role = user.role

    if role == UserRole.ACCOUNTANT:
        kpis = _finance_kpis()
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