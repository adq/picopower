import json
import machine
from machine import I2C
import asyncio
import mqtt_async
import cfgsecrets

LIGHT_SENSOR_I2C_ADDRESS = 0x23
LIGHT_SENSOR_PULSE_THRESHOLD = 40

MQTT_PUBLISH_EVERY_SECS = 30
SENSOR_SLEEP_INTERVAL_MS = 100

ENERGY_CONFIG = json.dumps({"device_class": "energy",
                            "state_class": "total_increasing",
                            "state_topic": "homeassistant/sensor/picopower/state",
                            "unit_of_measurement": "Wh",
                            "unique_id": "picopowenergy",
                            "device": {"identifiers": ["picopower"], "name": "Pico Power"}
                            })


pulse_counter = 0


async def sensor():
    global pulse_counter

    # hardware setup
    sda = machine.Pin(20)
    scl = machine.Pin(21)
    i2c = I2C(0, sda=sda, scl=scl, freq=400000)

    led = machine.Pin("LED", machine.Pin.OUT)

    while True:
        try:
            led.off()

            # continuous measurement, low resolution mode, 4lx, ~16ms measurement time
            i2c.writeto(LIGHT_SENSOR_I2C_ADDRESS, bytes([0x13]))

            current_state = 0
            while True:
                # read from sensor
                b = i2c.readfrom(LIGHT_SENSOR_I2C_ADDRESS, 2)
                v = (b[0] << 8) | b[1]

                # detect+count pulses!
                if v >= LIGHT_SENSOR_PULSE_THRESHOLD and not current_state:
                    pulse_counter += 1
                    current_state = 1
                    led.on()

                elif v < LIGHT_SENSOR_PULSE_THRESHOLD and current_state:
                    current_state = 0
                    led.off()

                await asyncio.sleep_ms(SENSOR_SLEEP_INTERVAL_MS)

        except Exception as ex:
            print("SENSORFAIL")
            print(ex)
            await asyncio.sleep(5)


async def mqtt():
    global pulse_counter

    mqtt_async.config['ssid'] = cfgsecrets.WIFI_SSID
    mqtt_async.config['wifi_pw'] = cfgsecrets.WIFI_PASSWORD
    mqtt_async.config['server'] = cfgsecrets.MQTT_HOST

    while True:
        try:
            mqc = mqtt_async.MQTTClient(mqtt_async.config)
            await mqc.connect()
            print("MQTT connected")

            while True:
                await mqc.publish('homeassistant/sensor/picopower/config', ENERGY_CONFIG)
                await mqc.publish("homeassistant/sensor/picopower/state", str(pulse_counter))
                await asyncio.sleep(MQTT_PUBLISH_EVERY_SECS)

        except Exception as ex:
            print("MQTTFAIL")
            print(ex)
            await asyncio.sleep(5)


async def main():
    what = [
        sensor(),
        mqtt()
    ]
    await asyncio.gather(*what)

asyncio.run(main())
