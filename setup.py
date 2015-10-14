# Copyright 2015 Nir Soffer <nsoffer@redhat.com>
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions
# of the GNU General Public License v2 or (at your option) any later version.

from distutils.core import setup, Extension

setup(
    author="Nir Soffer",
    author_email="nsoffer@redhat.com",
    description="Reimplementation of threading syncronization primitives",
    ext_modules=[
        Extension(
            name="cthreading._cthreading",
            sources=["cthreading/_cthreading.c"]
        )
    ],
    license="GNU GPLv2+",
    name="cthreading",
    platforms=["Linux"],
    packages=["cthreading"],
    url="?",
    version="0.1",
)
