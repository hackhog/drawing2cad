"""Maintained STEP adapters. These modules require no CAD kernel or GUI."""

import hashlib
from pathlib import Path

PROFILE = "drawing2cad.step-adapters/1"


def identity():
    """Identify all packaged adapter sources with exact file hashes."""
    root = Path(__file__).parent
    names = ["__init__.py", "p21.py", "procedural.py", "pmi.py", "review.py", "origins.json"]
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    digest = hashlib.sha256("".join(name + ":" + hashes[name] + "\n" for name in names).encode()).hexdigest()
    return {"profile": PROFILE, "source_sha256": digest, "module_sha256": hashes,
            "cad_kernel_used": False, "geometry_validated": False}
