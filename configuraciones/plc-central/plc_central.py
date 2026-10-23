import asyncio
import logging
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.server import StartAsyncTcpServer

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)

co_block = ModbusSequentialDataBlock(0, [False] * 10)
hr_block = ModbusSequentialDataBlock(0, [0] * 10)

store = ModbusSlaveContext(
    di=ModbusSequentialDataBlock(0, [0] * 10),
    co=co_block,
    hr=hr_block,
    ir=ModbusSequentialDataBlock(0, [0] * 10)
)
context = ModbusServerContext(slaves=store, single=True)

# HR[0]=50% (Nivel), HR[1]=150 (1.50 ppm Cloro), HR[2]=20% (Min Safety), HR[3]=90% (Max Safety), HR[4]=0 (Codigo Alarma)
context[0].setValues(3, 0, [50, 150, 20, 90, 0])
# Coils: Coil[0]=False (Bomba OFF), Coil[1]=False (Alarma Nivel), Coil[2]=False (Alarma Cloro)
context[0].setValues(1, 0, [False, False, False])

async def lazo_control_plc(context):
    slave = context[0]
    while True:
        await asyncio.sleep(1)
        hr = slave.getValues(3, 0, count=5)
        nivel = hr[0]
        cloro_raw = hr[1]
        cloro_ppm = cloro_raw / 100.0
        umbral_min = hr[2]
        umbral_max = hr[3]

        coils = slave.getValues(1, 0, count=3)
        bomba_activa = bool(coils[0])

        alarma_nivel = False
        alarma_cloro = False
        codigo_alarma = 0

        if nivel <= umbral_min:
            alarma_nivel = True
            codigo_alarma = 1
            if not bomba_activa:
                bomba_activa = True
                logging.warning(f"[ALERTA SAFETY PLC] Nivel critico bajo ({nivel}% <= {umbral_min}%). ENCENDIENDO BOMBA.")
        elif nivel >= umbral_max:
            alarma_nivel = True
            codigo_alarma = 2
            if bomba_activa:
                bomba_activa = False
                logging.warning(f"[ALERTA SAFETY PLC] Nivel critico alto ({nivel}% >= {umbral_max}%). APAGANDO BOMBA.")

        if cloro_ppm < 0.20 or cloro_ppm > 4.00:
            alarma_cloro = True
            codigo_alarma = 3
            logging.error(f"[ALERTA QUIMICA PLC] Cloro fuera de norma: {cloro_ppm:.2f} ppm (Rango seguro: 0.2 - 4.0 ppm)")

        slave.setValues(1, 0, [bomba_activa, alarma_nivel, alarma_cloro])
        slave.setValues(3, 4, [codigo_alarma])

        estado_b = "ACTIVA (ON)" if bomba_activa else "INACTIVA (OFF)"
        logging.info(f"[PLC CENTRAL] Nivel: {nivel}% | Cloro: {cloro_ppm:.2f} ppm | Bomba: {estado_b} | Alarma: {codigo_alarma}")

async def main():
    logging.info("=== PLC CENTRAL INICIADO (Modbus TCP Puerto 502) ===")
    asyncio.create_task(lazo_control_plc(context))
    await StartAsyncTcpServer(context=context, address=("0.0.0.0", 502))

if __name__ == "__main__":
    asyncio.run(main())
