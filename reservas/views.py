from decimal import Decimal, InvalidOperation
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import Vuelo, Reserva, Operacion
from . import redis_service


# =========================================================================
# AYUDANTES PARA LA CACHÉ DE BÚSQUEDAS (Redis)
# En la caché no podemos guardar objetos de Django, solo texto (JSON).
# Por eso convertimos cada reserva en un diccionario "plano" con lo que
# necesita la tabla de inicio.html. Usamos el MISMO formato tanto si los datos
# vienen de SQL como de Redis, así la plantilla no tiene que distinguirlos.
# =========================================================================
def _reserva_a_fila(r):
    return {
        'id': r.id,
        'codigo_vuelo': r.vuelo.codigo_vuelo,
        'aerolinea': r.vuelo.aerolinea,
        'asiento': r.asiento,
        'origen': r.vuelo.origen,
        'destino': r.vuelo.destino,
        'fecha_salida': r.vuelo.fecha_salida,
        'vendedor': r.vendedor.username,
        'precio_original': r.vuelo.precio_original,
        'precio_cesion': r.precio_cesion,
        'precio_cambio_nombre': r.vuelo.precio_cambio_nombre,
        'precio_total': r.precio_total_comprador,
        'ahorro': r.ahorro_comprador,
    }


def _fila_desde_cache(fila):
    # Al leer de Redis los importes y la fecha llegan como texto:
    # los volvemos a convertir a Decimal y datetime para que la plantilla
    # pueda comparar (ahorro > 0) y formatear la fecha (|date) igual que antes.
    for campo in ('precio_original', 'precio_cesion', 'precio_cambio_nombre', 'precio_total', 'ahorro'):
        fila[campo] = Decimal(fila[campo])
    fila['fecha_salida'] = parse_datetime(fila['fecha_salida'])
    return fila


# =========================================================================
# F3: PÁGINA PRINCIPAL Y BUSCADOR DE RESERVAS DISPONIBLES (con caché Redis)
# =========================================================================
def inicio(request):
    # Recogemos lo que el usuario haya escrito en los filtros del buscador (por GET)
    origen_q = request.GET.get('origen', '').strip()
    destino_q = request.GET.get('destino', '').strip()

    # 1) Primero preguntamos a Redis si esta búsqueda ya está cacheada (cache HIT)
    filas_cache = redis_service.obtener_busqueda_cache(origen_q, destino_q)

    if filas_cache is not None:
        reservas = [_fila_desde_cache(f) for f in filas_cache]
        origen_datos = 'redis'
    else:
        # 2) Cache MISS: consulta básica en SQL de las reservas DISPONIBLES de vuelos futuros
        consulta = Reserva.objects.select_related('vuelo', 'vendedor').filter(
            estado='DISPONIBLE',
            vuelo__fecha_salida__gt=timezone.now(),
        )

        # Si el usuario filtró por origen o destino, aplicamos el filtro (icontains ignora mayúsculas/minúsculas)
        if origen_q:
            consulta = consulta.filter(vuelo__origen__icontains=origen_q)
        if destino_q:
            consulta = consulta.filter(vuelo__destino__icontains=destino_q)

        # Ordenamos por fecha de salida del vuelo más próxima
        reservas = [_reserva_a_fila(r) for r in consulta.order_by('vuelo__fecha_salida')]

        # 3) Guardamos el resultado en Redis con TTL para las siguientes búsquedas iguales.
        # Si Redis está caído, guardar devuelve False y lo indicamos en pantalla (la web sigue funcionando).
        if redis_service.guardar_busqueda_cache(origen_q, destino_q, reservas):
            origen_datos = 'sql'
        else:
            origen_datos = 'sql_sin_redis'

    contexto = {
        'reservas': reservas,
        'origen_q': origen_q,
        'destino_q': destino_q,
        'origen_datos': origen_datos,
        'ttl_cache': redis_service.TTL_CACHE_BUSQUEDA,
    }
    return render(request, 'reservas/inicio.html', contexto)


# =========================================================================
# F4: CONSULTAR DETALLE DE UNA RESERVA (+ estado del bloqueo en Redis)
# =========================================================================
def detalle_reserva(request, reserva_id):
    # Buscamos la reserva por su ID (si no existe devuelve error 404)
    reserva = get_object_or_404(Reserva.objects.select_related('vuelo', 'vendedor'), id=reserva_id)

    # Consultamos en Redis si alguien está comprando esta reserva ahora mismo,
    # para mostrar el botón adecuado (iniciar compra, introducir OTP o "bloqueada")
    lock_mio = False
    lock_segundos = 0
    redis_caido = False
    if reserva.estado == 'DISPONIBLE' and request.user.is_authenticated:
        try:
            lock_mio, lock_segundos = redis_service.estado_lock(reserva.id, request.user.id)
        except redis_service.RedisNoDisponible:
            redis_caido = True

    contexto = {
        'reserva': reserva,
        'lock_mio': lock_mio,
        # Bloqueada por OTRO usuario: hay segundos restantes pero el bloqueo no es nuestro
        'lock_ajeno_segundos': lock_segundos if (lock_segundos and not lock_mio) else 0,
        'lock_segundos': lock_segundos,
        'redis_caido': redis_caido,
    }
    return render(request, 'reservas/detalle.html', contexto)


# =========================================================================
# F5 (paso 1): INICIAR COMPRA -> BLOQUEO TEMPORAL EN REDIS + CÓDIGO OTP
# =========================================================================
def _motivo_no_comprable(reserva, usuario):
    # Mismas comprobaciones de negocio que hace la compra en SQL.
    # Las hacemos también aquí para no bloquear ni generar OTP de algo que no se puede comprar.
    if reserva.estado != 'DISPONIBLE':
        return 'Esta reserva ya no está disponible.'
    if reserva.vuelo.fecha_salida <= timezone.now():
        return 'No se puede comprar una reserva de un vuelo que ya ha salido.'
    if reserva.vendedor == usuario:
        return 'No puedes comprar una reserva que has publicado tú mismo.'
    return None


@login_required(login_url='login_usuario')
def iniciar_compra(request, reserva_id):
    # Cambia estado (crea un bloqueo), así que solo se permite por POST
    if request.method != 'POST':
        return redirect('detalle_reserva', reserva_id=reserva_id)

    reserva = get_object_or_404(Reserva.objects.select_related('vuelo', 'vendedor'), id=reserva_id)

    motivo = _motivo_no_comprable(reserva, request.user)
    if motivo:
        messages.error(request, motivo)
        return redirect('detalle_reserva', reserva_id=reserva.id)

    try:
        # SET lock:reserva:<id> <user_id> NX EX 180
        conseguido, segundos = redis_service.adquirir_lock(reserva.id, request.user.id)
        if not conseguido:
            messages.error(
                request,
                f'Otro usuario está comprando esta reserva ahora mismo. Inténtalo de nuevo en {segundos} segundos.'
            )
            return redirect('detalle_reserva', reserva_id=reserva.id)

        codigo = redis_service.generar_otp(reserva.id, request.user.id)
    except redis_service.RedisNoDisponible:
        # Sin Redis no podemos garantizar el bloqueo ni el OTP, así que preferimos no vender
        messages.error(request, 'El servicio de verificación no está disponible ahora mismo. Inténtalo en unos minutos.')
        return redirect('detalle_reserva', reserva_id=reserva.id)

    # Proyecto académico sin SMS/email real: mostramos el OTP en pantalla para poder introducirlo
    messages.info(
        request,
        f'Reserva bloqueada para ti durante {segundos // 60} minutos. '
        f'Tu código de confirmación (simulado, en producción llegaría por SMS/email) es: {codigo}'
    )
    return redirect('detalle_reserva', reserva_id=reserva.id)


@login_required(login_url='login_usuario')
def cancelar_compra(request, reserva_id):
    # El usuario se arrepiente: liberamos el bloqueo para que otros puedan comprarla ya
    if request.method == 'POST':
        redis_service.limpiar_proceso_compra(reserva_id, request.user.id)
        messages.info(request, 'Has cancelado la compra. La reserva vuelve a estar libre para otros usuarios.')
    return redirect('detalle_reserva', reserva_id=reserva_id)


# =========================================================================
# F5 (paso 2): CONFIRMAR COMPRA CON OTP -> TRANSACCIÓN SQL
# =========================================================================
@login_required(login_url='login_usuario')
def comprar_reserva(request, reserva_id):
    if request.method != 'POST':
        return redirect('detalle_reserva', reserva_id=reserva_id)

    codigo_introducido = request.POST.get('otp', '')

    # --- 1) Comprobaciones en Redis: el bloqueo debe ser nuestro y el OTP correcto ---
    try:
        lock_mio, _ = redis_service.estado_lock(reserva_id, request.user.id)
        if not lock_mio:
            messages.error(request, 'Tu bloqueo de 3 minutos ha caducado o no has iniciado la compra. Pulsa "Iniciar compra" de nuevo.')
            return redirect('detalle_reserva', reserva_id=reserva_id)

        resultado, intentos_restantes = redis_service.validar_otp(reserva_id, request.user.id, codigo_introducido)
    except redis_service.RedisNoDisponible:
        messages.error(request, 'El servicio de verificación no está disponible ahora mismo. Inténtalo en unos minutos.')
        return redirect('detalle_reserva', reserva_id=reserva_id)

    if resultado == 'CADUCADO':
        messages.error(request, 'El código ha caducado. Pulsa "Iniciar compra" para recibir uno nuevo.')
        return redirect('detalle_reserva', reserva_id=reserva_id)
    if resultado == 'INCORRECTO':
        messages.error(request, f'Código incorrecto. Te quedan {intentos_restantes} intentos.')
        return redirect('detalle_reserva', reserva_id=reserva_id)
    if resultado == 'AGOTADO':
        # Demasiados fallos: liberamos la reserva para no tenerla secuestrada
        redis_service.limpiar_proceso_compra(reserva_id, request.user.id)
        messages.error(request, 'Has superado el número de intentos. La compra se ha cancelado y la reserva se ha liberado.')
        return redirect('detalle_reserva', reserva_id=reserva_id)

    # --- 2) OTP correcto: compra en SQL (fuente de verdad) ---
    # Usamos transacción atómica y select_for_update() para evitar que dos usuarios la compren a la vez.
    # El lock de Redis ya evita casi todos los choques; SQL es la última barrera
    # (además Operacion.reserva es OneToOne, así que una reserva nunca puede venderse dos veces).
    with transaction.atomic():
        reserva = get_object_or_404(
            Reserva.objects.select_for_update().select_related('vuelo', 'vendedor'),
            id=reserva_id,
        )

        # Comprobaciones 1, 2 y 3: disponible, vuelo no salido y no autocompra
        motivo = _motivo_no_comprable(reserva, request.user)
        if motivo:
            redis_service.limpiar_proceso_compra(reserva_id, request.user.id)
            messages.error(request, motivo)
            return redirect('detalle_reserva', reserva_id=reserva_id)

        reserva.estado = 'VENDIDA'
        reserva.save()

        # Guardamos el recibo en Operacion incluyendo tanto vendedor como comprador
        Operacion.objects.create(
            reserva=reserva,
            vendedor=reserva.vendedor,
            comprador=request.user,
            importe_pagado=reserva.precio_total_comprador,
        )

    # --- 3) Compra cerrada en SQL: limpiamos Redis ---
    # Borramos lock + OTP y vaciamos la caché, porque esta reserva ya no debe salir en los listados
    redis_service.limpiar_proceso_compra(reserva_id, request.user.id)
    redis_service.invalidar_cache_busquedas()

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

        # Hay una reserva nueva: las búsquedas cacheadas en Redis ya no están completas, las borramos
        redis_service.invalidar_cache_busquedas()

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
