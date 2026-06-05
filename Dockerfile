FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build with production settings so WhiteNoise generates the static manifest
# that the runtime (DEBUG=False) expects.
ENV DEBUG=False
RUN python manage.py collectstatic --noinput

EXPOSE 8000

# Railway injects PORT; default to 8000 for local runs. Migrations run on
# boot so a fresh volume (or a new deploy) is always up to date.
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn worldcup26.wsgi:application --bind 0.0.0.0:${PORT:-8000}"]
