import os
import django

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bolio_core.settings')
django.setup()

from django.contrib.auth import get_user_model

def create_admin():
    User = get_user_model()
    
    # Get credentials from environment variables with safe fallbacks
    username = os.getenv('ADMIN_USERNAME', 'admin')
    email = os.getenv('ADMIN_EMAIL', 'admin@example.com')
    password = os.getenv('ADMIN_PASSWORD', 'admin123')

    try:
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username, email, password)
            print(f"Successfully created superuser: {username}")
        else:
            print(f"Superuser '{username}' already exists. Skipping creation.")
    except Exception as e:
        print(f"Error creating superuser: {e}")

if __name__ == "__main__":
    create_admin()
