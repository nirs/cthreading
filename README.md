# cthreading

cthreading implements Python 2 Lock, RLock, and Condition in C.  Like
[pthreading](https://github.com/oVirt/pthreading), without the undefined
behavior.

[![Build Status](https://travis-ci.org/nirs/cthreading.svg)](https://travis-ci.org/nirs/cthreading)

## Usage

```python
import cthreading
cthreading.monkeypatch()
```

## Distributions

Tested on:

- Fedora 22 / Python 2.7.10
- RHEL 7.1 / Python 2.7.5
- RHEL 6.7 / Python-2.6.6
- Ubuntu 14.04 Server / Python 2.7.6
- Ubuntu 12.04 Server / Python 2.7.3 (python regression tests not available)
- Ubuntu 12.04 / Python 2.6.9 (Travis container)
- Ubuntu 12.04 / Python 2.7.9 (Travis container)

## Hacking

For rpm based distributions:
```
yum install python-devel python-test
```

For deb based distributions:
```
apt-get install python-dev libpython2.7-testsuite
```

Installing Python packages:
```
pip install pytest pytest-timeout yappi==0.93
```

Building and running the quick tests:
```
make
```

Before submitting patches, run the Python regression tests suite:
```
make regrtest
```

Check the `Makefile` for more info.
