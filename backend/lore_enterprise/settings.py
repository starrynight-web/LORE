import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get('DEBUG', 'True').lower() in ('true', '1', 'yes')

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'lore-enterprise-dev-secret-key-insecure-only-for-dev'
    else:
        raise ImproperlyConfigured("SECRET_KEY environment variable is required in production.")

raw_allowed_hosts = os.environ.get('ALLOWED_HOSTS', '*')
ALLOWED_HOSTS = [h.strip() for h in raw_allowed_hosts.split(',') if h.strip()] if raw_allowed_hosts != '*' else ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party apps
    'rest_framework',
    'rest_framework.authtoken',
    'corsheaders',
    
    # LORE Enterprise domain apps
    'apps.identity',
    'apps.workspaces',
    'apps.sources',
    'apps.ingestion',
    'apps.knowledge',
    'apps.retrieval',
    'apps.governance',
    'apps.decisions',
    'apps.audit',
    'apps.subscriptions',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'lore_enterprise.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'lore_enterprise.wsgi.application'
ASGI_APPLICATION = 'lore_enterprise.asgi.application'

# Database: PostgreSQL with fallback to SQLite for local standalone development
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres'):
    import dj_database_url
    DATABASES['default'] = dj_database_url.parse(DATABASE_URL)

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/minute',
        'user': '1200/minute',
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# CORS Configuration
raw_cors = os.environ.get('CORS_ALLOWED_ORIGINS')
if raw_cors:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in raw_cors.split(',') if o.strip()]
    CORS_ALLOW_ALL_ORIGINS = False
else:
    CORS_ALLOW_ALL_ORIGINS = True  # Safe dev fallback; override with CORS_ALLOWED_ORIGINS in prod
CORS_ALLOW_CREDENTIALS = True

# Embedding & Retrieval Engine Configuration
# Providers: 'sentence-transformers' (default local semantic), 'openai', 'test-projection'
EMBEDDING_PROVIDER = os.environ.get('EMBEDDING_PROVIDER', 'sentence-transformers')
EMBEDDING_MODEL_NAME = os.environ.get('EMBEDDING_MODEL_NAME', 'all-MiniLM-L6-v2')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')
OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')

# SaaS Subscriptions & Billing Configuration
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
BILLING_ENABLED = os.environ.get('BILLING_ENABLED', 'False').lower() in ('true', '1', 'yes')

# Celery Configuration
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
# If Celery worker is not running, run tasks synchronously in eager mode for development/tests
CELERY_TASK_ALWAYS_EAGER = os.environ.get('CELERY_ALWAYS_EAGER', 'True').lower() in ('true', '1', 'yes')

# Qdrant Vector Engine Configuration
QDRANT_URL = os.environ.get('QDRANT_URL', '')
QDRANT_API_KEY = os.environ.get('QDRANT_API_KEY', '')
QDRANT_LOCAL_PATH = os.environ.get('QDRANT_LOCAL_PATH', str(BASE_DIR / 'qdrant_storage'))

# OCR & Tesseract Binary Auto-detection
TESSERACT_CMD = os.environ.get('TESSERACT_CMD', '')
if not TESSERACT_CMD:
    possible_paths = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        '/usr/bin/tesseract',
        '/usr/local/bin/tesseract',
    ]
    for p in possible_paths:
        if os.path.exists(p):
            TESSERACT_CMD = p
            break
