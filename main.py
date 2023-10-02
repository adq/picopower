import machine
from machine import I2C
import network
import time
import rp2
import json
from umqtt.simple import MQTTClient
import secrets

LIGHT_SENSOR_I2C_ADDRESS = 0x23
LIGHT_SENSOR_PULSE_THRESHOLD = 40
WIFI_SSID = secrets.WIFI_SSID
WIFI_PASSWORD = secrets.WIFI_PASSWORD
MQTT_HOST = secrets.MQTT_HOST
MQTT_STATE_TOPIC = 'homeassistant/sensor/picopower/state'
MQTT_CONFIG_TOPIC = 'homeassistant/sensor/picopower/config'
MQTT_CLIENT_ID = 'picopower'

MQTT_PUBLISH_EVERY_MS = 30 * 1000
SLEEP_INTERVAL_MS = 100

ENERGY_CONFIG = {"device_class": "energy",
                 "state_class": "total_increasing",
                 "state_topic": "homeassistant/sensor/picopower/state",
                 "unit_of_measurement": "Wh",
                 "unique_id": "picopowenergy",
                 "device": {"identifiers": ["picopower"], "name": "Pico Power"}
                }


pulse_counter = 0


def main():
    global pulse_counter

    # i2c setup
    sda = machine.Pin(20)
    scl = machine.Pin(21)
    i2c = I2C(0, sda=sda, scl=scl, freq=400000)

    led = machine.Pin("LED", machine.Pin.OUT)

    # continuous measurement, low resolution mode, 4lx, ~16ms measurement time
    i2c.writeto(LIGHT_SENSOR_I2C_ADDRESS, bytes([0x13]))

    # Connect to WiFi
    print("Connecting to WIFI")
    rp2.country('GB')
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    while not wlan.isconnected():
        print(wlan.status())
        print('Waiting for connection...')
        time.sleep(1)
    print("Connected to WiFi")

    # Initialize our MQTTClient and connect to the MQTT server
    mqtt_client = MQTTClient(client_id=MQTT_CLIENT_ID, server=MQTT_HOST)
    mqtt_client.connect()
    print("Connected to MQTT")
    mqtt_client.publish(MQTT_CONFIG_TOPIC, json.dumps(ENERGY_CONFIG))

    last_mqtt_publish = 0
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

        # sleep/ send counter to mqtt
        if (time.ticks_ms() - last_mqtt_publish) > MQTT_PUBLISH_EVERY_MS:
            mqtt_client.publish(MQTT_STATE_TOPIC, str(pulse_counter))
            last_mqtt_publish = time.ticks_ms()
        else:
            time.sleep_ms(SLEEP_INTERVAL_MS)


# main loop - keep running forever
while True:
    try:
        main()
    except Exception as ex:
        print(ex)
    time.sleep(5)
