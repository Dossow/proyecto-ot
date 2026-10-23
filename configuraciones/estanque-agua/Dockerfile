FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && apt install -y --no-install-recommends \
    python3 \
    python3-pip \
    iproute2 \
    iputils-ping \
    curl \
    && pip3 install --no-cache-dir flask \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY estanque_agua.py /app/estanque_agua.py

EXPOSE 5000

CMD ["python3", "/app/estanque_agua.py"]
