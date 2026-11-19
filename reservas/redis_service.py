"""
SERVICIO DE REDIS PARA FLYSWAP (Parte 1 - Jose)
================================================
Aquí está TODO el acceso a Redis. Las vistas solo llaman a estas funciones,
así si cambiamos algo de Redis solo hay que tocar este archivo.

Usamos Redis para tres cosas:
  1. Caché de búsquedas frecuentes con TTL      -> cache:busqueda:<origen>:<destino>
  2. Bloqueo temporal de una reserva al comprar -> lock:reserva:<id>          (SET NX EX)
  3. Código OTP de confirmación de la compra    -> otp:compra:<reserva_id>:<user_id>
     (+ contador de intentos fallidos)           -> otp:intentos:<reserva_id>:<user_id>

¿Por qué Redis y no SQL para esto? Porque son datos temporales que deben
caducar solos (TTL) y que se consultan muchísimo: Redis los guarda en memoria
y los borra automáticamente al expirar, sin tener que limpiar tablas a mano.
"""
import json
import secrets

import redis
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder


# -------------------------------------------------------------------------
# Tiempos de vida (en segundos) de cada tipo de dato temporal
# -------------------------------------------------------------------------
TTL_CACHE_BUSQUEDA = 120   # 2 minutos: suficiente para aliviar SQL sin mostrar datos muy viejos
TTL_LOCK_COMPRA = 180      # 3 minutos para completar la compra
TTL_OTP = 180              # El OTP dura lo mismo que el bloqueo
MAX_INTENTOS_OTP = 5       # Tras 5 códigos erróneos se libera la reserva (evita probar códigos a fuerza bruta)


# -------------------------------------------------------------------------
# Cliente de Redis (uno solo para toda la aplicación)
# - decode_responses=True: Redis nos devuelve str en vez de bytes.
# - Timeouts de 1 segundo: si Redis está caído, la web NO se queda colgada
#   esperando; falla rápido y nosotros lo gestionamos.
# Crear el cliente no conecta todavía: la conexión se abre en el primer comando.
# -------------------------------------------------------------------------
cliente = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)


class RedisNoDisponible(Exception):
    """Error propio que lanzamos cuando Redis no responde en el proceso de compra.
    Así las vistas no necesitan conocer las excepciones internas de la librería redis."""
    pass


# =========================================================================
# 1. CACHÉ DE BÚSQUEDAS
# Si Redis falla aquí NO pasa nada grave: simplemente consultamos SQL.
# Por eso estas funciones nunca lanzan excepciones hacia la vista.
# =========================================================================
def _clave_busqueda(origen, destino):
    # Normalizamos a minúsculas y sin espacios en los extremos para que
    # "Sevilla", "sevilla " y "SEVILLA" compartan la misma entrada de caché
    return f"cache:busqueda:{origen.strip().lower()}:{destino.strip().lower()}"


def obtener_busqueda_cache(origen, destino):
    """Devuelve la lista de resultados guardada en caché, o None si no existe (MISS) o Redis falla."""
    try:
        datos_json = cliente.get(_clave_busqueda(origen, destino))
    except redis.exceptions.RedisError:
        return None
    if datos_json is None:
        return None
    return json.loads(datos_json)


def guardar_busqueda_cache(origen, destino, resultados):
    """Guarda los resultados en JSON con caducidad automática (TTL).
    DjangoJSONEncoder sabe convertir Decimal y datetime a texto."""
    try:
        cliente.set(
            _clave_busqueda(origen, destino),
            json.dumps(resultados, cls=DjangoJSONEncoder),
            ex=TTL_CACHE_BUSQUEDA,
        )
        return True
    except redis.exceptions.RedisError:
        return False


def invalidar_cache_busquedas():
    """Borra todas las búsquedas cacheadas. Se llama al publicar o comprar una reserva,
    porque en ese momento los listados guardados dejan de ser correctos.

    Usamos SCAN (scan_iter) y no KEYS: KEYS recorre toda la base de golpe y bloquea
    Redis mientras tanto; SCAN va por tandas y no bloquea al resto de clientes.
    Si Redis falla, como mucho se verán datos antiguos hasta que caduque el TTL (2 min)."""
    try:
        claves = list(cliente.scan_iter(match="cache:busqueda:*", count=100))
        if claves:
            cliente.delete(*claves)
        return len(claves)
    except redis.exceptions.RedisError:
        return 0


# =========================================================================
# 2. BLOQUEO TEMPORAL DE RESERVA (TTL LOCK)
# Aquí Redis SÍ es imprescindible: si no responde lanzamos RedisNoDisponible
# y la vista impide la compra con un mensaje claro.
# =========================================================================
def _clave_lock(reserva_id):
    return f"lock:reserva:{reserva_id}"


def adquirir_lock(reserva_id, user_id):
    """Intenta bloquear la reserva para este usuario durante 3 minutos.

    Devuelve (True, TTL_LOCK_COMPRA) si el bloqueo es nuestro,
    o (False, segundos_restantes) si lo tiene otro usuario.

    SET ... NX EX es una única operación ATÓMICA en Redis: "créala solo si no existe
    y con caducidad". Si dos usuarios pulsan a la vez, Redis garantiza que solo uno gana."""
    clave = _clave_lock(reserva_id)
    try:
        conseguido = cliente.set(clave, str(user_id), nx=True, ex=TTL_LOCK_COMPRA)
        if conseguido:
            return True, TTL_LOCK_COMPRA

        # Ya existía un bloqueo: miramos de quién es
        propietario = cliente.get(clave)
        if propietario == str(user_id):
            # Es nuestro (el usuario ha vuelto a pulsar "Iniciar compra"): renovamos los 3 minutos
            cliente.expire(clave, TTL_LOCK_COMPRA)
            return True, TTL_LOCK_COMPRA

        # Es de otro usuario: devolvemos cuántos segundos le quedan
        return False, max(cliente.ttl(clave), 0)
    except redis.exceptions.RedisError as error:
        raise RedisNoDisponible() from error


def estado_lock(reserva_id, user_id):
    """Para la página de detalle. Devuelve (es_mio, segundos_restantes).
    Si no hay bloqueo devuelve (False, 0)."""
    clave = _clave_lock(reserva_id)
    try:
        propietario = cliente.get(clave)
        if propietario is None:
            return False, 0
        return propietario == str(user_id), max(cliente.ttl(clave), 0)
    except redis.exceptions.RedisError as error:
        raise RedisNoDisponible() from error


# Pequeño script Lua: "borra la clave SOLO si su valor es mi user_id".
# Redis ejecuta los scripts Lua de forma atómica. Si lo hiciéramos en Python con
# GET y luego DELETE, entre ambos pasos el bloqueo podría caducar y otro usuario
# cogerlo, y nosotros le borraríamos SU bloqueo por error.
_SCRIPT_LIBERAR_LOCK = cliente.register_script("""
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
""")


def liberar_lock(reserva_id, user_id):
    """Quita el bloqueo solo si pertenece a este usuario. No lanza errores:
    si Redis falla, el bloqueo caducará solo por su TTL."""
    try:
        _SCRIPT_LIBERAR_LOCK(keys=[_clave_lock(reserva_id)], args=[str(user_id)])
    except redis.exceptions.RedisError:
        pass


# =========================================================================
# 3. CÓDIGO OTP DE CONFIRMACIÓN
# =========================================================================
def _clave_otp(reserva_id, user_id):
    return f"otp:compra:{reserva_id}:{user_id}"


def _clave_intentos(reserva_id, user_id):
    return f"otp:intentos:{reserva_id}:{user_id}"


def generar_otp(reserva_id, user_id):
    """Genera un código numérico de 6 dígitos, lo guarda con TTL y reinicia los intentos.
    Usamos 'secrets' y no 'random' porque secrets está pensado para códigos de seguridad
    (no se puede predecir el siguiente número)."""
    codigo = f"{secrets.randbelow(1_000_000):06d}"
    try:
        cliente.set(_clave_otp(reserva_id, user_id), codigo, ex=TTL_OTP)
        cliente.delete(_clave_intentos(reserva_id, user_id))
    except redis.exceptions.RedisError as error:
        raise RedisNoDisponible() from error
    return codigo


def validar_otp(reserva_id, user_id, codigo_introducido):
    """Comprueba el código introducido por el usuario.

    Devuelve una tupla (resultado, intentos_restantes) donde resultado es:
      'OK'         -> código correcto
      'CADUCADO'   -> no hay OTP guardado (pasaron los 3 minutos o no se inició la compra)
      'INCORRECTO' -> código erróneo, aún quedan intentos
      'AGOTADO'    -> se han superado los intentos máximos"""
    try:
        codigo_guardado = cliente.get(_clave_otp(reserva_id, user_id))
        if codigo_guardado is None:
            return 'CADUCADO', 0

        # compare_digest compara en tiempo constante (buena práctica al comparar códigos secretos)
        if secrets.compare_digest(codigo_guardado, codigo_introducido.strip()):
            return 'OK', MAX_INTENTOS_OTP

        # Código erróneo: sumamos un intento fallido (INCR es atómico) con la misma caducidad que el OTP
        clave_intentos = _clave_intentos(reserva_id, user_id)
        fallos = cliente.incr(clave_intentos)
        cliente.expire(clave_intentos, TTL_OTP)

        if fallos >= MAX_INTENTOS_OTP:
            return 'AGOTADO', 0
        return 'INCORRECTO', MAX_INTENTOS_OTP - fallos
    except redis.exceptions.RedisError as error:
        raise RedisNoDisponible() from error


def limpiar_proceso_compra(reserva_id, user_id):
    """Borra el OTP, el contador de intentos y el bloqueo del usuario.
    Se usa al terminar la compra, al cancelarla o al agotar los intentos."""
    try:
        cliente.delete(_clave_otp(reserva_id, user_id), _clave_intentos(reserva_id, user_id))
    except redis.exceptions.RedisError:
        pass
    liberar_lock(reserva_id, user_id)
