#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cooling fan manageer and MQTT client.

Script provides following functionalities:

- Script manages a fan attached to a GPIO pin for cooling the system
  on the basis of the system temperature provided by the SoC.
- Script acts as a MQTT client utilizing local MQTT broker ``mosquitto``
  for data exchange with outside environment.
- Script publishes system temperature, configuration fata, and fan status
  to the ``local MQTT broker``.
- Script can receive commands from `local MQTT broker` in order to change its
  behaviour during running, e.g., turn on or off the fan, change fan trigger
  temperatures, etc.

"""
__version__ = "0.1.0"
__status__ = "Development"
__author__ = "Libor Gabaj"
__copyright__ = "Copyright 2019, " + __author__
__credits__ = [__author__]
__license__ = "MIT"
__maintainer__ = __author__
__email__ = "libor.gabaj@gmail.com"

# Standard library modules
import time
import os
import os.path
import sys
import argparse
import logging
# Third party modules
import gbj_pythonlib_sw.config as modConfig
import gbj_pythonlib_sw.mqtt as modMQTT
import gbj_pythonlib_sw.statfilter as modFilter
import gbj_pythonlib_sw.timer as modTimer
import gbj_pythonlib_sw.trigger as modTrigger
import gbj_pythonlib_hw.orangepi as modOrangePi


###############################################################################
# Script constants - General states and MQTT commands
###############################################################################
ON = "ON"
OFF = "OFF"
TOGGLE = "TOGGLE"
RESET = "RESET"


###############################################################################
# Script constants - Fan MQTT commands and maps
###############################################################################
CMD_FAN_ON = ON
CMD_FAN_OFF = OFF
CMD_FAN_TOGGLE = TOGGLE
CMD_FAN_PERCON = "PERCON"  # Percentage of maximal temperature for fan on
CMD_FAN_PERCOFF = "PERCOFF"  # Percentage of maximal temperature for fan off
STATE_FAN_ON = ON
STATE_FAN_OFF = OFF


###############################################################################
# Script global variables
###############################################################################
script_run = True  # Flag about running script in a loop
cmdline = None  # Object with command line arguments
logger = None  # Object with standard logging
trigger = None  # Object with triggers
filter = None  # Object with statistical smoothing and filtering
config = None  # Object with MQTT configuration file processing
mqtt = None  # Object for MQTT broker manipulation
pi = None  # Object with OrangePi GPIO control


###############################################################################
# General actions
###############################################################################
def action_fan(command, value=None):
    """Perform command for the fan.

    Arguments
    ---------
    command : str
        Action name to be realized.
    value
        Any value that the action should be realized with.

    """
    # Controlling fan
    if command in [CMD_FAN_ON, CMD_FAN_OFF, CMD_FAN_TOGGLE]:
        # Suppress publishing useless command, i.e., the command changes pin
        # state that it already has been.
        try:
            if command == CMD_FAN_TOGGLE:
                if pi.is_pin_on(pi.PIN_FAN):
                    command = CMD_FAN_OFF
                else:
                    command = CMD_FAN_ON
            if command == CMD_FAN_ON:
                if pi.is_pin_on(pi.PIN_FAN):
                    return
                pi.pin_on(pi.PIN_FAN)
            elif command == CMD_FAN_OFF:
                if pi.is_pin_off(pi.PIN_FAN):
                    return
                pi.pin_off(pi.PIN_FAN)
            else:
                return
            logger.info("Fan set to %s", command)
        except Exception as errmsg:
            logger.error("Fan command %s failed: %s", command, errmsg)
        # Publishing action
        mqtt_publish_fan_status()
    # Updating fan temperature percentage ON
    if command == CMD_FAN_PERCON:
        try:
            value = abs(float(value))
            setup_trigger_fan(fan_perc_on=value)
            logger.info("Updated fan percentage ON=%s%%", value)
            mqtt_publish_fan_percon()
        except Exception:
            logger.error("Fan command %s failed", command)
    # Updating fan temperature percentage OFF
    if command == CMD_FAN_PERCOFF:
        try:
            value = abs(float(value))
            setup_trigger_fan(fan_perc_off=value)
            logger.info("Updated fan percentage OFF=%s%%", value)
            mqtt_publish_fan_percoff()
        except Exception:
            logger.error("Fan command %s failed", command)
    # Setting fan temperature percentages to default values
    if command == RESET:
        setup_trigger_fan(
            fan_perc_on=pi.FAN_PERC_ON_DEF,
            fan_perc_off=pi.FAN_PERC_OFF_DEF,
        )
        logger.info("Reset fan limits to defaults")
        mqtt_publish_fan_limits()


def action_script(command):
    """Perform command for this script itself.

    Arguments
    ---------
    command : str
        Received command to be realized: ``{"EXIT"}``.

    """
    # Stop script
    if command == "EXIT":
        global script_run
        script_run = False


###############################################################################
# MQTT actions
###############################################################################
def mqtt_publish_temp():
    """Publish SoC temperature to a MQTT topic."""
    if not mqtt.get_connected():
        return
    message = filter.result()
    option = "fan_data_temp"
    section = mqtt.GROUP_TOPICS
    try:
        mqtt.publish(message, option, section)
        logger.debug(
            "Published temperature %s°C to MQTT topic %s",
            filter.result(), mqtt.topic_name(option, section))
    except Exception as errmsg:
        logger.error(
            "Temperature publishing to MQTT topic option %s:[%s] failed: %s",
            option, section, errmsg)


def mqtt_publish_fan_status():
    """Publish fan status to the MQTT status topic."""
    if not mqtt.get_connected():
        return
    cfg_option = "fan_status_control"
    cfg_section = mqtt.GROUP_TOPICS
    if pi.is_pin_on(pi.PIN_FAN):
        message = STATE_FAN_ON
    else:
        message = STATE_FAN_OFF
    try:
        mqtt.publish(message, cfg_option, cfg_section)
        logger.debug(
            "Published fan status %s to MQTT topic %s",
            message, mqtt.topic_name(cfg_option, cfg_section),
        )
    except Exception as errmsg:
        logger.error(
            "Publishing fan status %s to MQTT topic %s failed: %s",
            message,
            mqtt.topic_name(cfg_option, cfg_section),
            errmsg,
        )


def mqtt_publish_fan_percon():
    """Publish fan temperature percentage ON to the MQTT status topic."""
    if not mqtt.get_connected():
        return
    cfg_option = "fan_status_percon"
    cfg_section = mqtt.GROUP_TOPICS
    try:
        mqtt.publish(str(pi.FAN_PERC_ON_CUR), cfg_option, cfg_section)
        logger.debug(
            "Published fan percentage ON=%s%% to MQTT topic %s",
            pi.FAN_PERC_ON_CUR, mqtt.topic_name(cfg_option, cfg_section))
    except Exception as errmsg:
        logger.error(
            "Publishing fan percentage ON=%s%% to MQTT topic %s failed: %s",
            pi.FAN_PERC_ON_CUR, mqtt.topic_name(cfg_option, cfg_section),
            errmsg)


def mqtt_publish_fan_percoff():
    """Publish fan temperature percentage OFF to the MQTT status topic."""
    if not mqtt.get_connected():
        return
    cfg_option = "fan_status_percoff"
    cfg_section = mqtt.GROUP_TOPICS
    try:
        mqtt.publish(str(pi.FAN_PERC_OFF_CUR), cfg_option, cfg_section)
        logger.debug(
            "Published fan percentage OFF=%s%% to MQTT topic %s",
            pi.FAN_PERC_OFF_CUR, mqtt.topic_name(cfg_option, cfg_section))
    except Exception as errmsg:
        logger.error(
            "Publishing fan percentage OFF=%s%% to MQTT topic %s failed: %s",
            pi.FAN_PERC_OFF_CUR, mqtt.topic_name(cfg_option, cfg_section),
            errmsg)


def mqtt_publish_fan_limits():
    """Publish fan temperature percentages to the MQTT status topic."""
    mqtt_publish_fan_percon()
    mqtt_publish_fan_percoff()


def mqtt_message_log(message):
    """Log receiving from a MQTT topic.

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
    logger.debug(
        "Message from MQTT topic %s with qos %s and retain %s",
        message.topic, message.qos, message.retain)
    if message.payload is None:
        return False
    logger.debug("%s: %s", sys._getframe(1).f_code.co_name,
                 message.payload.decode("utf-8"))
    return True


###############################################################################
# Callback functions
###############################################################################
def cbTimer_temp_measure(*arg, **kwargs):
    """Measure current CPU temperature."""
    exec_last = kwargs.pop("exec_last", False)
    logger.debug(
        "Measured temperature %s°C",
        filter.result(pi.measure_temperature())
    )
    if exec_last:
        # global script_run
        # script_run = False
        pass


def cbTimer_temp_publish(*arg, **kwargs):
    """Publish current CPU temperature."""
    logger.debug(
        "Published temperature %s°C",
        filter.result()
    )
    mqtt_publish_temp()


def cbTimer_temp_triggers(*arg, **kwargs):
    """Execute CPU temperature triggers."""
    trigger.exec_triggers(filter.result(), ids=["fanon", "fanoff"])


def cbTrigger_fan(*args, **kwargs):
    """Execute command for the fan."""
    command = kwargs.pop("cmd", None)
    if command is None:
        return
    action_fan(command)


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
        logger.debug("Connected to %s: %s", str(mqtt), userdata)
        setup_mqtt_filters()
        mqtt_publish_fan_status()
        mqtt_publish_fan_limits()
    else:
        logger.error("Connection to MQTT broker failed: %s (rc = %d)",
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
    logger.warning("Disconnected from %s: %s (rc = %d)",
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
    # logger.debug("Subscribed to MQTT topic with message id %d", mid)
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


def cbMqtt_on_message_data(client, userdata, message):
    """Process server data send through a MQTT topic(s).

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    message : MQTTMessage object
        The object with members `topic`, `payload`, `qos`, `retain`.

    """
    if not mqtt_message_log(message):
        return
    # CPU Temperature
    if message.topic == mqtt.topic_name("fan_data_temp"):
        value = float(message.payload)
        logger.debug("Received temperature %s°C", value)
    # Unexpected data
    else:
        logger.warning(
            "Received unknown data %s from topic %s",
            message.payload.decode("utf-8"), message.topic)


def cbMqtt_on_message_command(client, userdata, message):
    """Process server command at receiving a message from the command topic(s).

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
    # Command
    command = message.payload.decode("utf-8")
    if message.topic == mqtt.topic_name("mqtt_topic_fan_command"):
        logger.debug(
            "Received general command %s from topic %s",
            command, message.topic)
        action_script(command)
    # Fan control
    elif message.topic == mqtt.topic_name("fan_command_control"):
        logger.debug(
            "Received fan command %s from topic %s",
            command, message.topic)
        action_fan(command)
    elif message.topic in [mqtt.topic_name("fan_command_percon"),
                           mqtt.topic_name("fan_command_percoff"),
                           ]:
        command = message.topic.split("/").pop().upper()
        logger.debug(
            "Received fan command %s with value %s from topic %s",
            command, message.payload.decode("utf-8"), message.topic)
        action_fan(command, message.payload.decode("utf-8"))
    # Unexpected data
    else:
        logger.warning(
            "Received unknown command %s from topic %s",
            message.payload.decode("utf-8"), message.topic)


###############################################################################
# Setup functions
###############################################################################
def setup_cmdline():
    """Define command line arguments."""
    config_file = os.path.splitext(os.path.abspath(__file__))[0] + ".ini"
    log_folder = "/var/log"

    parser = argparse.ArgumentParser(
        description="Cooling fan manager and MQTT client, version "
        + __version__
    )
    # Position arguments
    parser.add_argument(
        "config",
        type=argparse.FileType("r"),
        nargs="?",
        default=config_file,
        help="Configuration INI file, default: " + config_file
    )
    # Options
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=__version__,
        help="Current version of the script."
    )
    parser.add_argument(
        "-v", "--verbose",
        choices=["debug", "warning", "info", "error", "critical"],
        default="warning",
        help="Level of logging to the console."
    )
    parser.add_argument(
        "-l", "--loglevel",
        choices=["debug", "warning", "info", "error", "critical"],
        default="debug",
        help="Level of logging to a log file."
    )
    parser.add_argument(
        "-d", "--logdir",
        default=log_folder,
        help="Folder of a log file, default " + log_folder
    )
    parser.add_argument(
        "-c", "--configuration",
        action="store_true",
        help="""Print configuration parameters in form of INI file content."""
    )
    # Process command line arguments
    global cmdline
    cmdline = parser.parse_args()


def setup_logger():
    """Configure logging facility."""
    global logger
    # Set logging to file for module and script logging
    log_file = "/".join([cmdline.logdir, os.path.basename(__file__) + ".log"])
    logging.basicConfig(
        level=getattr(logging, cmdline.loglevel.upper()),
        format="%(asctime)s - %(levelname)-8s - %(name)s: %(message)s",
        filename=log_file,
        filemode="w"
    )
    # Set console logging
    formatter = logging.Formatter(
        "%(levelname)-8s - %(name)-20s: %(message)s")
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, cmdline.verbose.upper()))
    console_handler.setFormatter(formatter)
    logger = logging.getLogger("{} {}".format(
        os.path.basename(__file__), __version__))
    logger.addHandler(console_handler)
    logger.warning("Script started from file %s", os.path.abspath(__file__))


def setup_config():
    """Define configuration file management."""
    global config
    config = modConfig.Config(cmdline.config)


def setup_pi():
    """Define GPIO control.

    Notes
    -----
    - Operational pin names are stored in the object as attributes.
    - Default fan percentage limits are stored in the object as attributes.

    """
    global pi
    pi = modOrangePi.OrangePiOne()
    pi.PIN_FAN = config.option("pin_fan_name", "Fan")
    # pi.PIN_LED = config.option("pin_led_name", "Fan")
    # Temperature percentage for fan ON
    pi.FAN_PERC_ON_DEF = abs(float(config.option(
        "percentage_maxtemp_on", "Fan", 85.0)))
    pi.FAN_PERC_ON_MIN = 80.0
    pi.FAN_PERC_ON_MAX = 95.0
    pi.FAN_PERC_ON_CUR = pi.FAN_PERC_ON_DEF
    # Temperature percentage for fan OFF
    pi.FAN_PERC_OFF_DEF = abs(float(config.option(
        "percentage_maxtemp_off", "Fan", 75.0)))
    pi.FAN_PERC_OFF_MIN = 60.0
    pi.FAN_PERC_OFF_MAX = 75.0
    pi.FAN_PERC_OFF_CUR = pi.FAN_PERC_OFF_DEF


def setup_mqtt():
    """Define MQTT management."""
    global mqtt
    mqtt = modMQTT.MqttBroker(config)
    mqtt.connect(
        username=config.option("username", mqtt.GROUP_BROKER),
        password=config.option("password", mqtt.GROUP_BROKER),
        connect=cbMqtt_on_connect,
        disconnect=cbMqtt_on_disconnect,
        subscribe=cbMqtt_on_subscribe,
        message=cbMqtt_on_message,
    )


def setup_mqtt_filters():
    """Define MQTT topic filters and subscribe to them.

    Notes
    -----
    - The function is called in 'on_connect' callback function after successful
      connection to a MQTT broker.

    """
    mqtt.callback_filters(
        fan_filter_data=cbMqtt_on_message_data,
        fan_filter_command=cbMqtt_on_message_command,
    )
    try:
        mqtt.subscribe_filters()
    except Exception as errcode:
        logger.error(
            "MQTT subscribtion to topic filters failed with error code %s",
            errcode)


def setup_filter():
    """Define statistical smoothing and filtering."""
    global filter
    filter = modFilter.StatFilterExponential(
        decimals=3,
        factor=0.2
    )


def setup_trigger():
    """Define triggers for evaluating value limits."""
    global trigger
    trigger = modTrigger.Trigger()
    setup_trigger_fan()


def setup_trigger_fan(fan_perc_on=None, fan_perc_off=None):
    """Define triggers for controlling fan by SoC temperature.

    Arguments
    ---------
    fan_perc_on : float
        Percentage of maximal temperature for turning fan on.
    fan_perc_off : float
        Percentage of maximal temperature for turning fan off.

    """
    # Sanitize parameters
    pi.FAN_PERC_ON_CUR = max(min(float(fan_perc_on or pi.FAN_PERC_ON_CUR),
                                 pi.FAN_PERC_ON_MAX),
                             pi.FAN_PERC_ON_MIN)
    pi.FAN_PERC_OFF_CUR = max(min(float(fan_perc_off or pi.FAN_PERC_OFF_CUR),
                                  pi.FAN_PERC_OFF_MAX),
                              pi.FAN_PERC_OFF_MIN)
    if pi.FAN_PERC_OFF_CUR > pi.FAN_PERC_ON_CUR:
        pi.FAN_PERC_OFF_CUR, pi.FAN_PERC_ON_CUR \
            = pi.FAN_PERC_ON_CUR, pi.FAN_PERC_OFF_CUR
    # Set triggers
    logger.debug(
        "Setup fan triggers: %s = %s%%, %s = %s%%",
        ON, pi.FAN_PERC_ON_CUR,
        OFF, pi.FAN_PERC_OFF_CUR)
    trigger.set_trigger(
        id="fanon",
        mode=modTrigger.UPPER,
        value=pi.convert_percentage_temperature(pi.FAN_PERC_ON_CUR),
        callback=cbTrigger_fan,
        cmd=CMD_FAN_ON,     # Arguments to callback
    )
    trigger.set_trigger(
        id="fanoff",
        mode=modTrigger.LOWER,
        value=pi.convert_percentage_temperature(pi.FAN_PERC_OFF_CUR),
        callback=cbTrigger_fan,
        cmd=CMD_FAN_OFF,     # Arguments to callback
    )


def setup_timers():
    """Define dictionary of timers."""
    # Timer 01
    name = "Timer_temp"
    cfg_section = "TimerTemperature"
    # Measurement period
    c_period = float(config.option("period_measure", cfg_section, 5.0))
    c_period = max(min(c_period, 60.0), 1.0)
    # Publishing prescale
    c_publish = int(config.option("prescale_publish", cfg_section, 3))
    c_publish = max(min(c_publish, 10), 1)
    # Trigger evaluation prescale
    c_triggers = int(config.option("prescale_triggers", cfg_section, 6))
    c_triggers = max(min(c_triggers, 1000), 1)
    logger.debug(
        "Setup timer %s: period = %ss, publish = %sx, triggers = %sx",
        name, c_period, c_publish, c_triggers)
    # Definition
    timer1 = modTimer.Timer(
        c_period,
        cbTimer_temp_measure,
        name=name,
        # count=9,
    )
    timer1.prescaler(c_publish, cbTimer_temp_publish)
    timer1.prescaler(c_triggers, cbTimer_temp_triggers)
    modTimer.register_timer(name, timer1)
    # Start all timers
    modTimer.start_timers()


def setup():
    """Global initialization."""
    # Print configuration file to the console
    if cmdline.configuration:
        print(config.get_content())


def loop():
    """Wait for keyboard or system exit."""
    try:
        logger.info("Script loop started")
        while (script_run):
            time.sleep(1)
        logger.warning("Script finished")
    except (KeyboardInterrupt, SystemExit):
        logger.warning("Script cancelled")
    finally:
        modTimer.stop_timers()


def main():
    """Fundamental control function."""
    setup_cmdline()
    setup_logger()
    setup_config()
    setup_pi()
    setup_mqtt()
    setup_filter()
    setup_trigger()
    setup_timers()
    setup()
    loop()


if __name__ == "__main__":
    if os.getegid() != 0:
        sys.exit('Script must be run as root')
    main()
