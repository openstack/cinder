import threading
import weakref
import six
import time
import logging
from oslo_concurrency import lockutils

LOG = logging.getLogger(__name__)

class ReaderWriterLocks(object):
    """A garbage collected container of ReaderWriterLock.

    This collection internally uses a weak value dictionary so that when a
    ReaderWriterLock is no longer in use (by any threads) it will automatically be
    removed from this container by the garbage collector.
    """

    def __init__(self):
        self._rwlocks = weakref.WeakValueDictionary()
        self._lock = threading.Lock()

    def get(self, name):
        """Gets (or creates) a ReaderWriterLock with a given name.

        :param name: The ReaderWriterLock name to get/create (used to associate
                     previously created names with the same ReaderWriterLock).

        Returns an newly constructed ReaderWriterLock (or an existing one if it was
        already created for the given name).
        """
        with self._lock:
            try:
                return self._rwlocks[name]
            except KeyError:
                rw_lock = lockutils.ReaderWriterLock()
                self._rwlocks[name] = rw_lock
                return rw_lock

    def __len__(self):
        """Returns how many ReaderWriterLock exist at the current time."""
        return len(self._rwlocks)


_rwlocks = ReaderWriterLocks()


def get_rwlock(name, rwlocks=None):
    if rwlocks is None:
        rwlocks = _rwlocks
    return rwlocks.get(name)


def read_lock(name, rwlocks=None):
    """read_lock decorator.

    Decorating a method like so::

        @read_lock('mylock')
        def foo(self, *args):
           ...

    ensures that thread has a read lock.

    Different methods can share the same lock::

        @read_lock('mylock')
        def foo(self, *args):
           ...

        @read_lock('mylock')
        def bar(self, *args):
           ...

    This way both foo and bar can acquire the read lock.
    """

    def wrap(f):
        @six.wraps(f)
        def inner(*args, **kwargs):
            t1 = time.time()
            t2 = None
            try:
                rwlock = get_rwlock(name, rwlocks=rwlocks)
                with rwlock.read_lock():
                    t2 = time.time()
                    LOG.debug('Read Lock "%(name)s" acquired by "%(function)s" :: '
                              'waited %(wait_secs)0.3fs',
                              {'name': name, 'function': f.__name__,
                               'wait_secs': (t2 - t1)})
                    return f(*args, **kwargs)
            finally:
                t3 = time.time()
                if t2 is None:
                    held_secs = "N/A"
                else:
                    held_secs = "%0.3fs" % (t3 - t2)

                LOG.debug('Read Lock "%(name)s" released by "%(function)s" :: held '
                          '%(held_secs)s',
                          {'name': name, 'function': f.__name__,
                           'held_secs': held_secs})
        return inner
    return wrap


def write_lock(name, rwlocks=None):
    """write_lock decorator.

    Decorating a method like so::

        @write_lock('mylock')
        def foo(self, *args):
           ...

    ensures that only one thread can acquire lock in write mode.

    Different methods can share the same lock::

        @write_lock('mylock')
        def foo(self, *args):
           ...

        @write_lock('mylock')
        def bar(self, *args):
           ...

    This way only one of either foo or bar can acquire the write lock.
    """

    def wrap(f):
        @six.wraps(f)
        def inner(*args, **kwargs):
            t1 = time.time()
            t2 = None
            try:
                rwlock = get_rwlock(name, rwlocks=rwlocks)
                with rwlock.write_lock():
                    t2 = time.time()
                    LOG.debug('Write Lock "%(name)s" acquired by "%(function)s" :: '
                              'waited %(wait_secs)0.3fs',
                              {'name': name, 'function': f.__name__,
                               'wait_secs': (t2 - t1)})
                    return f(*args, **kwargs)
            finally:
                t3 = time.time()
                if t2 is None:
                    held_secs = "N/A"
                else:
                    held_secs = "%0.3fs" % (t3 - t2)

                LOG.debug('Write Lock "%(name)s" released by "%(function)s" :: held '
                          '%(held_secs)s',
                          {'name': name, 'function': f.__name__,
                           'held_secs': held_secs})
        return inner
    return wrap
