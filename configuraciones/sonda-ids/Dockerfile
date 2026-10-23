FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && apt install -y --no-install-recommends \
    python3 \
    python3-pip \
    tcpdump \
    libpcap0.8 \
    iproute2 \
    iputils-ping \
    && pip3 install --no-cache-dir scapy \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY sonda_ids.py /app/sonda_ids.py

CMD ["python3", "/app/sonda_ids.py"]
