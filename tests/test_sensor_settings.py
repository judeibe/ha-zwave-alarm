from custom_components.zwave_alarm.sensor_settings import (
    DEFAULT_SETTINGS, sensor_device_class, settings_from_sensor, to_wire,
)


def test_settings_default_and_legacy_chirp_tone():
    assert settings_from_sensor({}) == DEFAULT_SETTINGS
    s = settings_from_sensor({"chirpTone": "guitar"})
    assert s["chime_enabled"] and s["chime_sound"] == "guitar"
    assert not settings_from_sensor({"chirpTone": "none"})["chime_enabled"]


def test_new_fields_win_over_legacy():
    s = settings_from_sensor({"chirpTone": "guitar", "chimeEnabled": False, "chimeSound": "doorbell", "entryway": "Front", "sensorKind": "window"})
    assert (s["chime_enabled"], s["chime_sound"], s["entryway"], s["sensor_kind"]) == (False, "doorbell", "Front", "window")


def test_to_wire_maps_and_forces_interior():
    assert to_wire({"chime_enabled": True, "entryway": " Front "}) == {"chimeEnabled": True, "entryway": "Front"}
    assert to_wire({"entryway": "  "})["entryway"] is None
    assert to_wire({"sensor_kind": "interior", "is_interior": False})["isInterior"] is True


def test_device_class():
    assert [sensor_device_class(k) for k in ("door", "window", "interior", None)] == ["door", "window", "motion", "door"]


def test_quick_exit_field_and_legacy_alias():
    assert to_wire({"quick_exit_enabled": True}) == {"quickExitEnabled": True}
    assert settings_from_sensor({"quickExitEnabled": True})["quick_exit_enabled"] is True
    assert settings_from_sensor({"quickEntrySupported": True})["quick_exit_enabled"] is True
    assert settings_from_sensor({"quickEntrySupported": True, "quickExitEnabled": False})["quick_exit_enabled"] is False
