# Home Assistant Add-on: AC Pro Thermostat

This add-on bridges the AC Pro X/XB-Series smart communicating touchscreen
control to Home Assistant over your own network, and publishes it as a
climate device through MQTT discovery.

## Supported hardware

| | |
| --- | --- |
| AC Pro SKU | 85432 — *X Series and XB Series Air Handler Wi-Fi Touchscreen Control OEM* |
| OEM model | WK-010WD1 |
| Fitted to | AC Pro X-Series and XB-Series air handlers |
| Vendor apps | Kinghome Plus / Gree+ (not needed once this add-on runs) |

The panel is a Gree-family Wi-Fi module. It listens for JSON datagrams on
UDP port 7000 and answers on the source port, with the payload encrypted
under either AES-128-ECB (older firmware) or AES-128-GCM (newer firmware).
The add-on detects which of the two your panel speaks.

Other controls in the same family — the non-Wi-Fi WK-010WC1 excepted, since
it has no network at all — generally work too. If the panel answers
discovery, the add-on will bridge whatever functions it reports.

### Checking you have the right panel

AC Pro sells equipment from more than one manufacturer, and their thermostats
are not all the same underneath. This add-on speaks the Gree-family protocol,
which is the one the WK-010WD1 uses. The quickest check is which app the panel
was commissioned with:

| Vendor app | Protocol | Supported here |
| --- | --- | --- |
| Kinghome Plus, Gree+ | Gree family, UDP 7000 | Yes |
| NetHome Plus, SmartHome | Midea family, UDP 6444 | No |

If the add-on finds nothing and the panel pairs with NetHome Plus, it is a
Midea-family module and needs a different bridge — please open an issue with
the panel's model number so support can be added.

## Before you start

1. Commission the panel through the vendor app once, so it joins your Wi-Fi.
   After that the app is optional; the add-on does not need the account.
2. Give the panel a DHCP reservation. Discovery copes with an address change,
   but a fixed address makes the logs easier to follow.
3. Install and start the **Mosquitto broker** add-on, and set up Home
   Assistant's MQTT integration. This add-on picks the broker credentials up
   from the Supervisor automatically.

The add-on runs on the host network, because discovery is a UDP broadcast and
the add-on bridge network would not carry it to your LAN.

## Installation

1. Settings → Add-ons → Add-on Store → ⋮ → Repositories, and add
   `https://github.com/Cdower/hassio-addons`.
2. Install **AC Pro Thermostat**.
3. Start it, and open the log. A healthy start looks like this:

   ```text
   Starting the AC Pro thermostat bridge
   Looking for the control via 255.255.255.255
   Using control 502cc6aabbcc at 192.168.1.50 (model 'WK-010WD1', ...)
   Bound to control 502cc6aabbcc at 192.168.1.50
   Control 502cc6aabbcc supports 8 of 20 known properties: Pow, Mod, SetTem, ...
   Connected to MQTT broker
   ```

4. The thermostat shows up under Settings → Devices & Services → MQTT.

## Configuration

Every option is optional; the defaults suit a single panel on a flat network.

```yaml
device_host: ""
device_name: ""
broadcast_address: 255.255.255.255
scan_interval: 30
encryption_version: 0
extra_properties: []
ignored_properties: []
log_level: info
```

### Finding the panel

#### Option: `device_host`

The panel's IP address. Leave empty to discover it by broadcast. Set it when
you have more than one panel, or when Home Assistant is on a different subnet
or VLAN from the thermostat and broadcasts are not forwarded.

#### Option: `device_port`

The UDP port the panel listens on. Defaults to `7000`; there is no reason to
change it.

#### Option: `broadcast_address`

The broadcast address discovery is sent to. Defaults to `255.255.255.255`.
Some networks drop the global broadcast but pass a subnet-directed one, in
which case set it to your subnet's broadcast address, such as
`192.168.1.255`. Ignored when `device_host` is set.

#### Option: `device_name`

Overrides the name Home Assistant shows. Defaults to the name set on the
panel itself, falling back to `AC Pro <last six of the MAC>`.

#### Option: `encryption_version`

`0` (default) detects the panel's encryption scheme from its discovery reply.
Set `1` for AES-ECB or `2` for AES-GCM only if detection picks the wrong one —
a few firmware revisions answer discovery under one scheme and then expect the
other for the session that follows.

### Behaviour

#### Option: `scan_interval`

Seconds between reads of the panel. Defaults to `30`; the accepted range is
5 to 3600. Commands are applied the moment they arrive and are followed by an
immediate read, so a short interval is not needed for a responsive dashboard.

#### Option: `request_timeout`

Seconds to wait for a reply before retrying. Defaults to `2`. Raise it on a
weak Wi-Fi link where the log shows repeated `No usable reply` warnings.

#### Option: `extra_properties`

Extra protocol columns to ask the panel for, on top of the ones the add-on
knows about. Only useful when working out what an unusual panel exposes; see
*Adding an unknown function* below.

#### Option: `ignored_properties`

Columns to leave alone, by protocol name — for example `["SwUpDn",
"SwingLfRig"]` to drop louvre switches on an air handler that reports them
but has no louvres.

### MQTT

Leave all of these empty to use the broker the Supervisor provides, which is
what the Mosquitto add-on sets up. Anything you do set overrides it, so an
external broker can be used without disabling Mosquitto.

| Option | Meaning |
| --- | --- |
| `mqtt_host` | Broker hostname or IP |
| `mqtt_port` | Broker port, default `1883` |
| `mqtt_username` | Broker username |
| `mqtt_password` | Broker password |
| `mqtt_ssl` | Connect with TLS |
| `mqtt_discovery_prefix` | Discovery prefix, default `homeassistant` |
| `mqtt_topic_prefix` | State and command topic prefix, default `acpro` |

#### Option: `log_level`

`trace`, `debug`, `info` (default), `notice`, `warning`, `error`, or `fatal`.
Use `debug` to see each datagram exchange when diagnosing a connection.

## Entities

The panel is asked at start-up which functions it has, and only those become
entities. A typical air handler control produces:

| Entity | From | Notes |
| --- | --- | --- |
| `climate.*` | `Pow`, `Mod`, `SetTem` | Off / heat / cool / auto / dry / fan only |
| `sensor.*_indoor_temperature` | `TemSen` | Always in °C; Home Assistant converts for display |
| `switch.*_auxiliary_heat` | `StHt` | Supplementary electric heat |
| `switch.*_display` | `Lig` | Panel backlight |

Fan speed, presets, and any further switches appear when the panel reports
the matching columns. The log line beginning `Control ... supports` lists
exactly what was found.

### Temperature scale

The setpoint follows the scale the panel itself is displaying. When the panel
is in Fahrenheit the protocol stores the setpoint as whole degrees Celsius
plus a half-step flag, and the add-on converts between the two so that a
value set in Home Assistant comes back unchanged. Change the scale on the
panel and the add-on republishes its discovery configuration to match.

The indoor temperature sensor is always published in Celsius and left to
Home Assistant to convert, so its history stays consistent across a scale
change.

### What is deliberately not published

There is no `hvac_action` attribute. The protocol reports the *commanded*
mode, not whether the compressor or heat strip is actually energised, and a
guess dressed up as a reading would be worse than nothing. Use the panel's
own display, or a current sensor on the air handler, if you need to know
whether the system is running.

## How start-up works

On its first run the add-on discovers the panel, pairs with it, and asks it
about each function it might have. Panels that ignore a request naming a
column they do not have make that last step slow, so the pairing key and the
list of supported functions are cached in the add-on's own storage. Later
restarts reuse both and come up immediately.

The cache is discarded automatically when it stops working — the panel was
re-paired, or was reset — and whenever `extra_properties` or
`ignored_properties` changes, so editing those re-probes rather than quietly
keeping the previous answer.

## Troubleshooting

### "No AC Pro control answered"

- Confirm the panel is on Wi-Fi: it should be reachable by ping.
- Home Assistant and the panel must be on the same network segment for the
  broadcast to arrive. If they are not, set `device_host`.
- Some access points block client-to-client traffic ("AP isolation" or
  "client isolation"). Turn it off for the thermostat's SSID.
- Try `broadcast_address` set to your subnet's broadcast address.

### "No MQTT broker configured"

Install and start the Mosquitto broker add-on, or set `mqtt_host` and its
credentials manually.

### The panel is found but binding fails

Set `encryption_version` to `1`, then `2`, restarting between the two. If
neither works, the panel may still be held by the vendor app on another
device — some firmware allows only one bound controller at a time. Reset the
panel's Wi-Fi (Function → User Setup → Wi-Fi Reset), re-commission it, and
start the add-on again.

### Entities go unavailable now and then

The add-on marks the device unavailable after three consecutive failed reads
and recovers on its own. Persistent flapping usually means a weak Wi-Fi
signal at the panel; raise `request_timeout` and check the access point.

### Adding an unknown function

Set `log_level` to `debug` and add candidate protocol column names to
`extra_properties`. Columns the panel accepts appear in the `supports` line
at start-up and in the state topic; ones it rejects are dropped. Please open
an issue with what you find so it can be supported properly.

## Removing the add-on

Uninstalling leaves the retained MQTT discovery messages behind, so the
entities linger. Delete the device from Settings → Devices & Services → MQTT
before uninstalling, or clear the retained topics under
`homeassistant/+/acpro_<mac>/`.
