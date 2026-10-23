import logging
from scapy.all import sniff, IP, TCP, Raw

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)

PLC_IP = "192.168.10.10"
IP_SENSOR_AUTORIZADO = "192.168.10.12"
IPS_LECTURA_AUTORIZADAS = {"192.168.10.13", "192.168.10.14", "192.168.10.15"}

CODIGOS_FUNCION = {
    1: "FC01 Read Coils",
    2: "FC02 Read Discrete Inputs",
    3: "FC03 Read Holding Registers",
    4: "FC04 Read Input Registers",
    5: "FC05 Write Single Coil",
    6: "FC06 Write Single Register",
    15: "FC15 Write Multiple Coils",
    16: "FC16 Write Multiple Registers"
}

contador_lecturas = 0

def analizar_paquete(pkt):
    global contador_lecturas
    if not (pkt.haslayer(IP) and pkt.haslayer(TCP) and pkt.haslayer(Raw)):
        return

    ip_src = pkt[IP].src
    ip_dst = pkt[IP].dst
    dport = pkt[TCP].dport
    payload = bytes(pkt[Raw].load)

    # Analizar peticiones dirigidas al puerto 502 (Modbus TCP) del PLC Central
    if dport == 502 and len(payload) >= 8:
        # Cabecera MBAP (7 bytes) + Codigo de Funcion (byte 7)
        proto_id = (payload[2] << 8) | payload[3]
        if proto_id != 0:
            return

        fc = payload[7]
        nombre_fc = CODIGOS_FUNCION.get(fc, f"FC{fc} Desconocido")

        # 1. Deteccion de Comandos de Escritura (FC 5, 6, 15, 16)
        if fc in (5, 6, 15, 16):
            # Solo el sensor (192.168.10.12) tiene permiso para escribir Holding Registers (FC 16)
            if ip_src == IP_SENSOR_AUTORIZADO and fc == 16:
                logging.info(f"[IDS TRAFICO LEGITIMO] Escritura autorizada de Sensor ({ip_src} -> {ip_dst}:502) | {nombre_fc}")
            else:
                logging.critical(
                    f"[ALERTA INTRUSION OT - ESCRITURA NO AUTORIZADA] "
                    f"Origen: {ip_src} -> Destino: {ip_dst}:502 | Comando: {nombre_fc}"
                )

        # 2. Monitoreo de Consultas de Lectura (FC 1, 2, 3, 4)
        elif fc in (1, 2, 3, 4):
            if ip_src not in IPS_LECTURA_AUTORIZADAS:
                logging.warning(
                    f"[ALERTA SONDEO NO AUTORIZADO] IP desconocida leyendo el PLC: "
                    f"{ip_src} -> {ip_dst}:502 | {nombre_fc}"
                )
            else:
                contador_lecturas += 1
                if contador_lecturas % 10 == 1:
                    logging.info(f"[IDS SPAN MONITOR] Sondeo normal ({ip_src} -> {ip_dst}:502) | {nombre_fc}")

def main():
    logging.info("=== SONDA-IDS INICIADA EN MODO PASIVO (Scapy escuchando SPAN en eth0) ===")
    sniff(iface="eth0", filter="tcp port 502", prn=analizar_paquete, store=False)

if __name__ == "__main__":
    main()
