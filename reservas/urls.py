from django.urls import path
from . import views

# Rutas sencillas y claras para cada funcionalidad de FlySwap
urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('reserva/<int:reserva_id>/', views.detalle_reserva, name='detalle_reserva'),
    # Compra en 2 pasos: iniciar (lock + OTP en Redis) -> comprar (valida OTP + transacción SQL)
    path('reserva/<int:reserva_id>/iniciar-compra/', views.iniciar_compra, name='iniciar_compra'),
    path('reserva/<int:reserva_id>/cancelar-compra/', views.cancelar_compra, name='cancelar_compra'),
    path('reserva/<int:reserva_id>/comprar/', views.comprar_reserva, name='comprar_reserva'),
    path('publicar/', views.publicar_reserva, name='publicar_reserva'),
    path('historial/', views.historial_usuario, name='historial_usuario'),
    path('login/', views.login_usuario, name='login_usuario'),
    path('registro/', views.registro_usuario, name='registro_usuario'),
    path('logout/', views.logout_usuario, name='logout_usuario'),
]
