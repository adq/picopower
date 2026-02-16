import json
import machine
from machine import I2C
import asyncio
from async_mqtt_client import AsyncMQTTClient
from lib import send_syslog
import cfgsecrets
import time
import network
import utime
import rp2


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
    send_syslog("Sensor initialized: I2C on pins 20/21, monitoring light pulses")

    while True:
        try:
            led.off()

            # continuous measurement, low resolution mode, 4lx, ~16ms measurement time
            i2c.writeto(LIGHT_SENSOR_I2C_ADDRESS, bytes([0x13]))
            send_syslog("Sensor started: continuous measurement mode")

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
            send_syslog(f"Sensor error: {ex}, restarting in 5 seconds")
            await asyncio.sleep(5)


async def mqtt():
    global pulse_counter

    mqc = None
    send_syslog(f"MQTT client starting: connecting to {cfgsecrets.MQTT_HOST}")
    while True:
        try:
            mqc = AsyncMQTTClient("picopower", cfgsecrets.MQTT_HOST, keepalive=60)
            await mqc.connect()
            send_syslog("MQTT connected successfully")

            while True:
                await mqc.publish_string('homeassistant/sensor/picopower/config', ENERGY_CONFIG)
                await mqc.publish_string("homeassistant/sensor/picopower/state", str(pulse_counter))
                await asyncio.sleep(MQTT_PUBLISH_EVERY_SECS)

        except Exception as ex:
            if mqc:
                try:
                    await mqc.disconnect()
                    send_syslog("MQTT disconnected cleanly")
                except Exception as disconnect_ex:
                    send_syslog(f"MQTT disconnect error: {disconnect_ex}")
                mqc = None
            send_syslog(f"MQTT error: {ex}, reconnecting in 5 seconds")
            await asyncio.sleep(5)


async def main():
    what = [
        sensor(),
        mqtt()
    ]
    await asyncio.gather(*what)

time.sleep(5)
def do_connect():
    rp2.country('GB')
    print("WiFi: Setting country code to GB")

    sta_if = network.WLAN(network.STA_IF)
    if not sta_if.isconnected():
        print(f"WiFi: Connecting to {cfgsecrets.WIFI_SSID}")
        sta_if.active(True)
        sta_if.connect(cfgsecrets.WIFI_SSID, cfgsecrets.WIFI_PASSWORD)
        while not sta_if.isconnected():
            print("WiFi: Attempting to connect...")
            utime.sleep(1)
    config = sta_if.ifconfig()
    print(f"WiFi: Connected! IP={config[0]}, Netmask={config[1]}, Gateway={config[2]}, DNS={config[3]}")
    send_syslog(f"WiFi connected: IP={config[0]}")
do_connect()

send_syslog("Application starting: Pico Power Monitor v1.0")
time.sleep(5)
asyncio.run(main())
