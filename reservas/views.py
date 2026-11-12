from decimal import Decimal, InvalidOperation
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from .models import Vuelo, Reserva, Operacion


# =========================================================================
# F3: PÁGINA PRINCIPAL Y BUSCADOR DE RESERVAS DISPONIBLES
# =========================================================================
def inicio(request):
    # Recogemos lo que el usuario haya escrito en los filtros del buscador (por GET)
    origen_q = request.GET.get('origen', '').strip()
    destino_q = request.GET.get('destino', '').strip()

    # Consulta básica en SQL: traemos las reservas DISPONIBLES de vuelos futuros en una sola consulta
    reservas = Reserva.objects.select_related('vuelo', 'vendedor').filter(
        estado='DISPONIBLE',
        vuelo__fecha_salida__gt=timezone.now(),
    )

    # Si el usuario filtró por origen o destino, aplicamos el filtro (icontains ignora mayúsculas/minúsculas)
    if origen_q:
        reservas = reservas.filter(vuelo__origen__icontains=origen_q)
    if destino_q:
        reservas = reservas.filter(vuelo__destino__icontains=destino_q)

    # Ordenamos por fecha de salida del vuelo más próxima
    reservas = reservas.order_by('vuelo__fecha_salida')

    contexto = {
        'reservas': reservas,
        'origen_q': origen_q,
        'destino_q': destino_q,
    }
    return render(request, 'reservas/inicio.html', contexto)


# =========================================================================
# F4: CONSULTAR DETALLE DE UNA RESERVA
# =========================================================================
def detalle_reserva(request, reserva_id):
    # Buscamos la reserva por su ID (si no existe devuelve error 404)
    reserva = get_object_or_404(Reserva.objects.select_related('vuelo', 'vendedor'), id=reserva_id)
    return render(request, 'reservas/detalle.html', {'reserva': reserva})


# =========================================================================
# F5: ADQUIRIR RESERVA (COMPRA / CESIÓN SIMULADA CON TRANSACCIÓN SQL)
# =========================================================================
@login_required(login_url='login_usuario')
def comprar_reserva(request, reserva_id):
    if request.method != 'POST':
        return redirect('detalle_reserva', reserva_id=reserva_id)

    # Usamos transacción atómica y select_for_update() para evitar que dos usuarios la compren a la vez
    with transaction.atomic():
        reserva = get_object_or_404(
            Reserva.objects.select_for_update().select_related('vuelo', 'vendedor'),
            id=reserva_id,
        )

        # Comprobación 1: Que la reserva siga disponible
        if reserva.estado != 'DISPONIBLE':
            messages.error(request, 'Esta reserva ya no está disponible.')
            return redirect('inicio')

        # Comprobación 2: Que el vuelo no haya salido ya
        if reserva.vuelo.fecha_salida <= timezone.now():
            messages.error(request, 'No se puede comprar una reserva de un vuelo que ya ha salido.')
            return redirect('inicio')

        # Comprobación 3: Un usuario no puede comprarse a sí mismo su propia reserva
        if reserva.vendedor == request.user:
            messages.error(request, 'No puedes comprar una reserva que has publicado tú mismo.')
            return redirect('detalle_reserva', reserva_id=reserva.id)

        reserva.estado = 'VENDIDA'
        reserva.save()

        # Guardamos el recibo en Operacion incluyendo tanto vendedor como comprador
        Operacion.objects.create(
            reserva=reserva,
            vendedor=reserva.vendedor,
            comprador=request.user,
            importe_pagado=reserva.precio_total_comprador,
        )

    messages.success(
        request,
        f'¡Compra completada! Has adquirido la reserva {reserva.localizador} por {reserva.precio_total_comprador} € (cesión + cambio de nombre).'
    )
    return redirect('historial_usuario')


# =========================================================================
# F2: PUBLICAR UNA NUEVA RESERVA PARA CEDER / REVENDER
# =========================================================================
@login_required(login_url='login_usuario')
def publicar_reserva(request):
    # Traemos solo los vuelos futuros para el desplegable
    vuelos_existentes = Vuelo.objects.filter(fecha_salida__gt=timezone.now()).order_by('fecha_salida')

    if request.method == 'POST':
        localizador = request.POST.get('localizador', '').strip().upper()
        asiento = request.POST.get('asiento', '').strip().upper()
        vuelo_id = request.POST.get('vuelo_id', '')

        # Validamos que localizador y asiento no estén vacíos y que el precio sea un número positivo
        try:
            precio_cesion = Decimal(request.POST.get('precio_cesion', ''))
        except InvalidOperation:
            messages.error(request, 'El precio de cesión introducido no es válido.')
            return render(request, 'reservas/publicar.html', {'vuelos': vuelos_existentes})

        if not localizador or not asiento or precio_cesion <= 0:
            messages.error(request, 'Completa el localizador y asiento, e indica un precio de cesión mayor que 0 €.')
            return render(request, 'reservas/publicar.html', {'vuelos': vuelos_existentes})

        # Comprobamos que el localizador no esté repetido en la base de datos
        if Reserva.objects.filter(localizador=localizador).exists():
            messages.error(request, 'Ya existe una reserva publicada con ese código localizador.')
            return render(request, 'reservas/publicar.html', {'vuelos': vuelos_existentes})

        # Si eligió un vuelo que ya existe en la tabla Vuelo, lo usamos; si no, creamos el vuelo nuevo
        if vuelo_id and vuelo_id != 'nuevo':
            vuelo = get_object_or_404(Vuelo, id=vuelo_id)
            if vuelo.fecha_salida <= timezone.now():
                messages.error(request, 'El vuelo seleccionado ya ha salido.')
                return render(request, 'reservas/publicar.html', {'vuelos': vuelos_existentes})
        else:
            codigo_vuelo = request.POST.get('codigo_vuelo', '').strip().upper()
            aerolinea = request.POST.get('aerolinea', '').strip()
            origen = request.POST.get('origen', '').strip()
            destino = request.POST.get('destino', '').strip()
            fecha_str = request.POST.get('fecha_salida', '').strip()

            try:
                precio_original = Decimal(request.POST.get('precio_original', ''))
                precio_cambio = Decimal(request.POST.get('precio_cambio_nombre', ''))
                fecha_dt = timezone.make_aware(datetime.strptime(fecha_str, '%Y-%m-%dT%H:%M'))
            except (InvalidOperation, ValueError):
                messages.error(request, 'Revisa la fecha y los importes del nuevo vuelo.')
                return render(request, 'reservas/publicar.html', {'vuelos': vuelos_existentes})

            if not all([codigo_vuelo, aerolinea, origen, destino]) or precio_original <= 0 or precio_cambio < 0:
                messages.error(request, 'Completa todos los datos del vuelo con precios válidos.')
                return render(request, 'reservas/publicar.html', {'vuelos': vuelos_existentes})

            if fecha_dt <= timezone.now():
                messages.error(request, 'La fecha de salida del vuelo debe ser posterior al momento actual.')
                return render(request, 'reservas/publicar.html', {'vuelos': vuelos_existentes})

            vuelo = Vuelo.objects.create(
                codigo_vuelo=codigo_vuelo,
                aerolinea=aerolinea,
                origen=origen,
                destino=destino,
                fecha_salida=fecha_dt,
                precio_original=precio_original,
                precio_cambio_nombre=precio_cambio,
            )

        # Evitamos que se publique dos veces el mismo asiento disponible en el mismo vuelo
        if Reserva.objects.filter(vuelo=vuelo, asiento=asiento, estado='DISPONIBLE').exists():
            messages.error(request, f'El asiento {asiento} ya está anunciado como disponible en ese vuelo.')
            return render(request, 'reservas/publicar.html', {'vuelos': vuelos_existentes})

        # Creamos la reserva en estado DISPONIBLE asociada al usuario conectado como vendedor
        Reserva.objects.create(
            localizador=localizador,
            vendedor=request.user,
            vuelo=vuelo,
            asiento=asiento,
            precio_cesion=precio_cesion,
            estado='DISPONIBLE',
        )

        messages.success(request, f'Reserva {localizador} publicada correctamente.')
        return redirect('inicio')

    return render(request, 'reservas/publicar.html', {'vuelos': vuelos_existentes})


# =========================================================================
# F6: HISTORIAL DEL USUARIO (COMPRAS, VENTAS Y RESERVAS EN VENTA)
# =========================================================================
@login_required(login_url='login_usuario')
def historial_usuario(request):
    # Gracias a tener 'comprador' y 'vendedor' en Operacion, las dos consultas son directas y sencillas
    mis_compras = Operacion.objects.select_related('reserva__vuelo', 'vendedor').filter(
        comprador=request.user
    ).order_by('-fecha_operacion')

    mis_ventas = Operacion.objects.select_related('reserva__vuelo', 'comprador').filter(
        vendedor=request.user
    ).order_by('-fecha_operacion')

    mis_reservas_activas = Reserva.objects.select_related('vuelo').filter(
        vendedor=request.user,
        estado='DISPONIBLE'
    ).order_by('-fecha_publicacion')

    contexto = {
        'mis_compras': mis_compras,
        'mis_ventas': mis_ventas,
        'mis_reservas_activas': mis_reservas_activas,
    }
    return render(request, 'reservas/historial.html', contexto)


# =========================================================================
# F1: REGISTRO, INICIO Y CIERRE DE SESIÓN
# =========================================================================
def login_usuario(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f'¡Hola de nuevo, {user.username}!')
            return redirect('inicio')
        else:
            messages.error(request, 'Usuario o contraseña incorrectos.')

    return render(request, 'reservas/login.html')


def registro_usuario(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')

        if not username or not email or not password.strip():
            messages.error(request, 'Debes rellenar usuario, correo y una contraseña válida.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, 'Ese nombre de usuario ya está en uso.')
        else:
            nuevo_user = User.objects.create_user(username=username, email=email, password=password)
            login(request, nuevo_user)
            messages.success(request, f'Cuenta creada con éxito. ¡Bienvenido, {nuevo_user.username}!')
            return redirect('inicio')

    return render(request, 'reservas/registro.html')


def logout_usuario(request):
    if request.method == 'POST':
        logout(request)
        messages.info(request, 'Has cerrado sesión correctamente.')
    return redirect('inicio')
