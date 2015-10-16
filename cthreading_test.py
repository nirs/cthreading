# Copyright 2015 Nir Soffer <nsoffer@redhat.com>
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions
# of the GNU General Public License v2 or (at your option) any later version.

import contextlib
import os
import signal
import sys
import threading
import time
import weakref

import pytest
import cthreading

def Lock():
    return cthreading.Lock()

def RLock():
    return cthreading.RLock()

def Condition():
    return cthreading.Condition(Lock())

def RCondition():
    return cthreading.Condition(RLock())

# Lock tests

@pytest.mark.timeout(2, method='thread')
@pytest.mark.parametrize("timeout", [0, 0.1, 1])
@pytest.mark.parametrize("locktype", [Lock, Condition])
def test_lock_acquire_timeout_timedout(locktype, timeout):
    lock = locktype()
    with lock:
        assert not lock.acquire(True, timeout)

@pytest.mark.parametrize("timeout", [0.9, 1.0])
@pytest.mark.parametrize("locktype", [Lock, Condition])
def test_lock_acquire_timeout_block(locktype, timeout):
    lock = locktype()
    ready = threading.Event()

    def release():
        ready.wait()
        time.sleep(0.1)
        lock.release()

    lock.acquire()
    t = start_thread(release)
    try:
        ready.set()
        assert lock.acquire(True, timeout)
        assert locked(lock)
    finally:
        t.join()

@pytest.mark.parametrize("blocking", [0, False])
@pytest.mark.parametrize("locktype", [Lock, Condition])
def test_lock_acquire_nobloking(locktype, blocking):
    lock = locktype()
    with lock:
        assert not lock.acquire(blocking)

@pytest.mark.parametrize("locktype", [Lock, Condition])
def test_lock_release_from_other_thread(locktype):
    lock = locktype()
    lock.acquire()
    start_thread(lock.release).join()
    assert not locked(lock)

def test_lock_locked_released():
    lock = Lock()
    assert not lock.locked()

def test_lock_locked_acquired():
    lock = Lock()
    lock.acquire()
    assert lock.locked()

@pytest.mark.parametrize("locktype", [Lock, Condition])
def test_lock_release_save(locktype):
    lock = locktype()
    lock.acquire()
    owner = lock._release_save()
    assert owner == threading.current_thread().ident
    assert not locked(lock)

@pytest.mark.parametrize("locktype", [Lock, Condition])
def test_lock_release_save_unacquired(locktype):
    lock = locktype()
    pytest.raises(RuntimeError, lock._release_save)

@pytest.mark.parametrize("locktype", [Lock, Condition])
def test_lock_acquire_restore(locktype):
    lock = locktype()
    me = threading.current_thread().ident
    lock._acquire_restore(me)
    assert locked(lock)
    assert lock._release_save() == me

@pytest.mark.parametrize("state", [
    (),
    (1, "extra"),
    ("invalid",),
])
@pytest.mark.parametrize("locktype", [Lock, Condition])
def test_lock_acquire_restore_bad_state(locktype, state):
    lock = locktype()
    pytest.raises(TypeError, lock._acquire_restore, state)

# RLock tests

@pytest.mark.parametrize("locktype", [RLock, RCondition])
def test_rlock_delete_locked_recursive(locktype):
    lock = locktype()
    lock.acquire()
    lock.acquire()
    del lock

@pytest.mark.parametrize("locktype", [RLock, RCondition])
def test_rlock_acquire_recursive(locktype):
    lock = locktype()
    for i in range(100):
        assert lock.acquire(False)
    assert locked(lock)

@pytest.mark.parametrize("timeout", [-1.0, -1, 0.0, 1.0, 1000])
@pytest.mark.parametrize("locktype", [RLock, RCondition])
def test_rlock_acquire_timeout_free(locktype, timeout):
    lock = locktype()
    assert lock.acquire(blocking=True, timeout=timeout)
    assert locked(lock)

@pytest.mark.timeout(2, method='thread')
@pytest.mark.parametrize("timeout", [0, 0.1, 1])
@pytest.mark.parametrize("locktype", [RLock, RCondition])
def test_rlock_acquire_timeout_timedout(locktype, timeout):
    lock = locktype()
    lock_taken = [False]

    def take():
        lock_taken[0] = lock.acquire(blocking=True, timeout=timeout)

    assert lock.acquire()
    start_thread(take).join()
    assert not lock_taken[0]

@pytest.mark.parametrize("timeout", [0.9, 1.0])
@pytest.mark.parametrize("locktype", [RLock, RCondition])
def test_rlock_acquire_timeout_block(locktype, timeout):
    lock = locktype()
    ready = threading.Event()
    lock_taken = [False]

    def take():
        ready.set()
        lock_taken[0] = lock.acquire(blocking=True, timeout=timeout)

    lock.acquire()
    t = start_thread(take)
    try:
        ready.wait()
        time.sleep(0.1)
        lock.release()
    finally:
        t.join()

    assert lock_taken[0]

@pytest.mark.parametrize("locktype", [RLock, RCondition])
def test_rlock_release_owned_by_other_thread(locktype):
    lock = locktype()
    ready = threading.Event()
    done = threading.Event()

    def own():
        with lock:
            ready.set()
            done.wait()

    t = start_thread(own)
    try:
        ready.wait(0.5)
        if not ready.is_set():
            raise RuntimeError("Timeout starting owner thread")
        pytest.raises(RuntimeError, lock.release)
    finally:
        done.set()
        t.join()

@pytest.mark.parametrize("depth", [1, 2, 100])
@pytest.mark.parametrize("locktype", [RLock, RCondition])
def test_rlock_release_save(locktype, depth):
    lock = locktype()
    for i in range(depth):
        lock.acquire()
    count, owner = lock._release_save()
    assert count == depth
    assert owner == threading.current_thread().ident
    assert not locked(lock)

@pytest.mark.parametrize("locktype", [RLock, RCondition])
def test_rlock_release_save_unacquired(locktype):
    lock = locktype()
    pytest.raises(RuntimeError, lock._release_save)

@pytest.mark.parametrize("depth", [1, 2, 100])
@pytest.mark.parametrize("locktype", [RLock, RCondition])
def test_rlock_acquire_restore(locktype, depth):
    lock = locktype()
    me = threading.current_thread().ident
    lock._acquire_restore((depth, me))
    assert locked(lock)
    count, owner = lock._release_save()
    assert count == depth
    assert owner == me

@pytest.mark.parametrize("state", [
    (),
    (1,),
    (1, 0, "extra"),
    ("invalid", 0),
    (1, "invalid"),
])
@pytest.mark.parametrize("locktype", [RLock, RCondition])
def test_rlock_acquire_restore_bad_state(locktype, state):
    lock = locktype()
    pytest.raises(TypeError, lock._acquire_restore, state)

# Common tests

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_init(locktype):
    lock = locktype()
    assert not locked(lock)

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_delete_unlocked(locktype):
    lock = locktype()
    del lock

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_delete_locked(locktype):
    lock = locktype()
    lock.acquire()
    del lock

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_acquire(locktype):
    lock = locktype()
    lock.acquire()
    assert locked(lock)

@pytest.mark.parametrize("blocking", [0, False, 1, True])
@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_acquire_blocking(locktype, blocking):
    lock = locktype()
    assert lock.acquire(blocking)

@pytest.mark.parametrize("blocking", [0, False, 1, True])
@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_acquire_blocking_kwarg(locktype, blocking):
    lock = locktype()
    assert lock.acquire(blocking=blocking)

@pytest.mark.parametrize("timeout", ["1", "1.0"])
@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_acquire_timeout_bad_type(locktype, timeout):
    lock = locktype()
    pytest.raises(TypeError, lock.acquire, blocking=True, timeout=timeout)

@pytest.mark.parametrize("timeout", [-1.1, -2])
@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_acquire_timeout_negative(locktype, timeout):
    lock = locktype()
    pytest.raises(ValueError, lock.acquire, blocking=True, timeout=timeout)

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_acquire_timeout_noblocking(locktype):
    lock = locktype()
    pytest.raises(ValueError, lock.acquire, blocking=False, timeout=2)

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_release_unlocked(locktype):
    lock = locktype()
    pytest.raises(RuntimeError, lock.release)

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_release(locktype):
    lock = locktype()
    lock.acquire()
    lock.release()
    assert not locked(lock)

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_with_acquire(locktype):
    lock = locktype()
    with lock:
        assert locked(lock)

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_with_release(locktype):
    lock = locktype()
    with lock:
        pass
    assert not locked(lock)

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_multiple_threads(locktype):
    lock = locktype()
    ready = threading.Event()
    concurrency = 100
    counter = [0]

    def take():
        ready.set()
        with lock:
            counter[0] += 1

    threads = []
    lock.acquire()
    try:
        for i in range(concurrency):
            ready.clear()
            t = start_thread(take)
            threads.append(t)
            ready.wait()
    finally:
        lock.release()
        for t in threads:
            t.join()

    assert counter[0] == concurrency

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_weakref_exists(locktype):
    lock = locktype()
    ref = weakref.ref(lock)
    assert ref() is not None

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_weakref_deleted(locktype):
    lock = locktype()
    ref = weakref.ref(lock)
    del lock
    assert ref() is None

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_acquire_interrupt(locktype):
    lock = locktype()
    holder_ready = threading.Event()
    sender_ready = threading.Event()
    done = threading.Event()
    signal_received = [0]
    signo = signal.SIGUSR1

    def hold():
        with lock:
            holder_ready.set()
            done.wait()

    def receive(signo, frame):
        print '[%f] received signal %d' % (time.time(), signo)
        signal_received[0] += 1

    def send():
        try:
            sender_ready.set()
            time.sleep(0.1)
            print '[%f] sending signal %d' % (time.time(), signo)
            os.kill(os.getpid(), signo)
            time.sleep(0.1)
        finally:
            done.set()

    with handle_signal(signo, receive):
        holder = start_thread(hold)
        try:
            holder_ready.wait(0.5)
            if not holder_ready.is_set():
                raise RuntimeError("Timeout starting holder thread")
            sender = start_thread(send)
            try:
                sender_ready.wait(0.5)
                if not sender_ready.is_set():
                    raise RuntimeError("Timeout starting sender thread")
                # Will succeed although underlying sem_wait interrupted by
                # signal.
                assert lock.acquire()
            finally:
                sender.join()
        finally:
            done.set()
            holder.join()

        assert signal_received[0] == 1

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_is_not_owned(locktype):
    lock = locktype()
    assert not lock._is_owned()

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_is_owned_by_caller(locktype):
    lock = locktype()
    lock.acquire()
    assert lock._is_owned()

@pytest.mark.parametrize("locktype", [Lock, RLock, Condition, RCondition])
def test_common_is_owned_by_other(locktype):
    lock = locktype()
    ready = threading.Event()
    done = threading.Event()

    def own():
        with lock:
            ready.set()
            done.wait()

    t = start_thread(own)
    try:
        ready.wait(0.5)
        if not ready.is_set():
            raise RuntimeError("Timeout starting owner thread")
        assert not lock._is_owned()
    finally:
        done.set()
        t.join()

# Condition

@pytest.mark.timeout(2, method='thread')
@pytest.mark.parametrize("timeout", [0, 0.1, 1])
@pytest.mark.parametrize("condtype", [Condition, RCondition])
def test_cond_wait_timeout_timedout(condtype, timeout):
    cond = condtype()
    with cond:
        assert not cond.wait(timeout)

@pytest.mark.parametrize("timeout", ["1", "1.0"])
@pytest.mark.parametrize("condtype", [Condition, RCondition])
def test_cond_wait_timeout_bad_type(condtype, timeout):
    cond = condtype()
    pytest.raises(TypeError, cond.wait, timeout=timeout)

@pytest.mark.parametrize("timeout", [-1.1, -2])
@pytest.mark.parametrize("condtype", [Condition, RCondition])
def test_cond_wait_timeout_negative(condtype, timeout):
    cond = condtype()
    pytest.raises(ValueError, cond.wait, timeout=timeout)

@pytest.mark.parametrize("condtype", [Condition, RCondition])
def test_common_release_unlocked(condtype):
    cond = condtype()
    pytest.raises(RuntimeError, cond.wait)

@pytest.mark.timeout(2, method='thread')
@pytest.mark.parametrize("condtype", [Condition, RCondition])
def test_cond_wait_notify(condtype):
    cond = condtype()
    ready = threading.Event()

    def notify():
        ready.wait()
        with cond:
            cond.notify()

    t = start_thread(notify)
    try:
        with cond:
            ready.set()
            notified = cond.wait()
            assert notified
            assert locked(cond)
    finally:
        t.join()

@pytest.mark.timeout(2, method='thread')
@pytest.mark.parametrize("timeout", [None, 0.9, 1.0, 1e100, sys.maxint])
@pytest.mark.parametrize("condtype", [Condition, RCondition])
def test_cond_wait_notify_timeout(condtype, timeout):
    cond = condtype()
    ready = threading.Event()

    def notify():
        ready.wait()
        with cond:
            cond.notify()

    t = start_thread(notify)
    try:
        with cond:
            ready.set()
            notified = cond.wait(timeout)
            assert notified
            assert locked(cond)
    finally:
        t.join()

@pytest.mark.parametrize("condtype", [Condition, RCondition])
def test_cond_notify_no_waiters(condtype):
    cond = condtype()
    with cond:
        cond.notify()
    with cond:
        notified = cond.wait(0.0)
    assert not notified

@pytest.mark.parametrize("notify", [1, 2, 10, 11])
@pytest.mark.parametrize("condtype", [Condition, RCondition])
def test_cond_notify_many(condtype, notify):
    cond = condtype()
    ready = threading.Event()
    results = []

    def wait():
        with cond:
            ready.set()
            res = cond.wait(0.5)
            results.append(res)

    threads = []
    try:
        for i in range(10):
            ready.clear()
            t  = start_thread(wait)
            threads.append(t)
            ready.wait()
        with cond:
            cond.notify(notify)
    finally:
        for t in threads:
            t.join()

    assert len(results) == 10
    assert len(filter(None, results)) == min(notify, 10)

@pytest.mark.parametrize("condtype", [Condition, RCondition])
def test_cond_notify_all(condtype):
    cond = condtype()
    ready = threading.Event()
    results = []

    def wait():
        with cond:
            ready.set()
            res = cond.wait(0.5)
            results.append(res)

    threads = []
    try:
        for i in range(10):
            ready.clear()
            t  = start_thread(wait)
            threads.append(t)
            ready.wait()
        with cond:
            cond.notify_all()
    finally:
        for t in threads:
            t.join()

    assert len(results) == 10
    assert all(results)

@pytest.mark.parametrize("condtype", [Condition, RCondition])
def test_cond_notify_no_waiters(condtype):
    cond = condtype()
    with cond:
        cond.notify()
    with cond:
        notified = cond.wait(0.0)
    assert not notified

@pytest.mark.parametrize("condtype", [Condition, RCondition])
def test_cond_notify_unlocked(condtype):
    cond = condtype()
    pytest.raises(RuntimeError, cond.notify)

def test_cond_recursive_wait_notify():
    cond = RCondition()
    ready = threading.Event()

    def notify():
        ready.wait()
        with cond:
            cond.notify()

    t = start_thread(notify)
    try:
        with cond:
            with cond:
                ready.set()
                notified = cond.wait(0.5)
                assert notified
                assert locked(cond)
            assert locked(cond)
        assert not locked(cond)
    finally:
        t.join()

# Monkeypatching

def test_monkeypatch_patch(monkeypatch):
    monkeypatch.delitem(sys.modules, "threading")
    monkeypatch.delitem(sys.modules, "thread")
    monkeypatch.setattr(cthreading, "_patched", False)
    cthreading.monkeypatch()
    import thread
    import threading
    assert thread.allocate_lock is cthreading.Lock
    assert threading._allocate_lock is cthreading.Lock
    assert threading.Lock is cthreading.Lock
    assert threading.RLock is cthreading.RLock
    assert threading.Condition is cthreading.Condition

def test_monkeypatch_twice(monkeypatch):
    monkeypatch.delitem(sys.modules, "threading")
    monkeypatch.delitem(sys.modules, "thread")
    monkeypatch.setattr(cthreading, "_patched", False)
    cthreading.monkeypatch()
    pytest.raises(RuntimeError, cthreading.monkeypatch)

def test_monkeypatch_threading_exists(monkeypatch):
    monkeypatch.delitem(sys.modules, "thread")
    monkeypatch.setitem(sys.modules, "threading", None)
    monkeypatch.setattr(cthreading, "_patched", False)
    pytest.raises(RuntimeError, cthreading.monkeypatch)

def test_monkeypatch_thread_exists(monkeypatch):
    monkeypatch.delitem(sys.modules, "threading")
    monkeypatch.setitem(sys.modules, "thread", None)
    monkeypatch.setattr(cthreading, "_patched", False)
    pytest.raises(RuntimeError, cthreading.monkeypatch)

# Helpers

@contextlib.contextmanager
def handle_signal(signo, handler):
    prev = signal.signal(signo, handler)
    try:
        yield
    finally:
        signal.signal(signo, prev)

def locked(lock):
    """
    Check if a lock is locked by trying to acquire it from another thread.
    lock may be instance of Lock, RLock or a Condition using one of these
    locks.
    """
    acquired = [False]

    def check():
        acquired[0] = lock.acquire(False)
        if acquired[0]:
            lock.release()

    start_thread(check).join()
    return not acquired[0]

def start_thread(func, args=(), kwargs=None):
    kwargs = {} if kwargs is None else kwargs
    t = threading.Thread(target=func, args=args, kwargs=kwargs)
    t.deamon = True
    t.start()
    return t
