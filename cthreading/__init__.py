# Copyright 2015 Nir Soffer <nsoffer@redhat.com>
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions
# of the GNU General Public License v2 or (at your option) any later version.

import sys
from _cthreading import Lock, RLock, Condition

_patched = False


def monkeypatch():
    global _patched

    if _patched:
        raise RuntimeError("System already patched")

    if "threading" in sys.modules:
        raise RuntimeError("Module 'threading' is already imported, cannot "
                           "monkeypatch it.")

    # Must be first
    import thread
    thread.allocate_lock = Lock

    import threading
    threading.RLock = RLock
    threading.Condition = Condition

    _patched = True
