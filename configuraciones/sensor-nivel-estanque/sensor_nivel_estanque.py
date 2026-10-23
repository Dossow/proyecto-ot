import time
import logging
import requests
from pymodbus.client import ModbusTcpClient

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)

ESTANQUE_API_URL = "http://192.168.10.11:5000/estado"
PLC_IP = "192.168.10.10"
PLC_PORT = 502

def main():
    logging.info("=== SENSOR-NIVEL-ESTANQUE INICIADO (API REST -> Modbus TCP) ===")
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT)

    while True:
        try:
            # 1. Consulta HTTP GET al gemelo digital (estanque-agua)
            resp = requests.get(ESTANQUE_API_URL, timeout=3)
            resp.raise_for_status()
            datos = resp.json()

            nivel = int(datos.get("nivel_agua", 50))
            cloro_ppm = float(datos.get("cloro_ppm", 1.50))
            # Escalamiento a entero para Holding Register (ej: 1.50 ppm -> 150)
            cloro_reg = int(round(cloro_ppm * 100))

            # 2. Escritura continua por Modbus TCP (Puerto 502) en HR[0] (Nivel) y HR[1] (Cloro)
            if client.connect():
                resultado = client.write_registers(0, [nivel, cloro_reg])
                if not resultado.isError():
                    logging.info(
                        f"[SENSOR -> PLC] Nivel: {nivel}% (HR0) | "
                        f"Cloro: {cloro_ppm:.2f} ppm (HR1={cloro_reg})"
                    )
                else:
                    logging.error(f"[ERROR MODBUS] Fallo al escribir registros en el PLC: {resultado}")
            else:
                logging.warning(f"[REINTENTO MODBUS] Sin conexion con plc-central ({PLC_IP}:{PLC_PORT})")

        except Exception as e:
            logging.warning(f"[ESPERANDO CONEXION] {e}")

        time.sleep(1)

if __name__ == "__main__":
    main()
