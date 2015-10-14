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

    if options.profile:
        import yappi
        yappi.set_clock_type('cpu')
        yappi.start(builtins=True, profile_threads=True)

    leftmost = queue.Queue()
    left = leftmost
    for i in _range(options.whispers):
        right = queue.Queue()
        t = threading.Thread(target=whisper, args=(left, right))
        t.daemon = True
        t.start()
        left = right

    for i in _range(options.jobs):
        right.put(1)

    for i in _range(options.jobs):
        n = leftmost.get()
        assert n == options.whispers + 1

    if options.profile:
        yappi.stop()
        stats = yappi.get_func_stats()
        stats.save(options.profile, 'pstat')


def parse_args(args):
    parser = optparse.OptionParser(usage="whispers [options]")
    parser.add_option("-w", "--whispers", dest="whispers", type="int",
                      help="number of whispers")
    parser.add_option("-j", "--jobs", dest="jobs", type="int",
                      help="number of jobs")
    parser.add_option("-m", "--monkeypatch", dest="monkeypatch",
                      help="monkeypatch type (native, cthreading, pthreading)")
    parser.add_option("-p", "--profile", dest="profile",
                      help="create profile (requires yappi 0.93)")
    parser.set_defaults(whispers=200, jobs=5000, monkeypatch=None)
    return parser.parse_args(args)


def whisper(left, right):
    while True:
        n = right.get()
        left.put(n + 1)


if __name__ == "__main__":
    main(sys.argv)
