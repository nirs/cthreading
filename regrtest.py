# Copyright 2015 Nir Soffer <nsoffer@redhat.com>
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions
# of the GNU General Public License v2 or (at your option) any later version.

import cthreading
cthreading.monkeypatch()

# Requires python-test package, not installed by default
from test import regrtest
regrtest.main()
