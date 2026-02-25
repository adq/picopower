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


LIGHT_SENSOR_I2C_ADDRESS = 0x29
LIGHT_SENSOR_PULSE_THRESHOLD = 40

# TSL2591 registers
TSL2591_COMMAND_BIT = 0xA0
TSL2591_REG_ENABLE = 0x00
TSL2591_REG_CONFIG = 0x01
TSL2591_REG_ID = 0x12
TSL2591_REG_STATUS = 0x13
TSL2591_REG_C0DATAL = 0x14

# ENABLE register: PON (bit 0) + AEN (bit 1)
TSL2591_ENABLE_POWERON = 0x01
TSL2591_ENABLE_AEN = 0x02

# CONFIG register: AGAIN (bits 5:4), ATIME (bits 2:0)
TSL2591_GAIN_LOW = 0x00    # 1x
TSL2591_ATIME_100MS = 0x00 # 100ms, fastest


def tsl2591_write(i2c, reg, value):
    i2c.writeto(LIGHT_SENSOR_I2C_ADDRESS, bytes([TSL2591_COMMAND_BIT | reg, value]))


def tsl2591_read(i2c, reg, count):
    i2c.writeto(LIGHT_SENSOR_I2C_ADDRESS, bytes([TSL2591_COMMAND_BIT | reg]))
    return i2c.readfrom(LIGHT_SENSOR_I2C_ADDRESS, count)


def tsl2591_init(i2c):
    # verify chip ID
    chip_id = tsl2591_read(i2c, TSL2591_REG_ID, 1)
    if chip_id[0] != 0x50:
        raise RuntimeError(f"TSL2591 not found, got ID 0x{chip_id[0]:02x}")

    # power on + enable ALS
    tsl2591_write(i2c, TSL2591_REG_ENABLE, TSL2591_ENABLE_POWERON | TSL2591_ENABLE_AEN)

    # configure gain=Low(1x), integration time=100ms
    tsl2591_write(i2c, TSL2591_REG_CONFIG, (TSL2591_GAIN_LOW << 4) | TSL2591_ATIME_100MS)


def tsl2591_read_ch0(i2c):
    # read all 4 data bytes starting at C0DATAL to minimise skew
    data = tsl2591_read(i2c, TSL2591_REG_C0DATAL, 4)
    ch0 = data[0] | (data[1] << 8)
    return ch0

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

            tsl2591_init(i2c)
            send_syslog("Sensor started: TSL2591 gain=Low atime=100ms")

            current_state = 0
            while True:
                # read CH0 (visible+IR) from sensor
                v = tsl2591_read_ch0(i2c)

                # detect+count pulses!
                if v >= LIGHT_SENSOR_PULSE_THRESHOLD and not current_state:
                    pulse_counter += 1
                    current_state = 1
                    led.on()
                    print("Pulse ON")

                elif v < LIGHT_SENSOR_PULSE_THRESHOLD and current_state:
                    current_state = 0
                    led.off()
                    print("Pulse OFF")

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
