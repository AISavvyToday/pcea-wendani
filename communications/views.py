# communications/views.py
"""
Communications module views for announcements, SMS, and email management.
"""

import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, DetailView, View, TemplateView
from django.urls import reverse_lazy
from django.db.models import Q
from django.utils import timezone
from core.mixins import RoleRequiredMixin, OrganizationFilterMixin
from core.models import UserRole
from accounts.models import User
from students.models import Student, Parent
from academics.models import Staff
from .models import Announcement, SMSNotification, EmailNotification, NotificationTemplate
from .services.sms_service import SMSService
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
    fields = ['title', 'message', 'target_audience', 'send_sms']
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('communications:announcement_list')
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.organization = self.request.organization
        form.instance.send_email = False  # Email disabled
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
            
            # SMS sending with placeholder replacement
            if announcement.send_sms:
                from .services.sms_template_service import SMSTemplateService
                template_service = SMSTemplateService()
                
                # TODO: Uncomment when ready to send SMS
                # sms_service = SMSService()
                # bulk_recipients = []
                # 
                # for r in recipients:
                #     if r.get('phone'):
                #         # Build context for placeholder replacement
                #         context = {
                #             'parent': r.get('parent'),
                #             'student': r.get('student'),
                #             'invoice': r.get('invoice'),
                #             'attendance': r.get('attendance'),
                #             'grade': r.get('grade'),
                #         }
                #         
                #         # Replace placeholders in message
                #         personalized_message = template_service.replace_placeholders(
                #             announcement.message,
                #             context
                #         )
                #         
                #         parent_obj = r.get('parent')
                #         bulk_recipients.append({
                #             'phone_number': r['phone'],
                #             'message': personalized_message,
                #             'parent': parent_obj,
                #         })
                # 
                # # Send SMS via package service
                # sms_notifications = sms_service.send_bulk_sms(
                #     recipients=bulk_recipients,
                #     organization=request.organization,
                #     user=request.user,
                #     purpose='announcement',
                #     sms_notification_model=None
                # )
                # 
                # # Create SMSNotification records
                # for r in recipients:
                #     if r.get('phone'):
                #         context = {
                #             'parent': r.get('parent'),
                #             'student': r.get('student'),
                #             'invoice': r.get('invoice'),
                #         }
                #         personalized_message = template_service.replace_placeholders(
                #             announcement.message,
                #             context
                #         )
                #         SMSNotification.objects.create(
                #             organization=request.organization,
                #             recipient_phone=r['phone'],
                #             message=personalized_message,
                #             status='sent',
                #             sent_at=timezone.now(),
                #             purpose='announcement',
                #             related_announcement=announcement,
                #             triggered_by=request.user,
                #         )
                #         sms_count += 1
                messages.info(request, 'SMS sending is currently disabled. Logic is ready but commented out.')
                sms_count = 0
            
            # Email sending removed - SMS only
            email_count = 0
            
            announcement.is_sent = True
            announcement.sent_at = timezone.now()
            announcement.sms_count = sms_count
            announcement.email_count = email_count
            announcement.save()
            
            messages.success(request, f'Announcement sent! SMS: {sms_count}')
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


class SMSSettingsView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    """SMS Credits Settings and Purchase Instructions."""
    template_name = 'communications/sms_settings.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = getattr(self.request, 'organization', None)
        if organization:
            from django.conf import settings
            from .services.sms_api_client import sms_api_client
            
            context['organization'] = organization
            context['sms_account_number'] = organization.sms_account_number or 'Not Set'
            
            # Get balance from central service
            balance_result = sms_api_client.get_balance(organization)
            if balance_result.get('success'):
                context['sms_balance'] = balance_result.get('balance', 0)
                context['sms_price'] = balance_result.get('price_per_sms', 1.0)
            else:
                # Fallback to local balance if API fails
                context['sms_balance'] = getattr(organization, 'sms_balance', 0)
                context['sms_price'] = 1.0
            
            # Payment details from settings (for KCB payment instructions)
            context['paybill'] = getattr(settings, 'SWIFT_RESIDE_PAYBILL', '522533')
            context['till'] = getattr(settings, 'SWIFT_RESIDE_TILL', 'SWIFTTECH')
            
            # Generate account format for payment: SWIFTTECH#SMS001
            if organization.sms_account_number:
                context['payment_account'] = f"{context['till']}#{organization.sms_account_number}"
            else:
                context['payment_account'] = None
        return context


class SendSingleSMSView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Send SMS to single or multiple phone numbers."""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    
    def get(self, request):
        """Show form for sending single SMS."""
        from .services.sms_template_service import SMSTemplateService
        parents = Parent.objects.filter(organization=request.organization, is_active=True).order_by('last_name', 'first_name')[:100]
        placeholders = SMSTemplateService.get_available_placeholders()
        
        return render(request, 'communications/send_single_sms.html', {
            'parents': parents,
            'placeholders': placeholders,
        })
    
    def post(self, request):
        """Send SMS to provided phone numbers."""
        from .utils import parse_phone_numbers, normalize_phone_number
        from .services.sms_template_service import SMSTemplateService
        from .services.sms_service import SMSService
        
        phone_input = request.POST.get('phone_numbers', '').strip()
        parent_ids = request.POST.getlist('parent_ids')
        message = request.POST.get('message', '').strip()
        
        if not message:
            messages.error(request, 'Message is required.')
            return redirect('communications:send_single_sms')
        
        # Collect phone numbers
        phone_numbers = []
        
        # Add phones from comma-separated input
        if phone_input:
            parsed_phones = parse_phone_numbers(phone_input)
            phone_numbers.extend(parsed_phones)
        
        # Add phones from selected parents
        if parent_ids:
            parents = Parent.objects.filter(
                pk__in=parent_ids,
                organization=request.organization
            )
            for parent in parents:
                if parent.phone_primary:
                    normalized = normalize_phone_number(parent.phone_primary)
                    if normalized and normalized not in phone_numbers:
                        phone_numbers.append(normalized)
        
        if not phone_numbers:
            messages.error(request, 'Please provide at least one valid phone number.')
            return redirect('communications:send_single_sms')
        
        # TODO: Uncomment when ready to send SMS
        # sms_service = SMSService()
        # bulk_recipients = []
        # 
        # for phone in phone_numbers:
        #     # Find parent if phone matches
        #     parent_obj = None
        #     try:
        #         parent_obj = Parent.objects.filter(
        #             organization=request.organization,
        #             phone_primary=phone
        #         ).first()
        #     except:
        #         pass
        #     
        #     # Replace placeholders if parent found
        #     personalized_message = message
        #     if parent_obj:
        #         context = {'parent': parent_obj}
        #         # Try to get student if parent has children (using related_name 'children')
        #         student = parent_obj.children.first() if hasattr(parent_obj, 'children') and parent_obj.children.exists() else None
        #         if student:
        #             context['student'] = student
        #         personalized_message = SMSTemplateService.replace_placeholders(message, context)
        #     
        #     bulk_recipients.append({
        #         'phone_number': phone,
        #         'message': personalized_message,
        #         'parent': parent_obj,
        #     })
        # 
        # # Send SMS
        # sms_service.send_bulk_sms(
        #     recipients=bulk_recipients,
        #     organization=request.organization,
        #     user=request.user,
        #     purpose='manual',
        #     sms_notification_model=None
        # )
        # 
        # # Create notification records
        # for phone in phone_numbers:
        #     parent_obj = Parent.objects.filter(
        #         organization=request.organization,
        #         phone_primary=phone
        #     ).first()
        #     
        #     context = {'parent': parent_obj}
        #     if parent_obj:
        #         student = parent_obj.children.first() if hasattr(parent_obj, 'children') and parent_obj.children.exists() else None
        #         if student:
        #             context['student'] = student
        #     
        #     personalized_message = SMSTemplateService.replace_placeholders(message, context)
        #     
        #     SMSNotification.objects.create(
        #         organization=request.organization,
        #         recipient_phone=phone,
        #         message=personalized_message,
        #         status='sent',
        #         sent_at=timezone.now(),
        #         purpose='manual',
        #         triggered_by=request.user,
        #     )
        
        messages.info(request, f'SMS sending is currently disabled. Would send to {len(phone_numbers)} recipient(s).')
        return redirect('communications:send_single_sms')
