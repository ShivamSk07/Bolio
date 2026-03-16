import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
# Moved model imports inside methods to avoid startup issues

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if self.scope["user"].is_anonymous:
            await self.close()
        else:
            self.user_group_name = f'user_notif_{self.scope["user"].username}'
            await self.channel_layer.group_add(
                self.user_group_name,
                self.channel_name
            )
            await self.accept()

    async def disconnect(self, close_code):
        if not self.scope["user"].is_anonymous:
            await self.channel_layer.group_discard(
                self.user_group_name,
                self.channel_name
            )

    async def notification_message(self, event):
        # This is for events with type 'notification_message'
        await self.send(text_data=json.dumps({
            'action': 'notification',
            'chat_id': event['chat_id'],
            'chat_name': event['chat_name'],
            'sender': event['sender'],
            'message': event['message'],
            'message_type': event['message_type']
        }))

    async def new_notification(self, event):
        # Backward compatibility or if we use 'new_notification' type
        await self.notification_message(event)

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.chat_id = self.scope['url_route']['kwargs']['chat_id']
        self.room_group_name = f'chat_{self.chat_id}'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()
        
        # Broadcast online status
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'status_update',
                'sender': self.scope['user'].username,
                'status': 'online'
            }
        )
        await self.update_user_status(True)

        # Load history
        history = await self.fetch_history()
        for msg in history:
            await self.send(text_data=json.dumps(msg))

    async def disconnect(self, close_code):
        # Broadcast offline status
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'status_update',
                'sender': self.scope['user'].username,
                'status': 'offline'
            }
        )
        await self.update_user_status(False)
        
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get('action', 'message')

        if action == 'message':
            message_content = data['message']
            message_type = data.get('message_type', 'text')
            file_path = data.get('file_path', data.get('file_url')) # Fallback to URL if path missing
            timer = data.get('timer', 0)
            reply_to_id = data.get('reply_to', None)
            unlock_at = data.get('unlock_at', None)
            is_view_once = data.get('is_view_once', False)
            is_protected = data.get('is_protected', False)
            sender_id = self.scope['user'].id

            # Save message to database after broadcast check
            can_send = await self.check_broadcast_permission(sender_id, self.chat_id)
            if not can_send:
                return 

            saved_message = await self.save_message(sender_id, self.chat_id, message_content, message_type, file_path, reply_to_id, unlock_at, is_view_once, is_protected)

            reply_data = None
            if saved_message.reply_to:
                reply_data = {
                    'sender': saved_message.reply_to.sender.username,
                    'content': saved_message.reply_to.content[:50]
                }

            # Send message to room group
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'id': str(saved_message.id),
                    'message': message_content,
                    'message_type': message_type,
                    'file_url': data.get('file_url', file_path),
                    'timer': timer,
                    'reply_to': reply_data,
                    'unlock_at': unlock_at,
                    'is_view_once': is_view_once,
                    'is_protected': is_protected,
                    'sender': self.scope['user'].username,
                    'timestamp': saved_message.timestamp.strftime('%H:%M')
                }
            )

            # Send notification to each member's user group
            members = await self.get_chat_members(self.chat_id)
            chat_name = await self.get_chat_display_name(self.chat_id, self.scope['user'].username)
            
            for username in members:
                if username == self.scope['user'].username: continue # Skip sender
                await self.channel_layer.group_send(
                    f'user_notif_{username}',
                    {
                        'type': 'new_notification',
                        'chat_id': str(self.chat_id),
                        'chat_name': chat_name,
                        'sender': self.scope['user'].username,
                        'message': message_content,
                        'message_type': message_type
                    }
                )
        
        elif action == 'typing':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_typing',
                    'sender': self.scope['user'].username,
                    'is_typing': data.get('is_typing', True),
                    'typing_type': data.get('typing_type', 'typing')
                }
            )

        elif action == 'reaction':
            message_id = data.get('message_id')
            emoji = data.get('emoji')
            res_action, res_emoji = await self.add_reaction(message_id, self.scope['user'].id, emoji)
            
            # Broadcast update with counts to keep everyone in sync
            reactions_summary = await self.get_reactions_summary(message_id)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'message_update',
                    'action': 'reaction_update',
                    'message_id': message_id,
                    'reactions': reactions_summary,
                    'trigger_sender': self.scope['user'].username,
                    'trigger_emoji': emoji if res_action == 'added' else None
                }
            )

        elif action == 'pin_message':
            message_id = data.get('message_id')
            is_pinned = data.get('is_pinned', True)
            await self.toggle_pin(message_id, is_pinned)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'message_update',
                    'action': 'pin',
                    'message_id': message_id,
                    'is_pinned': is_pinned
                }
            )

        elif action == 'edit_message':
            message_id = data.get('message_id')
            new_content = data.get('message')
            await self.edit_message(message_id, new_content)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'message_update',
                    'action': 'edit',
                    'message_id': message_id,
                    'message': new_content
                }
            )

        elif action == 'delete_message':
            message_id = data.get('message_id')
            await self.delete_message(message_id)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'message_update',
                    'action': 'delete',
                    'message_id': message_id
                }
            )

        elif action == 'create_poll':
            question = data.get('question')
            options = data.get('options', [])
            poll_obj = await self.save_poll(self.chat_id, self.scope['user'].id, question, options)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'id': str(poll_obj.message.id),
                    'message': '📊 New Poll Created',
                    'message_type': 'poll',
                    'poll': {
                        'id': poll_obj.id,
                        'question': question,
                        'options': [{'id': o.id, 'text': o.text, 'votes': 0} for o in poll_obj.options.all()]
                    },
                    'sender': self.scope['user'].username,
                    'timestamp': poll_obj.created_at.strftime('%H:%M')
                }
            )

        elif action == 'vote_poll':
            poll_id = data.get('poll_id')
            option_id = data.get('option_id')
            updated_options = await self.process_vote(poll_id, option_id, self.scope['user'].id)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'message_update',
                    'action': 'poll_update',
                    'poll_id': poll_id,
                    'options': updated_options
                }
            )

        elif action == 'emoji_reaction':
            emoji = data.get('emoji')
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'message_update',
                    'action': 'emoji_reaction',
                    'emoji': emoji,
                    'sender': self.scope['user'].username
                }
            )
        elif action == 'mark_read':
            await self.mark_messages_read(self.scope['user'].id, self.chat_id)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'read_notification',
                    'reader': self.scope['user'].username
                }
            )

        # WebRTC Signaling
        elif action in ['call-offer', 'call-answer', 'ice-candidate', 'hangup']:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'webrtc_signal',
                    'data': data,
                    'sender': self.scope['user'].username
                }
            )

    # Receive message from room group
        elif action == 'schedule_call':
            reason = data.get('reason')
            scheduled_time = data.get('scheduled_time')
            sched_obj = await self.save_schedule_call(self.chat_id, self.scope['user'].id, reason, scheduled_time)
            msg_obj = self.temp_msg # Get from temp storage
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'action': 'schedule_call',
                    'id': str(msg_obj.id),
                    'schedule_id': str(sched_obj.id),
                    'reason': reason,
                    'scheduled_time': scheduled_time,
                    'sender': self.scope['user'].username,
                    'message': f"📅 Call Scheduled: {reason}",
                    'message_type': 'schedule_call'
                }
            )
            # Send notification to participants
            members = await self.get_chat_members(self.chat_id)
            chat_name = await self.get_chat_display_name(self.chat_id, self.scope['user'].username)
            for member in members:
                if member != self.scope['user'].username:
                    await self.channel_layer.group_send(
                        f"user_notif_{member}",
                        {
                            'type': 'notification_message',
                            'chat_id': self.chat_id,
                            'chat_name': chat_name,
                            'message': f"📅 Call Invitation: {reason}",
                            'message_type': 'schedule_call',
                            'sender': self.scope['user'].username
                        }
                    )

        elif action == 'accept_schedule':
            schedule_id = data.get('schedule_id')
            await self.accept_schedule_call(schedule_id)
            
            # Save a message for acceptance
            msg_obj = await self.save_message(
                self.scope['user'].id, 
                self.chat_id, 
                f"✅ {self.scope['user'].username} Accepted Call", 
                message_type='schedule_accept',
                related_id=schedule_id
            )
            
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'action': 'accept_schedule',
                    'id': str(msg_obj.id),
                    'schedule_id': schedule_id,
                    'message': f"✅ {self.scope['user'].username} Accepted Call",
                    'message_type': 'schedule_accept',
                    'sender': self.scope['user'].username,
                    'is_accepted': True
                }
            )
            # Send notification for acceptance
            members = await self.get_chat_members(self.chat_id)
            chat_name = await self.get_chat_display_name(self.chat_id, self.scope['user'].username)
            for member in members:
                if member != self.scope['user'].username:
                    await self.channel_layer.group_send(
                        f"user_notif_{member}",
                        {
                            'type': 'notification_message',
                            'chat_id': self.chat_id,
                            'chat_name': chat_name,
                            'message': f"✅ {self.scope['user'].username} accepted the call",
                            'message_type': 'schedule_accept',
                            'sender': self.scope['user'].username
                        }
                    )
            # Send notification for acceptance
            members = await self.get_chat_members(self.chat_id)
            chat_name = await self.get_chat_name(self.chat_id)
            for member in members:
                if member != self.scope['user'].username:
                    await self.channel_layer.group_send(
                        f"user_{member}",
                        {
                            'type': 'notification',
                            'chat_id': self.chat_id,
                            'chat_name': chat_name,
                            'message': "✅ Call Invitation Accepted",
                            'message_type': 'schedule_accept',
                            'sender': self.scope['user'].username
                        }
                    )

        elif action == 'view_once_opened':
            message_id = data['message_id']
            await self.mark_viewed(message_id)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'action': 'view_once_opened',
                    'id': message_id
                }
            )

    async def chat_message(self, event):
        # Ensure action and timestamp exist for immediate UI update
        from django.utils import timezone
        action = event.get('action') or 'message'
        timestamp = event.get('timestamp') or timezone.now().strftime('%H:%M')
        
        # Send message to WebSocket
        data = {
            'action': action,
            'id': event.get('id'),
            'reason': event.get('reason'),
            'scheduled_time': event.get('scheduled_time'),
            'schedule_id': event.get('schedule_id'),
            'is_accepted': event.get('is_accepted'),
            'message': event['message'],
            'message_type': event.get('message_type', 'text'),
            'file_url': event.get('file_url'),
            'timer': event.get('timer', 0),
            'reply_to': event.get('reply_to'),
            'poll': event.get('poll'),
            'unlock_at': event.get('unlock_at'),
            'sender': event['sender'],
            'timestamp': timestamp,
            'is_read': event.get('is_read', False),
            'is_edited': event.get('is_edited', False),
            'is_deleted': event.get('is_deleted', False),
            'is_pinned': event.get('is_pinned', False),
            'is_view_once': event.get('is_view_once', False),
            'is_viewed': event.get('is_viewed', False),
            'is_protected': event.get('is_protected', False)
        }
        await self.send(text_data=json.dumps(data))

    async def user_typing(self, event):
        # Send typing status to WebSocket
        await self.send(text_data=json.dumps({
            'action': 'typing',
            'sender': event['sender'],
            'is_typing': event['is_typing'],
            'typing_type': event.get('typing_type', 'typing')
        }))

    async def message_update(self, event):
        # Send update status to WebSocket
        await self.send(text_data=json.dumps(event))

    async def status_update(self, event):
        await self.send(text_data=json.dumps({
            'action': 'status',
            'sender': event['sender'],
            'status': event['status']
        }))

    async def read_notification(self, event):
        await self.send(text_data=json.dumps({
            'action': 'read_update',
            'reader': event['reader']
        }))

    async def group_update(self, event):
        await self.send(text_data=json.dumps(event))

    async def webrtc_signal(self, event):
        # Forward the signal to other participants except sender
        if event['sender'] != self.scope['user'].username:
            await self.send(text_data=json.dumps(event['data']))

    @database_sync_to_async
    def update_user_status(self, is_online):
        from django.utils import timezone
        user = self.scope['user']
        user.is_online = is_online
        if not is_online:
            user.last_seen = timezone.now()
        user.save()

    @database_sync_to_async
    def save_message(self, sender_id, chat_id, content, message_type='text', file_data=None, reply_to_id=None, unlock_at=None, is_view_once=False, is_protected=False, related_id=None):
        from .models import Chat, Message
        from django.contrib.auth import get_user_model
        User = get_user_model()
        sender = User.objects.get(id=sender_id)
        chat = Chat.objects.get(id=chat_id)
        reply_to = None
        if reply_to_id:
            try:
                reply_to = Message.objects.get(id=reply_to_id)
            except (Message.DoesNotExist, ValueError):
                pass
        
        msg = Message.objects.create(
            sender=sender, 
            chat=chat, 
            content=content, 
            message_type=message_type,
            file=file_data,
            reply_to=reply_to,
            unlock_at=unlock_at,
            is_view_once=is_view_once,
            is_protected=is_protected,
            related_id=related_id
        )
        return msg

    @database_sync_to_async
    def add_reaction(self, message_id, user_id, emoji):
        from .models import MessageReaction
        user = User.objects.get(id=user_id)
        message = Message.objects.get(id=message_id)
        
        # Check if user already has exactly this reaction
        existing = MessageReaction.objects.filter(message=message, user=user, emoji=emoji).first()
        if existing:
            existing.delete()
            return 'removed', emoji
        else:
            # Enforce 1 reaction per user per message (standard behavior)
            MessageReaction.objects.filter(message=message, user=user).delete()
            MessageReaction.objects.create(message=message, user=user, emoji=emoji)
            return 'added', emoji

    @database_sync_to_async
    def get_reactions_summary(self, message_id):
        from .models import MessageReaction
        from django.db.models import Count
        reactions = MessageReaction.objects.filter(message_id=message_id).values('emoji').annotate(count=Count('id'))
        return [{'emoji': r['emoji'], 'count': r['count']} for r in reactions]

    @database_sync_to_async
    def toggle_pin(self, message_id, is_pinned):
        message = Message.objects.get(id=message_id)
        message.is_pinned = is_pinned
        message.save()
        return message

    @database_sync_to_async
    def edit_message(self, message_id, new_content):
        message = Message.objects.get(id=message_id)
        if message.sender == self.scope['user']:
            message.content = new_content
            message.is_edited = True
            message.save()
        return message

    @database_sync_to_async
    def delete_message(self, message_id):
        message = Message.objects.get(id=message_id)
        if message.sender == self.scope['user']:
            message.is_deleted = True
            message.save()
        return message

    @database_sync_to_async
    def save_poll(self, chat_id, user_id, question, options):
        from .models import Poll, PollOption, Message
        user = User.objects.get(id=user_id)
        chat = Chat.objects.get(id=chat_id)
        
        msg = Message.objects.create(
            sender=user,
            chat=chat,
            content=f"Poll: {question}",
            message_type='poll'
        )
        
        poll = Poll.objects.create(chat=chat, message=msg, question=question)
        for opt_text in options:
            PollOption.objects.create(poll=poll, text=opt_text)
        return poll

    @database_sync_to_async
    def process_vote(self, poll_id, option_id, user_id):
        from .models import Poll, PollOption
        user = User.objects.get(id=user_id)
        options = PollOption.objects.filter(poll_id=poll_id)
        for opt in options:
            opt.votes.remove(user)
        
        new_opt = PollOption.objects.get(id=option_id)
        new_opt.votes.add(user)
        
        return [{'id': o.id, 'votes': o.votes.count()} for o in options]

    @database_sync_to_async
    def check_broadcast_permission(self, user_id, chat_id):
        from .models import Chat, GroupRole
        chat = Chat.objects.get(id=chat_id)
        if not chat.is_broadcast:
            return True
            
        # Check if user is admin or creator
        if chat.created_by_id == user_id:
            return True
            
        role = GroupRole.objects.filter(chat=chat, user_id=user_id, role='admin').exists()
        return role

    async def fetch_history(self):
        from .models import Message
        messages = await database_sync_to_async(lambda: list(Message.objects.filter(chat_id=self.chat_id).order_by('timestamp')[:50]))()
        history_data = []
        for msg in messages:
            msg_data = await database_sync_to_async(self.get_message_info_sync)(msg)
            msg_data['reactions'] = await self.get_reactions_summary(msg.id)
            history_data.append(msg_data)
        return history_data

    def get_message_info_sync(self, msg):
        reply_data = None
        if msg.reply_to:
            reply_data = {
                'sender': msg.reply_to.sender.username,
                'content': msg.reply_to.content[:50]
            }
        
        data = {
            'action': 'message',
            'id': str(msg.id),
            'message': msg.content,
            'message_type': msg.message_type,
            'file_url': msg.file.url if msg.file else None,
            'timer': 0,
            'reply_to': reply_data,
            'unlock_at': msg.unlock_at.isoformat() if msg.unlock_at else None,
            'sender': msg.sender.username,
            'timestamp': msg.timestamp.strftime('%H:%M'),
            'is_read': msg.is_read,
            'is_edited': msg.is_edited,
            'is_deleted': msg.is_deleted,
            'is_pinned': msg.is_pinned,
            'is_view_once': msg.is_view_once,
            'is_viewed': msg.is_viewed,
            'is_protected': msg.is_protected
        }

        if msg.message_type == 'poll':
            try:
                poll = msg.poll
                data['poll'] = {
                    'id': poll.id,
                    'question': poll.question,
                    'options': [{'id': o.id, 'text': o.text, 'votes': o.votes.count()} for o in poll.options.all()]
                }
            except:
                pass
        
        if msg.message_type in ['schedule_call', 'schedule_accept']:
            data['schedule_id'] = msg.related_id
            from .models import ScheduledCall
            try:
                sched = ScheduledCall.objects.get(id=msg.related_id)
                data['reason'] = sched.reason
                data['scheduled_time'] = sched.scheduled_time.isoformat()
                data['is_accepted'] = sched.is_accepted
            except:
                pass

        return data

    @database_sync_to_async
    def mark_messages_read(self, user_id, chat_id):
        # Mark all messages as read except those sent by the current user
        Message.objects.filter(chat_id=chat_id, is_read=False).exclude(sender_id=user_id).update(is_read=True)

    @database_sync_to_async
    def mark_viewed(self, message_id):
        Message.objects.filter(id=message_id).update(is_viewed=True)

    @database_sync_to_async
    def save_schedule_call(self, chat_id, user_id, reason, scheduled_time):
        from .models import ScheduledCall, Chat, Message
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.get(id=user_id)
        chat = Chat.objects.get(id=chat_id)
        
        # Create message first but temporarily
        msg = Message.objects.create(
            sender=user,
            chat=chat,
            content=f"📅 Call Scheduled: {reason}",
            message_type='schedule_call'
        )
        
        sched = ScheduledCall.objects.create(
            chat=chat,
            message=msg,
            creator=user,
            reason=reason,
            scheduled_time=scheduled_time
        )
        
        # Update msg with related_id
        msg.related_id = str(sched.id)
        msg.save()
        
        self.temp_msg = msg
        return sched

    @database_sync_to_async
    def accept_schedule_call(self, schedule_id):
        from .models import ScheduledCall
        ScheduledCall.objects.filter(id=schedule_id).update(is_accepted=True)

    @database_sync_to_async
    def get_chat_members(self, chat_id):
        chat = Chat.objects.get(id=chat_id)
        return [m.username for m in chat.members.all()]

    @database_sync_to_async
    def get_chat_display_name(self, chat_id, sender_username):
        chat = Chat.objects.get(id=chat_id)
        if chat.is_group:
            return chat.name
        return sender_username

    async def new_notification(self, event):
        # Forward notification to WebSocket
        await self.send(text_data=json.dumps({
            'action': 'notification',
            'chat_id': event['chat_id'],
            'chat_name': event['chat_name'],
            'sender': event['sender'],
            'message': event['message'],
            'message_type': event['message_type']
        }))

class RoomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_code = self.scope['url_route']['kwargs']['room_code']
        self.room_group_name = f'room_{self.room_code}'
        self.username = self.scope['user'].username if not self.scope['user'].is_anonymous else 'Guest'

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Check if admission is needed
        needs_admission, is_host = await self.check_admission_status()
        
        if needs_admission and not is_host:
            # Notify host only
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'room_event',
                    'action': 'admission-requested',
                    'sender': self.username,
                    'user_id': self.scope['user'].id,
                    'channel_name': self.channel_name
                }
            )
        else:
            # Notify others that someone joined normally
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'room_event',
                    'action': 'user-joined',
                    'sender': self.username,
                    'channel_name': self.channel_name
                }
            )

    async def disconnect(self, close_code):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'room_event',
                'action': 'user-left',
                'sender': self.username,
                'channel_name': self.channel_name
            }
        )
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        import json
        data = json.loads(text_data)
        action = data.get('action')
        target_channel = data.get('target')

        # Check admission status before allowing any action
        needs_admission, is_host = await self.check_admission_status()
        if needs_admission and not is_host and action != 'admission-requested':
            # Block unauthorized guest actions
            return

        # Peer-to-peer signaling or general room messages
        if action in ['offer', 'answer', 'ice-candidate']:
            # Send directed signal or broadcast
            if target_channel:
                await self.channel_layer.send(
                    target_channel,
                    {
                        'type': 'webrtc_signal',
                        'data': data,
                        'sender': self.username,
                        'channel_name': self.channel_name
                    }
                )
            else:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'webrtc_signal',
                        'data': data,
                        'sender': self.username,
                        'channel_name': self.channel_name
                    }
                )
        elif action == 'chat_message':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'room_event',
                    'action': 'chat_message',
                    'message': data.get('message'),
                    'sender': self.username
                }
            )
        elif action == 'camera-status':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'room_event',
                    'action': 'camera-status',
                    'enabled': data.get('enabled'),
                    'sender': self.username,
                    'channel_name': self.channel_name
                }
            )
        elif action == 'ready':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'room_event',
                    'action': 'ready',
                    'sender': self.username,
                    'channel_name': self.channel_name
                }
            )
        elif action == 'admit-response':
            # Host responding to admission request
            target_user_id = data.get('target_user_id')
            action_type = data.get('action_type') # admit or reject
            
            # Broadcast to everyone so they know user status updated
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'room_event',
                    'action': 'admitted' if action_type == 'admit' else 'rejected',
                    'user_id': target_user_id,
                    'username': await self.get_username_by_id(target_user_id)
                }
            )

    async def room_event(self, event):
        # Exclude sender from joining their own events unless required
        if event.get('action') in ['user-joined', 'user-left'] and event.get('channel_name') == self.channel_name:
            return

        # Merge event into dict to ensure target_user_id etc are sent
        data = event.copy()
        data.pop('type', None)
        await self.send(text_data=json.dumps(data))

    async def webrtc_signal(self, event):
        if event['channel_name'] == self.channel_name:
            return
            
        data = event['data']
        # include sender info to reply back
        data['sender'] = event['sender']
        data['sender_channel'] = event['channel_name']
        await self.send(text_data=json.dumps(data))

    @database_sync_to_async
    def check_admission_status(self):
        from .models import Room, RoomParticipant
        try:
            room = Room.objects.get(code=self.room_code)
            is_host = room.host == self.scope['user']
            if not room.require_admission:
                return False, is_host
            
            participant = RoomParticipant.objects.filter(room=room, user=self.scope['user']).first()
            if participant and participant.is_admitted:
                return False, is_host
            
            # If guest and not admitted, they need admission
            if not is_host:
                # Create participant record in waiting state if doesn't exist
                RoomParticipant.objects.get_or_create(room=room, user=self.scope['user'])
                return True, False
            
            return False, True
        except Room.DoesNotExist:
            return True, False

    @database_sync_to_async
    def get_username_by_id(self, user_id):
        from accounts.models import User
        try:
            return User.objects.get(id=user_id).username
        except:
            return "Unknown"
