"""Do'kon CRM sozlamalari. Maxfiy qiymatlar .env faylidan o'qiladi."""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-only-insecure-key-change-me')
DEBUG = os.environ.get('DEBUG', '1') == '1'
ALLOWED_HOSTS = [h for h in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',') if o]
# Railway o'zi beradigan domen (masalan dokon-production.up.railway.app)
if os.environ.get('RAILWAY_PUBLIC_DOMAIN'):
    ALLOWED_HOSTS.append(os.environ['RAILWAY_PUBLIC_DOMAIN'])
    CSRF_TRUSTED_ORIGINS.append(f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}")

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'core',
    'inventory',
    'sales',
    'reports',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.LanguageMiddleware',
    'core.middleware.ForcePasswordChangeMiddleware',
    'core.middleware.NoIndexMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.app_context',
            ],
            'builtins': ['core.templatetags.t'],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# DATABASE_URL berilmasa lokal SQLite ishlatiladi.
# Neon/Supabase uchun: DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
DATABASES = {
    'default': dj_database_url.parse(
        os.environ.get('DATABASE_URL') or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

AUTH_USER_MODEL = 'core.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 6}},
]

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'login'

LANGUAGE_CODE = 'uz'
TIME_ZONE = 'Asia/Tashkent'
USE_I18N = True
LANGUAGES = [('uz', "O'zbek"), ('ru', 'Русский')]
USE_TZ = True
USE_THOUSAND_SEPARATOR = True
THOUSAND_SEPARATOR = ' '
NUMBER_GROUPING = 3

# Statik fayllar collectstatic qilinmasa ham to'g'ridan-to'g'ri xizmat qilinadi
WHITENOISE_USE_FINDERS = True

# HTTPS orqali ishlaganda (internetga joylanganda) SECURE_COOKIES=1 qiling
if os.environ.get('SECURE_COOKIES', '0') == '1':
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 12  # 12 soat
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True

if not DEBUG and SECRET_KEY.startswith('dev-only'):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(".env faylida SECRET_KEY o'rnatilmagan")

(BASE_DIR / 'logs').mkdir(exist_ok=True)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {'class': 'logging.FileHandler', 'filename': BASE_DIR / 'logs' / 'app.log', 'encoding': 'utf-8'},
        'console': {'class': 'logging.StreamHandler'},
    },
    'root': {'handlers': ['file', 'console'], 'level': 'WARNING'},
}

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Do'kon sozlamalari
SHOP_NAME = os.environ.get('SHOP_NAME', "Do'kon")
SHOP_ADDRESS = os.environ.get('SHOP_ADDRESS', '')
SHOP_PHONE = os.environ.get('SHOP_PHONE', '')
# Ommaviy bosh sahifa va Google uchun
SHOP_DESCRIPTION = os.environ.get('SHOP_DESCRIPTION', '')
SHOP_HOURS = os.environ.get('SHOP_HOURS', '')  # masalan: Har kuni 08:00-22:00
SHOP_CITY = os.environ.get('SHOP_CITY', '')
GOOGLE_SITE_VERIFICATION = os.environ.get('GOOGLE_SITE_VERIFICATION', '')
EXPIRY_WARNING_DAYS = int(os.environ.get('EXPIRY_WARNING_DAYS', '30'))

# Avtomatik vazifalar vaqti (telegram_bot ishlab turganda bajariladi)
DAILY_REPORT_TIME = os.environ.get('DAILY_REPORT_TIME', '21:00')
DEBT_REMINDER_TIME = os.environ.get('DEBT_REMINDER_TIME', '10:00')
BACKUP_TIME = os.environ.get('BACKUP_TIME', '21:30')

# Telegram bot (ega uchun hisobot va ogohlantirishlar, qarzdorlarga eslatma)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_OWNER_CHAT_ID = os.environ.get('TELEGRAM_OWNER_CHAT_ID', '')

# Eskiz.uz SMS xizmati (qarzdorlarga eslatma)
ESKIZ_EMAIL = os.environ.get('ESKIZ_EMAIL', '')
ESKIZ_PASSWORD = os.environ.get('ESKIZ_PASSWORD', '')
ESKIZ_FROM = os.environ.get('ESKIZ_FROM', '4546')
