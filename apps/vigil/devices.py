"""What one Jackil Dynamic Item looks like to Vigil as a device."""

from apps.vigil import client as vigil_client

#: What a Jackil device kind maps to when the kind itself says nothing.
DEFAULT_DEVICE_TYPE = "other"

#: The attribute that carries a serial number, matched case-insensitively.
SERIAL_KEY = "serial"

#: What the owning department is called in Vigil's ``extra``.
DEPARTMENT_KEY = "Department"

#: How many facts Vigil will carry as a device's ``extra``, and how long each may be.
MAX_EXTRA = 50
MAX_EXTRA_VALUE = 300


def can_write_devices() -> bool:
    """Whether Vigil lets this key create, change and delete devices.

    Asked through the client module, so one fake connection handed to
    ``client.get_client`` is the whole app's view of Vigil.
    """
    return (
        vigil_client.get_client() is not None
        and "device_write" in vigil_client.vigil_capabilities()
    )


def device_payload(item) -> dict:
    """Vigil's device fields for this Item.

    Vigil has no IP, MAC or rack field of its own, so every attribute except
    the serial travels as an ``extra`` fact, trimmed to what its endpoint takes.
    """
    attributes = {
        str(key): str(value) for key, value in (item.attributes or {}).items() if str(key).strip()
    }
    serial = ""
    extra: dict[str, str] = {}
    for key, value in attributes.items():
        if key.lower() == SERIAL_KEY and not serial:
            serial = value[:MAX_EXTRA_VALUE]
            continue
        extra[key] = value[:MAX_EXTRA_VALUE]
    if item.department_id and item.department is not None:
        extra[DEPARTMENT_KEY] = item.department.name[:MAX_EXTRA_VALUE]

    return {
        "name": item.name,
        "device_type": item.kind.vigil_device_type or DEFAULT_DEVICE_TYPE,
        "vendor": item.vendor,
        "warranty_end": item.warranty_end.isoformat() if item.warranty_end else None,
        "owner": _owner(item),
        "serial": serial,
        "notes": item.notes,
        "extra": dict(list(extra.items())[:MAX_EXTRA]),
    }


def _owner(item) -> str:
    """Who Vigil sees as owning the device — name, with the address when we have one."""
    user = item.owner
    if user is None:
        return ""
    name = user.get_full_name() or user.username
    return f"{name} <{user.email}>" if user.email else name
