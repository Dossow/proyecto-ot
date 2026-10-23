FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && apt install -y --no-install-recommends \
    python3 \
    python3-pip \
    iproute2 \
    iputils-ping \
    curl \
    && pip3 install --no-cache-dir requests "pymodbus==3.6.8" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY sensor_nivel_estanque.py /app/sensor_nivel_estanque.py

CMD ["python3", "/app/sensor_nivel_estanque.py"]
