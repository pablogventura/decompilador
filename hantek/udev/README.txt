Reglas udev — Hantek 0483:2d42
==============================

1) Instalar y recargar:
   sudo cp 99-hantek-2d42.rules /etc/udev/rules.d/
   sudo udevadm control --reload-rules
   sudo udevadm trigger

2) OBLIGATORIO: desenchufa y vuelve a enchufar el USB (sin esto el nodo sigue con permisos viejos).

3) Comprobar permisos del nodo (debe ser crw-rw-rw- o al menos rw para tu usuario):
   bash diagnose.sh
   o manualmente:
   ls -l /dev/bus/usb/*/*

4) Si el PID no es 2d42, edita el .rules (idProduct) o añade otra línea.

5) Si sigue fallando:
   - Ejecuta el CLI en la misma máquina donde está el USB (no por SSH a otro host).
   - Comprueba que no sea un contenedor sin acceso al bus USB.
   - Prueba temporalmente: sudo python3 hantek_cli.py list
     Si con sudo funciona, el problema es solo permisos udev.

6) Backend pyusb: debe existir libusb (p. ej. paquete libusb-1.0-0 en Debian/Ubuntu).
