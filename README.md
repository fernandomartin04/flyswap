# ✈️ FlySwap - Plataforma de Cesión y Reventa de Reservas de Viaje

Proyecto grupal para la asignatura **Ampliación de Bases de Datos** (3º de Grado en Ingeniería del Software, Universidad Loyola Andalucía).

**Integrantes del grupo:**
* Fernando Martín González
* Alfonso Nicolás Martínez Márquez
* José María Tomillo Morera

---

## 🎯 Objetivo del Proyecto

Desarrollar una plataforma web que permita conectar usuarios que tienen una reserva de vuelo que no van a utilizar con compradores interesados en adquirirla a buen precio, integrando de forma justificada cuatro tecnologías de bases de datos coordinadas por Django y orquestadas con Docker Compose.

---

## 🚀 Tecnologías y Arquitectura

* **Django 5 (Web y Lógica):** Coordina los flujos de usuario y el acceso a todas las bases de datos.
* **SQL (SQLite / Base Principal):** Fuente de verdad transaccional (usuarios, vuelos, reservas publicadas y compras simuladas).
* **Redis (Caché y Memoria):** Búsquedas frecuentes con TTL e invalidación, códigos OTP temporales y bloqueo temporal de reservas durante la compra.
* **MongoDB (Documental):** Registro flexible de eventos/actividad de los usuarios y cálculo de métricas para el dashboard de administración.
* **Neo4j (Grafo):** Relaciones de afinidad (Usuario–Vuelo–Destino) para generar recomendaciones personalizadas mediante Cypher.
* **Docker y Docker Compose:** Despliegue reproducible con un solo comando en red interna y con volúmenes persistentes.

---

## 📁 Estructura del Repositorio

| Archivo / Carpeta | Descripción |
| :--- | :--- |
| [`docker-compose.yml`](docker-compose.yml) | Orquestación de los 4 servicios (`web`, `redis`, `mongo`, `neo4j`), volúmenes y red interna. |
| [`Dockerfile`](Dockerfile) | Imagen ligera de Python 3.11 para ejecutar Django. |
| [`requirements.txt`](requirements.txt) | Dependencias de Python (`Django`, `redis`, `pymongo`, `neo4j`). |
| [`.env.example`](.env.example) | Plantilla de variables de entorno y credenciales seguras. |
| [`manage.py`](manage.py) | Gestor de comandos de Django. |
| [`flyswap/`](flyswap/) | Configuración principal del proyecto Django (`settings.py`, `urls.py`, `wsgi.py`). |
| [`reservas/`](reservas/) | Aplicación con los modelos, vistas y lógica de negocio de FlySwap. |

---

## 🛠️ Puesta en Marcha

### 1. Clonar el repositorio y configurar variables de entorno
```bash
cp .env.example .env
```

### 2. Construir y levantar los contenedores
```bash
docker compose up --build -d
```

### 3. Comprobar que todos los servicios están activos
```bash
docker compose ps
```

* **Web (Django):** http://localhost:8000
* **Neo4j Browser:** http://localhost:7474

---

## ⚡ Parte 1 — Integración con Redis (`reservas/redis_service.py`)

Todo el acceso a Redis está en `reservas/redis_service.py`; `views.py` solo llama a sus funciones.

| Uso | Clave | Comando / TTL |
| :--- | :--- | :--- |
| Caché de búsquedas | `cache:busqueda:<origen>:<destino>` (minúsculas) | `SET ... EX 120` · se invalida con `SCAN` + `DEL` al publicar o comprar |
| Bloqueo de compra | `lock:reserva:<id>` → `user_id` | `SET ... NX EX 180` (atómico) · se libera con un script Lua solo si el lock es tuyo |
| Código OTP | `otp:compra:<reserva_id>:<user_id>` | 6 dígitos con `secrets`, `EX 180` |
| Intentos fallidos | `otp:intentos:<reserva_id>:<user_id>` | `INCR` · al 5º fallo se libera la reserva |

**Flujo de compra (F5) en dos pasos:**
1. **Iniciar compra** (`POST /reserva/<id>/iniciar-compra/`): bloquea la reserva 3 minutos y muestra el OTP en pantalla (simulado, sin SMS/email). Si otro usuario la tiene bloqueada, se le muestran los segundos restantes (`TTL`).
2. **Confirmar** (`POST /reserva/<id>/comprar/`): comprueba que el lock es tuyo y que el OTP es correcto. Después ejecuta la compra en SQL (`transaction.atomic()` + `select_for_update()`) y borra el lock, el OTP y la caché.
3. **Cancelar** (`POST /reserva/<id>/cancelar-compra/`): libera el bloqueo.

**Tolerancia a fallos:** si Redis cae, el buscador sigue funcionando contra SQL (lo indica en pantalla) y publicar funciona con normalidad. La compra se bloquea con un aviso claro, porque sin lock ni OTP no se puede garantizar.

**Demostración rápida:**
1. Busca "Sevilla" dos veces: la primera indica *SQL* y la segunda *caché Redis*.
2. Con `josemaria`, pulsa *Iniciar compra* en una reserva de `fernando`. En otro navegador, entra como `alfonso` en esa misma reserva: aparece bloqueada con su TTL.
3. Ver las claves en Redis: `docker exec -it flyswap_redis redis-cli --scan` y `docker exec -it flyswap_redis redis-cli TTL lock:reserva:<id>`.
4. Introduce el OTP: la compra se completa y la reserva desaparece del buscador.
5. `docker stop flyswap_redis`: la web sigue funcionando, pero no se puede comprar. Después, `docker start flyswap_redis`.
