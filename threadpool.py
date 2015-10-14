# Copyright 2015 Nir Soffer <nsoffer@redhat.com>
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions
# of the GNU General Public License v2 or (at your option) any later version.

import optparse
import sys


def main(args):
    options, args = parse_args(args)

    if options.monkeypatch:
        if options.monkeypatch == "cthreading":
            import cthreading
            cthreading.monkeypatch()
        elif options.monkeypatch == "pthreading":
            import pthreading
            pthreading.monkey_patch()
        else:
            raise ValueError("Usupported monkeypatch %r" % options.monkeypatch)

    try:
        import Queue as queue
        _range = xrange
    except ImportError:
        import queue
        _range = range

    import threading

    src = queue.Queue()
    dst = queue.Queue()

    for i in _range(options.workers):
        t = threading.Thread(target=worker, args=(src, dst))
        t.daemon = True
        t.start()

    for i in _range(options.rounds):
        for j in _range(options.jobs):
            src.put(1)
        for j in _range(options.jobs):
            n = dst.get()
            assert n == 2


def parse_args(args):
    parser = optparse.OptionParser(usage="threadpool [options]")
    parser.add_option("-w", "--workers", dest="workers", type="int",
                      help="number of workers")
    parser.add_option("-j", "--jobs", dest="jobs", type="int",
                      help="number of jobs to queue")
    parser.add_option("-r", "--rounds", dest="rounds", type="int",
                      help="number of rounds")
    parser.add_option("-m", "--monkeypatch", dest="monkeypatch",
                      help="monkeypatch type (native, cthreading, pthreading)")
    parser.set_defaults(workers=20, jobs=3000, rounds=200, monkeypatch=None)
    return parser.parse_args(args)


def worker(src, dst):
    while True:
        n = src.get()
        dst.put(n + 1)


if __name__ == "__main__":
    main(sys.argv)
