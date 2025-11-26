from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model for PCEA Wendani School Management System.
    Extend this later with role, phone, etc.
    """
    pass