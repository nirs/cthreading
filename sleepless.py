# Copyright 2015 Nir Soffer <nsoffer@redhat.com>
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions
# of the GNU General Public License v2 or (at your option) any later version.

import optparse
import sys
import benchlib

parser = benchlib.option_parser("sleepless [options]")
parser.add_option("-s", "--timeout", dest="timeout", type="float",
                  help="number of seconds to sleep")
parser.set_defaults(threads=400, timeout=10)


def sleepless(options):
    import threading

    cond = threading.Condition(threading.Lock())
    threads = []

    for i in benchlib.range(options.threads):
        t = threading.Thread(target=sleep, args=(cond, options.timeout))
        t.daemon = True
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


def sleep(cond, timeout):
    with cond:
        cond.wait(timeout)


if __name__ == "__main__":
    options, args = parser.parse_args(sys.argv)
    benchlib.run(sleepless, options)
