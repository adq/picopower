import json
import machine
from machine import I2C
import asyncio
from umqtt.robust import MQTTClient
import cfgsecrets
import socket
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


def send_syslog(message, port=514, hostname="picopower", appname="main", procid="-", msgid="-"):
    print(message)

    syslog_addr = ('255.255.255.255', port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    pri = 13  # user.notice
    version = 1
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    # If timezone is missing, add 'Z' for UTC
    if not timestamp.endswith('Z') and not timestamp[-5:].startswith(('+', '-')):
        timestamp += 'Z'
    syslog_msg = f"<{pri}>{version} {timestamp} {hostname} {appname} {procid} {msgid} - {message}".encode('utf-8')
    try:
        sock.sendto(syslog_msg, syslog_addr)
    finally:
        sock.close()


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
            send_syslog(f"Sensor error: {ex}")
            await asyncio.sleep(5)


async def mqtt():
    global pulse_counter

    mqc = None
    while True:
        try:
            mqc = MQTTClient("picopower", cfgsecrets.MQTT_HOST, keepalive=60)
            mqc.connect()
            send_syslog("MQTT connected")

            while True:
                mqc.publish('homeassistant/sensor/picopower/config', ENERGY_CONFIG)
                mqc.publish("homeassistant/sensor/picopower/state", str(pulse_counter))
                await asyncio.sleep(MQTT_PUBLISH_EVERY_SECS)

        except Exception as ex:
            if mqc:
                try:
                    mqc.sock.close()
                except Exception:
                    pass
                mqc = None
            send_syslog(f"MQTT error: {ex}")
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

    sta_if = network.WLAN(network.STA_IF)
    if not sta_if.isconnected():
        print('connecting to network...')
        sta_if.active(True)
        sta_if.connect(cfgsecrets.WIFI_SSID, cfgsecrets.WIFI_PASSWORD)
        while not sta_if.isconnected():
            print("Attempting to connect....")
            utime.sleep(1)
    print('Connected! Network config:', sta_if.ifconfig())

print("Connecting to your wifi...")
do_connect()

time.sleep(5)
asyncio.run(main())
