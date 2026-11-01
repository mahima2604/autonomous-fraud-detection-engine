"""Privacy-minimized DeviceInfo v2 contract.

In v2, DeviceInfo means a coarse operating-system family. It is a categorical
model input only and is never used as a graph identity or device fingerprint.
"""

import re


DEVICE_INFO_V2_CLASSES = frozenset({"Windows", "MacOS", "iOS", "Android", "Linux"})
DEVICE_INFO_V2_SOURCE = "client_platform_family_v2"


def normalize_device_platform(raw_value):
    """Normalize a browser platform hint or IEEE-CIS id_30 value to OS family."""
    if not isinstance(raw_value, str):
        return "UNKNOWN"
    value = raw_value.strip().casefold()
    if not value:
        return "UNKNOWN"
    if re.search(r"\bwindows\b|^win(32|64)?$", value):
        return "Windows"
    if "macos" in value or "mac os" in value or value in {"macintel", "macppc", "mac68k"}:
        return "MacOS"
    if "ios" in value or value in {"iphone", "ipad", "ipod"}:
        return "iOS"
    if "android" in value:
        return "Android"
    if "linux" in value:
        return "Linux"
    return "UNKNOWN"


def build_training_device_platform(raw_id_30):
    """Derive v2 platform categories from the training set's OS field id_30."""
    return normalize_device_platform(raw_id_30)


def normalize_browser_platform_hint(raw_value):
    """Accept only a small set of explicit, coarse browser platform labels."""
    if not isinstance(raw_value, str):
        return "UNKNOWN"
    value = raw_value.strip().casefold()
    aliases = {
        "windows": "Windows", "win32": "Windows", "win64": "Windows",
        "macos": "MacOS", "mac os": "MacOS", "macintel": "MacOS",
        "ios": "iOS", "iphone": "iOS", "ipad": "iOS", "ipod": "iOS",
        "android": "Android", "linux": "Linux",
    }
    return aliases.get(value, "UNKNOWN")
