from django.contrib import admin
from django.urls import path, include

# Conectamos el panel de administrador y todas las rutas de nuestra app 'reservas'
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('reservas.urls')),
]
