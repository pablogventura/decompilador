"""Descubrimiento USB, claim de interfaz y transferencias bulk."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator, Iterator, Optional, Tuple

import usb.core
import usb.util

from hantek_usb.constants import (
    CHUNK,
    DEFAULT_PID_HANTEK,
    DEFAULT_TIMEOUT_MS,
    VID_HANTEK_2XX2,
)


class HantekUsbError(RuntimeError):
    """Error al abrir o hablar con el dispositivo."""


@dataclass(frozen=True)
class EndpointPair:
    out: int
    inn: int


def find_device(
    vid: int = VID_HANTEK_2XX2,
    pid: int = DEFAULT_PID_HANTEK,
    bus: Optional[int] = None,
    address: Optional[int] = None,
) -> usb.core.Device:
    if bus is not None and address is not None:
        dev = usb.core.find(bus=bus, address=address)
        if dev is None or dev.idVendor != vid or dev.idProduct != pid:
            raise HantekUsbError(
                f"No hay {vid:04x}:{pid:04x} en bus {bus} dirección {address}"
            )
        return dev
    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        raise HantekUsbError(
            f"No se encontró {vid:04x}:{pid:04x} "
            "(¿cable, udev, o driver del kernel ocupando la interfaz?)"
        )
    return dev


def _detach_kernel_if_needed(dev: usb.core.Device, interface: int) -> None:
    try:
        if dev.is_kernel_driver_active(interface):
            dev.detach_kernel_driver(interface)
    except (usb.core.USBError, NotImplementedError, ValueError):
        pass


def open_bulk_endpoints(
    dev: usb.core.Device,
    interface: int = 0,
    altsetting: int = 0,
) -> EndpointPair:
    dev.set_configuration()
    cfg = dev.get_active_configuration()
    intf = usb.util.find_descriptor(cfg, bInterfaceNumber=interface)
    if intf is None:
        raise HantekUsbError(f"No existe la interfaz USB {interface}")
    if altsetting != 0:
        alt = usb.util.find_descriptor(intf, bAlternateSetting=altsetting)
        if alt is None:
            raise HantekUsbError(f"No existe altsetting {altsetting}")
        intf = alt
    _detach_kernel_if_needed(dev, interface)
    usb.util.claim_interface(dev, interface)

    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
        == usb.util.ENDPOINT_OUT,
    )
    ep_in = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
        == usb.util.ENDPOINT_IN,
    )
    if ep_out is None or ep_in is None:
        raise HantekUsbError("La interfaz no expone BULK IN y BULK OUT")
    return EndpointPair(out=ep_out.bEndpointAddress, inn=ep_in.bEndpointAddress)


class HantekLink:
    """Un dispositivo abierto: escrituras y lecturas alineadas con el DLL."""

    __slots__ = ("_dev", "_iface", "_timeout", "ep_in", "ep_out")

    def __init__(
        self,
        vid: int = VID_HANTEK_2XX2,
        pid: int = DEFAULT_PID_HANTEK,
        bus: Optional[int] = None,
        address: Optional[int] = None,
        interface: int = 0,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        self._dev = find_device(vid, pid, bus, address)
        self._iface = interface
        self._timeout = timeout_ms
        eps = open_bulk_endpoints(self._dev, interface)
        self.ep_out, self.ep_in = eps.out, eps.inn

    def close(self) -> None:
        try:
            usb.util.release_interface(self._dev, self._iface)
        except usb.core.USBError:
            pass
        usb.util.dispose_resources(self._dev)

    def write(self, data: bytes) -> int:
        """Escribe en OUT; trocea en bloques de CHUNK si hace falta."""
        if not data:
            return 0
        n = 0
        if len(data) <= CHUNK:
            return int(self._dev.write(self.ep_out, data, timeout=self._timeout))
        for i in range(0, len(data), CHUNK):
            chunk = data[i : i + CHUNK]
            n += int(self._dev.write(self.ep_out, chunk, timeout=self._timeout))
        return n

    def read64(self) -> bytes:
        return bytes(self._dev.read(self.ep_in, CHUNK, timeout=self._timeout))

    def read_n(self, blocks: int) -> bytes:
        return b"".join(self.read64() for _ in range(blocks))


@contextmanager
def hantek_session(**kwargs: object) -> Iterator[HantekLink]:
    link = HantekLink(**kwargs)  # type: ignore[arg-type]
    try:
        yield link
    finally:
        link.close()


def iter_usb_devices() -> Iterator[Tuple[int, int, int, int]]:
    """(bus, address, vid, pid) por cada dispositivo."""
    for d in usb.core.find(find_all=True):
        try:
            yield (d.bus, d.address, d.idVendor, d.idProduct)
        except ValueError:
            continue
