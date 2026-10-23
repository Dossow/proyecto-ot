import time
import logging
import requests
from pymodbus.client import ModbusTcpClient

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)

ESTANQUE_BOMBA_URL = "http://192.168.10.11:5000/bomba"
PLC_IP = "192.168.10.10"
PLC_PORT = 502

def main():
    logging.info("=== ACTUADOR-BOMBA-AGUA INICIADO (Modbus TCP -> API REST) ===")
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT)

    while True:
        try:
            # 1. Lectura de Coil[0] en plc-central por Modbus TCP (Puerto 502)
            if client.connect():
                rr = client.read_coils(0, 1)
                if not rr.isError():
                    estado_bomba = bool(rr.bits[0])

                    # 2. Envio de comando HTTP POST al motor fisico (estanque-agua)
                    resp = requests.post(
                        ESTANQUE_BOMBA_URL,
                        json={"activa": estado_bomba},
                        timeout=3
                    )
                    resp.raise_for_status()

                    estado_txt = "ACTIVA (ON)" if estado_bomba else "INACTIVA (OFF)"
                    logging.info(f"[PLC -> ACTUADOR -> ESTANQUE] Bomba: {estado_txt}")
                else:
                    logging.error(f"[ERROR MODBUS] Fallo al leer Coil 0 del PLC: {rr}")
            else:
                logging.warning(f"[REINTENTO MODBUS] Sin conexion con plc-central ({PLC_IP}:{PLC_PORT})")

        except Exception as e:
            logging.warning(f"[ESPERANDO CONEXION] {e}")

        time.sleep(1)

if __name__ == "__main__":
    main()
