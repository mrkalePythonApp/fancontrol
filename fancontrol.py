#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cooling fan manager and MQTT client.

Script provides following functionalities:

- Script manages a fan attached to a GPIO pin for cooling the system
  on the basis of the system temperature provided by the SoC.
- Script acts as a MQTT client utilizing local MQTT broker ``mosquitto``
  for data exchange with outside environment.
- Script publishes system temperature, configuration fata, and fan status
  to the ``local MQTT broker``.
- Script can receive commands from `local MQTT broker` in order to change its
  behaviour during running, e.g., turn on or off the fan, change fan
  temperatures limits, etc.

"""
__version__ = '0.3.0'
__status__ = 'Beta'
__author__ = 'Libor Gabaj'
__copyright__ = 'Copyright 2019, ' + __author__
__credits__ = [__author__]
__license__ = 'MIT'
__maintainer__ = __author__
__email__ = 'libor.gabaj@gmail.com'

# Standard library modules
import time
import os
import sys
import argparse
import logging

# Third party modules
import gbj_pythonlib_sw.utils as modUtils
import gbj_pythonlib_sw.config as modConfig
import gbj_pythonlib_sw.mqtt as modMQTT
import gbj_pythonlib_sw.timer as modTimer
import gbj_pythonlib_hws.orangepi as modOrangePi
# import gbj_pythonlib_hw.orangepi as modOrangePi
import gbj_pythonlib_iot.common as iot
import gbj_pythonlib_iot.fan as iot_fan


###############################################################################
# Enumeration and parameter classes
###############################################################################
class Script:
    """Script parameters."""

    (
        fullname, basename, name,
        running, service, lwt
    ) = (
            None, None, None,
            True, False, 'lwt',
        )


###############################################################################
# Script global variables
###############################################################################
cmdline = None  # Object with command line arguments
logger = None  # Object with standard logging
config = None  # Object with MQTT configuration file processing
mqtt = None  # Object for MQTT broker manipulation
pi = None  # Object with OrangePi GPIO control
dev_fan = None  # Object for processing cooling fan parameters


###############################################################################
# General actions
###############################################################################
def action_exit():
    """Perform all activities right before exiting the script."""
    modTimer.stop_all()
    mqtt_publish_lwt(iot.Status.OFFLINE)
    mqtt.disconnect()


def mqtt_message_log(message):
    """Log receiving from an MQTT topic.

    Arguments
    ---------
    message : MQTTMessage object
        This is an object with members `topic`, `payload`, `qos`, `retain`.

    Returns
    -------
    bool
        Flag about present message payload.

    See Also
    --------
    gbj_pythonlib_sw.mqtt
        Module for MQTT processing.

    """
    if message.payload is None:
        payload = "None"
    else:
        payload = message.payload.decode('utf-8')
    logger.debug(
        '%s -- MQTT topic %s, QoS=%s, retain=%s: %s',
        sys._getframe(1).f_code.co_name,
        message.topic, message.qos, bool(message.retain), payload,
    )
    return message.payload is not None


###############################################################################
# MQTT actions
###############################################################################
def mqtt_publish_lwt(status):
    """Publish script status to the MQTT LWT topic."""
    if not mqtt.get_connected():
        return
    cfg_option = Script.lwt
    cfg_section = mqtt.GROUP_TOPICS
    message = iot.get_status(status)
    try:
        mqtt.publish(message, cfg_option, cfg_section)
        logger.debug(
            'Published to LWT MQTT topic %s: %s',
            mqtt.topic_name(cfg_option, cfg_section),
            message
        )
    except Exception as errmsg:
        logger.error(
            'Publishing %s to LWT MQTT topic %s failed: %s',
            message,
            mqtt.topic_name(cfg_option, cfg_section),
            errmsg,
        )


def mqtt_publish_fan_percon():
    """Publish fan temperature percentage ON to the MQTT status topic."""
    if not mqtt.get_connected():
        return
    cfg_option = 'fan_status_percon'
    cfg_section = mqtt.GROUP_TOPICS
    value = dev_fan.get_percentage_on()
    try:
        mqtt.publish(str(value), cfg_option, cfg_section)
        logger.debug(
            'Published fan percentage ON=%s%% to MQTT topic %s',
            value, mqtt.topic_name(cfg_option, cfg_section))
    except Exception as errmsg:
        logger.error(
            'Publishing fan percentage ON=%s%% to MQTT topic %s failed: %s',
            value, mqtt.topic_name(cfg_option, cfg_section), errmsg)


def mqtt_publish_fan_percoff():
    """Publish fan temperature percentage OFF to the MQTT status topic."""
    if not mqtt.get_connected():
        return
    cfg_option = 'fan_status_percoff'
    cfg_section = mqtt.GROUP_TOPICS
    value = dev_fan.get_percentage_off()
    try:
        mqtt.publish(str(value), cfg_option, cfg_section)
        logger.debug(
            'Published fan percentage OFF=%s%% to MQTT topic %s',
            value, mqtt.topic_name(cfg_option, cfg_section))
    except Exception as errmsg:
        logger.error(
            'Publishing fan percentage OFF=%s%% to MQTT topic %s failed: %s',
            value, mqtt.topic_name(cfg_option, cfg_section), errmsg)


def mqtt_publish_fan_tempon():
    """Publish fan temperature value ON to the MQTT status topic."""
    if not mqtt.get_connected():
        return
    cfg_option = 'fan_status_tempon'
    cfg_section = mqtt.GROUP_TOPICS
    value = dev_fan.get_temperature_on()
    try:
        mqtt.publish(str(value), cfg_option, cfg_section)
        logger.debug(
            'Published fan temperature ON=%s°C to MQTT topic %s',
            value, mqtt.topic_name(cfg_option, cfg_section))
    except Exception as errmsg:
        logger.error(
            'Publishing fan temperature ON=%s°C to MQTT topic %s failed: %s',
            value, mqtt.topic_name(cfg_option, cfg_section), errmsg)


def mqtt_publish_fan_tempoff():
    """Publish fan temperature value OFF to the MQTT status topic."""
    if not mqtt.get_connected():
        return
    cfg_option = 'fan_status_tempoff'
    cfg_section = mqtt.GROUP_TOPICS
    value = dev_fan.get_temperature_off()
    try:
        mqtt.publish(str(value), cfg_option, cfg_section)
        logger.debug(
            'Published fan temperature OFF=%s°C to MQTT topic %s',
            value, mqtt.topic_name(cfg_option, cfg_section))
    except Exception as errmsg:
        logger.error(
            'Publishing fan temperature OFF=%s°C to MQTT topic %s failed: %s',
            value, mqtt.topic_name(cfg_option, cfg_section), errmsg)


def mqtt_publish_fan_status():
    """Publish fan status to the MQTT status topic."""
    if not mqtt.get_connected():
        return
    cfg_option = 'mqtt_topic_fan_status'
    cfg_section = mqtt.GROUP_DEFAULT
    if pi.is_pin_on(dev_fan.get_pin()):
        message = iot.get_status(iot.Status.ACTIVE)
    else:
        message = iot.get_status(iot.Status.IDLE)
    try:
        mqtt.publish(message, cfg_option, cfg_section)
        logger.debug(
            'Published fan status %s to MQTT topic %s',
            message, mqtt.topic_name(cfg_option, cfg_section),
        )
    except Exception as errmsg:
        logger.error(
            'Publishing fan status %s to MQTT topic %s failed: %s',
            message,
            mqtt.topic_name(cfg_option, cfg_section),
            errmsg,
        )


def mqtt_publish_fan_state():
    """Publish fan status and all parameters to the MQTT topics."""
    mqtt_publish_fan_status()
    mqtt_publish_fan_percon()
    mqtt_publish_fan_percoff()
    mqtt_publish_fan_tempon()
    mqtt_publish_fan_tempoff()


###############################################################################
# Callback functions
###############################################################################
def cbTimer_mqtt_reconnect(*arg, **kwargs):
    """Execute MQTT reconnect."""
    if mqtt.get_connected():
        return
    logger.warning('Reconnecting to MQTT broker')
    try:
        mqtt.reconnect()
    except Exception as errmsg:
        logger.error(
            'Reconnection to MQTT broker failed with error: %s',
            errmsg)


def cbTimer_fan(*arg, **kwargs):
    """Check SoC temperature and control fan accordingly."""
    fan_pin = dev_fan.get_pin()
    temp_cur = dev_fan.get_temperature()
    temp_on = dev_fan.get_temperature_on()
    temp_off = dev_fan.get_temperature_off()
    logger.debug('Current SoC temperature %.1f°C', temp_cur)
    # Turn on fan at reaching start temperature and fan is switched off
    if temp_cur >= temp_on and pi.is_pin_off(fan_pin):
        pi.pin_on(fan_pin)
        mqtt_publish_fan_status()
        logger.info('Fan switched ON')
    # Turn off fan at reaching stop temperature and fan is switched on
    if temp_cur <= temp_off and pi.is_pin_on(fan_pin):
        pi.pin_off(fan_pin)
        mqtt_publish_fan_status()
        logger.info('Fan switched OFF')


def cbMqtt_on_connect(client, userdata, flags, rc):
    """Process actions when the broker responds to a connection request.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    flags : dict
        Response flags sent by the MQTT broker.
    rc : int
        The connection result (result code).

    See Also
    --------
    gbj_pythonlib_sw.mqtt._on_connect()
        Description of callback arguments for proper utilizing.

    """
    if rc == 0:
        logger.debug('Connected to %s: %s', str(mqtt), userdata)
        setup_mqtt_filters()
        mqtt_publish_fan_state()
    else:
        logger.error('Connection to MQTT broker failed: %s (rc = %d)',
                     userdata, rc)


def cbMqtt_on_disconnect(client, userdata, rc):
    """Process actions when the client disconnects from the broker.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    rc : int
        The connection result (result code).

    See Also
    --------
    gbj_pythonlib_sw.mqtt._on_connect()
        Description of callback arguments for proper utilizing.

    """
    logger.warning('Disconnected from %s: %s (rc = %d)',
                   str(mqtt), userdata, rc)


def cbMqtt_on_subscribe(client, userdata, mid, granted_qos):
    """Process actions when the broker responds to a subscribe request.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    mid : int
        The message ID from the subscribe request.
    granted_qos : int
        The list of integers that give the QoS level the broker has granted
        for each of the different subscription requests.

    """
    # logger.debug('Subscribed to MQTT topic with message id %d', mid)
    pass


def cbMqtt_on_message(client, userdata, message):
    """Process actions when a non-filtered message has been received.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    message : MQTTMessage object
        The object with members `topic`, `payload`, `qos`, `retain`.

    Notes
    -----
    - The topic that the client subscribes to and the message does not match
      an existing topic filter callback.
    - Use message_callback_add() to define a callback that will be called for
      specific topic filters. This function serves as fallback when none
      topic filter matched.

    """
    if not mqtt_message_log(message):
        return


def cbMqtt_dev_fan(client, userdata, message):
    """Process command at receiving a message from the command topic(s).

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    message : MQTTMessage object
        The object with members `topic`, `payload`, `qos`, `retain`.

    Notes
    -----
    - The topic that the client subscribes to and the message match the topic
      filter for server commands.

    """
    if not mqtt_message_log(message):
        return
    command = iot.get_command_index(message.payload.decode('utf-8'))
    try:
        value = float(message.payload)
    except ValueError:
        value = None
    if message.topic == mqtt.topic_name('mqtt_topic_fan_command',
                                        mqtt.GROUP_DEFAULT):
        fan_pin = dev_fan.get_pin()
        if command == iot.Command.ON and pi.is_pin_off(fan_pin):
            pi.pin_on(fan_pin)
            mqtt_publish_fan_status()
        elif command == iot.Command.OFF and pi.is_pin_on(fan_pin):
            pi.pin_off(fan_pin)
            mqtt_publish_fan_status()
        elif command == iot.Command.TOGGLE:
            if pi.is_pin_on(fan_pin):
                pi.pin_off(fan_pin)
            else:
                pi.pin_on(fan_pin)
            mqtt_publish_fan_status()
        elif command == iot.Command.STATUS:
            mqtt_publish_fan_state()
        elif command == iot.Command.RESET:
            dev_fan.reset()
            mqtt_publish_fan_state()
    elif message.topic == mqtt.topic_name('fan_command_percon'):
        if value is not None:
            dev_fan.set_percentage_on(value)
            mqtt_publish_fan_percon()
            logger.info('Updated fan percentage ON=%s%%', value)
    elif message.topic == mqtt.topic_name('fan_command_percoff'):
        if value is not None:
            dev_fan.set_percentage_off(value)
            mqtt_publish_fan_percoff()
            logger.info('Updated fan percentage OFF=%s%%', value)
    elif message.topic == mqtt.topic_name('fan_command_tempon'):
        if value is not None:
            dev_fan.set_temperature_on(value)
            mqtt_publish_fan_tempon()
            logger.info('Updated fan temperature ON=%s°C', value)
    elif message.topic == mqtt.topic_name('fan_command_tempoff'):
        if value is not None:
            dev_fan.set_temperature_off(value)
            mqtt_publish_fan_tempoff()
            logger.info('Updated fan temperature OFF=%s°C', value)
    # Unexpected command
    else:
        logger.debug(
            'Unexpected topic "%s" with value: "%s"',
            message.topic,
            message.payload
        )


###############################################################################
# Setup functions
###############################################################################
def setup_params():
    """Determine script operational parameters."""
    Script.fullname = os.path.splitext(os.path.abspath(__file__))[0]
    Script.basename = os.path.basename(__file__)
    Script.name = os.path.splitext(Script.basename)[0]
    Script.service = modUtils.check_service(Script.name)


def setup_cmdline():
    """Define command line arguments."""
    config_file = Script.fullname + '.ini'
    if modUtils.linux():
        log_folder = '/var/log'
    elif modUtils.windows():
        log_folder = 'c:/Temp'
    else:
        log_folder = '.'

    parser = argparse.ArgumentParser(
        description='Cooling fan manager and MQTT client, version '
        + __version__
    )
    # Position arguments
    parser.add_argument(
        'config',
        type=argparse.FileType('r'),
        nargs='?',
        default=config_file,
        help='Configuration INI file, default: ' + config_file
    )
    # Options
    parser.add_argument(
        '-V', '--version',
        action='version',
        version=__version__,
        help='Current version of the script.'
    )
    parser.add_argument(
        '-v', '--verbose',
        choices=['debug', 'info', 'warning', 'error', 'critical'],
        default='debug',
        help='Level of logging to the console.'
    )
    parser.add_argument(
        '-l', '--loglevel',
        choices=['debug', 'info', 'warning', 'error', 'critical'],
        default='debug',
        help='Level of logging to a log file.'
    )
    parser.add_argument(
        '-d', '--logdir',
        default=log_folder,
        help='Folder of a log file, default ' + log_folder
    )
    parser.add_argument(
        '-c', '--configuration',
        action='store_true',
        help="""Print configuration parameters in form of INI file content."""
    )
    # Process command line arguments
    global cmdline
    cmdline = parser.parse_args()


def setup_logger():
    """Configure logging facility."""
    global logger
    # Set logging to file for module and script logging
    log_file = '/'.join([cmdline.logdir, Script.basename + '.log'])
    logging.basicConfig(
        level=getattr(logging, cmdline.loglevel.upper()),
        format='%(asctime)s - %(levelname)-8s - %(name)s: %(message)s',
        filename=log_file,
        filemode='w'
    )
    # Set console logging
    formatter = logging.Formatter(
        '%(levelname)-8s - %(name)-20s: %(message)s')
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, cmdline.verbose.upper()))
    console_handler.setFormatter(formatter)
    logger = logging.getLogger('{} {}'.format(
        os.path.basename(__file__), __version__))
    logger.addHandler(console_handler)
    logger.warning('Script started from file %s', os.path.abspath(__file__))


def setup_config():
    """Define configuration file management."""
    global config
    config = modConfig.Config(cmdline.config)


def setup_pi():
    """Define microcomputer GPIO control."""
    global pi
    pi = modOrangePi.OrangePiOne()


def setup_fan():
    """Define cooling fan parameters."""
    global dev_fan
    dev_fan = iot_fan.Fan(config.option('pin_name', 'Fan'))
    dev_fan.set_percentage_on(float(config.option(
        'percentage_on', 'Fan', None)))
    dev_fan.set_percentage_off(float(config.option(
        'percentage_off', 'Fan', None)))


def setup_mqtt():
    """Define MQTT management."""
    global mqtt
    mqtt = modMQTT.MqttBroker(
        config,
        connect=cbMqtt_on_connect,
        disconnect=cbMqtt_on_disconnect,
        subscribe=cbMqtt_on_subscribe,
        message=cbMqtt_on_message,
    )
    # Last will and testament
    status = iot.get_status(iot.Status.OFFLINE)
    mqtt.lwt(status, Script.lwt, mqtt.GROUP_TOPICS)
    try:
        mqtt.connect(
            username=config.option('username', mqtt.GROUP_BROKER),
            password=config.option('password', mqtt.GROUP_BROKER),
        )
    except Exception as errmsg:
        logger.error(
            'Connection to MQTT broker failed with error: %s',
            errmsg)


def setup_mqtt_filters():
    """Define MQTT topic filters and subscribe to them.

    Notes
    -----
    - The function is called in 'on_connect' callback function after successful
      connection to a MQTT broker.

    """
    mqtt.callback_filters(
        filter_fan=cbMqtt_dev_fan,
    )
    try:
        mqtt.subscribe_filters()
    except Exception as errcode:
        logger.error(
            'MQTT subscribtion to topic filters failed with error code %s',
            errcode)


def setup_timers():
    """Define dictionary of timers."""
    cfg_section = 'Timers'
    # Timer1
    name = 'Timer_mqtt'
    c_period = float(config.option('period_mqtt', cfg_section, 15.0))
    c_period = max(min(c_period, 180.0), 5.0)
    logger.debug('Setup timer %s: period = %ss', name, c_period)
    modTimer.Timer(
        c_period,
        cbTimer_mqtt_reconnect,
        name=name,
    )
    # Timer2
    name = 'Timer_fan'
    c_period = float(config.option('period_fan', cfg_section, 5.0))
    c_period = max(min(c_period, 60.0), 1.0)
    logger.debug('Setup timer %s: period = %ss', name, c_period)
    modTimer.Timer(
        c_period,
        cbTimer_fan,
        name=name,
    )
    # Start all timers
    modTimer.start_all()


def setup():
    """Global initialization."""
    # Print configuration file to the console
    if cmdline.configuration:
        print(config.get_content())
    # Running mode
    msg = \
        f'Script runs as a ' \
        f'{"service" if Script.service else "program"}'
    logger.info(msg)
    # Initially switch off the fan
    pi.pin_off(dev_fan.get_pin())


def loop():
    """Wait for keyboard or system exit."""
    try:
        logger.info('Script loop started')
        while (Script.running):
            time.sleep(0.01)
        logger.warning('Script finished')
    except (KeyboardInterrupt, SystemExit):
        logger.warning('Script cancelled from keyboard')
    finally:
        action_exit()


def main():
    """Fundamental control function."""
    setup_params()
    setup_cmdline()
    setup_logger()
    setup_config()
    setup_pi()
    setup_fan()
    setup_mqtt()
    setup_timers()
    setup()
    loop()


if __name__ == '__main__':
    if modUtils.linux() and not modUtils.root():
        sys.exit('Script must be run as root')
    main()
