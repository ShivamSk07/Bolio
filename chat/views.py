from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@login_required
def home(request):
    user = request.user
    chats = user.chats.all()
    
    if not chats.exists():
        from accounts.models import User
        from .models import Chat, Message
        
        bot, created = User.objects.get_or_create(
            username='BolioBot',
            defaults={'first_name': 'Bolio', 'last_name': 'Bot', 'is_active': True}
        )
        
        welcome_chat = Chat.objects.create(name='Bolio Support')
        welcome_chat.members.add(user, bot)
        
        Message.objects.create(
            sender=bot, chat=welcome_chat,
            content="Welcome to Bolio! I'm your assistant Shivam. How can I help you today?"
        )
        Message.objects.create(
            sender=bot, chat=welcome_chat,
            content="You can send text, images, and files here. Try double-clicking this message to react with ❤️"
        )
        chats = user.chats.all()

    for chat in chats:
        chat.unread_count = chat.messages.filter(is_read=False).exclude(sender=user).count()
        chat.latest_msg = chat.messages.order_by('-timestamp').first()

    from accounts.models import User
    all_users = User.objects.exclude(id=user.id).exclude(username='BolioBot')

    return render(request, 'chat/home.html', {
        'chats': chats,
        'all_users': all_users
    })

@csrf_exempt
@login_required
def upload_file(request):
    if request.method == 'POST' and request.FILES.get('file'):
        uploaded_file = request.FILES['file']
        from django.core.files.storage import default_storage
        filename = default_storage.save(f'chat_media/{uploaded_file.name}', uploaded_file)
        file_url = default_storage.url(filename)
        return JsonResponse({'file_url': file_url, 'filename': filename})
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
@login_required
def create_group(request):
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        group_name = data.get('name')
        member_ids = data.get('members', [])
        is_broadcast = data.get('is_broadcast', False)
        
        from .models import Chat, GroupRole
        from accounts.models import User
        
        group = Chat.objects.create(
            name=group_name, is_group=True, is_broadcast=is_broadcast, created_by=request.user
        )
        group.members.add(request.user)
        GroupRole.objects.create(chat=group, user=request.user, role='admin')
        
        for m_id in member_ids:
            try:
                member = User.objects.get(id=m_id)
                group.members.add(member)
                GroupRole.objects.create(chat=group, user=member, role='member')
            except User.DoesNotExist:
                continue
                
        return JsonResponse({'chat_id': str(group.id), 'name': group.name})
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def generate_chat_qr(request, chat_id):
    import qrcode
    from io import BytesIO
    from django.http import HttpResponse
    
    join_url = f"{request.build_absolute_uri('/')}join/{chat_id}/"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(join_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#2d3436", back_color="#ffffff")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return HttpResponse(buffer.getvalue(), content_type="image/png")

@login_required
def join_chat(request, chat_id):
    from .models import Chat
    try:
        chat = Chat.objects.get(id=chat_id)
        if request.user not in chat.members.all():
            chat.members.add(request.user)
    except Chat.DoesNotExist:
        pass
    return redirect('home')

@csrf_exempt
@login_required
def update_profile(request):
    if request.method == 'POST':
        user = request.user
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.bio = request.POST.get('bio', user.bio)
        user.status_message = request.POST.get('status_message', user.status_message)
        user.chat_background = request.POST.get('chat_background', user.chat_background)
        user.privacy_last_seen = request.POST.get('privacy_last_seen', user.privacy_last_seen)
        user.privacy_profile_photo = request.POST.get('privacy_profile_photo', user.privacy_profile_photo)
        user.two_factor_enabled = request.POST.get('two_factor_enabled') == 'true'
        user.is_private = request.POST.get('is_private') == 'true'
        user.email = request.POST.get('email', user.email)
        user.phone_number = request.POST.get('phone_number', user.phone_number)
        
        if request.FILES.get('profile_photo'):
            user.profile_photo = request.FILES['profile_photo']
        
        user.save()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
@login_required
def toggle_block(request):
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        target_user_id = data.get('user_id')
        from .models import BlockedUser
        from accounts.models import User
        
        try:
            target_user = User.objects.get(id=target_user_id)
            block_obj = BlockedUser.objects.filter(blocker=request.user, blocked=target_user).first()
            if block_obj:
                block_obj.delete()
                return JsonResponse({'status': 'unblocked'})
            else:
                BlockedUser.objects.create(blocker=request.user, blocked=target_user)
                return JsonResponse({'status': 'blocked'})
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def get_user_info(request, user_id):
    from accounts.models import User
    from .models import Chat
    try:
        user = User.objects.get(id=user_id)
        photo_url = user.profile_photo.url if user.profile_photo else None
        last_seen_str = user.last_seen.strftime("%b %d, %H:%M") if user.last_seen else "Never"

        if user.privacy_profile_photo == 'nobody' and user != request.user:
            photo_url = None
        elif user.privacy_profile_photo == 'contacts' and user != request.user:
            if not Chat.objects.filter(members=user).filter(members=request.user).exists():
                photo_url = None

        if user.privacy_last_seen == 'nobody' and user != request.user:
            last_seen_str = "Hidden"
        elif user.privacy_last_seen == 'contacts' and user != request.user:
            if not Chat.objects.filter(members=user).filter(members=request.user).exists():
                last_seen_str = "Hidden"

        return JsonResponse({
            'username': user.username,
            'bio': user.bio,
            'status': user.status_message,
            'photo': photo_url,
            'is_online': user.is_online,
            'last_seen': last_seen_str,
            'is_private': user.is_private
        })
    except User.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)

@csrf_exempt
@login_required
def start_private_chat(request):
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        target_user_id = data.get('user_id')
        
        from accounts.models import User
        from .models import Chat
        
        try:
            target_user = User.objects.get(id=target_user_id)
            existing_chat = Chat.objects.filter(is_group=False, members=request.user).filter(members=target_user).first()
            
            if existing_chat:
                return JsonResponse({'chat_id': str(existing_chat.id), 'name': target_user.username, 'status': existing_chat.status})
            
            status = 'pending' if target_user.is_private else 'active'
            new_chat = Chat.objects.create(
                name=f"Chat with {target_user.username}", 
                is_group=False, status=status, requested_by=request.user
            )
            new_chat.members.add(request.user, target_user)
            
            # Send notification via WebSocket
            if target_user.is_private:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'user_notif_{target_user.username}',
                    {
                        'type': 'notification_message',
                        'chat_id': str(new_chat.id),
                        'chat_name': request.user.username,
                        'sender': request.user.username,
                        'message': f'🔒 {request.user.username} sent you a connection request',
                        'message_type': 'connection_request'
                    }
                )
            
            return JsonResponse({'chat_id': str(new_chat.id), 'name': target_user.username, 'status': status})
            
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def get_group_info(request, chat_id):
    from .models import Chat, GroupRole
    try:
        chat = Chat.objects.get(id=chat_id, is_group=True)
        if request.user not in chat.members.all():
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        
        members = []
        for m in chat.members.all():
            role_obj = GroupRole.objects.filter(chat=chat, user=m).first()
            members.append({
                'id': m.id, 'username': m.username,
                'role': role_obj.role if role_obj else 'member',
                'photo': m.profile_photo.url if m.profile_photo else None
            })
            
        return JsonResponse({
            'name': chat.name, 'description': chat.description or 'No description',
            'created_at': chat.created_at.strftime("%b %d, %Y"),
            'is_broadcast': chat.is_broadcast, 'members': members,
            'is_admin': GroupRole.objects.filter(chat=chat, user=request.user, role='admin').exists()
        })
    except (Chat.DoesNotExist, ValueError):
        return JsonResponse({'error': 'Group not found'}, status=404)

@csrf_exempt
@login_required
def leave_group(request, chat_id):
    from .models import Chat, GroupRole
    if request.method == 'POST':
        try:
            chat = Chat.objects.get(id=chat_id, is_group=True)
            if request.user in chat.members.all():
                chat.members.remove(request.user)
                GroupRole.objects.filter(chat=chat, user=request.user).delete()
                if chat.members.count() == 0:
                    chat.delete()
                return JsonResponse({'status': 'success'})
            return JsonResponse({'error': 'Not a member'}, status=403)
        except Chat.DoesNotExist:
            return JsonResponse({'error': 'Group not found'}, status=404)
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
@login_required
def delete_group(request, chat_id):
    from .models import Chat, GroupRole
    if request.method == 'POST':
        try:
            chat = Chat.objects.get(id=chat_id, is_group=True)
            is_admin = GroupRole.objects.filter(chat=chat, user=request.user, role='admin').exists()
            if is_admin:
                chat.delete()
                return JsonResponse({'status': 'success'})
            return JsonResponse({'error': 'Unauthorized: Admin only'}, status=403)
        except Chat.DoesNotExist:
            return JsonResponse({'error': 'Group not found'}, status=404)
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def settings_view(request):
    return render(request, 'chat/settings.html', {'user': request.user})

@login_required
def user_profile_view(request, user_id):
    from accounts.models import User
    from .models import BlockedUser, Chat
    try:
        target_user = User.objects.get(id=user_id)
        is_blocked = BlockedUser.objects.filter(blocker=request.user, blocked=target_user).exists()
        
        # Check connection status
        existing_chat = Chat.objects.filter(is_group=False, members=request.user).filter(members=target_user).first()
        chat_status = existing_chat.status if existing_chat else None
        is_connection = chat_status == 'active'
        is_pending = chat_status == 'pending'

        return render(request, 'chat/user_profile.html', {
            'target_user': target_user, 
            'is_blocked': is_blocked,
            'is_connection': is_connection,
            'is_pending': is_pending,
            'chat_status': chat_status
        })
    except User.DoesNotExist:
        from django.http import Http404
        raise Http404("User not found")

@csrf_exempt
@login_required
def respond_chat_request(request):
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        chat_id = data.get('chat_id')
        action = data.get('action')
        
        from .models import Chat, Message
        try:
            chat = Chat.objects.get(id=chat_id, status='pending')
            if request.user in chat.members.all() and request.user != chat.requested_by:
                if action == 'accept':
                    chat.status = 'active'
                    chat.save()
                    
                    Message.objects.create(
                        chat=chat, sender=request.user,
                        content="✅ Request accepted! You can now start chatting."
                    )
                    
                    # Notify requester
                    from channels.layers import get_channel_layer
                    from asgiref.sync import async_to_sync
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        f'user_notif_{chat.requested_by.username}',
                        {
                            'type': 'notification_message',
                            'chat_id': str(chat.id),
                            'chat_name': request.user.username,
                            'sender': request.user.username,
                            'message': f'✅ {request.user.username} accepted your connection request!',
                            'message_type': 'request_accepted'
                        }
                    )
                    
                    return JsonResponse({'status': 'success'})
                elif action == 'decline':
                    chat.status = 'declined'
                    chat.save()
                    
                    # Notify requester
                    from channels.layers import get_channel_layer
                    from asgiref.sync import async_to_sync
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        f'user_notif_{chat.requested_by.username}',
                        {
                            'type': 'notification_message',
                            'chat_id': str(chat.id),
                            'chat_name': request.user.username,
                            'sender': request.user.username,
                            'message': f'❌ {request.user.username} declined your connection request.',
                            'message_type': 'request_declined'
                        }
                    )
                    
                    return JsonResponse({'status': 'declined'})
        except (Chat.DoesNotExist, ValueError):
            return JsonResponse({'error': 'Request not found'}, status=404)
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def room_view(request, room_code):
    from .models import Room
    
    try:
        room = Room.objects.get(code=room_code, is_active=True)
    except Room.DoesNotExist:
        from django.contrib import messages
        messages.error(request, f"Room {room_code} does not exist or has expired.")
        return redirect('home')
    
    is_host = room.host == request.user
    return render(request, 'chat/room.html', {
        'room_code': room_code,
        'room': room,
        'is_host': is_host,
    })

@csrf_exempt
@login_required
def add_call_log(request):
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        from .models import CallLog
        CallLog.objects.create(
            user=request.user,
            room_code=data.get('room_code'),
            target=data.get('target'),
            call_type=data.get('call_type', 'room'),
            direction=data.get('direction', 'outgoing'),
            duration=data.get('duration', 0)
        )
        return JsonResponse({'status': 'success'})
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def get_call_logs(request):
    from .models import CallLog
    logs = CallLog.objects.filter(user=request.user).order_by('-created_at')[:50]
    data = [{
        'id': log.id,
        'room_code': log.room_code,
        'target': log.target,
        'call_type': log.call_type,
        'direction': log.direction,
        'duration': log.duration,
        'created_at': log.created_at.strftime('%Y-%m-%d %H:%M:%S')
    } for log in logs]
    return JsonResponse({'logs': data})

@csrf_exempt
@login_required
def clear_call_logs(request):
    if request.method == 'POST':
        from .models import CallLog
        CallLog.objects.filter(user=request.user).delete()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
@login_required
def create_story(request):
    if request.method == 'POST':
        import json
        from .models import Story
        
        media_type = request.POST.get('media_type', 'text')
        text_content = request.POST.get('text_content', '')
        text_style = request.POST.get('text_style', 'gradient1')
        duration_hours = int(request.POST.get('duration_hours', 24))
        privacy = request.POST.get('privacy', 'public')
        media_file = request.FILES.get('media_file')

        story = Story.objects.create(
            user=request.user,
            media_type=media_type,
            text_content=text_content,
            text_style=text_style,
            duration_hours=duration_hours,
            privacy=privacy,
            media_file=media_file
        )
        
        # Handle selected users for privacy
        if privacy == 'selected':
            visible_to_ids = request.POST.get('visible_to', '')
            if visible_to_ids:
                from accounts.models import User
                ids = [int(i) for i in visible_to_ids.split(',') if i]
                users = User.objects.filter(id__in=ids)
                story.visible_to.set(users)
        
        return JsonResponse({'status': 'success', 'story_id': story.id})
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def get_stories(request):
    from .models import Story
    from django.utils import timezone
    from datetime import timedelta
    
    now = timezone.now()
    recent_stories_qs = Story.objects.select_related('user').prefetch_related('viewers').order_by('-created_at')[:100]
    
    my_stories = []
    others_stories = {}
    
    for s in recent_stories_qs:
        expiration_time = s.created_at + timedelta(hours=s.duration_hours)
        if expiration_time < now:
            continue
        
        # Privacy check
        if s.user != request.user:
            if s.privacy == 'selected':
                if not s.visible_to.filter(id=request.user.id).exists():
                    continue
            
        viewer_count = s.viewers.count()
        has_viewed = s.viewers.filter(user=request.user).exists()
        
        story_data = {
            'id': s.id,
            'media_type': s.media_type,
            'media_url': s.media_file.url if s.media_file else None,
            'text_content': s.text_content,
            'text_style': s.text_style,
            'created_at': s.created_at.strftime('%I:%M %p'),
            'created_at_full': s.created_at.isoformat(),
            'duration_hours': s.duration_hours,
            'privacy': s.privacy,
            'viewer_count': viewer_count,
            'has_viewed': has_viewed,
            'user': {
                'id': s.user.id,
                'username': s.user.username,
                'photo_url': s.user.profile_photo.url if s.user.profile_photo else None,
            }
        }
        
        if s.user == request.user:
            my_stories.append(story_data)
        else:
            if s.user.id not in others_stories:
                others_stories[s.user.id] = {'user': story_data['user'], 'stories': []}
            others_stories[s.user.id]['stories'].append(story_data)
            
    return JsonResponse({
        'my_stories': my_stories,
        'others': list(others_stories.values())
    })

@csrf_exempt
@login_required
def view_story(request):
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        story_id = data.get('story_id')
        from .models import Story, StoryViewer
        try:
            story = Story.objects.get(id=story_id)
            StoryViewer.objects.get_or_create(story=story, user=request.user)
            return JsonResponse({'status': 'success', 'viewer_count': story.viewers.count()})
        except Story.DoesNotExist:
            return JsonResponse({'error': 'Story not found'}, status=404)
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
@login_required
def delete_story(request):
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        story_id = data.get('story_id')
        from .models import Story
        try:
            story = Story.objects.get(id=story_id, user=request.user)
            story.delete()
            return JsonResponse({'status': 'success'})
        except Story.DoesNotExist:
            return JsonResponse({'error': 'Story not found'}, status=404)
    return JsonResponse({'error': 'Invalid request'}, status=400)

# ========== ROOM VIEWS ==========
@csrf_exempt
@login_required
def create_room(request):
    if request.method == 'POST':
        import json
        import string
        import random
        
        data = json.loads(request.body)
        room_name = data.get('name', 'Instant Room')
        require_admission = data.get('require_admission', True)
        scheduled_time = data.get('scheduled_time')
        
        from .models import Room, RoomParticipant, CallLog
        
        # Generate unique room code
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        room = Room.objects.create(
            code=code,
            name=room_name,
            host=request.user,
            require_admission=require_admission,
            scheduled_time=scheduled_time,
        )
        
        # Auto-admit host
        RoomParticipant.objects.create(room=room, user=request.user, is_admitted=True)
        
        # Log the call
        CallLog.objects.create(
            user=request.user,
            room_code=code,
            target=room_name,
            call_type='room',
            direction='outgoing'
        )
        
        return JsonResponse({
            'status': 'success',
            'code': code,
            'name': room_name,
            'room_id': room.id
        })
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
@login_required
def admit_user(request):
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        room_code = data.get('room_code')
        user_id = data.get('user_id')
        action = data.get('action', 'admit')  # admit or reject
        
        from .models import Room, RoomParticipant
        from accounts.models import User
        
        try:
            room = Room.objects.get(code=room_code, host=request.user)
            target_user = User.objects.get(id=user_id)
            
            if action == 'admit':
                participant, created = RoomParticipant.objects.get_or_create(
                    room=room, user=target_user, defaults={'is_admitted': True}
                )
                if not created:
                    participant.is_admitted = True
                    participant.save()
                return JsonResponse({'status': 'admitted'})
            elif action == 'reject':
                RoomParticipant.objects.filter(room=room, user=target_user).delete()
                return JsonResponse({'status': 'rejected'})
        except Room.DoesNotExist:
            return JsonResponse({'error': 'Room not found or unauthorized'}, status=404)
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def get_room_info(request, room_code):
    from .models import Room, RoomParticipant
    try:
        room = Room.objects.get(code=room_code)
        participants = RoomParticipant.objects.filter(room=room).select_related('user')
        
        return JsonResponse({
            'code': room.code,
            'name': room.name,
            'host': room.host.username,
            'host_id': room.host.id,
            'is_host': room.host == request.user,
            'require_admission': room.require_admission,
            'is_active': room.is_active,
            'participants': [{
                'id': p.user.id,
                'username': p.user.username,
                'is_admitted': p.is_admitted,
                'photo': p.user.profile_photo.url if p.user.profile_photo else None
            } for p in participants],
            'waiting': [{
                'id': p.user.id,
                'username': p.user.username,
                'photo': p.user.profile_photo.url if p.user.profile_photo else None
            } for p in participants if not p.is_admitted]
        })
    except Room.DoesNotExist:
        return JsonResponse({'error': 'Room not found'}, status=404)

@login_required
def finish_tour(request):
    request.user.has_seen_tour = True
    request.user.save()
    return JsonResponse({'status': 'success'})
