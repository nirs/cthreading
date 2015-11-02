# Copyright 2015 Nir Soffer <nsoffer@redhat.com>
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions
# of the GNU General Public License v2 or (at your option) any later version.

import optparse
import sys
import benchlib

parser = benchlib.option_parser("threadpool [options]")
parser.add_option("-j", "--jobs", dest="jobs", type="int",
                  help="number of jobs to queue")
parser.add_option("-r", "--rounds", dest="rounds", type="int",
                  help="number of rounds")
parser.set_defaults(threads=20, jobs=3000, rounds=200)


def threadpool(options):
    import threading

    try:
        import Queue as queue
    except ImportError:
        import queue

    src = queue.Queue()
    dst = queue.Queue()

    for i in benchlib.range(options.threads):
        t = threading.Thread(target=worker, args=(src, dst))
        t.daemon = True
        t.start()

    for i in benchlib.range(options.rounds):
        for j in benchlib.range(options.jobs):
            src.put(1)
        for j in benchlib.range(options.jobs):
            n = dst.get()
            assert n == 2


def worker(src, dst):
    while True:
        n = src.get()
        dst.put(n + 1)


if __name__ == "__main__":
    options, args = parser.parse_args(sys.argv)
    benchlib.run(threadpool, options)
