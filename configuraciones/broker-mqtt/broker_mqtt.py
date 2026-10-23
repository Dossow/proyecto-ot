import subprocess
import time
import logging
import paho.mqtt.client as mqtt

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)

MOSQUITTO_CONF = """
listener 1883 0.0.0.0
allow_anonymous true
log_type error
log_type warning
"""

def on_connect(client, userdata, flags, rc):
    logging.info("[BROKER MOSQUITTO] Pizarra central activa en 0.0.0.0:1883 (Suscrito a planta/#)")
    client.subscribe("planta/#")

def on_message(client, userdata, msg):
    payload = msg.payload.decode('utf-8', errors='ignore')
    logging.info(f"[ FLUJO MQTT ] Topico: {msg.topic} | Payload: {payload}")

def main():
    logging.info("=== INICIANDO SERVIDOR ECLIPSE MOSQUITTO (BROKER-MQTT) ===")
    with open("/etc/mosquitto/conf.d/planta_ot.conf", "w") as f:
        f.write(MOSQUITTO_CONF.strip() + "\n")

    # Iniciar el servicio real Eclipse Mosquitto en segundo plano
    proc = subprocess.Popen(["/usr/sbin/mosquitto", "-c", "/etc/mosquitto/conf.d/planta_ot.conf"])
    time.sleep(2)

    # Cliente monitor local para visualizar el trafico en la consola de GNS3
    monitor = mqtt.Client(client_id="monitor-local-broker")
    monitor.on_connect = on_connect
    monitor.on_message = on_message

    while True:
        try:
            monitor.connect("127.0.0.1", 1883, keepalive=60)
            monitor.loop_forever()
        except Exception as e:
            logging.warning(f"[REINTENTO MONITOR BROKER] {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()
