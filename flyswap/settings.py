import os
from pathlib import Path

# Ruta base del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent

# Leemos la clave secreta y el modo debug desde las variables de entorno (.env)
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'clave-por-defecto-desarrollo')
DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('1','true','yes','on')

# Hosts permitidos leídos desde .env (separados por coma) con valores locales por defecto
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,web').split(',') if h.strip()]
# Uso strip para quitar los espacios en blanco alrededor de cada host

# Aplicaciones de Django + nuestra app 'reservas' donde irá toda la lógica de FlySwap
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'reservas',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'flyswap.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # Directorio base para templates compartidos
        'APP_DIRS': True, # Busca templates dentro de cada app
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

WSGI_APPLICATION = 'flyswap.wsgi.application'

# -------------------------------------------------------------------------
# 1. BASE DE DATOS PRINCIPAL (SQL - Fuente de verdad del negocio)
# Guardamos el archivo SQLite en la carpeta 'datos_sql' para que persista en el volumen de Docker
# -------------------------------------------------------------------------
CARPETA_SQL = BASE_DIR / 'datos_sql'
CARPETA_SQL.mkdir(exist_ok=True)

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': CARPETA_SQL / 'db.sqlite3',
    }
}

# -------------------------------------------------------------------------
# 2. VARIABLES DE CONEXIÓN A LAS BASES DE DATOS NOSQL (Redis, MongoDB, Neo4j)
# Las dejamos leídas aquí desde el .env para usarlas fácilmente en los siguientes pasos
# -------------------------------------------------------------------------
REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))

MONGO_HOST = os.environ.get('MONGO_HOST', 'localhost')
MONGO_PORT = int(os.environ.get('MONGO_PORT', 27017))
MONGO_DB = os.environ.get('MONGO_DB', 'flyswap_logs')

NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'password-por-defecto')

# Idioma y zona horaria de España
LANGUAGE_CODE = 'es-es'
TIME_ZONE = 'Europe/Madrid'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static'] # Directorio base para archivos estáticos como css o bootstrap
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
