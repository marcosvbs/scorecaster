FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build with production settings so WhiteNoise generates the static manifest
# that the runtime (DEBUG=False) expects. The throwaway SECRET_KEY only
# satisfies the settings boot guard; the real key comes from the environment
# at runtime.
ENV DEBUG=False
RUN SECRET_KEY=build-only-dummy python manage.py collectstatic --noinput

RUN chmod +x start.sh

EXPOSE 8000

# start.sh: migrate, background check_results loop (10 min), then gunicorn.
# Railway injects PORT; defaults to 8000 for local runs.
CMD ["./start.sh"]
