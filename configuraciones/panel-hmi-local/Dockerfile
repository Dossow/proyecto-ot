FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && apt install -y --no-install-recommends \
    python3 \
    python3-pip \
    iproute2 \
    iputils-ping \
    curl \
    && pip3 install --no-cache-dir flask "pymodbus==3.6.8" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY panel_hmi_local.py /app/panel_hmi_local.py

EXPOSE 8080

CMD ["python3", "/app/panel_hmi_local.py"]
