# academics/services/timetable_service.py
"""
Service for timetable management and conflict detection.
"""

import logging
from django.db.models import Q
from academics.models import Timetable, Class, Staff
from django.utils import timezone

logger = logging.getLogger(__name__)


class TimetableService:
    """
    Service for timetable operations and conflict detection.
    """
    
    @staticmethod
    def check_conflicts(class_obj, day, start_time, end_time, teacher=None, room=None, exclude_timetable_id=None, organization=None):
        """
        Check for timetable conflicts.
        
        Args:
            class_obj: Class instance
            day: Day of week (0-4)
            start_time: Start time
            end_time: End time
            teacher: Staff instance (optional)
            room: Room name (optional)
            exclude_timetable_id: Timetable ID to exclude from conflict check (for updates)
            organization: Organization instance
        
        Returns:
            dict with 'has_conflict' (bool) and 'conflicts' (list of conflict descriptions)
        """
        if not organization:
            if class_obj and hasattr(class_obj, 'organization'):
                organization = class_obj.organization
        
        conflicts = []
        
        # Check class conflicts (same class, same day, overlapping time)
        if class_obj and organization:
            class_conflicts = Timetable.objects.filter(
                class_obj=class_obj,
                day_of_week=day,
                organization=organization
            )
            
            if exclude_timetable_id:
                class_conflicts = class_conflicts.exclude(id=exclude_timetable_id)
            
            for tt in class_conflicts:
                if _times_overlap(start_time, end_time, tt.start_time, tt.end_time):
                    conflicts.append(f"Class {class_obj.name} already has {tt.subject.name} at this time")
        
        # Check teacher conflicts (same teacher, same day, overlapping time)
        if teacher:
            teacher_conflicts = Timetable.objects.filter(
                teacher=teacher,
                day_of_week=day,
                organization=organization
            )
            
            if exclude_timetable_id:
                teacher_conflicts = teacher_conflicts.exclude(id=exclude_timetable_id)
            
            for tt in teacher_conflicts:
                if _times_overlap(start_time, end_time, tt.start_time, tt.end_time):
                    conflicts.append(f"Teacher {teacher.user.full_name} already has {tt.subject.name} for {tt.class_obj.name} at this time")
        
        # Check room conflicts (same room, same day, overlapping time)
        if room:
            room_conflicts = Timetable.objects.filter(
                room=room,
                day_of_week=day,
                organization=organization
            )
            
            if exclude_timetable_id:
                room_conflicts = room_conflicts.exclude(id=exclude_timetable_id)
            
            for tt in room_conflicts:
                if _times_overlap(start_time, end_time, tt.start_time, tt.end_time):
                    conflicts.append(f"Room {room} is already booked for {tt.subject.name} ({tt.class_obj.name}) at this time")
        
        return {
            'has_conflict': len(conflicts) > 0,
            'conflicts': conflicts
        }
    
    @staticmethod
    def validate_room_availability(room, day, start_time, end_time, exclude_timetable_id=None, organization=None):
        """
        Check if a room is available at the specified time.
        
        Returns:
            bool: True if available, False if booked
        """
        result = TimetableService.check_conflicts(
            class_obj=None,  # Not checking class conflicts
            day=day,
            start_time=start_time,
            end_time=end_time,
            room=room,
            exclude_timetable_id=exclude_timetable_id,
            organization=organization
        )
        return not result['has_conflict']


def _times_overlap(start1, end1, start2, end2):
    """Check if two time ranges overlap."""
    return start1 < end2 and start2 < end1

