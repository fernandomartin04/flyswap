from datetime import datetime
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from reservas.models import Vuelo, Reserva, Operacion
from reservas import redis_service


class Command(BaseCommand):
    help = "Carga usuarios, vuelos, reservas y operaciones de prueba en la base de datos SQL"

    def handle(self, *args, **kwargs):
        self.stdout.write("==========================================================")
        self.stdout.write("CARGANDO DATOS DE PRUEBA EN FLYSWAP (BASE DE DATOS SQL)")
        self.stdout.write("==========================================================")

        # 1. Limpiamos datos anteriores de nuestras tablas para no duplicar si lo ejecutamos varias veces
        Operacion.objects.all().delete()
        Reserva.objects.all().delete()
        Vuelo.objects.all().delete()

        # 2. Creamos los usuarios del grupo y un administrador (contraseña para todos: 1234)
        usuarios_datos = [
            ("admin", "admin@flyswap.es", True),
            ("fernando", "fernando@flyswap.es", False),
            ("alfonso", "alfonso@flyswap.es", False),
            ("josemaria", "josemaria@flyswap.es", False),
        ]

        usuarios = {}
        for username, email, es_admin in usuarios_datos:
            user, creado = User.objects.get_or_create(
                username=username,
                defaults={"email": email, "is_staff": es_admin, "is_superuser": es_admin}
            )
            user.set_password("1234")
            user.is_staff = es_admin
            user.is_superuser = es_admin
            user.save()
            usuarios[username] = user

        self.stdout.write("-> Usuarios listos: admin, fernando, alfonso, josemaria (password: 1234)")

        # 3. Creamos un catálogo sencillo y realista de vuelos
        # Formato: (codigo, aerolinea, origen, destino, año, mes, dia, hora, min, precio_original, precio_cambio)
        lista_vuelos = [
            ("FR4012", "Ryanair", "Sevilla", "Roma", 2026, 12, 10, 9, 30, "150.00", "35.00"),
            ("IB3120", "Iberia", "Sevilla", "Madrid", 2026, 12, 12, 8, 15, "110.00", "20.00"),
            ("VY2210", "Vueling", "Sevilla", "Barcelona", 2026, 12, 14, 16, 45, "130.00", "25.00"),
            ("VY8140", "Vueling", "Madrid", "París", 2026, 12, 15, 11, 0, "180.00", "30.00"),
            ("FR9910", "Ryanair", "Sevilla", "Londres", 2026, 12, 18, 19, 20, "165.00", "40.00"),
            ("IB5090", "Iberia", "Madrid", "Roma", 2026, 12, 20, 14, 10, "195.00", "25.00"),
        ]

        vuelos_obj = {}
        for cod, aero, orig, dest, y, m, d, h, mins, p_orig, p_cambio in lista_vuelos:
            fecha = timezone.make_aware(datetime(y, m, d, h, mins))
            v = Vuelo.objects.create(
                codigo_vuelo=cod,
                aerolinea=aero,
                origen=orig,
                destino=dest,
                fecha_salida=fecha,
                precio_original=Decimal(p_orig),
                precio_cambio_nombre=Decimal(p_cambio),
            )
            vuelos_obj[cod] = v

        self.stdout.write(f"-> Vuelos creados: {len(vuelos_obj)}")

        # 4. Creamos reservas publicadas por distintos usuarios (algunas disponibles y otras ya vendidas)
        # Formato: (localizador, vendedor_user, codigo_vuelo, asiento, precio_cesion, estado)
        lista_reservas = [
            ("LOC-101A", "fernando", "FR4012", "14A", "65.00", "DISPONIBLE"),   # Total comprador: 65 + 35 = 100€ (Original 150€)
            ("LOC-102B", "alfonso", "IB3120", "08C", "50.00", "DISPONIBLE"),    # Total comprador: 50 + 20 = 70€  (Original 110€)
            ("LOC-103C", "josemaria", "VY2210", "21F", "60.00", "DISPONIBLE"),  # Total comprador: 60 + 25 = 85€  (Original 130€)
            ("LOC-104D", "fernando", "VY8140", "11B", "90.00", "DISPONIBLE"),   # Total comprador: 90 + 30 = 120€ (Original 180€)
            ("LOC-105E", "alfonso", "FR9910", "04A", "70.00", "DISPONIBLE"),    # Total comprador: 70 + 40 = 110€ (Original 165€)
            ("LOC-201X", "fernando", "IB5090", "16D", "100.00", "VENDIDA"),     # Ya vendida a josemaria
            ("LOC-202Y", "josemaria", "FR4012", "15B", "70.00", "VENDIDA"),     # Ya vendida a alfonso
        ]

        reservas_obj = {}
        for loc, vend_name, cod_vuelo, asiento, p_cesion, estado in lista_reservas:
            r = Reserva.objects.create(
                localizador=loc,
                vendedor=usuarios[vend_name],
                vuelo=vuelos_obj[cod_vuelo],
                asiento=asiento,
                precio_cesion=Decimal(p_cesion),
                estado=estado,
            )
            reservas_obj[loc] = r

        self.stdout.write(f"-> Reservas creadas: {len(reservas_obj)} (5 disponibles y 2 vendidas)")

        # 5. Creamos las operaciones cerradas para las 2 reservas que están marcadas como VENDIDA
        r1 = reservas_obj["LOC-201X"]
        Operacion.objects.create(
            reserva=r1,
            vendedor=r1.vendedor,
            comprador=usuarios["josemaria"],
            importe_pagado=r1.precio_total_comprador,
        )

        r2 = reservas_obj["LOC-202Y"]
        Operacion.objects.create(
            reserva=r2,
            vendedor=r2.vendedor,
            comprador=usuarios["alfonso"],
            importe_pagado=r2.precio_total_comprador,
        )

        self.stdout.write("-> Operaciones históricas creadas: 2")
        self.stdout.write(self.style.SUCCESS("¡Base de datos SQL poblada con éxito!"))

        # 6. REDIS: vaciamos la caché de búsquedas para que no muestre datos de la carga anterior
        borradas = redis_service.invalidar_cache_busquedas()
        self.stdout.write(f"-> Redis: caché de búsquedas vaciada ({borradas} claves borradas)")
