FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && apt install -y --no-install-recommends \
    python3 \
    python3-pip \
    iproute2 \
    iputils-ping \
    net-tools \
    && pip3 install --no-cache-dir "pymodbus==3.6.8" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY plc_central.py /app/plc_central.py

EXPOSE 502

CMD ["python3", "/app/plc_central.py"]
