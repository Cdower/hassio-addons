# Tempur-Pedic Sleeptracker

A Home Assistant integration for Tempur-Pedic Ergo smart bases with the
Sleeptracker-AI G2 processor (product `SleepTracker Gen2`, model `sts60`). It
controls the bed frame and brings in the room-environment readings and the
nightly sleep summaries the Tempur Sleeptracker app shows.

## How it talks to the bed

The processor in the bed has **no local API**. Its only open TCP port is 5355,
an LLMNR responder (Link-Local Multicast Name Resolution, as run by
systemd-resolved): it answers name lookups for the bed's own hostname and
nothing else. The `_sleeptracker._tcp` mDNS record it advertises points at
port 0 with
`server=incoming.tsi.sleeptracker.com`. The app goes through the
Sleeptracker cloud, and so does this integration:

| What | Endpoint |
| --- | --- |
| Login | `auth.tsi.sleeptracker.com/v1/app/user/session` (email and password, HTTP Basic) |
| Devices, environment, bed commands and status | `app.tsi.sleeptracker.com/actrack-client/v2/fpcsiot/...` |
| Snore-relief settings | `.../fpcsiot/settings/getSnoreRelief`, `setSnoreRelief` |
| Nightly sleep summaries | `portal.tsi.sleeptracker.com/api/downloadAccountData` (ZIP, one JSON file per night) |

The API is undocumented and could change if the app changes. Endpoints and
command codes come from the Android app, as recorded by
[smartbed-mqtt](https://github.com/richardhopton/smartbed-mqtt) and
[sleeptracker-influx](https://github.com/gavinmcfall/sleeptracker-influx), and
were checked against a 2023 Ergo Smart (king, single controller).

## Installation

With [HACS](https://hacs.xyz): add `https://github.com/Cdower/hassio-addons` as
a custom repository of type *Integration*, install **Tempur-Pedic
Sleeptracker**, and restart Home Assistant.

By hand: copy `custom_components/sleeptracker` into your Home Assistant
`config/custom_components/` folder and restart.

Then go to **Settings → Devices & services → Add integration →
Tempur-Pedic Sleeptracker** and sign in with your Tempur Sleeptracker app
account.

## What you get

Entities are created only for hardware the base reports in its capability
roster. For example, there is no head-tilt cover on a base without a tilt
motor.

**Bed device** (named as in the app, for example "Bedroom")

| Platform | Entities |
| --- | --- |
| Light | Under-bed light |
| Cover | Head, Foot, Lumbar, Head tilt: open raises, close lowers, stop halts. Attributes give the motor pulse count and, for head and foot, the angle. |
| Button | Presets: Flat, Zero G, TV, Anti-snore, Favorite. Save position to Zero G / TV / Anti-snore / Favorite (config). Massage: head level, foot level, overall level, pattern, timer. |
| Switch | Snore relief: tilt, Snore relief: vibration (config) |
| Sensor | Head angle, foot angle, lumbar and tilt position, head/foot massage strength, massage pattern, massage time left, last movement; room temperature, humidity, CO2, VOC, air-quality index; Wi-Fi signal and RSSI, last cloud check-in, last sleep upload (diagnostic) |
| Binary sensor | Massage running, moving, panel light (disabled by default); frame connected, cloud connected, left/right sleep sensor connected (diagnostic) |

**Sleep device** (one per account, named after the bed, for example "Bedroom
sleep")

Sensors for the most recent night: sleep score, night (date), total / deep /
light / REM sleep, awake time, time out of bed, sleep efficiency, sleep goal
reached, wake-ups, times out of bed, average heart rate, average respiration
rate, HRV (RMSSD and SDNN), arousal index, breathing disturbance, bedtime,
fell asleep, wake time. The sleep score sensor also carries the night's stage
timeline (`stages`) and events (`events`) as attributes. These are kept out of
the recorder.

**Long-term statistics.** Every night the portal holds, back to the bed's
first recording, is imported as external statistics named
`sleeptracker:bed<bed ID>_side<side>_<metric>`: sleep score, total / deep / light / REM
sleep, awake time, efficiency, wake-ups, heart rate, respiration rate, HRV.
Add them to a *Statistics graph* card to chart sleep trends over months.

## Commands without an entity

The `sleeptracker.send_command` action sends any `bedControlCommand` code and
returns the cloud's reply, which includes the frame's status snapshot:

```yaml
action: sleeptracker.send_command
data:
  config_entry_id: <your entry>
  command: 7          # PresetSnore1
response_variable: reply
```

Known codes (from the app): presets 0 Zero G, 2 Flat, 3 TV, 4 Anti-snore,
6 Favorite, 7/8 Snore 1/2; save position 300 TV, 302 Anti-snore,
303 Zero G, 304 Favorite; motors 100/101/107 head up/down/stop, 102/103/108
foot, 104/105/106 lumbar, 120/121/122 tilt; massage 210 head step, 211 foot
step (both sent with `{"massageAdjustment": 1, "requestStatus": true}`),
225 overall step, 226 pattern step, 231 timer step; 230 toggles the light;
1 reads status.

## Options

* **Control the bed frame from this account.** Partners usually each have
  an account on the same bed. Add both to get both people's sleep data, and
  turn this off for one of them so the frame's controls are created only once.
  On a split base (two controllers) the cloud should route each account's
  commands to that account's side. That follows how smartbed-mqtt handles
  split bases; the base this was tested on has a single controller.
* **Bed status polling interval** (default 60 s). After a motor or preset
  command, status is also polled every few seconds until the frame stops.
* **Sleep data download interval** (default 60 min). Each download is the
  account's whole history (about 1 MB for a year) and takes around 10 s.

## Notes and limits

* Only the account's own side has sleep data. The partner's side needs the
  partner's account.
* Sleep summaries appear once the processor uploads the night, usually soon
  after you get up.
* Covers have no "set position": the cloud has no move-to-position command.
  Use the presets, or open/close then stop.
* The light, presets and massage use the cloud's toggle and step commands. The
  integration reads back the state the bed reports after each command.
* Diagnostics (**Download diagnostics** on the integration) redact the email,
  password, serial numbers, MAC addresses and user IDs.
