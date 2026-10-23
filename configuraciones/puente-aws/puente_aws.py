"""
puente-aws  |  Nivel 3 / 3.5 (Borde Cloud)

Cliente puente: se suscribe a broker-mqtt (telemetria ya desacoplada) y la exporta
de forma segura (HTTPS/TLS) hacia la instancia EC2 de AWS Academy, escribiendo en
InfluxDB 2.x mediante su API /api/v2/write (protocolo de linea).

Principios de diseno
  * Solo trafico saliente: puente-aws inicia las conexiones, la nube nunca entra a la planta.
  * No habla Modbus ni consulta al PLC: unicamente consume del broker.
  * Almacenamiento y reenvio: si la nube, el FortiGate o el laboratorio de AWS caen, los
    datos quedan en una cola acotada y se envian con su timestamp original al volver.
  * TLS verificado por defecto (AWS_CA_CERT para certificado autofirmado de laboratorio).

Entrada (publicada por gateway-borde, TOPICO_BASE = planta/agua):
    planta/agua/telemetria  -> medicion "telemetria" (nivel, cloro, bomba, alarmas, umbrales)
    planta/agua/alarmas     -> medicion "alarmas"    (un punto por activacion / resolucion)
"""
import itertools
import json
import logging
import os
import signal
import threading
import time
from collections import deque

import paho.mqtt.client as mqtt
import requests
import urllib3

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)

# --- Configuracion (sobrescribible con variables de entorno desde GNS3) --------------------
MQTT_BROKER = os.getenv("MQTT_BROKER", "192.168.10.16")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USUARIO = os.getenv("MQTT_USUARIO", "")
MQTT_CLAVE = os.getenv("MQTT_CLAVE", "")
TOPICO_BASE = os.getenv("TOPICO_BASE", "planta/agua")

AWS_HOST = os.getenv("AWS_HOST", "")                  # IP elastica o DNS de la instancia EC2
AWS_PUERTO = int(os.getenv("AWS_PUERTO", "443"))
AWS_TLS_VERIFICAR = os.getenv("AWS_TLS_VERIFICAR", "1") not in ("0", "false", "False", "no")
AWS_CA_CERT = os.getenv("AWS_CA_CERT", "")            # ruta al certificado de la EC2 (autofirmado)

INFLUX_ORG = os.getenv("INFLUX_ORG", "planta")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "agua")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")          # NUNCA subir el token al repositorio

PLANTA_ID = os.getenv("PLANTA_ID", "planta-agua")
INTERVALO_ENVIO = float(os.getenv("INTERVALO_ENVIO", "5"))   # s entre lotes
TAMANO_LOTE = int(os.getenv("TAMANO_LOTE", "200"))           # puntos maximos por peticion
MAX_COLA = int(os.getenv("MAX_COLA", "5000"))                # puntos retenidos si no hay nube
TIMEOUT_HTTP = float(os.getenv("TIMEOUT_HTTP", "8"))

TOPICO_TELEMETRIA = f"{TOPICO_BASE}/telemetria"
TOPICO_ALARMAS = f"{TOPICO_BASE}/alarmas"
TOPICO_ESTADO_GATEWAY = f"{TOPICO_BASE}/gateway/estado"

salir = threading.Event()
cola = deque(maxlen=MAX_COLA)       # elementos: (id, linea_de_protocolo)
cola_lock = threading.Lock()
contador_id = itertools.count(1)
hay_urgente = threading.Event()     # una alarma espera: no aguardar al siguiente lote


# --- Protocolo de linea de InfluxDB -------------------------------------------------------
def esc_tag(v):
    return str(v).replace("\\", "\\\\").replace(",", "\\,").replace("=", "\\=").replace(" ", "\\ ")


def esc_texto(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def linea_telemetria(d):
    campos = (
        f"nivel_pct={float(d['nivel_pct']):.1f},"
        f"cloro_ppm={float(d['cloro_ppm']):.2f},"
        f"bomba_activa={int(bool(d['bomba_activa']))}i,"
        f"alarma_nivel={int(bool(d['alarma_nivel']))}i,"
        f"alarma_cloro={int(bool(d['alarma_cloro']))}i,"
        f"codigo_alarma={int(d['codigo_alarma'])}i,"
        f"umbral_min={int(d['umbral_min'])}i,"
        f"umbral_max={int(d['umbral_max'])}i"
    )
    return f"telemetria,planta={esc_tag(PLANTA_ID)} {campos} {int(d['ts_ms'])}"


def linea_alarma(d):
    campos = [
        f'evento="{esc_texto(d["evento"])}"',
        f"activa={1 if d['evento'] == 'ACTIVADA' else 0}i",
        f'mensaje="{esc_texto(d.get("mensaje", ""))}"',
    ]
    if d.get("valor") is not None:
        campos.append(f"valor={float(d['valor']):.2f}")
    if d.get("umbral") is not None:
        campos.append(f"umbral={float(d['umbral']):.2f}")
    if d.get("duracion_s") is not None:
        campos.append(f"duracion_s={float(d['duracion_s']):.1f}")
    etiquetas = f"planta={esc_tag(PLANTA_ID)},tipo={esc_tag(d['tipo'])},severidad={esc_tag(d.get('severidad', 'critica'))}"
    return f"alarmas,{etiquetas} {','.join(campos)} {int(d['ts_ms'])}"


def encolar(linea, urgente=False):
    with cola_lock:
        if len(cola) == cola.maxlen:
            logging.warning("[PUENTE-AWS] Cola llena: se descarta el punto mas antiguo")
        cola.append((next(contador_id), linea))
    if urgente:
        hay_urgente.set()


# --- MQTT (entrada local) -----------------------------------------------------------------
def on_connect(cliente, userdata, flags, rc):
    if rc == 0:
        logging.info(f"[BROKER -> PUENTE] Suscrito a {TOPICO_BASE}/# en {MQTT_BROKER}:{MQTT_PORT}")
        cliente.subscribe(f"{TOPICO_BASE}/#", qos=1)
    else:
        logging.error(f"[BROKER -> PUENTE] Conexion rechazada por el broker (rc={rc})")


def on_disconnect(cliente, userdata, rc):
    if rc != 0:
        logging.warning("[BROKER -> PUENTE] Conexion perdida; reintentando automaticamente...")


def on_message(cliente, userdata, msg):
    try:
        texto = msg.payload.decode("utf-8", errors="replace")
        if msg.topic == TOPICO_ESTADO_GATEWAY:
            logging.info(f"[BROKER -> PUENTE] Estado de gateway-borde: {texto}")
        elif msg.topic == TOPICO_TELEMETRIA:
            encolar(linea_telemetria(json.loads(texto)))
        elif msg.topic == TOPICO_ALARMAS:
            d = json.loads(texto)
            encolar(linea_alarma(d), urgente=True)
            logging.warning(f"[BROKER -> PUENTE] Alarma {d.get('evento')}: {d.get('tipo')} -> prioridad de envio")
    except (ValueError, KeyError, TypeError) as e:
        logging.warning(f"[PUENTE-AWS] Mensaje descartado en {msg.topic} (formato invalido): {e!r}")


# --- Exportacion HTTPS/TLS hacia EC2 ------------------------------------------------------
def configurar_sesion():
    """Devuelve (sesion, verificacion). 'verificacion' se pasa EXPLICITO en cada POST porque
    requests da prioridad a la variable de entorno REQUESTS_CA_BUNDLE sobre Session.verify."""
    sesion = requests.Session()
    sesion.headers.update({
        "Authorization": f"Token {INFLUX_TOKEN}",
        "Content-Type": "text/plain; charset=utf-8",
    })
    if AWS_CA_CERT:
        if not os.path.isfile(AWS_CA_CERT):
            raise SystemExit(f"[PUENTE-AWS] AWS_CA_CERT apunta a un archivo inexistente: {AWS_CA_CERT}")
        logging.info(f"[PUENTE-AWS] TLS verificado con certificado propio: {AWS_CA_CERT}")
        return sesion, AWS_CA_CERT
    if not AWS_TLS_VERIFICAR:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logging.warning("[PUENTE-AWS] TLS SIN VERIFICAR (AWS_TLS_VERIFICAR=0): usar solo en laboratorio")
        return sesion, False
    return sesion, True


def enviar_lote(sesion, verificacion, url, lote):
    """Devuelve True si el lote debe retirarse de la cola (entregado o irrecuperable)."""
    cuerpo = "\n".join(linea for _, linea in lote).encode("utf-8")
    params = {"org": INFLUX_ORG, "bucket": INFLUX_BUCKET, "precision": "ms"}
    try:
        r = sesion.post(url, params=params, data=cuerpo, timeout=TIMEOUT_HTTP, verify=verificacion)
    except requests.exceptions.SSLError as e:
        logging.error(f"[PUENTE -> EC2] Fallo de verificacion TLS (revisar AWS_CA_CERT / SAN del certificado): {e}")
        return False
    except requests.exceptions.RequestException as e:
        logging.warning(f"[PUENTE -> EC2] Sin conectividad con {url} (politica FortiGate, Security Group o lab detenido): {type(e).__name__}")
        return False

    if r.status_code in (200, 204):
        return True
    if r.status_code in (400, 422):
        logging.error(f"[PUENTE -> EC2] Lote rechazado por formato (HTTP {r.status_code}); se descarta: {r.text[:200]}")
        return True
    if r.status_code in (401, 403):
        logging.error(f"[PUENTE -> EC2] Token de InfluxDB invalido o sin permisos (HTTP {r.status_code})")
    else:
        logging.warning(f"[PUENTE -> EC2] Respuesta inesperada HTTP {r.status_code}: {r.text[:200]}")
    return False


def hilo_exportador():
    sesion, verificacion = configurar_sesion()
    url = f"https://{AWS_HOST}:{AWS_PUERTO}/api/v2/write"
    fallos = 0
    proximo_intento = 0.0
    ultimo_envio = 0.0

    while not salir.is_set():
        salir.wait(0.5)
        ahora = time.monotonic()
        with cola_lock:
            pendientes = len(cola)
        if pendientes == 0 or ahora < proximo_intento:
            continue
        if not (hay_urgente.is_set() or pendientes >= TAMANO_LOTE or ahora - ultimo_envio >= INTERVALO_ENVIO):
            continue
        if not AWS_HOST:
            logging.warning(f"[PUENTE-AWS] AWS_HOST no definido: {pendientes} puntos en cola (sin destino en la nube)")
            proximo_intento = ahora + 10
            continue

        enviados = 0
        while not salir.is_set():
            with cola_lock:
                lote = list(itertools.islice(cola, TAMANO_LOTE))
            if not lote:
                break
            if not enviar_lote(sesion, verificacion, url, lote):
                fallos += 1
                proximo_intento = time.monotonic() + min(30, 2 ** fallos)
                with cola_lock:
                    pendientes = len(cola)
                logging.warning(f"[PUENTE-AWS] Reintento en {min(30, 2 ** fallos)}s | puntos en cola: {pendientes}")
                break
            ultimo_id = lote[-1][0]
            with cola_lock:
                while cola and cola[0][0] <= ultimo_id:
                    cola.popleft()
            enviados += len(lote)
            fallos = 0

        if enviados:
            hay_urgente.clear()
            ultimo_envio = time.monotonic()
            with cola_lock:
                pendientes = len(cola)
            logging.info(f"[PUENTE -> EC2] {enviados} puntos enviados por HTTPS/TLS a {AWS_HOST}:{AWS_PUERTO} | en cola: {pendientes}")


# --- Programa principal -------------------------------------------------------------------
def main():
    signal.signal(signal.SIGTERM, lambda *_: salir.set())
    signal.signal(signal.SIGINT, lambda *_: salir.set())

    logging.info("=== PUENTE-AWS INICIADO (MQTT local -> HTTPS/TLS -> EC2 InfluxDB) ===")
    if not AWS_HOST:
        logging.warning("[PUENTE-AWS] AWS_HOST vacio: se acumulan datos en cola hasta que se defina el destino")
    if not INFLUX_TOKEN:
        logging.warning("[PUENTE-AWS] INFLUX_TOKEN vacio: la nube rechazara las escrituras (HTTP 401)")

    exportador = threading.Thread(target=hilo_exportador, daemon=True)
    exportador.start()

    cliente = mqtt.Client(client_id="puente-aws", clean_session=False)   # sesion persistente
    if MQTT_USUARIO:
        cliente.username_pw_set(MQTT_USUARIO, MQTT_CLAVE)
    cliente.reconnect_delay_set(min_delay=1, max_delay=30)
    cliente.on_connect = on_connect
    cliente.on_disconnect = on_disconnect
    cliente.on_message = on_message
    cliente.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=30)
    cliente.loop_start()

    salir.wait()
    logging.info("[PUENTE-AWS] Deteniendo...")
    cliente.loop_stop()
    cliente.disconnect()
    exportador.join(timeout=3)


if __name__ == "__main__":
    main()
