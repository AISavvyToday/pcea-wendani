"""Backward-compatible SMS service wrapper around the central SMS API client."""

from .sms_api_client import sms_api_client


class SMSService:
    """Backward-compatible wrapper for the central SMS API client."""

    def send_sms(
        self,
        phone_number,
        message,
        organization=None,
        purpose='',
        related_student=None,
        triggered_by=None,
        parent=None,
        user=None,
        student=None,
        **kwargs,
    ):
        if triggered_by is None:
            triggered_by = user

        if related_student is None:
            related_student = student

        if organization is None and parent is not None:
            organization = getattr(parent, 'organization', None)

        return sms_api_client.send_sms(
            phone_number=phone_number,
            message=message,
            organization=organization,
            purpose=purpose,
            related_student=related_student,
            triggered_by=triggered_by,
        )

    def send_bulk_sms(
        self,
        recipients,
        message='',
        organization=None,
        purpose='',
        triggered_by=None,
        user=None,
        **kwargs,
    ):
        if triggered_by is None:
            triggered_by = user

        normalized_recipients = []
        for recipient in recipients or []:
            phone = (
                recipient.get('phone')
                or recipient.get('phone_number')
                or recipient.get('recipient_phone')
            )
            if not phone:
                continue

            normalized_recipients.append(
                {
                    'phone': phone,
                    'message': recipient.get('message', message),
                    'student': recipient.get('student') or recipient.get('related_student'),
                    'parent': recipient.get('parent'),
                }
            )

        return sms_api_client.send_bulk_sms(
            recipients=normalized_recipients,
            message=message,
            organization=organization,
            purpose=purpose,
            triggered_by=triggered_by,
        )


sms_service = SMSService()

__all__ = ['SMSService', 'sms_service', 'sms_api_client']
