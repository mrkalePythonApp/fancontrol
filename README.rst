fancontrol
**********

Script manages attached fan for cooling the system on the basis of
the system temperature provided by the SoC [1]_. At the same time the script
acts as an MQTT [2]_ client communicating with a MQTT broker, usually a local
one ``mosquitto`` for data exchange within IoT [3]_.

- The script is aimed for Pi microcomputers running as headless servers,
  e.g., ``Raspberry Pi``, ``Orange Pi``, ``Nano Pi``, etc.

- The script runS under ``Python3`` as well as ``Python3`` as it is defined
  by the `shebang`.

- It is recommended to run the **script as a service** of the operating system.

- All relevant parameters for the script are located in the configuration INI
  file. It contains sensitive data as well, like passwords. So that the
  repository contains just the sample INI file with placeholders instead
  of real such as sensitive data. The production INI file should be present
  only and only in some trusted locality with root access, e.g., in the folder
  ``/usr/local/etc`` in order not to be exposed to regular users.

.. [1] System on Chip
.. [2] MQ Telemetry Transport
.. [3] Internet of Things
.. [4] Hyper Text Markup Language
.. [5] Portable Document Format
