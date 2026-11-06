"""
gateway-borde  |  Nivel 3 (Zona OT)

Recolector intermedio: hace sondeo (polling) controlado del plc-central por
Modbus TCP y publica la telemetria en broker-mqtt (MQTT, puerto 1883).

Es el UNICO componente que consulta al PLC con fines de telemetria hacia IT.
Aguas abajo, puente-aws solo lee del broker, por lo que la nube nunca genera
carga ni trafico directo sobre el controlador.

Mapa de memoria del PLC (definido en plc_central.py):
    HR0 = nivel (%)            HR1 = cloro (ppm x 100)
    HR2 = umbral minimo (%)    HR3 = umbral maximo (%)     HR4 = codigo de alarma
    Coil0 = bomba              Coil1 = alarma de nivel     Coil2 = alarma de cloro

Topicos MQTT publicados (TOPICO_BASE = planta/agua):
    planta/agua/telemetria        JSON con el estado completo, cada INTERVALO_SONDEO
    planta/agua/alarmas           JSON, un evento por cada alarma que se activa o se resuelve
    planta/agua/gateway/estado    "online" / "offline" (retenido; "offline" via Last Will)
"""
import json
import logging
import os
import signal
import threading
import time

import paho.mqtt.client as mqtt
from pymodbus.client import ModbusTcpClient

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)  # los reintentos ya se informan abajo

# --- Configuracion (sobrescribible con variables de entorno desde GNS3) --------------------
PLC_IP = os.getenv("PLC_IP", "192.168.10.10")
PLC_PORT = int(os.getenv("PLC_PORT", "502"))

MQTT_BROKER = os.getenv("MQTT_BROKER", "192.168.20.20")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USUARIO = os.getenv("MQTT_USUARIO", "")
MQTT_CLAVE = os.getenv("MQTT_CLAVE", "")

# Sondeo controlado: nunca mas rapido que 0.5 s para no saturar al PLC
INTERVALO_SONDEO = max(0.5, float(os.getenv("INTERVALO_SONDEO", "1.0")))
FALLOS_PARA_ALARMA_COMUNICACION = 3

TOPICO_BASE = os.getenv("TOPICO_BASE", "planta/agua")
TOPICO_TELEMETRIA = f"{TOPICO_BASE}/telemetria"
TOPICO_ALARMAS = f"{TOPICO_BASE}/alarmas"
TOPICO_ESTADO = f"{TOPICO_BASE}/gateway/estado"

# Rango normativo del cloro. Debe coincidir con plc_central.py (0.20 - 4.00 ppm)
CLORO_MIN_PPM = 0.20
CLORO_MAX_PPM = 4.00

salir = threading.Event()


# --- Modbus TCP: lectura del PLC ----------------------------------------------------------
def sondear_plc(cliente):
    """Dos peticiones por ciclo (FC03 + FC01). Lanza excepcion si el PLC no responde bien."""
    if not cliente.connect():
        raise ConnectionError(f"sin conexion con plc-central ({PLC_IP}:{PLC_PORT})")

    hr = cliente.read_holding_registers(0, 5)
    if hr.isError():
        raise IOError(f"fallo FC03 Read Holding Registers: {hr}")
    co = cliente.read_coils(0, 3)
    if co.isError():
        raise IOError(f"fallo FC01 Read Coils: {co}")

    return {
        "nivel_pct": hr.registers[0],
        "cloro_ppm": round(hr.registers[1] / 100.0, 2),
        "umbral_min": hr.registers[2],
        "umbral_max": hr.registers[3],
        "codigo_alarma": hr.registers[4],
        "bomba_activa": bool(co.bits[0]),
        "alarma_nivel": bool(co.bits[1]),
        "alarma_cloro": bool(co.bits[2]),
    }


# --- Deteccion de alarmas (transiciones) --------------------------------------------------
def evaluar_alarmas(t):
    """Clasifica las alarmas activas usando una misma instantanea de registros del PLC."""
    activas = {}

    if t["alarma_nivel"]:
        if t["nivel_pct"] <= t["umbral_min"]:
            activas["NIVEL"] = {
                "tipo": "NIVEL_BAJO", "severidad": "critica",
                "valor": float(t["nivel_pct"]), "umbral": float(t["umbral_min"]),
                "mensaje": f"Nivel critico bajo: {t['nivel_pct']}% <= {t['umbral_min']}%",
            }
        elif t["nivel_pct"] >= t["umbral_max"]:
            activas["NIVEL"] = {
                "tipo": "NIVEL_ALTO", "severidad": "critica",
                "valor": float(t["nivel_pct"]), "umbral": float(t["umbral_max"]),
                "mensaje": f"Nivel critico alto: {t['nivel_pct']}% >= {t['umbral_max']}%",
            }

    if t["alarma_cloro"]:
        if t["cloro_ppm"] < CLORO_MIN_PPM:
            activas["CLORO"] = {
                "tipo": "CLORO_BAJO", "severidad": "critica",
                "valor": t["cloro_ppm"], "umbral": CLORO_MIN_PPM,
                "mensaje": f"Cloro bajo la norma: {t['cloro_ppm']:.2f} ppm < {CLORO_MIN_PPM} ppm",
            }
        elif t["cloro_ppm"] > CLORO_MAX_PPM:
            activas["CLORO"] = {
                "tipo": "CLORO_ALTO", "severidad": "critica",
                "valor": t["cloro_ppm"], "umbral": CLORO_MAX_PPM,
                "mensaje": f"Cloro sobre la norma: {t['cloro_ppm']:.2f} ppm > {CLORO_MAX_PPM} ppm",
            }
    return activas


def diferencias_alarmas(anteriores, actuales, ts_ms):
    """Devuelve [(alarma, 'ACTIVADA'|'RESUELTA')] solo para los cambios de estado (por flanco)."""
    eventos = []
    for canal in set(anteriores) | set(actuales):
        antes, ahora = anteriores.get(canal), actuales.get(canal)
        cambio = (antes or {}).get("tipo") != (ahora or {}).get("tipo")
        if antes and cambio:
            duracion = max(0.0, (ts_ms - antes["desde_ms"]) / 1000.0)
            eventos.append(({
                "tipo": antes["tipo"], "severidad": "info", "duracion_s": round(duracion, 1),
                "mensaje": f"Alarma resuelta: {antes['tipo']} (duro {duracion:.0f} s)",
            }, "RESUELTA"))
        if ahora and cambio:
            eventos.append((ahora, "ACTIVADA"))
    return eventos


# --- MQTT ---------------------------------------------------------------------------------
def crear_cliente_mqtt():
    cliente = mqtt.Client(client_id="gateway-borde", clean_session=True)
    if MQTT_USUARIO:
        cliente.username_pw_set(MQTT_USUARIO, MQTT_CLAVE)
    cliente.will_set(TOPICO_ESTADO, "offline", qos=1, retain=True)   # Last Will
    cliente.reconnect_delay_set(min_delay=1, max_delay=30)
    cliente.max_queued_messages_set(500)   # buffer acotado si el broker cae

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            logging.info(f"[GATEWAY -> BROKER] Conectado a broker-mqtt ({MQTT_BROKER}:{MQTT_PORT})")
            c.publish(TOPICO_ESTADO, "online", qos=1, retain=True)
        else:
            logging.error(f"[GATEWAY -> BROKER] Conexion rechazada por el broker (rc={rc})")

    def on_disconnect(c, userdata, rc):
        if rc != 0:
            logging.warning("[GATEWAY -> BROKER] Conexion perdida; reintentando automaticamente...")

    cliente.on_connect = on_connect
    cliente.on_disconnect = on_disconnect
    cliente.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=30)
    cliente.loop_start()
    return cliente


def publicar_alarma(cliente, alarma, evento, ts_ms):
    carga = {"ts_ms": ts_ms, "evento": evento, "origen": "gateway-borde",
             **{k: v for k, v in alarma.items() if k != "desde_ms"}}
    cliente.publish(TOPICO_ALARMAS, json.dumps(carga), qos=1)
    nivel_log = logging.WARNING if evento == "ACTIVADA" else logging.INFO
    logging.log(nivel_log, f"[GATEWAY ALARMA {evento}] {alarma['tipo']}: {alarma['mensaje']}")


# --- Bucle principal ----------------------------------------------------------------------
def main():
    signal.signal(signal.SIGTERM, lambda *_: salir.set())
    signal.signal(signal.SIGINT, lambda *_: salir.set())

    logging.info("=== GATEWAY-BORDE INICIADO (Modbus TCP -> MQTT) ===")
    logging.info(f"Sondeo cada {INTERVALO_SONDEO:.1f}s a {PLC_IP}:{PLC_PORT} | Broker: {MQTT_BROKER}:{MQTT_PORT}")

    plc = ModbusTcpClient(PLC_IP, port=PLC_PORT, timeout=3)
    mqtt_cliente = crear_cliente_mqtt()

    alarmas = {}
    fallos = 0
    secuencia = 0
    proximo = time.monotonic()

    while not salir.is_set():
        ts = time.time()
        ts_ms = int(ts * 1000)

        try:
            t = sondear_plc(plc)
            if fallos >= FALLOS_PARA_ALARMA_COMUNICACION:
                logging.info(f"[GATEWAY] Comunicacion con el PLC restablecida tras {fallos} fallos")
            fallos = 0
            nuevas = evaluar_alarmas(t)

            secuencia += 1
            t.update({"ts_ms": ts_ms, "secuencia": secuencia, "origen": "gateway-borde"})
            mqtt_cliente.publish(TOPICO_TELEMETRIA, json.dumps(t), qos=1)
            logging.info(
                f"[PLC -> GATEWAY -> BROKER] #{secuencia} Nivel: {t['nivel_pct']}% | "
                f"Cloro: {t['cloro_ppm']:.2f} ppm | Bomba: {'ON' if t['bomba_activa'] else 'OFF'} | "
                f"Alarma: {t['codigo_alarma']}"
            )

        except Exception as e:
            fallos += 1
            plc.close()   # fuerza una reconexion limpia en el siguiente ciclo
            logging.warning(f"[REINTENTO MODBUS] {e} (fallo consecutivo {fallos})")
            nuevas = dict(alarmas)   # sin datos nuevos: se conserva el estado previo de las alarmas
            if fallos >= FALLOS_PARA_ALARMA_COMUNICACION:
                nuevas["COMUNICACION"] = {
                    "tipo": "PLC_SIN_COMUNICACION", "severidad": "alta",
                    "mensaje": f"plc-central ({PLC_IP}) no responde desde hace {fallos} ciclos",
                }

        for canal, a in nuevas.items():   # instante de activacion, para calcular la duracion
            previa = alarmas.get(canal)
            a["desde_ms"] = previa["desde_ms"] if previa and previa["tipo"] == a["tipo"] else ts_ms

        for alarma, evento in diferencias_alarmas(alarmas, nuevas, ts_ms):
            publicar_alarma(mqtt_cliente, alarma, evento, ts_ms)
        alarmas = nuevas

        # Cadencia fija sin acumular deriva
        proximo += INTERVALO_SONDEO
        espera = proximo - time.monotonic()
        if espera > 0:
            salir.wait(espera)
        else:
            proximo = time.monotonic()

    logging.info("[GATEWAY] Deteniendo...")
    mqtt_cliente.publish(TOPICO_ESTADO, "offline", qos=1, retain=True).wait_for_publish(timeout=2)
    mqtt_cliente.loop_stop()
    mqtt_cliente.disconnect()
    plc.close()


if __name__ == "__main__":
    main()
