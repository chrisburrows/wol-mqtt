#!/usr/bin/python3
#
# Send WoL packets controlled by MQTT messages.
#
# Chris Burrows
# 8 July 2021

import os
import logging
import logging.handlers
import time
import json
import subprocess
import paho.mqtt.client as mqtt

UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "60"))

MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt.local")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "mqtt")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "password")
MQTT_BASE_TOPIC = "wol"

LOG_FILENAME = '/var/log/wol-mqtt.log'

# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    '''Callback to handle connection to MQTT broker'''

    log.info("MQTT: connected to broker with result code " + str(rc))

    if rc == 0:
        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.

        client.subscribe(MQTT_BASE_TOPIC + "/command")
        client.publish(MQTT_BASE_TOPIC + "/status", payload="online")
    else:
        log.error("Failed to correctly login to MQTT broker")
        client.disconnect()
        time.sleep(5)

# The callback for when a PUBLISH message is received from the server.
def on_message(client, userdata, msg):
    '''Callback to handle received messages'''

    log.debug("MQTT: Message " + msg.topic + " = " + str(msg.payload, "UTF-8"))
    try:
        data = json.loads(msg.payload)
        ip = data['ip'] if 'ip' in data else None
        count = data['repeat'] if 'repeat' in data else 2
        if 'mac' in data:
            wakeup(data['mac'], ip, count)
        else:
            log.error("No 'mac' provided in payload: '" + str(msg.payload, "UTF-8") + "'")

    except json.decoder.JSONDecodeError:
        log.error("Malformed JSON payload: '" + str(msg.payload, "UTF-8") + "'")

def send_wol(mac, ip=None):
    '''Send a single WOL UDP packet'''

    if ip is None:
        status = subprocess.run(["wakeonlan", mac], capture_output=True, text=True, encoding="UTF-8")
    else:
        status = subprocess.run(["wakeonlan", "-i", ip, mac], capture_output=True, text=True, encoding="UTF-8")
    if "magic packet" not in status.stdout:
        log.error("Error sending WoL packet: '{text}'".format(text=status.stderr.strip()))
        return False
    return True

def wakeup(mac, ip=None, count=2):
    '''Send one or more WoL Magic Packets to a device'''

    if ip is None:
        log.info("Sending WoL (x{count} to {mac}".format(count=count, mac=mac))
    else:
        log.info("Sending WoL (x{count}) to {mac} via {ip}".format(count=count, mac=mac, ip=ip))
    for i in range(count):
        if not send_wol(mac, ip):
            break
        # sleep if we have another iteration to go
        if i < count - 1:
            time.sleep(1)

# setup logging
log = logging.getLogger()
handler = logging.handlers.TimedRotatingFileHandler(LOG_FILENAME, when='midnight', backupCount=7)
formatter = logging.Formatter('{asctime} {levelname:8s} {message}', style='{')

handler.setFormatter(formatter)
log.addHandler(handler)
log.setLevel(logging.DEBUG)
log.info("Starting up...")

try:
    # Initialise connect to MQTT broker
    client = mqtt.Client(client_id="wol-mqtt")
    client.will_set(MQTT_BASE_TOPIC + "/status", payload="offline")
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    while(True):
        log.info("MQTT: connecting to broker...")

        try:
            client.connect(MQTT_BROKER, MQTT_PORT, 60)
            client.loop_start()

            while(True):
                log.debug("MQTT: publishing online Status update")
                client.publish(MQTT_BASE_TOPIC + "/status", payload="online")                
                time.sleep(UPDATE_INTERVAL)

        except ConnectionRefusedError:
            log.error("Failed to connect to broker on {ip}:{port}".format(ip=MQTT_BROKER, port=MQTT_PORT))
            time.sleep(30)

except KeyboardInterrupt:
    log.info("Interrupted... shutting down")
    
# mark us offline and disconnect
log.info("MQTT: Publishing offline status")

client.publish(MQTT_BASE_TOPIC + "/status", payload="offline")

time.sleep(3)
log.info("MQTT: disconnecting")

client.loop_stop()
client.disconnect()

