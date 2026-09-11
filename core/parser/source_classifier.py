from typing import Optional


class SourceClass:
    APP = "APP"
    DEVICE = "DEVICE"
    BLUETOOTH_SYSTEM = "BLUETOOTH_SYSTEM"
    WIFI_SYSTEM = "WIFI_SYSTEM"
    ANDROID_SYSTEM = "ANDROID_SYSTEM"
    VENDOR_SYSTEM = "VENDOR_SYSTEM"
    UNKNOWN = "UNKNOWN"


def classify(tag: Optional[str], package: Optional[str], message: str, parse_format: Optional[str] = None, profile: dict | None = None) -> str:
    """Deterministic conservative classification based on available hints.

    This is intentionally conservative: system-level indicators map to
    system classes and never to DEVICE unless profile explicitly configures.
    """
    m = (message or "").lower()
    tag_l = (tag or "").lower()
    pkg_l = (package or "").lower()

    # Bluetooth system signals
    if any(k in m for k in ("acl_disconnected", "acl_disconnected", "btif", "bluetoothgatt", "btif", "bt_")) or any(k in tag_l for k in ("btif", "bluetooth", "acl")):
        return SourceClass.BLUETOOTH_SYSTEM

    # Android framework/vendor keywords
    if any(k in pkg_l for k in ("android", "com.android", "vendor")) or any(k in m for k in ("android", "zygote", "binder", "system_server")):
        return SourceClass.ANDROID_SYSTEM

    # WiFi system
    if any(k in m for k in ("wifi", "wpa", "wlan")) or any(k in tag_l for k in ("wpa", "wlan", "wifi")):
        return SourceClass.WIFI_SYSTEM

    # Generic vendor/system marker; device mappings belong in profiles.
    if "vendor" in pkg_l:
        return SourceClass.VENDOR_SYSTEM

    # App-level: if parse_format is 'logcat' and tag looks like an app
    if parse_format == "logcat" and tag and ("app" in tag_l or ":" in tag):
        return SourceClass.APP

    # Device heuristics: messages mentioning device component names (conservative)
    if any(k in m for k in ("device", "fan", "controller", "motor", "sensor")):
        return SourceClass.DEVICE

    return SourceClass.UNKNOWN
