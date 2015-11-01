/*
 * Copyright 2015 Nir Soffer <nsoffer@redhat.com>
 *
 * This copyrighted material is made available to anyone wishing to use,
 * modify, copy, or redistribute it subject to the terms and conditions
 * of the GNU General Public License v2 or (at your option) any later version.
 */

#include <Python.h>
#include <structmember.h> /* offsetof */
#include <pythread.h>

#include <semaphore.h>
#include <string.h>
#include <stdio.h>
#include <time.h>
#include <stdlib.h>

static PyObject *ThreadError;

/* Helpers */

static PyObject *
set_error_info(int err, const char *msg, const char *file, int line)
{
    char buf[128];
    PyObject *value;

    snprintf(buf, sizeof(buf), "%s: %s (%s:%d)",
             msg, strerror(err), file, line);

    value = Py_BuildValue("(is)", err, buf);
    if (value == NULL)
        return NULL;

    PyErr_SetObject(PyExc_OSError, value);
    Py_CLEAR(value);

    return NULL;
}

#define set_error(err, msg) set_error_info(err, msg, __FILE__, __LINE__)

/* Compute deadline using current system time and timeout in seconds.
 *
 * Python 2.7 multiprocessing tests uses wait(1e100). This does not make sense,
 * but we like to be compatible with existing Python 2.7 code, so we will
 * truncate extreme timeouts to INT_MAX. Please open a bug if you tried to wait
 * after year 292471210647 and it did not work for you. */
static void
deadline_from_timeout(double timeout, struct timespec *deadline)
{
#define USEC_PER_SEC    1000000
#define NSEC_PER_USEC   1000

    struct timeval tv;
    long timeout_sec = (long)timeout;
    long timeout_usec = (timeout - (long)timeout) * USEC_PER_SEC;

    gettimeofday(&tv, NULL);

    if (tv.tv_sec <= INT_MAX - timeout_sec)
        tv.tv_sec += timeout_sec;
    else
        tv.tv_sec = INT_MAX;

    tv.tv_usec += timeout_usec;

    if (tv.tv_usec > 1000000) {
        tv.tv_usec -= 1000000;
        if (tv.tv_sec <= INT_MAX - 1)
            tv.tv_sec += 1;
    }

    deadline->tv_sec = tv.tv_sec;
    deadline->tv_nsec = tv.tv_usec * NSEC_PER_USEC;
}

#define UNLIMITED (-1)

static int
parse_timeout(PyObject *obj, double *timeout)
{
    double value;

    if (obj == Py_None) {
        *timeout = UNLIMITED;
        return 0;
    }

    value = PyFloat_AsDouble(obj);
    if (value == -1 && PyErr_Occurred())
        return -1;

    if (value < 0 && value != UNLIMITED) {
        PyErr_SetString(PyExc_ValueError, "timeout value must be positive");
        return -1;
    }

    *timeout = value;
    return 0;
}

/* Parse acquire args (blocking=True, timeout=-1)) and return the timeout by
 * reference. The blocking argument is not needed as timeout=-1 means blocking
 * without limit, and timeout=0 means no blocking. */
static int
acquire_parse_args(PyObject *args, PyObject *kwds, double *timeout)
{
    char *kwlist[] = {"blocking", "timeout", NULL};
    int blocking = 1;
    PyObject *obj = Py_None;
    double value;

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|iO:acquire", kwlist,
                                     &blocking, &obj))
        return -1;

    if (parse_timeout(obj, &value) != 0)
        return -1;

    if (!blocking && value != UNLIMITED) {
        PyErr_SetString(PyExc_ValueError,
                        "can't specify a timeout for a non-blocking call");
        return -1;
    }

    if (blocking)
        *timeout = value;
    else
        *timeout = 0;

    return 0;
}

typedef enum {
    ACQUIRE_OK,         /* Lock is acquired by calling thread */
    ACQUIRE_FAIL,       /* Lock is acquired by another thread */
    ACQUIRE_ERROR,      /* Invalid arguments or lower level error */
} acquire_result;

static acquire_result
acquire_lock(sem_t *sem, double timeout)
{
    int err;
    struct timespec deadline;

    if (timeout > 0)
        deadline_from_timeout(timeout, &deadline);

    /* First try non-blocking acquire without releasing the GIL. If this fails
     * and we have a timeout, release the GIL and block until we get the lock
     * or the timeout expires. */

    do {
        err = sem_trywait(sem);
    } while (err != 0 && errno == EINTR);

    if (err == 0)
        return ACQUIRE_OK;

    if (errno != EAGAIN) {
        set_error(errno, "sem_trywait");
        return ACQUIRE_ERROR;
    }

    if (timeout == 0)
        return ACQUIRE_FAIL;

    Py_BEGIN_ALLOW_THREADS;

    do {
        if (timeout > 0)
            err = sem_timedwait(sem, &deadline);
        else
            err = sem_wait(sem);
    } while (err != 0 && errno == EINTR);

    Py_END_ALLOW_THREADS;

    if (err != 0) {
        if (timeout > 0 && errno == ETIMEDOUT)
            return ACQUIRE_FAIL;

        /* Should never happen */
        set_error(errno, timeout > 0 ? "sem_timedwait" : "sem_wait");
        return ACQUIRE_ERROR;
    }

    return ACQUIRE_OK;
}

static int
release_lock(sem_t *sem)
{
    int err;

    err = sem_post(sem);

    /* Either EINVAL, or EOVERFLOW, should never happen. */
    if (err != 0) {
        set_error(errno, "sem_post");
        return -1;
    }

    return 0;
}

/* Lock */

typedef struct {
    PyObject_HEAD
    sem_t sem;
    long owner;
    PyObject *weakrefs;
} Lock;

PyDoc_STRVAR(Lock_doc,
"Lock()");

static PyObject *
Lock_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    Lock *self;
    int err;

    self = (Lock *)type->tp_alloc(type, 0);
    if (self == NULL)
        return NULL;

    /* First initialize all fields so Lock_dealloc does the right thing if
     * initializing the semaphore fails. */
    self->owner = 0;
    self->weakrefs = NULL;

    err = sem_init(&self->sem, 0, 1);
    if (err) {
        int saved_errno = errno;
        Py_CLEAR(self);
        set_error(saved_errno, "sem_init");
        return NULL;
    }

    return (PyObject *)self;
}

static void
Lock_dealloc(Lock* self)
{
    if (self->weakrefs)
        PyObject_ClearWeakRefs((PyObject *) self);

    /* This must not be called when other threads are waiting on the semaphore
     * in sem_wait(). We rely on the reference counting machanisim to call this
     * only when no object has a reference to the Lock object. */
    sem_destroy(&self->sem);

    PyObject_Del(self);
}

static PyObject *
Lock_acquire(Lock *self, PyObject *args, PyObject *kwds)
{
    double timeout;
    acquire_result res;

    if (acquire_parse_args(args, kwds, &timeout))
        return NULL;

    res = acquire_lock(&self->sem, timeout);
    if (res == ACQUIRE_ERROR)
        return NULL;

    if (res == ACQUIRE_OK)
        self->owner = PyThread_get_thread_ident();

    return PyBool_FromLong(res == ACQUIRE_OK);
}

static PyObject *
Lock_release(Lock *self, PyObject *args)
{
    int err;

    /* Sanity check: the lock must be locked */
    if (self->owner == 0) {
        PyErr_SetString(ThreadError, "release unlocked lock");
        return NULL;
    }

    err = release_lock(&self->sem);
    if (err != 0)
        return NULL;

    self->owner = 0;

    Py_RETURN_NONE;
}

static PyObject *
Lock_locked(Lock *self)
{
    return PyBool_FromLong(self->owner);
}

static PyObject *
Lock_is_owned(Lock *self)
{
    long tid = PyThread_get_thread_ident();
    return PyBool_FromLong(self->owner == tid);
}

static PyObject *
Lock_release_save(Lock *self)
{
    PyObject *saved_state;

    if (self->owner == 0) {
        PyErr_SetString(PyExc_RuntimeError,
                        "cannot release un-acquired lock");
        return NULL;
    }

    saved_state = Py_BuildValue("l", self->owner);
    if (saved_state == NULL)
        return NULL;

    if (release_lock(&self->sem) != 0)
        return NULL;

    self->owner = 0;

    return saved_state;
}

static PyObject *
Lock_acquire_restore(Lock *self, PyObject *args)
{
    long owner;
    acquire_result res;

    if (!PyArg_ParseTuple(args, "l:_acquire_restore", &owner))
        return NULL;

    /* May block forever but cannot fail unless the underlying sem_wait call
     * fails (unlikely). */
    res = acquire_lock(&self->sem, -1);
    if (res == ACQUIRE_ERROR)
        return NULL;

    assert(res == ACQUIRE_OK);
    assert(self->owner == 0);

    self->owner = owner;

    Py_RETURN_NONE;
}

static PyMethodDef Lock_methods[] = {
    {"acquire", (PyCFunction)Lock_acquire, METH_VARARGS | METH_KEYWORDS, NULL},
    {"__enter__", (PyCFunction)Lock_acquire, METH_VARARGS | METH_KEYWORDS, NULL},
    {"release", (PyCFunction)Lock_release, METH_VARARGS, NULL},
    {"__exit__", (PyCFunction)Lock_release, METH_VARARGS, NULL},
    {"locked", (PyCFunction)Lock_locked, METH_NOARGS, NULL},
    {"_is_owned", (PyCFunction)Lock_is_owned, METH_NOARGS, NULL},
    {"_release_save", (PyCFunction)Lock_release_save, METH_NOARGS, NULL},
    {"_acquire_restore", (PyCFunction)Lock_acquire_restore, METH_VARARGS, NULL},
    {NULL}  /* Sentinel */
};

static PyTypeObject LockType = {
    PyObject_HEAD_INIT(NULL)
    0,                          /* ob_size */
    "_cthreading.Lock",         /* tp_name */
    sizeof(Lock),               /* tp_basicsize */
    0,                          /* tp_itemsize */
    (destructor)Lock_dealloc,   /* tp_dealloc */
    0,                          /* tp_print */
    0,                          /* tp_getattr */
    0,                          /* tp_setattr */
    0,                          /* tp_compare */
    0,                          /* tp_repr */
    0,                          /* tp_as_number */
    0,                          /* tp_as_sequence */
    0,                          /* tp_as_mapping */
    0,                          /* tp_hash */
    0,                          /* tp_call */
    0,                          /* tp_str */
    0,                          /* tp_getattro */
    0,                          /* tp_setattro */
    0,                          /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,         /* tp_flags */
    Lock_doc,                   /* tp_doc */
    0,                          /* tp_traverse */
    0,                          /* tp_clear */
    0,                          /* tp_richcompare */
    offsetof(Lock, weakrefs),   /* tp_weaklistoffset */
    0,                          /* tp_iter */
    0,                          /* tp_iternext */
    Lock_methods,               /* tp_methods */
    0,                          /* tp_members */
    0,                          /* tp_getset */
    0,                          /* tp_base */
    0,                          /* tp_dict */
    0,                          /* tp_descr_get */
    0,                          /* tp_descr_set */
    0,                          /* tp_dictoffset */
    0,                          /* tp_init */
    0,                          /* tp_alloc */
    Lock_new,                   /* tp_new */
};

/* RLock */

typedef struct {
    PyObject_HEAD
    sem_t sem;
    long owner;
    unsigned long count;
    PyObject *weakrefs;
} RLock;

PyDoc_STRVAR(RLock_doc,
"RLock()");

static PyObject *
RLock_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    RLock *self;
    int err;

    self = (RLock *)type->tp_alloc(type, 0);
    if (self == NULL)
        return NULL;

    /* First initialize all fields so RLock_dealloc does the right thing if
     * initializing the semaphore fails. */
    self->owner = 0;
    self->count = 0;
    self->weakrefs = NULL;

    err = sem_init(&self->sem, 0, 1);
    if (err) {
        int saved_errno = errno;
        Py_CLEAR(self);
        set_error(saved_errno, "sem_init");
        return NULL;
    }

    return (PyObject *)self;
}

static void
RLock_dealloc(RLock* self)
{
    if (self->weakrefs)
        PyObject_ClearWeakRefs((PyObject *) self);

    /* This must not be called when other threads are waiting on the semaphore
     * in sem_wait(). We rely on the reference counting machanisim to call this
     * only when no object has a reference to the Lock object. */
    sem_destroy(&self->sem);

    PyObject_Del(self);
}

static PyObject *
RLock_acquire(RLock *self, PyObject *args, PyObject *kwds)
{
    double timeout;
    long tid;
    acquire_result res;

    if (acquire_parse_args(args, kwds, &timeout))
        return NULL;

    tid = PyThread_get_thread_ident();
    if (self->count > 0 && self->owner == tid) {
        unsigned long count = self->count + 1;
        if (count <= self->count) {
            PyErr_SetString(PyExc_OverflowError,
                            "Internal lock count overflowed");
            return NULL;
        }

        self->count = count;
        Py_RETURN_TRUE;
    }

    res = acquire_lock(&self->sem, timeout);
    if (res == ACQUIRE_ERROR)
        return NULL;

    if (res == ACQUIRE_OK) {
        assert(self->count == 0);
        self->owner = tid;
        self->count = 1;
    }

    return PyBool_FromLong(res == ACQUIRE_OK);
}

static PyObject *
RLock_release(RLock *self, PyObject *args)
{
    long tid = PyThread_get_thread_ident();

    if (self->count == 0 || self->owner != tid) {
        PyErr_SetString(PyExc_RuntimeError,
                        "cannot release un-acquired lock");
        return NULL;
    }

    if (self->count > 1) {
        --self->count;
        Py_RETURN_NONE;
    }

    assert(self->count == 1);
    if (release_lock(&self->sem) != 0)
        return NULL;

    self->count = 0;
    self->owner = 0;

    Py_RETURN_NONE;
}

static PyObject *
RLock_is_owned(RLock *self)
{
    long tid = PyThread_get_thread_ident();
    return PyBool_FromLong(self->count > 0 && self->owner == tid);
}

static PyObject *
RLock_release_save(RLock *self)
{
    PyObject *saved_state;

    if (self->count == 0) {
        PyErr_SetString(PyExc_RuntimeError,
                        "cannot release un-acquired lock");
        return NULL;
    }

    saved_state = Py_BuildValue("kl", self->count, self->owner);
    if (saved_state == NULL)
        return NULL;

    if (release_lock(&self->sem) != 0)
        return NULL;

    self->count = 0;
    self->owner = 0;

    return saved_state;
}

static PyObject *
RLock_acquire_restore(RLock *self, PyObject *args)
{
    unsigned long count;
    long owner;
    acquire_result res;

    if (!PyArg_ParseTuple(args, "(kl):_acquire_restore", &count, &owner))
        return NULL;

    /* May block forever but cannot fail unless the underlying sem_wait call
     * fails (unlikely). */
    res = acquire_lock(&self->sem, -1);
    if (res == ACQUIRE_ERROR)
        return NULL;

    assert(res == ACQUIRE_OK);
    assert(self->owner == 0);
    assert(self->count == 0);

    self->owner = owner;
    self->count = count;

    Py_RETURN_NONE;
}

static PyMethodDef RLock_methods[] = {
    {"acquire", (PyCFunction)RLock_acquire, METH_VARARGS | METH_KEYWORDS, NULL},
    {"__enter__", (PyCFunction)RLock_acquire, METH_VARARGS | METH_KEYWORDS, NULL},
    {"release", (PyCFunction)RLock_release, METH_VARARGS, NULL},
    {"__exit__", (PyCFunction)RLock_release, METH_VARARGS, NULL},
    {"_is_owned", (PyCFunction)RLock_is_owned, METH_NOARGS, NULL},
    {"_release_save", (PyCFunction)RLock_release_save, METH_NOARGS, NULL},
    {"_acquire_restore", (PyCFunction)RLock_acquire_restore, METH_VARARGS, NULL},
    {NULL}  /* Sentinel */
};

static PyTypeObject RLockType = {
    PyObject_HEAD_INIT(NULL)
    0,                          /* ob_size */
    "_cthreading.RLock",        /* tp_name */
    sizeof(RLock),              /* tp_basicsize */
    0,                          /* tp_itemsize */
    (destructor)RLock_dealloc,  /* tp_dealloc */
    0,                          /* tp_print */
    0,                          /* tp_getattr */
    0,                          /* tp_setattr */
    0,                          /* tp_compare */
    0,                          /* tp_repr */
    0,                          /* tp_as_number */
    0,                          /* tp_as_sequence */
    0,                          /* tp_as_mapping */
    0,                          /* tp_hash */
    0,                          /* tp_call */
    0,                          /* tp_str */
    0,                          /* tp_getattro */
    0,                          /* tp_setattro */
    0,                          /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,         /* tp_flags */
    RLock_doc,                  /* tp_doc */
    0,                          /* tp_traverse */
    0,                          /* tp_clear */
    0,                          /* tp_richcompare */
    offsetof(RLock, weakrefs),  /* tp_weaklistoffset */
    0,                          /* tp_iter */
    0,                          /* tp_iternext */
    RLock_methods,              /* tp_methods */
    0,                          /* tp_members */
    0,                          /* tp_getset */
    0,                          /* tp_base */
    0,                          /* tp_dict */
    0,                          /* tp_descr_get */
    0,                          /* tp_descr_set */
    0,                          /* tp_dictoffset */
    0,                          /* tp_init */
    0,                          /* tp_alloc */
    RLock_new,                  /* tp_new */
};

/* waitq */

#define WAITER_UNUSED ((struct waiter *) -1)

struct waiter {
    sem_t sem;
    struct waiter *next;
    struct waiter *prev;
};

static int
waiter_init(struct waiter *waiter)
{
    waiter->next = waiter->prev = WAITER_UNUSED;

    /* Initialize in blocked state */
    if (sem_init(&waiter->sem, 0, 0) != 0) {
        set_error(errno, "sem_init");
        return -1;
    }

    return 0;
}

static void
waiter_destroy(struct waiter *waiter)
{
    assert(waiter->next == WAITER_UNUSED && waiter->prev == WAITER_UNUSED);
    sem_destroy(&waiter->sem);
}

struct waitq {
    struct waiter *first;
    struct waiter *last;
    int count;
};

static void
waitq_init(struct waitq *waitq)
{
    waitq->first = waitq->last = NULL;
    waitq->count = 0;
}

static void
waitq_append(struct waitq *waitq, struct waiter *waiter)
{
    assert(waiter->next == WAITER_UNUSED && waiter->prev == WAITER_UNUSED);

    waiter->next = NULL;
    waiter->prev = waitq->last;

    if (waitq->last)
        waitq->last->next = waiter;
    else
        waitq->first = waiter;

    waitq->last = waiter;

    waitq->count++;
}

static void
waitq_remove(struct waitq *waitq, struct waiter *waiter)
{
    if (waiter->next == WAITER_UNUSED)
        return;

    if (waiter->prev)
        waiter->prev->next = waiter->next;
    else
        waitq->first = waiter->next;

    if (waiter->next)
        waiter->next->prev = waiter->prev;
    else
        waitq->last = waiter->prev;

    waiter->prev = waiter->next = WAITER_UNUSED;

    waitq->count--;
    assert(waitq->count >= 0);
}

/* Condition */

typedef struct {
    PyObject_HEAD
    PyObject *lock;
    PyObject *acquire;
    PyObject *release;
    PyObject *is_owned;
    PyObject *release_save;
    PyObject *acquire_restore;
    struct waitq waiters;
    PyObject *weakrefs;
} Condition;

PyDoc_STRVAR(Condition_doc,
"Condition(lock=None)");

static int
Condition_init(Condition *self, PyObject *args, PyObject *kwds)
{
    PyObject *lock = Py_None;
    PyObject *acquire = NULL;
    PyObject *release = NULL;
    PyObject *is_owned = NULL;
    PyObject *release_save = NULL;
    PyObject *acquire_restore = NULL;
    PyObject *tmp = NULL;
    static char *kwlist[] = {"lock", NULL};

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|O", kwlist, &lock))
        return -1;

    if (lock == Py_None) {
        lock = PyObject_CallObject((PyObject *)&RLockType, NULL);
        if (lock == NULL)
            return -1;
    } else {
        Py_INCREF(lock);
    }

    tmp = self->lock;
    self->lock = lock;
    Py_CLEAR(tmp);

    acquire = PyObject_GetAttrString(self->lock, "acquire");
    if (acquire == NULL)
        return -1;

    tmp = self->acquire;
    self->acquire = acquire;
    Py_CLEAR(tmp);

    release = PyObject_GetAttrString(self->lock, "release");
    if (release == NULL)
        return -1;

    tmp = self->release;
    self->release = release;
    Py_CLEAR(tmp);

    is_owned = PyObject_GetAttrString(self->lock, "_is_owned");
    if (is_owned == NULL)
        return -1;

    tmp = self->is_owned;
    self->is_owned = is_owned;
    Py_CLEAR(tmp);

    release_save = PyObject_GetAttrString(self->lock, "_release_save");
    if (release_save == NULL)
        return -1;

    tmp = self->release_save;
    self->release_save = release_save;
    Py_CLEAR(tmp);

    acquire_restore = PyObject_GetAttrString(self->lock, "_acquire_restore");
    if (acquire_restore == NULL)
        return -1;

    tmp = self->acquire_restore;
    self->acquire_restore = acquire_restore;
    Py_CLEAR(tmp);

    waitq_init(&self->waiters);

    return 0;
}

static void
Condition_dealloc(Condition* self)
{
    assert(self->waiters.first == NULL && self->waiters.last == NULL);

    if (self->weakrefs)
        PyObject_ClearWeakRefs((PyObject *) self);

    Py_CLEAR(self->lock);
    Py_CLEAR(self->acquire);
    Py_CLEAR(self->release);
    Py_CLEAR(self->is_owned);
    Py_CLEAR(self->release_save);
    Py_CLEAR(self->acquire_restore);

    PyObject_Del(self);
}

static PyObject *
Condition_release_save(Condition *self)
{
    return PyObject_CallObject(self->release_save, NULL);
}

static PyObject *
Condition_acquire_restore(Condition *self, PyObject *args)
{
    return PyObject_CallObject(self->acquire_restore, args);
}

static acquire_result
Condition_wait_released(Condition *self, struct waiter *waiter, double timeout)
{
    PyObject *saved_state = NULL;
    PyObject *r = NULL;
    acquire_result res;

    saved_state = PyObject_CallObject(self->release_save, NULL);
    if (saved_state == NULL)
        return ACQUIRE_ERROR;

    res = acquire_lock(&waiter->sem, timeout);

    r = PyObject_CallFunctionObjArgs(self->acquire_restore, saved_state, NULL);
    if (r == NULL)
        res = ACQUIRE_ERROR;

    Py_CLEAR(saved_state);
    Py_CLEAR(r);

    return res;
}

static int
Condition_is_owned_internal(Condition *self)
{
    PyObject *r;
    int is_owned;

    r = PyObject_CallObject(self->is_owned, NULL);
    is_owned = r == Py_True;
    Py_CLEAR(r);

    return is_owned;
}

static PyObject *
Condition_notify_waiters(Condition *self, int count)
{
    int i;

    if (!Condition_is_owned_internal(self)) {
        PyErr_SetString(PyExc_RuntimeError,
                        "cannot notify un-acquired condition");
        return NULL;
    }

    for (i = 0; i < count && self->waiters.first != NULL; i++) {
        struct waiter *waiter = self->waiters.first;
        if (release_lock(&waiter->sem) != 0)
            return NULL;
        waitq_remove(&self->waiters, waiter);
    }

    Py_RETURN_NONE;
}

static PyObject *
Condition_acquire(Condition *self, PyObject *args, PyObject *kwds)
{
    assert(args != NULL);
    return PyObject_Call(self->acquire, args, kwds);
}

static PyObject *
Condition_release(Condition *self, PyObject *args)
{
    return PyObject_CallObject(self->release, args);
}

static int
Condition_wait_parse_args(PyObject *args, PyObject *kwds, double *timeout)
{
    char *kwlist[] = {"timeout", "balancing", NULL};
    PyObject *obj = Py_None;
    PyObject *balancing = NULL; /* Unused */

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|OO:wait", kwlist,
                                     &obj, &balancing))
        return -1;

    if (parse_timeout(obj, timeout) != 0)
        return -1;

    return 0;
}

static PyObject *
Condition_wait(Condition *self, PyObject *args, PyObject *kwds)
{
    struct waiter waiter;
    double timeout;
    acquire_result res;

    if (Condition_wait_parse_args(args, kwds, &timeout) != 0)
        return NULL;

    if (!Condition_is_owned_internal(self)) {
        PyErr_SetString(PyExc_RuntimeError,
                        "cannot wait on un-acquired condition");
        return NULL;
    }

    if (waiter_init(&waiter) != 0)
        return NULL;

    waitq_append(&self->waiters, &waiter);

    res = Condition_wait_released(self, &waiter, timeout);

    if (res != ACQUIRE_OK)
        waitq_remove(&self->waiters, &waiter);

    waiter_destroy(&waiter);

    if (res == ACQUIRE_ERROR)
        return NULL;

    return PyBool_FromLong(res == ACQUIRE_OK);
}

static PyObject *
Condition_notify(Condition *self, PyObject *args)
{
    int count = 1;

    if (!PyArg_ParseTuple(args, "|i", &count))
        return NULL;

    return Condition_notify_waiters(self, count);
}

static PyObject *
Condition_notify_all(Condition *self)
{
    return Condition_notify_waiters(self, self->waiters.count);
}

static PyObject *
Condition_is_owned(Condition *self)
{
    return PyObject_CallObject(self->is_owned, NULL);
}

static PyMethodDef Condition_methods[] = {
    {"acquire", (PyCFunction)Condition_acquire, METH_VARARGS | METH_KEYWORDS, NULL},
    {"__enter__", (PyCFunction)Condition_acquire, METH_VARARGS | METH_KEYWORDS, NULL},
    {"release", (PyCFunction)Condition_release, METH_VARARGS, NULL},
    {"__exit__", (PyCFunction)Condition_release, METH_VARARGS, NULL},
    {"wait", (PyCFunction)Condition_wait, METH_VARARGS | METH_KEYWORDS, NULL},
    {"notify", (PyCFunction)Condition_notify, METH_VARARGS, NULL},
    {"notify_all", (PyCFunction)Condition_notify_all, METH_VARARGS, NULL},
    {"notifyAll", (PyCFunction)Condition_notify_all, METH_VARARGS, NULL},
    {"_is_owned", (PyCFunction)Condition_is_owned, METH_NOARGS, NULL},
    {"_release_save", (PyCFunction)Condition_release_save, METH_NOARGS, NULL},
    {"_acquire_restore", (PyCFunction)Condition_acquire_restore, METH_VARARGS, NULL},
    {NULL}  /* Sentinel */
};

static PyTypeObject ConditionType = {
    PyObject_HEAD_INIT(NULL)
    0,                          /* ob_size */
    "_cthreading.Condition",    /* tp_name */
    sizeof(Condition),          /* tp_basicsize */
    0,                          /* tp_itemsize */
    (destructor)Condition_dealloc,  /* tp_dealloc */
    0,                          /* tp_print */
    0,                          /* tp_getattr */
    0,                          /* tp_setattr */
    0,                          /* tp_compare */
    0,                          /* tp_repr */
    0,                          /* tp_as_number */
    0,                          /* tp_as_sequence */
    0,                          /* tp_as_mapping */
    0,                          /* tp_hash */
    0,                          /* tp_call */
    0,                          /* tp_str */
    0,                          /* tp_getattro */
    0,                          /* tp_setattro */
    0,                          /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,         /* tp_flags */
    Condition_doc,              /* tp_doc */
    0,                          /* tp_traverse */
    0,                          /* tp_clear */
    0,                          /* tp_richcompare */
    offsetof(Condition, weakrefs),  /* tp_weaklistoffset */
    0,                          /* tp_iter */
    0,                          /* tp_iternext */
    Condition_methods,          /* tp_methods */
    0,                          /* tp_members */
    0,                          /* tp_getset */
    0,                          /* tp_base */
    0,                          /* tp_dict */
    0,                          /* tp_descr_get */
    0,                          /* tp_descr_set */
    0,                          /* tp_dictoffset */
    (initproc)Condition_init,   /* tp_init */
    0,                          /* tp_alloc */
    0,                          /* tp_new */
};

/* Module */

static int
import_thread_error(void)
{
    PyObject *thread_mod;
    PyObject *thread_dict;

    thread_mod = PyImport_ImportModule("thread");
    if (thread_mod == NULL)
        return -1;

    thread_dict = PyModule_GetDict(thread_mod);
    Py_CLEAR(thread_mod);
    if (thread_dict == NULL)
        return -1;

    ThreadError = PyDict_GetItemString(thread_dict, "error");
    if (ThreadError == NULL)
        return -1;

    Py_INCREF(ThreadError);

    return 0;
}

PyDoc_STRVAR(module_doc,
"Copyright 2014 Red Hat, Inc.  All rights reserved.\n\
\n\
This copyrighted material is made available to anyone wishing to use,\n\
modify, copy, or redistribute it subject to the terms and conditions\n\
of the GNU General Public License v2 or (at your option) any later version.");

static PyMethodDef module_methods[] = {
    {NULL}  /* Sentinel */
};

PyMODINIT_FUNC
init_cthreading(void)
{
    PyObject* module;

    if (import_thread_error())
        return;

    if (PyType_Ready(&LockType) < 0)
        return;

    if (PyType_Ready(&RLockType) < 0)
        return;

    /* Portable init */
    ConditionType.tp_new = PyType_GenericNew;
    if (PyType_Ready(&ConditionType) < 0)
        return;

    module = Py_InitModule3("_cthreading", module_methods, module_doc);

    Py_INCREF(&LockType);
    PyModule_AddObject(module, "Lock", (PyObject *)&LockType);

    Py_INCREF(&RLockType);
    PyModule_AddObject(module, "RLock", (PyObject *)&RLockType);

    Py_INCREF(&ConditionType);
    PyModule_AddObject(module, "Condition", (PyObject *)&ConditionType);
}
