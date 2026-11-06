# Maqueta de Ciberseguridad Industrial OT/IT & Conectividad Cloud

Implementación y validación empírica de una infraestructura convergente OT/IT basada en el **Modelo Purdue (ISA-95 / IEC 62443)**. El entorno integra simulación de procesos físicos, supervisión y control distribuido, segmentación perimetral estricta mediante **FortiGate NGFW**, detección pasiva de intrusiones con **Inspección Profunda de Paquetes (DPI)** sobre Modbus TCP y exportación de telemetría hacia la nube (AWS EC2 / Node-RED).

---

## 🏛️ Arquitectura de Red y Segmentación (Modelo Purdue)

El diseño aísla estrictamente la red operacional de control de la red corporativa/DMZ mediante inspección con firewall de estado y listas de control de acceso granulares:

```text
[ Nivel 4: Nube Pública / Supervisión WAN ]
                      │
            (Internet / HTTPS:1880)
                      │
[ Nivel 3.5: Perímetro / DMZ IT (192.168.20.0/24) ]
   ┌──────────────────┴──────────────────┐
   │     FortiGate NGFW (Port1: NAT)     │
   │  Port3: 192.168.20.1 (Gateway DMZ)  │
   └──────────────────┬──────────────────┘
                      │
             Switch-IT (VLAN 20)
           ┌──────────┴──────────┐
           │                     │
    broker-mqtt-1           puente-aws-1
   (192.168.20.20)        (192.168.20.40)
   [Mosquitto 1883]       [Exportador AWS]
                      ▲
                      │ Tráfico MQTT Autorizado
                      ▼
   ┌─────────────────────────────────────┐
   │  FortiGate NGFW (Port2: 192.168.10.1)│
   └──────────────────┬──────────────────┘
                      │
[ Nivel 3 & 2: Supervisión y Control OT (192.168.10.0/24) ]
             Switch-OT (VLAN 10)
   ┌──────────┬───────────┬──────────────┬──────────────┐
   │          │           │              │              │
plc-central  panel-hmi  gateway_borde  Kali Linux   sonda-ids-1
 (10.10)     (10.30)       (10.21)      (10.14)      (SPAN Port)
[Modbus 502] [Web 8080]  [MQTT Client]  [Auditoría]  [DPI Scapy]
   │
   ├─► estanque-agua-1 (10.11: Gemelo Digital HTTP 5000)
   ├─► sensor-nivel-estanque-1 (10.12: Transmisor Nivel/Cloro)
   └─► actuador-bomba-agua-1 (10.13: Control de Impulsión)
