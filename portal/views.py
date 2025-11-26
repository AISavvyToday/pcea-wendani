# portal/views.py
from django.shortcuts import render

def home(request):
    context = {
        "quick_stats": [
            {"label": "Learners", "value": "1,248", "delta": "+32 vs last term", "icon": "mdi-account-group", "color": "primary"},
            {"label": "Staff", "value": "87", "delta": "Fully staffed", "icon": "mdi-account-tie", "color": "info"},
            {"label": "Attendance", "value": "96%", "delta": "Today", "icon": "mdi-check-circle", "color": "success"},
            {"label": "Open Tickets", "value": "12", "delta": "3 critical", "icon": "mdi-alert-decagram", "color": "danger"},
        ],
        "quick_actions": [
            {"label": "Admin Workspace", "helper": "Full oversight", "icon": "mdi-shield-account", "url_name": "portal:dashboard_admin"},
            {"label": "Bursar Console", "helper": "Fees & payments", "icon": "mdi-cash-multiple", "url_name": "portal:dashboard_bursar"},
            {"label": "Teacher Planner", "helper": "Schedules & grading", "icon": "mdi-teach", "url_name": "portal:dashboard_teacher"},
            {"label": "Parent View", "helper": "Student progress", "icon": "mdi-account-child", "url_name": "portal:dashboard_parent"},
        ],
        "notices": [
            {"title": "Term 3 visiting day", "timeframe": "Saturday 9:00 AM", "badge": "info"},
            {"title": "Board report due", "timeframe": "Tomorrow 4:00 PM", "badge": "warning"},
            {"title": "Transport audit", "timeframe": "Next week", "badge": "success"},
        ],
        "summaries": [
            {"title": "Pending invoices", "description": "Awaiting approval", "value": "24", "trend": "4 urgent", "trend_class": "danger"},
            {"title": "Library loans", "description": "Checked out items", "value": "312", "trend": "5 overdue", "trend_class": "warning"},
            {"title": "Helpdesk SLA", "description": "Response within 4h", "value": "92%", "trend": "+3% this week", "trend_class": "success"},
        ],
    }
    return render(request, "portal/home.html", context)


def dashboard_admin(request):
    context = {
        "stat_cards": [
            {"title": "Active Learners", "value": "1,248", "meta": "Updated 5 mins ago", "icon": "mdi-account-multiple", "bg": "bg-gradient-primary"},
            {"title": "Staff On Duty", "value": "73", "meta": "12 off campus", "icon": "mdi-account-tie", "bg": "bg-gradient-info"},
            {"title": "Facility Capacity", "value": "84%", "meta": "Comfortable range", "icon": "mdi-home-city-outline", "bg": "bg-gradient-success"},
        ],
        "tickets": [
            {"person": "Grace W.", "avatar": "assets/images/faces/face1.jpg", "subject": "ICT Lab refresh", "status": "Open", "badge": "warning", "updated": "Today 09:20", "ref": "PW-8934"},
            {"person": "James K.", "avatar": "assets/images/faces/face2.jpg", "subject": "Transport rota", "status": "In review", "badge": "info", "updated": "Yesterday", "ref": "PW-8928"},
            {"person": "Mary A.", "avatar": "assets/images/faces/face3.jpg", "subject": "Dorm maintenance", "status": "Closed", "badge": "success", "updated": "Mon", "ref": "PW-8899"},
            {"person": "Esther P.", "avatar": "assets/images/faces/face4.jpg", "subject": "New enrolment", "status": "Escalated", "badge": "danger", "updated": "Sun", "ref": "PW-8887"},
        ],
    }
    return render(request, "dashboard/admin.html", context)


def dashboard_bursar(request):
    context = {
        "finance_widgets": [
            {"label": "Fee Collections", "value": "KES 4.8M", "helper": "This month", "accent": "success"},
            {"label": "Outstanding", "value": "KES 1.2M", "helper": "Across 48 learners", "accent": "warning"},
            {"label": "Petty Cash", "value": "KES 145K", "helper": "Updated today", "accent": "info"},
            {"label": "Approvals", "value": "6 pending", "helper": "Need your review", "accent": "danger"},
        ],
        "balances": [
            {"student": "Nicole Wafula", "class": "Grade 9", "guardian": "Mrs. Wafula", "amount": "KES 31,000", "priority": "High", "priority_class": "danger"},
            {"student": "Misha Kuria", "class": "Grade 9", "guardian": "Mr. Kuria", "amount": "KES 44,250", "priority": "Medium", "priority_class": "warning"},
            {"student": "Victor Kariuki", "class": "Grade 9", "guardian": "Mr. Kariuki", "amount": "KES 22,500", "priority": "Low", "priority_class": "success"},
        ],
        "fee_events": [
            {"title": "Transport levy review", "date": "Thu 2:00 PM"},
            {"title": "Finance committee", "date": "Fri 9:00 AM"},
            {"title": "Term 3 invoicing", "date": "Mon next week"},
        ],
    }
    return render(request, "dashboard/bursar.html", context)


def dashboard_teacher(request):
    context = {
        "teaching_cards": [
            {"label": "Lessons Today", "value": "6", "icon": "mdi-calendar-clock", "trend": "2 practicals", "trend_class": "info"},
            {"label": "Assignments Due", "value": "4", "icon": "mdi-file-document", "trend": "Marking due tomorrow", "trend_class": "warning"},
            {"label": "Attendance", "value": "98%", "icon": "mdi-account-check", "trend": "+1% vs last week", "trend_class": "success"},
        ],
        "schedule": [
            {"time": "08:00 - 09:00", "class_name": "Grade 8 - Math", "room": "Block A / 2", "topic": "Algebra review"},
            {"time": "09:30 - 10:30", "class_name": "Grade 9 - Physics", "room": "Lab 1", "topic": "Electric circuits"},
            {"time": "11:00 - 12:00", "class_name": "Grade 7 - STEM", "room": "Innovation Hub", "topic": "Robotics basics"},
        ],
    }
    return render(request, "dashboard/teacher.html", context)


def dashboard_parent(request):
    context = {
        "children": [
            {"name": "Ryan Njoroge", "classroom": "Grade 7 Jade", "status": "On track", "badge_class": "success", "attendance": "95%", "average": "B+", "next_event": "STEM expo – Fri"},
            {"name": "Faith Njeri", "classroom": "Grade 4 Pearl", "status": "Support", "badge_class": "warning", "attendance": "90%", "average": "B", "next_event": "Reading clinic – Tue"},
        ],
    }
    return render(request, "dashboard/parent.html", context)


def academics_overview(request):
    widgets = [
        {"label": "Class timetables", "description": "Live calendars per stream", "icon": "mdi-calendar-blank"},
        {"label": "Assessment banks", "description": "Common exams & rubrics", "icon": "mdi-file-chart"},
        {"label": "CBC trackers", "description": "Competency-based milestones", "icon": "mdi-chart-line"},
        {"label": "Clubs & events", "description": "Co-curricular schedule", "icon": "mdi-account-group"},
    ]
    return render(request, "sections/academics.html", {"academic_widgets": widgets})


def finance_overview(request):
    queues = [
        {"title": "Pending receipts", "subtitle": "Awaiting proof", "count": "12", "badge_class": "primary", "percent": 60},
        {"title": "Refund requests", "subtitle": "Transport & meals", "count": "4", "badge_class": "warning", "percent": 35},
        {"title": "Capital approvals", "subtitle": "ICT, facilities", "count": "3", "badge_class": "success", "percent": 80},
    ]
    return render(request, "sections/finance.html", {"queues": queues})


def communications_overview(request):
    broadcasts = [
        {"title": "Weekly bulletin", "summary": "Highlights & reminders shared with guardians.", "timestamp": "Sent 8:00 AM"},
        {"title": "STEM expo brief", "summary": "Logistics update for exhibitors.", "timestamp": "Draft due tonight"},
    ]
    approvals = [
        {"title": "Sports day notice", "owner": "Games coach", "state": "Pending", "badge_class": "warning"},
        {"title": "Security update", "owner": "Operations", "state": "Approved", "badge_class": "success"},
    ]
    return render(request, "sections/communications.html", {"broadcasts": broadcasts, "approvals": approvals})


def resources_overview(request):
    resources = [
        {"title": "Policies & SOPs", "type": "PDF bundle", "description": "HR, finance, and safeguarding policies.", "icon": "mdi-file-document"},
        {"title": "Lesson templates", "type": "Docs", "description": "Editable lesson plan formats.", "icon": "mdi-file-outline"},
        {"title": "Media assets", "type": "Drive", "description": "Logos, photo packs, and brand kit.", "icon": "mdi-folder-image"},
    ]
    return render(request, "sections/resources.html", {"resources": resources})


def settings_overview(request):
    links = [
        {"title": "User & Role Management", "description": "Invite staff, assign permissions, reset credentials.", "cta": "Manage users"},
        {"title": "Academic Sessions", "description": "Configure terms, grading scales, holidays.", "cta": "Edit sessions"},
        {"title": "Integrations", "description": "Payments, SMS, RouteLLM APIs.", "cta": "Configure integrations"},
    ]
    return render(request, "sections/settings.html", {"settings_links": links})


def blank_page(request):
    return render(request, "pages/blank.html")


def login_page(request):
    return render(request, "auth/login.html")


def register_page(request):
    return render(request, "auth/register.html")