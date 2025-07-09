from .base import *
import sys

DEBUG = True

SECRET_KEY = "django-insecure-pn-#@uf@1!0lm!7p27d5^_)2)yw=6joel7qklh)8l(!p4fe_&_"

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
]

INSTALLED_APPS += [
    "debug_toolbar",
]
MIDDLEWARE += [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
]
INTERNAL_IPS = [
    "127.0.0.1",
    "localhost",
]

DATABASES = {
    "default": {
        # "ENGINE": "django.db.backends.sqlite3",
        # "NAME": BASE_DIR / "db.sqlite3",
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("MYSQL_DATABASE"),
        "HOST": os.environ.get("MYSQL_DATABASE_HOST"),
        "USER": os.environ.get("MYSQL_DATABASE_USER_NAME"),
        "PASSWORD": os.environ.get("MYSQL_ROOT_PASSWORD"),  # "Sumit@Dey",
        "PORT": "3306",
        "OPTIONS": {
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            "charset": "utf8mb4",
        },
    }
}

CELERY_BROKER_URL = "amqp://guest:guest@localhost:5672//"

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "kit.time.clg@gmail.com"
EMAIL_HOST_PASSWORD = "orsx rgvp rjcu miuy"

GOOGLE_API_KEY = "AIzaSyBIi5-B03yNolwRaQeWzy4n-XFpSUdzJBo"

LOGIN_URL = "https://hdip.vercel.app/auth/signin/loginmail"
BASE_URL = "https://hdip.vercel.app/api"
SITE_DOMAIN = "localhost:5173"
CF_CLIENTID = os.environ.get("CF_CLIENTID")
CF_CLIENTSECRET = os.environ.get("CF_CLIENTSECRET")
CF_RETURNURL = os.environ.get("CF_RETURNURL")

TAWKTO_API = os.environ.get("TAWKTO_API")

LOGGING["loggers"]["hdip"]["handlers"].append("console")
