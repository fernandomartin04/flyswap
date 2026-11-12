from django.contrib import admin
from .models import Vuelo, Reserva, Operacion

# Registramos las 3 tablas en el panel de administrador de Django para verlas fácilmente
admin.site.register(Vuelo)
admin.site.register(Reserva)
admin.site.register(Operacion)
