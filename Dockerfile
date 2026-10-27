# Usamos una imagen oficial de Python ligera para que no ocupe mucho espacio
FROM python:3.11-slim

# Evita que Python genere archivos .pyc innecesarios y hace que los prints salgan al instante en consola
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Carpeta de trabajo dentro del contenedor donde irá nuestro código
WORKDIR /app

# Primero copiamos e instalamos las librerías de requirements.txt
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto de archivos del proyecto dentro del contenedor
COPY . /app/

# Exponemos el puerto 8000 que es el que usa Django por defecto
EXPOSE 8000

# Al arrancar, aplica las migraciones de la base de datos SQL y levanta el servidor web
CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]
