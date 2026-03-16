from django.contrib import admin
from .models import Chat, Message, Room, Story, CallLog, ScheduledCall

@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_group', 'status', 'created_at')
    search_fields = ('name',)

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'chat', 'message_type', 'timestamp')
    list_filter = ('message_type', 'timestamp')

@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'host', 'is_active', 'created_at')

@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'media_type', 'created_at')

@admin.register(CallLog)
class CallLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'call_type', 'direction', 'created_at')

@admin.register(ScheduledCall)
class ScheduledCallAdmin(admin.ModelAdmin):
    list_display = ('chat', 'scheduled_time', 'creator', 'is_completed')
