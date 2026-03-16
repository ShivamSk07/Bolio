from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    bio = models.TextField(max_length=500, blank=True)
    profile_photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True)
    status_message = models.CharField(max_length=255, blank=True)
    birthday = models.DateField(null=True, blank=True)
    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    chat_background = models.CharField(max_length=50, default='default')
    
    # Privacy & Security
    privacy_last_seen = models.CharField(max_length=20, default='everyone') # everyone, contacts, nobody
    privacy_profile_photo = models.CharField(max_length=20, default='everyone')
    is_private = models.BooleanField(default=False)
    two_factor_enabled = models.BooleanField(default=False)
    has_seen_tour = models.BooleanField(default=False)
    
    def __str__(self):
        return self.username
