import os
import django
from django.core.asgi import get_asgi_application

# Set the settings module before doing anything else
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bolio_core.settings')

# Initialize Django
django.setup()

# Get the ASGI application for HTTP
django_asgi_app = get_asgi_application()

# Now it is safe to import channels and your routing
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
import chat.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(
                chat.routing.websocket_urlpatterns
            )
        )
    ),
})
