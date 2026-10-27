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
