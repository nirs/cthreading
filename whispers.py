# Copyright 2015 Nir Soffer <nsoffer@redhat.com>
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions
# of the GNU General Public License v2 or (at your option) any later version.

import optparse
import sys
import benchlib

parser = benchlib.option_parser("whispers [options]")
parser.add_option("-j", "--jobs", dest="jobs", type="int",
                  help="number of jobs")
parser.set_defaults(threads=200, jobs=5000)


def whispers(options):
    import threading
    try:
        import Queue as queue
    except ImportError:
        import queue

    leftmost = queue.Queue()
    left = leftmost
    for i in benchlib.range(options.threads):
        right = queue.Queue()
        t = threading.Thread(target=whisper, args=(left, right))
        t.daemon = True
        t.start()
        left = right

    for i in benchlib.range(options.jobs):
        right.put(1)
        n = leftmost.get()
        assert n == options.threads + 1


def whisper(left, right):
    while True:
        n = right.get()
        left.put(n + 1)


if __name__ == "__main__":
    options, args = parser.parse_args(sys.argv)
    benchlib.run(whispers, options)
