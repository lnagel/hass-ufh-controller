# Tasmota Relay Configuration

This guide covers configuring [Tasmota](https://tasmota.github.io/docs/)-flashed relay boards (e.g. ESP32 4CH Pro) to control UFH zone valves. The relay switches are exposed to Home Assistant via MQTT and used as valve entities in the controller.

## Relay Naming

Rename FriendlyName and WebButton to match the zone names they control. This ensures the entities appear with recognizable names in Home Assistant.

```
Backlog
FriendlyName1 Zone1;
FriendlyName2 Zone2;
FriendlyName3 Zone3;
FriendlyName4 Zone4;
```

```
Backlog
WebButton1 Zone1;
WebButton2 Zone2;
WebButton3 Zone3;
WebButton4 Zone4;
```

## Dead-Man-Switch (PulseTime)

Enable PulseTime to automatically turn off relays if no command is received within a timeout. This acts as a safety net — if Home Assistant or the network goes down, the valves will close rather than stay open indefinitely.

Set PulseTime to your observation period plus a margin. For the default 2-hour observation period, 2h 30min works well.

> **Note:** PulseTime values above 111 are interpreted as `(value - 100)` seconds. So `PulseTime 9100` = 9000 seconds = 2h 30min. See the [Tasmota PulseTime documentation](https://tasmota.github.io/docs/Commands/#pulsetime) for details.

```
Backlog
PulseTime1 9100;
PulseTime2 9100;
PulseTime3 9100;
PulseTime4 9100;
```

The controller's force-update mechanism re-sends valve commands at least once per observation period, which keeps the PulseTime from expiring during normal operation.

## Relay Status Reporting

Create a rule that reports relay states on MQTT reconnect and periodically every 20 seconds. This ensures the controller can detect external state changes and stay in sync with the actual relay positions.

```
Rule1
ON system#boot DO
   RuleTimer1 20
ENDON
ON mqtt#connected DO
   Backlog Power1; Power2; Power3; Power4
ENDON
ON rules#timer=1 DO
   Backlog Power1; Power2; Power3; Power4; RuleTimer1 20
ENDON
```

Enable Rule1

```
Rule1 1
```

Start the timer for Rule1

```
RuleTimer1 20
```
