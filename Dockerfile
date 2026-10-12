FROM python:3.12-slim

# hora de Argentina: sin esto date.today() usa UTC y despues de las 21:00
# los descuentos se cargarian con la fecha de mañana
ENV TZ=America/Argentina/Buenos_Aires
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# misma estructura que tu proyecto: /app/src y /app/templates
COPY src ./src
COPY templates ./templates

# carpetas donde la app escribe (si no existen, el log puede fallar al arrancar)
RUN mkdir -p logs reportes_temporales

EXPOSE 5000

# timeout alto: una carga grande de Excel puede superar los 30s por defecto
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "src.app:app"]
