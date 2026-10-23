FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    ca-certificates \
    iproute2 \
    iputils-ping \
    curl \
    && pip3 install --no-cache-dir requests "paho-mqtt==1.6.1" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY puente_aws.py /app/puente_aws.py

# Si la EC2 usa un certificado autofirmado, copiarlo aqui y definir AWS_CA_CERT=/app/certs/ec2.crt
# (crear antes la carpeta certs/ junto a este Dockerfile y descomentar la linea siguiente):
# COPY certs/ec2.crt /app/certs/ec2.crt

# Variables que se definen en la plantilla de GNS3 (Environment), NO en el repositorio:
#   AWS_HOST, INFLUX_TOKEN              (obligatorias)
#   AWS_PUERTO=443, AWS_CA_CERT, AWS_TLS_VERIFICAR=1, INFLUX_ORG=planta, INFLUX_BUCKET=agua
#   MQTT_BROKER=192.168.10.16, MQTT_USUARIO, MQTT_CLAVE
CMD ["python3", "/app/puente_aws.py"]
