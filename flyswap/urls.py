from django.contrib import admin
from django.urls import path

# En el Paso 2 añadiremos aquí las rutas de nuestra aplicación 'reservas'
urlpatterns = [
    path('admin/', admin.site.urls),
]
