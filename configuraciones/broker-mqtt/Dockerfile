FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && apt install -y --no-install-recommends \
    mosquitto \
    mosquitto-clients \
    python3 \
    python3-pip \
    iproute2 \
    iputils-ping \
    net-tools \
    && pip3 install --no-cache-dir "paho-mqtt==1.6.1" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY broker_mqtt.py /app/broker_mqtt.py

EXPOSE 1883

CMD ["python3", "/app/broker_mqtt.py"]
