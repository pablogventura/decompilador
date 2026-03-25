"""
Reproduce secuencias largas tipo dsoUpdateFPGA desde un JSON.

El DLL usa magics y trozos variables; aquí solo se ejecuta lo que describas en el guion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Union

Json = dict[str, Any]


def load_script(path: Path) -> Json:
    data = path.expanduser().read_text(encoding="utf-8")
    return json.loads(data)


def _hex_to_bytes(s: str) -> bytes:
    return bytes.fromhex(s.replace(" ", "").replace("\n", ""))


def expand_steps(script: Json) -> List[bytes]:
    """
    Formato soportado:

    ```json
    {
      "steps": [
        { "hex": "00aa..." },
        { "file": "payload.bin" },
        { "file": "chunk.bin", "chunk_size": 48, "repeat": 10 }
      ]
    }
    ```

    Si `chunk_size` está presente, cada `repeat` lee `chunk_size` bytes del archivo
    (avanzando offset) y los envía como un write; si no, se envía el archivo entero.
    """
    steps = script.get("steps")
    if not isinstance(steps, list):
        raise ValueError('El JSON debe tener clave "steps" (lista)')

    base = Path(script.get("base_dir", "."))
    out: List[bytes] = []

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"steps[{i}] debe ser objeto")
        if "hex" in step:
            out.append(_hex_to_bytes(str(step["hex"])))
            continue
        if "file" in step:
            fp = base / str(step["file"])
            raw = fp.read_bytes()
            cs = step.get("chunk_size")
            rep = int(step.get("repeat", 1))
            if cs is None:
                for _ in range(rep):
                    out.append(raw)
                continue
            cs = int(cs)
            off = 0
            for _ in range(rep):
                chunk = raw[off : off + cs]
                if len(chunk) != cs:
                    raise ValueError(
                        f"steps[{i}]: faltan bytes en {fp} (offset {off}, need {cs})"
                    )
                out.append(chunk)
                off += cs
            continue
        raise ValueError(f"steps[{i}]: usa 'hex' o 'file'")

    return out


def run_script_writes(link: Any, script: Json, *, verbose: bool, log: Any) -> int:
    blobs = expand_steps(script)
    total = 0
    for j, blob in enumerate(blobs):
        if verbose:
            log(f">> paso {j + 1}/{len(blobs)} ({len(blob)} B)")
        n = link.write(blob)
        total += n
    return total
