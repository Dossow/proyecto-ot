FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    iproute2 \
    iputils-ping \
    net-tools \
    && pip3 install --no-cache-dir "pymodbus==3.6.8" "paho-mqtt==1.6.1" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY gateway_borde.py /app/gateway_borde.py

# Variables ajustables desde la plantilla de GNS3 (Environment):
#   PLC_IP, PLC_PORT, MQTT_BROKER, MQTT_PORT, MQTT_USUARIO, MQTT_CLAVE, INTERVALO_SONDEO
CMD ["python3", "/app/gateway_borde.py"]
