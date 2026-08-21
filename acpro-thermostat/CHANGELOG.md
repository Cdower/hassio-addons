# Changelog

## 1.0.0

First release.

- Discovers the AC Pro X/XB-Series smart communicating control (SKU 85432,
  OEM model WK-010WD1) on the local network and pairs with it, with no cloud
  account or vendor app involved.
- Speaks both encryption schemes used by the panel's firmware (AES-128-ECB
  and AES-128-GCM) and detects which one is in use.
- Asks the panel which functions it has and publishes only those, as a
  `climate` entity plus a temperature sensor and switches, over MQTT
  discovery.
- Converts setpoints between the protocol's Celsius-plus-half-step encoding
  and the scale the panel displays, and republishes discovery when that scale
  changes.
- Reads the broker details from the Supervisor's MQTT service, with manual
  overrides for an external broker.
- Marks entities unavailable after repeated failed reads, and rediscovers the
  panel if it stops answering.
