# Copyright 2015 Nir Soffer <nsoffer@redhat.com>
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions
# of the GNU General Public License v2 or (at your option) any later version.

import collections
import threading


class Queue(object):

    def __init__(self):
        self._cond = threading.Condition(threading.Lock())
        self._queue = collections.deque()
        self._waiters = 0

    def put(self, item):
        self._queue.append(item)
        with self._cond:
            self._cond.notify()

    def get(self):
        while True:
            try:
                return self._queue.popleft()
            except IndexError:
                with self._cond:
                    if not self._queue:
                        self._cond.wait()
