# Copyright 2015 Nir Soffer <nsoffer@redhat.com>
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions
# of the GNU General Public License v2 or (at your option) any later version.

import optparse

try:
    range = xrange
except NameError:
    range = range


def option_parser(usage):
    parser = optparse.OptionParser(usage=usage)
    parser.add_option("-t", "--threads", dest="threads", type="int",
                      help="number of threads")
    parser.add_option("-m", "--monkeypatch", dest="monkeypatch",
                      help="monkeypatch type (native, cthreading, pthreading)")
    parser.add_option("-p", "--profile", dest="profile",
                      help="create profile (requires yappi 0.93)")
    parser.set_defaults(threads=10)
    return parser


def run(func, options):
    if options.monkeypatch:
        if options.monkeypatch == "cthreading":
            import cthreading
            cthreading.monkeypatch()
        elif options.monkeypatch == "pthreading":
            import pthreading
            pthreading.monkey_patch()
        else:
            raise ValueError("Usupported monkeypatch %r" % options.monkeypatch)

    if options.profile:
        import yappi
        yappi.set_clock_type('cpu')
        yappi.start(builtins=True, profile_threads=True)

    func(options)

    if options.profile:
        yappi.stop()
        stats = yappi.get_func_stats()
        stats.save(options.profile, 'pstat')
