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
        _range = xrange
    except NameError:
        _range = range

    import threading

    if options.profile:
        import yappi
        yappi.set_clock_type('cpu')
        yappi.start(builtins=True, profile_threads=True)

    cond = threading.Condition(threading.Lock())
    threads = []

    for i in _range(options.threads):
        t = threading.Thread(target=sleep, args=(cond, options.timeout))
        t.daemon = True
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    if options.profile:
        yappi.stop()
        stats = yappi.get_func_stats()
        stats.save(options.profile, 'pstat')


def parse_args(args):
    parser = optparse.OptionParser(usage="sleepless [options]")
    parser.add_option("-t", "--threads", dest="threads", type="int",
                      help="number of threads")
    parser.add_option("-s", "--timeout", dest="timeout", type="float",
                      help="number of seconds to sleep")
    parser.add_option("-m", "--monkeypatch", dest="monkeypatch",
                      help="monkeypatch type (native, cthreading, pthreading)")
    parser.add_option("-p", "--profile", dest="profile",
                      help="create profile (requires yappi 0.93)")
    parser.set_defaults(threads=400, timeout=10, monkeypatch=None)
    return parser.parse_args(args)


def sleep(cond, timeout):
    with cond:
        cond.wait(timeout)


if __name__ == "__main__":
    main(sys.argv)
