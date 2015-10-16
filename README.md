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

Currently tested on:

- Fedora 22
- Ubuntu 12.04 Server (python regression tests not available)
- Ubuntu 14.04 Server

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

Before submiting patches, run the Python regression tests suite:
```
make regrtest
```

Check the `Makefile` for more info.
