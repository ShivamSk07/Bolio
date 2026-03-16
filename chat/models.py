from django.db import models
from django.conf import settings
import uuid

class Chat(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, blank=True, null=True) # For groups
    is_group = models.BooleanField(default=False)
    is_broadcast = models.BooleanField(default=False)
    description = models.TextField(blank=True, null=True)
    icon = models.ImageField(upload_to='chat_icons/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='chats')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_chats')
    
    # Connection Request Fields
    CHAT_STATUS = (
        ('active', 'Active'),
        ('pending', 'Pending'),
        ('declined', 'Declined'),
    )
    status = models.CharField(max_length=10, choices=CHAT_STATUS, default='active')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='requested_chats')

    def __str__(self):
        return self.name if self.name else f"Chat {self.id}"

class Message(models.Model):
    MESSAGE_TYPES = (
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('file', 'File'),
        ('audio', 'Audio'),
        ('poll', 'Poll'),
        ('capsule', 'Time Capsule'),
        ('location', 'Location'),
    )
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages')
    content = models.TextField(blank=True)
    file = models.FileField(upload_to='chat_files/', blank=True, null=True)
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES, default='text')
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    unlock_at = models.DateTimeField(null=True, blank=True)
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    
    # PIN status
    is_pinned = models.BooleanField(default=False)
    
    # Advanced Privacy
    is_view_once = models.BooleanField(default=False)
    is_viewed = models.BooleanField(default=False)
    is_protected = models.BooleanField(default=False)
    
    related_id = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.sender.username}: {self.content[:50]}"

class MessageReaction(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='reactions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    emoji = models.CharField(max_length=10)

    class Meta:
        unique_together = ('message', 'user', 'emoji')

class GroupRole(models.Model):
    ROLES = (
        ('member', 'Member'),
        ('moderator', 'Moderator'),
        ('admin', 'Admin'),
    )
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='roles')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLES, default='member')

    class Meta:
        unique_together = ('chat', 'user')

class Poll(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='polls')
    message = models.OneToOneField(Message, on_delete=models.CASCADE, related_name='poll')
    question = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

class PollOption(models.Model):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name='options')
    text = models.CharField(max_length=100)
    votes = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='poll_votes', blank=True)

    def __str__(self):
        return self.text

class BlockedUser(models.Model):
    blocker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocking')
    blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocked_by')
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('blocker', 'blocked')

class ScheduledCall(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='scheduled_calls')
    message = models.OneToOneField(Message, on_delete=models.CASCADE, null=True, blank=True, related_name='scheduled_call')
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_scheduled_calls')
    reason = models.CharField(max_length=255)
    scheduled_time = models.DateTimeField()
    is_accepted = models.BooleanField(default=False)
    is_cancelled = models.BooleanField(default=False)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Call in {self.chat} at {self.scheduled_time}"

class CallLog(models.Model):
    CALL_TYPES = (
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('room', 'Room'),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='call_logs')
    room_code = models.CharField(max_length=50, blank=True, null=True)
    target = models.CharField(max_length=255, blank=True, null=True)
    call_type = models.CharField(max_length=10, choices=CALL_TYPES, default='room')
    direction = models.CharField(max_length=10, choices=(('incoming', 'Incoming'), ('outgoing', 'Outgoing')), default='outgoing')
    duration = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

class Story(models.Model):
    PRIVACY_CHOICES = (
        ('public', 'Public'),
        ('selected', 'Selected Users'),
    )
    STYLE_CHOICES = (
        ('gradient1', 'Ocean Blue'),
        ('gradient2', 'Sunset'),
        ('gradient3', 'Neon Purple'),
        ('gradient4', 'Emerald'),
        ('gradient5', 'Midnight'),
        ('plain', 'Plain Dark'),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='stories')
    media_file = models.FileField(upload_to='stories/', null=True, blank=True)
    media_type = models.CharField(max_length=10, choices=(('video', 'Video'), ('audio', 'Audio'), ('image', 'Image'), ('text', 'Text')), default='text')
    text_content = models.TextField(blank=True, null=True)
    text_style = models.CharField(max_length=20, choices=STYLE_CHOICES, default='gradient1')
    created_at = models.DateTimeField(auto_now_add=True)
    duration_hours = models.IntegerField(default=24)
    privacy = models.CharField(max_length=20, choices=PRIVACY_CHOICES, default='public')
    visible_to = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='visible_stories', blank=True)

class StoryViewer(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='viewers')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('story', 'user')

# ========== ROOM MODELS ==========
class Room(models.Model):
    code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=255, default='Instant Room')
    host = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hosted_rooms')
    is_active = models.BooleanField(default=True)
    require_admission = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    scheduled_time = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Room {self.code} by {self.host.username}"

class RoomParticipant(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='room_participations')
    is_admitted = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('room', 'user')
