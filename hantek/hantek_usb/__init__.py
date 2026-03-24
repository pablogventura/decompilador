"""Protocolo USB Hantek 2xx2 (HTHardDll) — uso interno del CLI."""

from hantek_usb.constants import (
    CHUNK,
    DEFAULT_PID_HANTEK,
    PID_HANTEK_2D42,
    PID_HANTEK_2D72,
    VID_HANTEK_2D42,
    VID_HANTEK_2XX2,
)
from hantek_usb.transport import HantekLink

__all__ = [
    "CHUNK",
    "DEFAULT_PID_HANTEK",
    "PID_HANTEK_2D42",
    "PID_HANTEK_2D72",
    "VID_HANTEK_2D42",
    "VID_HANTEK_2XX2",
    "HantekLink",
]
