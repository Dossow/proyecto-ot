import time
import math
import threading
import logging
from flask import Flask, jsonify, request

# Silenciar logs HTTP rutinarios de Werkzeug para mostrar la fisica limpia
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

estado_planta = {
    "nivel_agua": 50.0,        # Porcentaje (0.0 a 100.0 %)
    "cloro_ppm": 1.50,         # Concentracion de cloro (Rango seguro: 0.2 a 4.0 ppm)
    "bomba_activa": False,     # True = Llenando | False = Vaciando
    "caudal_entrada": 6.0,     # % por segundo cuando la bomba impulsa agua
    "caudal_salida": 3.0,      # % por segundo de consumo continuo de la planta
    "cloro_manual": None       # Permite forzar anomalias quimicas para pruebas
}

def motor_fisico_delta_time():
    ultimo_tiempo = time.time()
    inicio_sim = ultimo_tiempo

    while True:
        time.sleep(1.0)
        ahora = time.time()
        dt = ahora - ultimo_tiempo
        ultimo_tiempo = ahora

        # 1. Calculo de nivel por Delta Time (Ciclo completo 20% <-> 90% en ~46 segundos)
        if estado_planta["bomba_activa"]:
            tasa_neta = estado_planta["caudal_entrada"] - estado_planta["caudal_salida"]
        else:
            tasa_neta = -estado_planta["caudal_salida"]

        nuevo_nivel = estado_planta["nivel_agua"] + (tasa_neta * dt)
        estado_planta["nivel_agua"] = round(max(0.0, min(100.0, nuevo_nivel)), 1)

        # 2. Simulacion de Calidad Quimica (Cloro en ppm)
        if estado_planta["cloro_manual"] is not None:
            estado_planta["cloro_ppm"] = round(float(estado_planta["cloro_manual"]), 2)
        else:
            # Oscilacion natural dentro de la norma (1.20 a 2.40 ppm)
            onda = math.sin((ahora - inicio_sim) / 15.0) * 0.6
            estado_planta["cloro_ppm"] = round(1.80 + onda, 2)

        estado_b = "ACTIVA (Llenando)" if estado_planta["bomba_activa"] else "INACTIVA (Vaciando)"
        print(
            f"[ESTANQUE AGUA] dt: {dt:.2f}s | Nivel: {estado_planta['nivel_agua']}% | "
            f"Cloro: {estado_planta['cloro_ppm']:.2f} ppm | Bomba: {estado_b}",
            flush=True
        )

@app.route('/estado', methods=['GET'])
def obtener_estado():
    return jsonify({
        "nivel_agua": int(round(estado_planta["nivel_agua"])),
        "nivel_exacto": estado_planta["nivel_agua"],
        "cloro_ppm": estado_planta["cloro_ppm"],
        "bomba_activa": estado_planta["bomba_activa"]
    })

@app.route('/bomba', methods=['POST'])
def controlar_bomba():
    datos = request.get_json(force=True)
    nueva_orden = bool(datos.get("activa", False))
    if estado_planta["bomba_activa"] != nueva_orden:
        estado_planta["bomba_activa"] = nueva_orden
        accion = "ENCENDIDA" if nueva_orden else "APAGADA"
        print(f"[API REST POST /bomba] Bomba {accion} por actuador-bomba-agua", flush=True)
    return jsonify({"ok": True, "bomba_activa": estado_planta["bomba_activa"]})

@app.route('/cloro', methods=['POST'])
def simular_anomalia_cloro():
    datos = request.get_json(force=True)
    valor = datos.get("cloro_ppm", None)
    estado_planta["cloro_manual"] = valor
    print(f"[API REST POST /cloro] Cloro ajustado manualmente a: {valor} ppm", flush=True)
    return jsonify({"ok": True, "cloro_ppm": estado_planta["cloro_manual"]})

if __name__ == '__main__':
    print("=== GEMELO DIGITAL ESTANQUE-AGUA INICIADO (API REST Puerto 5000) ===", flush=True)
    hilo_fisico = threading.Thread(target=motor_fisico_delta_time, daemon=True)
    hilo_fisico.start()
    app.run(host='0.0.0.0', port=5000)
