# Z-Wave Alarm for Home Assistant

Custom component for the [Z-Wave Alarm service](https://github.com/judeibe/zwave_alarm). Install through [HACS](https://hacs.xyz) as a custom repository (category: Integration) or copy `custom_components/zwave_alarm` into your Home Assistant config directory.

It talks to the service through the [`zwave-alarm-client`](https://github.com/judeibe/zwave-alarm-client) package (installed automatically from PyPI via `manifest.json`), so client fixes ship without a component change.

**Testing:** `pip install -r requirements-test.txt && pytest` (Python 3.13). `tests/test_integration.py` boots a real Home Assistant against a fake service (REST + WebSocket); the `*_state.py` modules hold the pure logic and are also unit tested without Home Assistant. HTTP client tests live in the client repo.

**Releases:** versions are produced by [semantic-release](https://semantic-release.gitbook.io) from [Conventional Commits](https://www.conventionalcommits.org) pushed to `main` (`fix:` is a patch, `feat:` a minor, `!` or `BREAKING CHANGE:` a major). The release job rewrites `custom_components/zwave_alarm/manifest.json` with the new version, commits it as `chore(release): vX.Y.Z [skip ci]`, and tags and publishes the GitHub release. Never edit the manifest version by hand; the checked-in `1.0.0` is only the baseline until the first release.

## Entities

| Entity | Purpose |
|---|---|
| `alarm_control_panel.zwave_alarm` | Arm away/home and disarm (code required). Attributes: `armed_mode`, `pending_delay_ends_at`, `disarmed_zones`, `triggered_by_zone`, `triggered_by_sensor_id`. |
| `binary_sensor.zwave_alarm_zone_<zone>` | `on` while any sensor in the zone is breached; one per zone, including zones added after setup. Attributes: `sensors` (name, category, state) and `disarmed` (a zone-restricted guest disarmed this zone, FR-010a). |
| `sensor.zwave_alarm_fault_count` | Sensors offline or low on battery; attribute `sensors` lists each with its zone and reason. |
| `event.zwave_alarm_security_events` | One event per `SecurityEvent` the service records (`armed`, `disarmed`, `breach`, `alarm_triggered`, `alarm_cleared`, `device_fault`, `lockout`, `guest_code_used`), with `details` such as "Cleared by Owner". |

Each keypad the service discovers (for example a Ring Keypad v2) becomes its own device with these entities, kept live by `keypad.changed` and the snapshot:

| Entity | Purpose |
|---|---|
| `event.<keypad>_keypad_input` | One event per button press: `code_entered`, `arm_away`, `arm_home`, `disarm`, `cancel` or `emergency` (attribute `emergency`: `fire`, `police` or `medical`). The entered code is never exposed. Unknown kinds are ignored. |
| `binary_sensor.<keypad>_connectivity` | `on` while the keypad is online. |
| `sensor.<keypad>_battery` | Battery percentage; `unknown` when the keypad doesn't report one. |

The `zwave_alarm.keypad_chime` action plays a chime on the targeted keypad device (or one of its entities) with a `sound` and an optional `volume` from 0 to 99. It needs `zwave-alarm-client` 0.3.0 or later; with an older library the integration still loads and only this action reports the missing support.

All entities go `unavailable` while the service is unreachable (never `disarmed`). A rejected token starts Home Assistant's re-authentication flow. The config flow has a "Use HTTPS/WSS" option for deployments behind TLS.

This repo contains `custom_components/zwave_alarm`, the Home Assistant custom component built in Phase 03. It exposes this service's alarm panel and sensors as native Home Assistant entities (`alarm_control_panel.zwave_alarm`, `binary_sensor.zwave_alarm_zone_<zone>`, `sensor.zwave_alarm_fault_count`), kept live via a WebSocket connection to `/api/v1/stream`.

Installation and config-flow setup are covered in `specs/001-zwave-alarm-ha-integration/quickstart.md`, section 4. This README covers the remote-notification pattern from **FR-013**.

## Remote notifications are delegated to Home Assistant (FR-013)

Per `spec.md`'s FR-013 and Clarifications, this service's own responsibility for alarm notification stops at the **local audible siren** — a configured Z-Wave siren/alert device is the authoritative, no-Home-Assistant-required notification (see `src/alarm/siren.ts`). Any additional remote notification (push, SMS, email) is intentionally *not* built into the alarm system itself. Instead, it's delivered through a Home Assistant automation built on top of `alarm_control_panel.zwave_alarm`'s exposed state, once the custom component is installed (User Story 3, Phase 03).

This keeps the native alarm fully functional with zero notification configuration, while still letting a Home Assistant user get a push notification, SMS, sirens elsewhere in the house, or anything else Home Assistant's automation/notify platforms support.

## Sample automation: mobile notification on trigger

The following automation watches `alarm_control_panel.zwave_alarm` for a transition into the `triggered` state and sends a mobile push notification via the Home Assistant Companion App's `notify.mobile_app_<your_device>` service (satisfying User Story 3's first acceptance scenario: "a notification is sent to all designated recipients").

```yaml
alias: "Z-Wave Alarm: notify on trigger"
description: >
  Sends a mobile push notification when the Z-Wave Alarm's
  alarm_control_panel entity transitions into the triggered state.
triggers:
  - trigger: state
    entity_id: alarm_control_panel.zwave_alarm
    to: "triggered"
conditions: []
actions:
  - action: notify.mobile_app_your_phone # replace with your Companion App notify service
    data:
      title: "Alarm Triggered"
      message: "The Z-Wave Alarm has been triggered."
      data:
        # Optional: makes the notification a persistent, high-priority alert
        # on Android/iOS Companion Apps rather than a silent banner.
        priority: high
        ttl: 0
mode: single
```

Replace `notify.mobile_app_your_phone` with the actual `notify.mobile_app_<device>` service created by the [Home Assistant Companion App](https://www.home-assistant.io/integrations/mobile_app/) for each recipient's phone — add one `action` entry per recipient to notify more than one person.

## Sample automation: "cleared, and by whom" follow-up

`alarm_cleared` events recorded by this service (see `src/events/event-repository.ts` and `GET /api/v1/events`) carry a human-readable `details` string such as `"Cleared by Owner"` or `"Cleared by Home Assistant"` (User Story 3's second acceptance scenario). The `alarm_control_panel.zwave_alarm` entity's state transitions from `triggered` back to `disarmed` at the same moment, so a companion automation can send a follow-up notification confirming the alarm was cleared:

```yaml
alias: "Z-Wave Alarm: notify on clear"
description: >
  Sends a mobile push notification when the Z-Wave Alarm returns to
  disarmed after having been triggered.
triggers:
  - trigger: state
    entity_id: alarm_control_panel.zwave_alarm
    from: "triggered"
    to: "disarmed"
conditions: []
actions:
  - action: notify.mobile_app_your_phone # replace with your Companion App notify service
    data:
      title: "Alarm Cleared"
      message: "The Z-Wave Alarm has been disarmed."
mode: single
```

The `alarm_control_panel` state alone doesn't say who cleared the alarm; use the security event entity instead, which carries that text in its `details` attribute:

```yaml
alias: "Z-Wave Alarm: notify who cleared it"
triggers:
  - trigger: state
    entity_id: event.zwave_alarm_security_events
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.event_type == 'alarm_cleared' }}"
actions:
  - action: notify.mobile_app_your_phone # replace with your Companion App notify service
    data:
      title: "Alarm Cleared"
      message: "{{ trigger.to_state.attributes.details }}"
mode: queued
```
