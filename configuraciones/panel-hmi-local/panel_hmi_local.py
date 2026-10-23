import time
import threading
import logging
from flask import Flask, jsonify
from pymodbus.client import ModbusTcpClient

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)

PLC_IP = "192.168.10.10"
PLC_PORT = 502

app = Flask(__name__)

datos_hmi = {
    "nivel_agua": 0,
    "cloro_ppm": 0.0,
    "umbral_min": 20,
    "umbral_max": 90,
    "bomba_activa": False,
    "alarma_nivel": False,
    "alarma_cloro": False,
    "estado_seguridad": "NORMAL"
}

def sondeo_local_plc():
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT)
    while True:
        try:
            if client.connect():
                hr = client.read_holding_registers(0, 5)
                co = client.read_coils(0, 3)

                if not hr.isError() and not co.isError():
                    nivel = hr.registers[0]
                    cloro_ppm = hr.registers[1] / 100.0
                    u_min = hr.registers[2]
                    u_max = hr.registers[3]
                    cod_alarma = hr.registers[4]

                    bomba = bool(co.bits[0])
                    al_nivel = bool(co.bits[1])
                    al_cloro = bool(co.bits[2])

                    estados_txt = {
                        0: "OPERACION NORMAL",
                        1: "ALERTA SAFETY: NIVEL CRITICO BAJO (<=20%)",
                        2: "ALERTA SAFETY: NIVEL CRITICO ALTO (>=90%)",
                        3: "ALERTA QUIMICA: CLORO FUERA DE NORMA"
                    }
                    estado_seg = estados_txt.get(cod_alarma, "DESCONOCIDO")

                    datos_hmi.update({
                        "nivel_agua": nivel,
                        "cloro_ppm": round(cloro_ppm, 2),
                        "umbral_min": u_min,
                        "umbral_max": u_max,
                        "bomba_activa": bomba,
                        "alarma_nivel": al_nivel,
                        "alarma_cloro": al_cloro,
                        "estado_seguridad": estado_seg
                    })

                    barra = "#" * (nivel // 5) + "-" * (20 - (nivel // 5))
                    b_txt = "ACTIVA [ON]" if bomba else "INACTIVA [OFF]"
                    logging.info(
                        f"[HMI LOCAL] [{barra}] {nivel}% | Cloro: {cloro_ppm:.2f} ppm | "
                        f"Bomba: {b_txt} | {estado_seg}"
                    )
            else:
                logging.warning(f"[HMI LOCAL] Sin conexion Modbus TCP con PLC ({PLC_IP}:{PLC_PORT})")
        except Exception as e:
            logging.warning(f"[HMI LOCAL] Reintentando lectura: {e}")

        time.sleep(2)

@app.route('/', methods=['GET'])
def index_web():
    color_alerta = "#ef4444" if (datos_hmi["alarma_nivel"] or datos_hmi["alarma_cloro"]) else "#22c55e"
    html = f"""
    <html>
    <head><meta http-equiv="refresh" content="2"><title>Panel HMI Local - Planta OT</title></head>
    <body style="font-family: monospace; background: #111827; color: #f9fafb; padding: 20px;">
        <h2>PANEL HMI LOCAL - SUPERVISION PLANTA DE AGUA (NIVEL 3 OT)</h2>
        <p><b>Nivel del Estanque:</b> {datos_hmi['nivel_agua']}% (Umbrales Safety: {datos_hmi['umbral_min']}% - {datos_hmi['umbral_max']}%)</p>
        <p><b>Calidad Quimica (Cloro):</b> {datos_hmi['cloro_ppm']} ppm (Norma: 0.2 - 4.0 ppm)</p>
        <p><b>Estado Bomba Impulsion:</b> {'ACTIVA (ENCENDIDA)' if datos_hmi['bomba_activa'] else 'INACTIVA (APAGADA)'}</p>
        <div style="padding: 10px; background: {color_alerta}; color: #000; font-weight: bold;">
            ESTADO DE SEGURIDAD: {datos_hmi['estado_seguridad']}
        </div>
    </body>
    </html>
    """
    return html

@app.route('/api/hmi', methods=['GET'])
def api_hmi():
    return jsonify(datos_hmi)

if __name__ == "__main__":
    logging.info("=== PANEL-HMI-LOCAL INICIADO (Modbus TCP Cliente + Web Puerto 8080) ===")
    threading.Thread(target=sondeo_local_plc, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)
