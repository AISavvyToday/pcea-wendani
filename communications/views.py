# communications/views.py
"""
Communications module views for announcements, SMS, and email management.
"""

import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, DetailView, View
from django.urls import reverse_lazy
from django.db.models import Q
from django.utils import timezone
from core.mixins import RoleRequiredMixin, OrganizationFilterMixin
from core.models import UserRole
from accounts.models import User
from students.models import Student, Parent
from academics.models import Staff
from .models import Announcement, SMSNotification, EmailNotification, NotificationTemplate
from swift_sms_credits.sms_service import SMSService
from .services.email_service import EmailService

logger = logging.getLogger(__name__)


class AnnouncementListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    """List all announcements."""
    model = Announcement
    template_name = 'communications/announcement_list.html'
    context_object_name = 'announcements'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]
    paginate_by = 20


class AnnouncementCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    """Create a new announcement."""
    model = Announcement
    template_name = 'communications/announcement_form.html'
    fields = ['title', 'message', 'target_audience', 'send_sms', 'send_email']
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('communications:announcement_list')
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.organization = self.request.organization
        return super().form_valid(form)


class AnnouncementDetailView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, DetailView):
    """View announcement details."""
    model = Announcement
    template_name = 'communications/announcement_detail.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]


class SendAnnouncementView(LoginRequiredMixin, RoleRequiredMixin, View):
    """Send an announcement to selected audience."""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    
    def post(self, request, pk):
        announcement = get_object_or_404(Announcement, pk=pk, organization=request.organization)
        
        if announcement.is_sent:
            messages.warning(request, 'This announcement has already been sent.')
            return redirect('communications:announcement_detail', pk=pk)
        
        try:
            recipients = self._get_recipients(announcement, request.organization)
            
            sms_count = 0
            email_count = 0
            
            # SMS sending is temporarily disabled - logic kept ready for future use
            if announcement.send_sms:
                # TODO: Uncomment when ready to send SMS
                # sms_service = SMSService()
                # # Prepare recipients for package service (expects 'phone_number' and 'message' in each dict)
                # bulk_recipients = []
                # for r in recipients:
                #     if r.get('phone'):
                #         # Get parent object if available
                #         parent_obj = None
                #         if r.get('student'):
                #             parent_obj = r['student'].primary_parent
                #         elif 'parent' in r:
                #             # If parent object was passed directly
                #             parent_obj = r['parent']
                #         
                #         bulk_recipients.append({
                #             'phone_number': r['phone'],
                #             'message': announcement.message,
                #             'parent': parent_obj,  # Pass parent object if available
                #         })
                # 
                # # Package service returns list of SMSNotification instances if model provided
                # # Since our model has different fields, we'll create our own records
                # sms_notifications = sms_service.send_bulk_sms(
                #     recipients=bulk_recipients,
                #     organization=request.organization,
                #     user=request.user,
                #     purpose='announcement',
                #     sms_notification_model=None  # We'll create our own records
                # )
                # 
                # # Create our own SMSNotification records and count successes
                # # Package service deducts credits and sends SMS, we just track it
                # for r in recipients:
                #     if r.get('phone'):
                #         SMSNotification.objects.create(
                #             organization=request.organization,
                #             recipient_phone=r['phone'],
                #             message=announcement.message,
                #             status='sent',  # Assume sent if no exception
                #             sent_at=timezone.now(),
                #             purpose='announcement',
                #             related_announcement=announcement,
                #             triggered_by=request.user,
                #         )
                #         sms_count += 1
                messages.info(request, 'SMS sending is currently disabled. Logic is ready but commented out.')
                sms_count = 0
            
            if announcement.send_email:
                email_service = EmailService()
                email_notifications = email_service.send_bulk_email(
                    recipients=[r['email'] for r in recipients if r.get('email')],
                    subject=announcement.title,
                    message=announcement.message,
                    organization=request.organization,
                    purpose='announcement',
                    triggered_by=request.user
                )
                email_count = sum(1 for n in email_notifications if n.status == 'sent')
            
            announcement.is_sent = True
            announcement.sent_at = timezone.now()
            announcement.sms_count = sms_count
            announcement.email_count = email_count
            announcement.save()
            
            messages.success(request, f'Announcement sent! SMS: {sms_count}, Email: {email_count}')
            logger.info(f"Announcement {announcement.id} sent by {request.user.email}")
        
        except Exception as e:
            logger.error(f"Error sending announcement: {str(e)}", exc_info=True)
            messages.error(request, f'Error sending announcement: {str(e)}')
        
        return redirect('communications:announcement_detail', pk=pk)
    
    def _get_recipients(self, announcement, organization):
        """Get recipients based on target audience."""
        recipients = []
        
        if announcement.target_audience == 'all':
            # Get all parents
            parents = Parent.objects.filter(organization=organization, is_active=True)
            for parent in parents:
                recipients.append({
                    'phone': parent.phone_primary,
                    'email': parent.email,
                    'parent': parent,  # Include parent object for package service
                })
        
        elif announcement.target_audience == 'parents':
            parents = Parent.objects.filter(organization=organization, is_active=True)
            for parent in parents:
                recipients.append({
                    'phone': parent.phone_primary,
                    'email': parent.email,
                    'parent': parent,  # Include parent object for package service
                })
        
        elif announcement.target_audience == 'teachers':
            staff = Staff.objects.filter(organization=organization, status='active', staff_type='teaching')
            for s in staff:
                if s.user and s.user.email:
                    recipients.append({
                        'phone': s.user.phone_number or '',
                        'email': s.user.email,
                    })
        
        elif announcement.target_audience == 'students':
            students = Student.objects.filter(organization=organization, status='active')
            for student in students:
                # Get parent contact
                parent = student.primary_parent
                if parent:
                    recipients.append({
                        'phone': parent.phone_primary,
                        'email': parent.email,
                        'student': student,
                        'parent': parent,  # Include parent object for package service
                    })
        
        return recipients


class SMSNotificationListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    """List SMS notifications."""
    model = SMSNotification
    template_name = 'communications/sms_notification_list.html'
    context_object_name = 'sms_notifications'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]
    paginate_by = 50
    
    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        return queryset.order_by('-created_at')


class EmailNotificationListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    """List email notifications."""
    model = EmailNotification
    template_name = 'communications/email_notification_list.html'
    context_object_name = 'email_notifications'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]
    paginate_by = 50
    
    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        return queryset.order_by('-created_at')


class NotificationTemplateListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    """List notification templates."""
    model = NotificationTemplate
    template_name = 'communications/notification_template_list.html'
    context_object_name = 'templates'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    paginate_by = 20


class NotificationTemplateCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    """Create a new notification template."""
    model = NotificationTemplate
    template_name = 'communications/notification_template_form.html'
    fields = ['name', 'template_type', 'subject', 'template_text', 'variables', 'description']
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('communications:notification_template_list')
    
    def form_valid(self, form):
        form.instance.organization = self.request.organization
        return super().form_valid(form)
