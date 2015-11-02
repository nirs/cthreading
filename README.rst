==========
cthreading
==========

cthreading implements Python 2 Lock, RLock, and Condition in C, speeding
up threads synchronization and decreasing cpu usage.

Status: |travis|

.. |travis| image:: https://travis-ci.org/nirs/cthreading.svg?branch=master
    :alt: Travis-CI Build Status
    :target: https://travis-ci.org/nirs/cthreading


Performance
===========

cthreading eliminates the overhead of `threading.RLock` and
`threading.Condition` which are implemented in pure Python in Python 2.
In particular, `threading.Condition` is implemented using polling. In
Python 3 `threading.Condition` is implemented without polling;
cthreading implements a similar design in C.

.. code-block::

    $ time python whispers.py -m cthreading
    real    0m2.664s
    user    0m2.965s
    sys     0m0.808s

    $ time python3 whispers.py
    real    0m9.664s
    user    0m8.949s
    sys     0m1.812s

    $ time python whispers.py
    real    0m14.914s
    user    0m16.986s
    sys     0m12.690s

    $ time python whispers.py -m pthreading
    real    0m20.169s
    user    0m23.062s
    sys     0m17.022s

Your application is unlikely to have similar workload; do not expect
this improvement.

For more info see https://github.com/nirs/cthreading/wiki/performance.


Usage
=====

Import cthreading before any other module and monkeypatch the thread and
threading modules. From this point, threading.Lock, threading.RLock, and
threading.Condition are using cthreading.

.. code-block:: python

    import cthreading
    cthreading.monkeypatch()

Note: cthreading will raise RuntimeError if the threading module was
imported before `cthreading.monkeypatch()` is called.


Tested platforms
================

x86_64
------

- Fedora 22 / Python 2.7.10
- RHEL 7.2 / Python 2.7.5
- RHEL 7.2 / Python 2.7.10+ (upstream)
- RHEL 7.1 / Python 2.7.5
- RHEL 6.7 / Python-2.6.6
- Ubuntu 14.04 Server / Python 2.7.6
- Ubuntu 12.04 Server / Python 2.7.3 (python regression tests not available)
- Ubuntu 12.04 / Python 2.6.9 (Travis container)
- Ubuntu 12.04 / Python 2.7.9 (Travis container)

POWER8E
-------

- RHEL 7.2 / Python 2.7.5
- RHEL 7.2 / Python 2.7.10+ (upstream)


Hacking
=======

For rpm based distributions::

    yum install python-devel python-test

For deb based distributions::

    apt-get install python-dev libpython2.7-testsuite

Installing Python packages::

    pip install pytest pytest-timeout yappi==0.93

Building and running the quick tests::

    make

Before submitting patches, run the Python regression tests suite::

    make regrtest

Check the `Makefile` for more info.


Similar projects
================

- `pthreading <https://github.com/oVirt/pthreading>`_ - uses
  pthread_mutex and pthread_cond apis directly via ctypes. This
  introduces undefined behavior and actually slower and increases cpu
  usage in most cases compared to the original Python implementation.
