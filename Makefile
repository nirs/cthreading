# Copyright 2015 Nir Soffer <nsoffer@redhat.com>
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions
# of the GNU General Public License v2 or (at your option) any later version.

default: test regrtest

.PHONY: build
build:
	python setup.py build_ext -i

.PHONY: test
test: build
	py.test

.PHONY: regrtest
regrtest: build
	python regrtest.py -v test_threading

.PHONY: dist
dist:
	python setup.py sdist

.PHONY: clean
clean:
	python setup.py clean
	rm -f cthreading/*.so cthreading/*.pyc
