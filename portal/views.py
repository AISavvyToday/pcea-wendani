# portal/views.py
"""
Portal views for dashboards, sections, and authentication.
"""

import logging
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache

from core.models import UserRole
from accounts.decorators import role_required, admin_required, finance_required, teacher_required

logger = logging.getLogger(__name__)


# =============================================================================
# AUTHENTICATION VIEWS
# =============================================================================

@never_cache
@require_http_methods(["GET", "POST"])
def login_view(request):
    """
    Handle user login with email and password.
    Redirects authenticated users to their role-based dashboard.
    """
    # Redirect if already logged in
    if request.user.is_authenticated:
        logger.debug(f"Already authenticated user '{request.user.email}' accessing login page")
        return redirect('portal:role_redirect')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        remember_me = request.POST.get('remember_me')

        logger.info(f"Login attempt for email: {email}")

        if not email or not password:
            messages.error(request, 'Please enter both email and password.')
            return render(request, 'auth/login.html')

        # Authenticate user
        user = authenticate(request, username=email, password=password)

        if user is not None:
            # Check if account is locked
            if hasattr(user, 'is_locked') and user.is_locked():
                logger.warning(f"Login attempt for locked account: {email}")
                messages.error(request,
                               'Your account is temporarily locked. Please try again later or contact support.')
                return render(request, 'auth/login.html')

            # Check if account is active
            if not user.is_active:
                logger.warning(f"Login attempt for inactive account: {email}")
                messages.error(request, 'Your account is inactive. Please contact the administrator.')
                return render(request, 'auth/login.html')

            # Log the user in
            login(request, user)

            # Reset failed login attempts on successful login
            if hasattr(user, 'reset_failed_login'):
                user.reset_failed_login()

            # Set session expiry based on "remember me"
            if not remember_me:
                request.session.set_expiry(0)  # Expire on browser close

            logger.info(f"User '{email}' logged in successfully with role '{user.role}'")
            messages.success(request, f'Welcome back, {user.get_short_name()}!')

            # Redirect to intended page or role-based dashboard
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('portal:role_redirect')

        else:
            logger.warning(f"Failed login attempt for email: {email}")
            messages.error(request, 'Invalid email or password. Please try again.')

    return render(request, 'auth/login.html')


@login_required
@require_http_methods(["GET", "POST"])
def logout_view(request):
    """
    Log out the current user and redirect to login page.
    """
    user_email = request.user.email
    logout(request)
    logger.info(f"User '{user_email}' logged out")
    messages.info(request, 'You have been logged out successfully.')
    return redirect('portal:login')


@never_cache
@require_http_methods(["GET", "POST"])
def register_view(request):
    """
    User registration view.
    For now, registration is disabled - users are created by admins.
    """
    # Redirect if already logged in
    if request.user.is_authenticated:
        return redirect('portal:role_redirect')

    if request.method == 'POST':
        # Registration is currently admin-only
        messages.info(request,
                      'Registration is currently handled by school administrators. Please contact the school office.')
        return render(request, 'auth/register.html')

    return render(request, 'auth/register.html')


@login_required
def role_redirect(request):
    """
    Redirect authenticated users to their role-appropriate dashboard.
    """
    user = request.user
    role = user.role

    logger.debug(f"Role redirect for user '{user.email}' with role '{role}'")

    # Map roles to dashboard URLs
    dashboard_map = {
        UserRole.SUPER_ADMIN: 'portal:dashboard_admin',
        UserRole.SCHOOL_ADMIN: 'portal:dashboard_admin',
        UserRole.ACCOUNTANT: 'portal:dashboard_bursar',
        UserRole.TEACHER: 'portal:dashboard_teacher',
        UserRole.PARENT: 'portal:dashboard_parent',
        UserRole.STUDENT: 'portal:dashboard_parent',
    }

    redirect_url = dashboard_map.get(role, 'portal:home')
    logger.info(f"Redirecting user '{user.email}' to '{redirect_url}'")

    return redirect(redirect_url)


# =============================================================================
# DASHBOARD VIEWS
# =============================================================================

@login_required
def home(request):
    """
    Main home/landing page after login.
    Shows role-appropriate quick stats and actions.
    """
    user = request.user

    # Build context based on role
    context = {
        'quick_stats': _get_quick_stats(user),
        'quick_actions': _get_quick_actions(user),
        'notices': _get_notices(user),
        'summaries': _get_summaries(user),
    }

    return render(request, 'portal/home.html', context)


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN])
def dashboard_admin(request):
    """
    Administrator dashboard with full system overview.
    """
    context = {
        'stat_cards': [
            {
                'title': 'Total Students',
                'value': '1,247',
                'icon': 'mdi-account-group',
                'bg': 'bg-gradient-primary',
                'meta': '+12 this term',
            },
            {
                'title': 'Staff Members',
                'value': '86',
                'icon': 'mdi-account-tie',
                'bg': 'bg-gradient-success',
                'meta': '4 on leave',
            },
            {
                'title': 'Fee Collection',
                'value': 'KES 4.2M',
                'icon': 'mdi-cash',
                'bg': 'bg-gradient-warning',
                'meta': '78% of target',
            },
        ],
    }

    return render(request, 'dashboard/admin.html', context)


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT])
def dashboard_bursar(request):
    """
    Bursar/Accountant dashboard focused on finance.
    """
    context = {
        'finance_widgets': [
            {'label': 'Total Billed', 'value': 'KES 12.4M', 'accent': 'primary', 'helper': 'This term'},
            {'label': 'Collected', 'value': 'KES 9.8M', 'accent': 'success', 'helper': '79% collection rate'},
            {'label': 'Outstanding', 'value': 'KES 2.6M', 'accent': 'warning', 'helper': '312 students'},
            {'label': 'Overdue', 'value': 'KES 890K', 'accent': 'danger', 'helper': '45 students'},
        ],
        'balances': [
            {'student': 'John Kamau', 'class': 'Grade 8A', 'guardian': 'Mary Kamau', 'amount': 'KES 45,000',
             'priority': 'High', 'priority_class': 'danger'},
            {'student': 'Faith Wanjiku', 'class': 'Grade 7B', 'guardian': 'Peter Wanjiku', 'amount': 'KES 32,500',
             'priority': 'Medium', 'priority_class': 'warning'},
            {'student': 'Brian Ochieng', 'class': 'Grade 9', 'guardian': 'Grace Ochieng', 'amount': 'KES 28,000',
             'priority': 'Medium', 'priority_class': 'warning'},
            {'student': 'Alice Muthoni', 'class': 'Grade 6A', 'guardian': 'James Muthoni', 'amount': 'KES 15,000',
             'priority': 'Low', 'priority_class': 'info'},
        ],
        'fee_events': [
            {'title': 'Term 3 fees deadline', 'date': 'Dec 15, 2025'},
            {'title': 'Transport fee review', 'date': 'Dec 20, 2025'},
            {'title': 'Bursary applications close', 'date': 'Jan 5, 2026'},
        ],
    }

    return render(request, 'dashboard/bursar.html', context)


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.TEACHER])
def dashboard_teacher(request):
    """
    Teacher dashboard focused on classes and academics.
    """
    context = {
        'teaching_cards': [
            {'label': 'My Classes', 'value': '4', 'icon': 'mdi-google-classroom', 'trend': 'Active',
             'trend_class': 'success'},
            {'label': 'Total Students', 'value': '156', 'icon': 'mdi-account-group', 'trend': 'Across all classes',
             'trend_class': 'muted'},
            {'label': 'Pending Marks', 'value': '2', 'icon': 'mdi-file-document-edit', 'trend': 'Assessments',
             'trend_class': 'warning'},
        ],
        'schedule': [
            {'time': '8:00 - 8:40', 'class_name': 'Grade 8A', 'room': 'Room 12', 'topic': 'Mathematics'},
            {'time': '8:45 - 9:25', 'class_name': 'Grade 7B', 'room': 'Room 8', 'topic': 'Mathematics'},
            {'time': '10:00 - 10:40', 'class_name': 'Grade 9', 'room': 'Lab 2', 'topic': 'Science'},
            {'time': '11:00 - 11:40', 'class_name': 'Grade 6A', 'room': 'Room 5', 'topic': 'Mathematics'},
        ],
    }

    return render(request, 'dashboard/teacher.html', context)


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.PARENT, UserRole.STUDENT])
def dashboard_parent(request):
    """
    Parent/Student dashboard showing children's information.
    """
    context = {
        'children': [
            {
                'name': 'James Mwangi',
                'classroom': 'Grade 8A',
                'status': 'Active',
                'badge_class': 'success',
                'attendance': '94%',
                'average': 'B+',
                'next_event': 'End of Term Exams - Dec 10',
            },
            {
                'name': 'Grace Mwangi',
                'classroom': 'Grade 5B',
                'status': 'Active',
                'badge_class': 'success',
                'attendance': '98%',
                'average': 'A-',
                'next_event': 'Sports Day - Dec 8',
            },
        ],
    }

    return render(request, 'dashboard/parent.html', context)


# =============================================================================
# SECTION VIEWS
# =============================================================================

@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.TEACHER])
def academics_overview(request):
    """
    Academics section overview.
    """
    widgets = [
        {'icon': 'mdi-calendar-clock', 'label': 'Timetables', 'description': 'Manage class schedules'},
        {'icon': 'mdi-clipboard-check', 'label': 'Attendance', 'description': 'Daily attendance tracking'},
        {'icon': 'mdi-file-document-edit', 'label': 'Examinations', 'description': 'Exams and assessments'},
        {'icon': 'mdi-certificate', 'label': 'Report Cards', 'description': 'Generate student reports'},
    ]

    return render(request, 'sections/academics.html', {'academic_widgets': widgets})


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT])
def finance_overview(request):
    """
    Finance section overview.
    """
    queues = [
        {'title': 'Pending Invoices', 'subtitle': 'Awaiting generation', 'count': 45, 'percent': 30,
         'badge_class': 'warning'},
        {'title': 'Unmatched Payments', 'subtitle': 'Need reconciliation', 'count': 12, 'percent': 15,
         'badge_class': 'danger'},
        {'title': 'Overdue Accounts', 'subtitle': 'Past due date', 'count': 28, 'percent': 45, 'badge_class': 'info'},
    ]

    return render(request, 'sections/finance.html', {'queues': queues})


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN])
def communications_overview(request):
    """
    Communications section overview.
    """
    broadcasts = [
        {'title': 'Term 3 Fee Reminder', 'summary': 'Sent to all parents with outstanding balances',
         'timestamp': '2 hours ago'},
        {'title': 'Sports Day Announcement', 'summary': 'Event details for Dec 8th', 'timestamp': '1 day ago'},
        {'title': 'Holiday Schedule', 'summary': 'School closing dates', 'timestamp': '3 days ago'},
    ]

    approvals = [
        {'title': 'Fee Waiver Request', 'owner': 'Mary Kamau (Parent)', 'state': 'Pending', 'badge_class': 'warning'},
        {'title': 'Leave Application', 'owner': 'John Odhiambo (Teacher)', 'state': 'Pending',
         'badge_class': 'warning'},
    ]

    return render(request, 'sections/communications.html', {'broadcasts': broadcasts, 'approvals': approvals})


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.TEACHER])
def resources_overview(request):
    """
    Learning resources section.
    """
    resources = [
        {'title': 'CBC Curriculum Guide', 'type': 'PDF Document', 'icon': 'mdi-file-pdf-box',
         'description': 'Official CBC implementation guide'},
        {'title': 'Assessment Templates', 'type': 'Excel Templates', 'icon': 'mdi-file-excel',
         'description': 'Standardized assessment forms'},
        {'title': 'Teaching Resources', 'type': 'Resource Pack', 'icon': 'mdi-folder-multiple',
         'description': 'Subject-specific materials'},
    ]

    return render(request, 'sections/resources.html', {'resources': resources})


@login_required
@role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN])
def settings_overview(request):
    """
    System settings section.
    """
    links = [
        {'title': 'School Profile', 'description': 'Update school information', 'url': '#'},
        {'title': 'Academic Years', 'description': 'Manage academic years and terms', 'url': '#'},
        {'title': 'User Management', 'description': 'Manage staff and user accounts', 'url': '#'},
        {'title': 'System Configuration', 'description': 'General system settings', 'url': '#'},
    ]

    return render(request, 'sections/settings.html', {'settings_links': links})


@login_required
def blank_page(request):
    """
    Blank placeholder page for features under development.
    """
    return render(request, 'pages/blank.html')


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_quick_stats(user):
    """
    Get role-appropriate quick stats for home page.
    """
    role = user.role

    if role in [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]:
        return [
            {'label': 'Total Students', 'value': '1,247', 'icon': 'mdi-account-group', 'color': 'primary',
             'delta': '+12 this term'},
            {'label': 'Staff Members', 'value': '86', 'icon': 'mdi-account-tie', 'color': 'success',
             'delta': '4 on leave'},
            {'label': 'Fee Collection', 'value': '78%', 'icon': 'mdi-cash', 'color': 'warning',
             'delta': 'KES 9.8M collected'},
            {'label': 'Attendance Today', 'value': '94%', 'icon': 'mdi-clipboard-check', 'color': 'info',
             'delta': '1,172 present'},
        ]
    elif role == UserRole.ACCOUNTANT:
        return [
            {'label': 'Today\'s Collections', 'value': 'KES 245K', 'icon': 'mdi-cash-plus', 'color': 'success',
             'delta': '12 payments'},
            {'label': 'Pending Invoices', 'value': '45', 'icon': 'mdi-file-document', 'color': 'warning',
             'delta': 'Awaiting generation'},
            {'label': 'Outstanding', 'value': 'KES 2.6M', 'icon': 'mdi-alert-circle', 'color': 'danger',
             'delta': '312 students'},
            {'label': 'Bank Transactions', 'value': '8', 'icon': 'mdi-bank', 'color': 'info',
             'delta': 'Unmatched today'},
        ]
    elif role == UserRole.TEACHER:
        return [
            {'label': 'My Classes', 'value': '4', 'icon': 'mdi-google-classroom', 'color': 'primary',
             'delta': '156 students'},
            {'label': 'Today\'s Lessons', 'value': '5', 'icon': 'mdi-book-open', 'color': 'success',
             'delta': '2 completed'},
            {'label': 'Pending Marks', 'value': '2', 'icon': 'mdi-file-edit', 'color': 'warning',
             'delta': 'Assessments due'},
            {'label': 'Attendance', 'value': '96%', 'icon': 'mdi-clipboard-check', 'color': 'info',
             'delta': 'My classes avg'},
        ]
    else:  # Parent/Student
        return [
            {'label': 'Children', 'value': '2', 'icon': 'mdi-account-child', 'color': 'primary', 'delta': 'Enrolled'},
            {'label': 'Fee Balance', 'value': 'KES 15K', 'icon': 'mdi-cash', 'color': 'warning', 'delta': 'Due Dec 15'},
            {'label': 'Attendance', 'value': '96%', 'icon': 'mdi-clipboard-check', 'color': 'success',
             'delta': 'This term'},
            {'label': 'Avg Grade', 'value': 'B+', 'icon': 'mdi-certificate', 'color': 'info', 'delta': 'All subjects'},
        ]


def _get_quick_actions(user):
    """
    Get role-appropriate quick actions for home page.
    """
    role = user.role

    if role in [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]:
        return [
            {'label': 'Add Student', 'icon': 'mdi-account-plus', 'url_name': 'portal:blank_page',
             'helper': 'Register new student'},
            {'label': 'Generate Invoices', 'icon': 'mdi-file-document-edit', 'url_name': 'portal:blank_page',
             'helper': 'Bulk invoice generation'},
            {'label': 'Send Announcement', 'icon': 'mdi-bullhorn', 'url_name': 'portal:blank_page',
             'helper': 'Broadcast to parents'},
            {'label': 'View Reports', 'icon': 'mdi-chart-bar', 'url_name': 'portal:blank_page',
             'helper': 'Analytics dashboard'},
        ]
    elif role == UserRole.ACCOUNTANT:
        return [
            {'label': 'Record Payment', 'icon': 'mdi-cash-plus', 'url_name': 'portal:blank_page',
             'helper': 'Manual payment entry'},
            {'label': 'Generate Invoices', 'icon': 'mdi-file-document-edit', 'url_name': 'portal:blank_page',
             'helper': 'Bulk invoice generation'},
            {'label': 'Bank Reconciliation', 'icon': 'mdi-bank-transfer', 'url_name': 'portal:blank_page',
             'helper': 'Match transactions'},
            {'label': 'Fee Statement', 'icon': 'mdi-file-chart', 'url_name': 'portal:blank_page',
             'helper': 'Generate statements'},
        ]
    elif role == UserRole.TEACHER:
        return [
            {'label': 'Take Attendance', 'icon': 'mdi-clipboard-check', 'url_name': 'portal:blank_page',
             'helper': 'Daily attendance'},
            {'label': 'Enter Marks', 'icon': 'mdi-file-document-edit', 'url_name': 'portal:blank_page',
             'helper': 'Assessment scores'},
            {'label': 'View Timetable', 'icon': 'mdi-calendar-clock', 'url_name': 'portal:blank_page',
             'helper': 'My schedule'},
            {'label': 'Class List', 'icon': 'mdi-account-group', 'url_name': 'portal:blank_page',
             'helper': 'Student roster'},
        ]
    else:  # Parent/Student
        return [
            {'label': 'View Results', 'icon': 'mdi-certificate', 'url_name': 'portal:blank_page',
             'helper': 'Academic performance'},
            {'label': 'Fee Statement', 'icon': 'mdi-file-chart', 'url_name': 'portal:blank_page',
             'helper': 'Payment history'},
            {'label': 'Announcements', 'icon': 'mdi-bullhorn', 'url_name': 'portal:blank_page',
             'helper': 'School notices'},
            {'label': 'Contact School', 'icon': 'mdi-email', 'url_name': 'portal:blank_page', 'helper': 'Send message'},
        ]


def _get_notices(user):
    """
    Get recent notices for home page.
    """
    # In production, fetch from database
    return [
        {'title': 'End of Term Exams', 'timeframe': 'Dec 10-14', 'badge': 'warning'},
        {'title': 'Sports Day', 'timeframe': 'Dec 8', 'badge': 'info'},
        {'title': 'School Closes', 'timeframe': 'Dec 15', 'badge': 'success'},
    ]


def _get_summaries(user):
    """
    Get summary cards for home page.
    """
    role = user.role

    if role in [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]:
        return [
            {'title': 'Enrollment', 'description': 'Current term', 'value': '1,247', 'trend': '+2.4%',
             'trend_class': 'success'},
            {'title': 'Collection Rate', 'description': 'Fee recovery', 'value': '78%', 'trend': '+5%',
             'trend_class': 'success'},
            {'title': 'Attendance', 'description': 'Term average', 'value': '94%', 'trend': '-1%',
             'trend_class': 'warning'},
        ]
    elif role == UserRole.ACCOUNTANT:
        return [
            {'title': 'Monthly Target', 'description': 'December', 'value': 'KES 3.2M', 'trend': '65% achieved',
             'trend_class': 'warning'},
            {'title': 'Overdue Amount', 'description': 'Past 30 days', 'value': 'KES 890K', 'trend': '45 accounts',
             'trend_class': 'danger'},
            {'title': 'Today\'s Receipts', 'description': 'All channels', 'value': 'KES 245K', 'trend': '12 payments',
             'trend_class': 'success'},
        ]
    else:
        return [
            {'title': 'Term Progress', 'description': 'Academic calendar', 'value': '85%', 'trend': '2 weeks left',
             'trend_class': 'info'},
            {'title': 'Upcoming Events', 'description': 'This month', 'value': '3', 'trend': 'View calendar',
             'trend_class': 'primary'},
            {'title': 'Unread Messages', 'description': 'From school', 'value': '2', 'trend': 'New',
             'trend_class': 'warning'},
        ]