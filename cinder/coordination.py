# Copyright 2015 Intel
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Coordination and locking utilities."""

import inspect
import random
import threading
import uuid

import eventlet
from eventlet import tpool
import itertools
from oslo_config import cfg
from oslo_log import log
import six
from tooz import coordination
from tooz import locking

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW

LOG = log.getLogger(__name__)

coordination_opts = [
    cfg.StrOpt('backend_url',
               default='file://$state_path',
               help='The backend URL to use for distributed coordination.'),
    cfg.FloatOpt('heartbeat',
                 default=1.0,
                 help='Number of seconds between heartbeats for distributed '
                      'coordination.'),
    cfg.FloatOpt('initial_reconnect_backoff',
                 default=0.1,
                 help='Initial number of seconds to wait after failed '
                      'reconnection.'),
    cfg.FloatOpt('max_reconnect_backoff',
                 default=60.0,
                 help='Maximum number of seconds between sequential '
                      'reconnection retries.'),

]

CONF = cfg.CONF
CONF.register_opts(coordination_opts, group='coordination')


class Coordinator(object):
    """Tooz coordination wrapper.

    Coordination member id is created from concatenated
    `prefix` and `agent_id` parameters.

    :param str agent_id: Agent identifier
    :param str prefix: Used to provide member identifier with a
        meaningful prefix.
    """

    def __init__(self, agent_id=None, prefix=''):
        self.coordinator = None
        self.agent_id = agent_id or str(uuid.uuid4())
        self.started = False
        self.prefix = prefix
        self._ev = None
        self._dead = None

    def is_active(self):
        return self.coordinator is not None

    def start(self):
        """Connect to coordination backend and start heartbeat."""
        if not self.started:
            try:
                self._dead = threading.Event()
                self._start()
                self.started = True
                # NOTE(bluex): Start heartbeat in separate thread to avoid
                # being blocked by long coroutines.
                if self.coordinator and self.coordinator.requires_beating:
                    self._ev = eventlet.spawn(
                        lambda: tpool.execute(self.heartbeat))
            except coordination.ToozError:
                LOG.exception(_LE('Error starting coordination backend.'))
                raise
            LOG.info(_LI('Coordination backend started successfully.'))

    def stop(self):
        """Disconnect from coordination backend and stop heartbeat."""
        if self.started:
            self.coordinator.stop()
            self._dead.set()
            if self._ev is not None:
                self._ev.wait()
            self._ev = None
            self.coordinator = None
            self.started = False

    def get_lock(self, name):
        """Return a Tooz backend lock.

        :param str name: The lock name that is used to identify it
            across all nodes.
        """
        # NOTE(bluex): Tooz expects lock name as a byte string.
        lock_name = (self.prefix + name).encode('ascii')
        if self.coordinator is not None:
            return self.coordinator.get_lock(lock_name)
        else:
            raise exception.LockCreationFailed(_('Coordinator uninitialized.'))

    def heartbeat(self):
        """Coordinator heartbeat.

        Method that every couple of seconds (config: `coordination.heartbeat`)
        sends heartbeat to prove that the member is not dead.

        If connection to coordination backend is broken it tries to
        reconnect every couple of seconds
        (config: `coordination.initial_reconnect_backoff` up to
        `coordination.max_reconnect_backoff`)

        """
        while self.coordinator is not None and not self._dead.is_set():
            try:
                self._heartbeat()
            except coordination.ToozConnectionError:
                self._reconnect()
            else:
                self._dead.wait(cfg.CONF.coordination.heartbeat)

    def _start(self):
        # NOTE(bluex): Tooz expects member_id as a byte string.
        member_id = (self.prefix + self.agent_id).encode('ascii')
        self.coordinator = coordination.get_coordinator(
            cfg.CONF.coordination.backend_url, member_id)
        self.coordinator.start()

    def _heartbeat(self):
        try:
            self.coordinator.heartbeat()
            return True
        except coordination.ToozConnectionError:
            LOG.exception(_LE('Connection error while sending a heartbeat '
                              'to coordination backend.'))
            raise
        except coordination.ToozError:
            LOG.exception(_LE('Error sending a heartbeat to coordination '
                              'backend.'))
        return False

    def _reconnect(self):
        """Reconnect with jittered exponential backoff increase."""
        LOG.info(_LI('Reconnecting to coordination backend.'))
        cap = cfg.CONF.coordination.max_reconnect_backoff
        backoff = base = cfg.CONF.coordination.initial_reconnect_backoff
        for attempt in itertools.count(1):
            try:
                self._start()
                break
            except coordination.ToozError:
                backoff = min(cap, random.uniform(base, backoff * 3))
                msg = _LW('Reconnect attempt %(attempt)s failed. '
                          'Next try in %(backoff).2fs.')
                LOG.warning(msg, {'attempt': attempt, 'backoff': backoff})
                self._dead.wait(backoff)
        LOG.info(_LI('Reconnected to coordination backend.'))


COORDINATOR = Coordinator(prefix='cinder-')


class Lock(locking.Lock):
    """Lock with dynamic name.

    :param str lock_name: Lock name.
    :param dict lock_data: Data for lock name formatting.
    :param coordinator: Coordinator class to use when creating lock.
        Defaults to the global coordinator.

    Using it like so::

        with Lock('mylock'):
           ...

    ensures that only one process at a time will execute code in context.
    Lock name can be formatted using Python format string syntax::

        Lock('foo-{volume.id}, {'volume': ...,})

    Available field names are keys of lock_data.
    """
    def __init__(self, lock_name, lock_data=None, coordinator=None):
        super(Lock, self).__init__(str(id(self)))
        lock_data = lock_data or {}
        self.coordinator = coordinator or COORDINATOR
        self.blocking = True
        self.lock = self._prepare_lock(lock_name, lock_data)

    def _prepare_lock(self, lock_name, lock_data):
        if not isinstance(lock_name, six.string_types):
            raise ValueError(_('Not a valid string: %s') % lock_name)
        return self.coordinator.get_lock(lock_name.format(**lock_data))

    def acquire(self, blocking=None):
        """Attempts to acquire lock.

        :param blocking: If True, blocks until the lock is acquired. If False,
            returns right away. Otherwise, the value is used as a timeout
            value and the call returns maximum after this number of seconds.
        :return: returns true if acquired (false if not)
        :rtype: bool
        """
        blocking = self.blocking if blocking is None else blocking
        return self.lock.acquire(blocking=blocking)

    def release(self):
        """Attempts to release lock.

        The behavior of releasing a lock which was not acquired in the first
        place is undefined.
        """
        self.lock.release()


def synchronized(lock_name, blocking=True, coordinator=None):
    """Synchronization decorator.

    :param str lock_name: Lock name.
    :param blocking: If True, blocks until the lock is acquired.
            If False, raises exception when not acquired. Otherwise,
            the value is used as a timeout value and if lock is not acquired
            after this number of seconds exception is raised.
    :param coordinator: Coordinator class to use when creating lock.
        Defaults to the global coordinator.
    :raises tooz.coordination.LockAcquireFailed: if lock is not acquired

    Decorating a method like so::

        @synchronized('mylock')
        def foo(self, *args):
           ...

    ensures that only one process will execute the foo method at a time.

    Different methods can share the same lock::

        @synchronized('mylock')
        def foo(self, *args):
           ...

        @synchronized('mylock')
        def bar(self, *args):
           ...

    This way only one of either foo or bar can be executing at a time.

    Lock name can be formatted using Python format string syntax::

        @synchronized('{f_name}-{vol.id}-{snap[name]}')
        def foo(self, vol, snap):
           ...

    Available field names are: decorated function parameters and
    `f_name` as a decorated function name.
    """
    def wrap(f):
        @six.wraps(f)
        def wrapped(*a, **k):
            call_args = inspect.getcallargs(f, *a, **k)
            call_args['f_name'] = f.__name__
            lock = Lock(lock_name, call_args, coordinator)
            with lock(blocking):
                return f(*a, **k)
        return wrapped
    return wrap
