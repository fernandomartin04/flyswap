from django.db import models
from django.contrib.auth.models import User


# =========================================================================
# 1. TABLA VUELO: Información objetiva del viaje y tasas de la aerolínea
# =========================================================================
class Vuelo(models.Model):
    codigo_vuelo = models.CharField(max_length=20)
    aerolinea = models.CharField(max_length=60)
    # Añadimos índice (db_index=True) en origen, destino y fecha_salida para acelerar el buscador
    origen = models.CharField(max_length=80, db_index=True)
    destino = models.CharField(max_length=80, db_index=True)
    fecha_salida = models.DateTimeField(db_index=True)
    # Precio que costaba el billete originalmente en la aerolínea
    precio_original = models.DecimalField(max_digits=8, decimal_places=2)
    # Tasa extra que cobra la aerolínea por cambiar el nombre/titular del asiento
    precio_cambio_nombre = models.DecimalField(max_digits=8, decimal_places=2)

    def __str__(self):
        return f"{self.codigo_vuelo} ({self.origen} -> {self.destino})"


# =========================================================================
# 2. TABLA RESERVA: El billete/anuncio que un usuario pone en venta
# =========================================================================
class Reserva(models.Model):
    ESTADOS = [
        ('DISPONIBLE', 'Disponible'),
        ('VENDIDA', 'Vendida'),
    ]

    localizador = models.CharField(max_length=30, unique=True)
    # Usuario titular que publica la reserva porque no va a poder viajar
    vendedor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reservas_publicadas')
    # Vuelo al que corresponde este billete
    vuelo = models.ForeignKey(Vuelo, on_delete=models.CASCADE, related_name='reservas')
    asiento = models.CharField(max_length=10)
    # Precio que pide el vendedor por ceder su reserva
    precio_cesion = models.DecimalField(max_digits=8, decimal_places=2)
    # En SQL solo guardamos el estado definitivo (el bloqueo temporal irá en Redis con TTL)
    estado = models.CharField(max_length=15, choices=ESTADOS, default='DISPONIBLE', db_index=True)
    fecha_publicacion = models.DateTimeField(auto_now_add=True)

    # Propiedad sencilla para saber cuánto pagará en total el comprador (cesión + cambio de nombre)
    @property
    def precio_total_comprador(self):
        return self.precio_cesion + self.vuelo.precio_cambio_nombre

    # Propiedad sencilla para ver cuánto dinero se ahorra el comprador respecto al precio original
    @property
    def ahorro_comprador(self):
        return self.vuelo.precio_original - self.precio_total_comprador

    def __str__(self):
        return f"Reserva {self.localizador} - {self.vuelo.codigo_vuelo} ({self.estado})"


# =========================================================================
# 3. TABLA OPERACION: Registro histórico/recibo cuando se cierra una compra
# =========================================================================
class Operacion(models.Model):
    # Relación 1 a 1: garantiza en SQL que una misma reserva solo se puede vender una vez
    # Usamos PROTECT para evitar que se borre por accidente una reserva o usuario con operaciones cerradas
    reserva = models.OneToOneField(Reserva, on_delete=models.PROTECT, related_name='operacion')
    # Guardamos tanto vendedor como comprador para consultar el historial directamente sin JOINs complejos
    vendedor = models.ForeignKey(User, on_delete=models.PROTECT, related_name='ventas_realizadas')
    comprador = models.ForeignKey(User, on_delete=models.PROTECT, related_name='compras_realizadas')
    # Importe final pagado (precio_cesion + precio_cambio_nombre)
    importe_pagado = models.DecimalField(max_digits=8, decimal_places=2)
    fecha_operacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Operación #{self.id}: {self.vendedor.username} -> {self.comprador.username} ({self.importe_pagado} €)"
