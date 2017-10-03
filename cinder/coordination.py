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
import uuid

import decorator
from oslo_config import cfg
from oslo_log import log
from oslo_utils import timeutils
from tooz import coordination

from cinder import exception
from cinder.i18n import _

LOG = log.getLogger(__name__)

coordination_opts = [
    cfg.StrOpt('backend_url',
               default='file://$state_path',
               help='The backend URL to use for distributed coordination.'),
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

    def start(self):
        if self.started:
            return

        # NOTE(bluex): Tooz expects member_id as a byte string.
        member_id = (self.prefix + self.agent_id).encode('ascii')
        self.coordinator = coordination.get_coordinator(
            cfg.CONF.coordination.backend_url, member_id)
        self.coordinator.start(start_heart=True)
        self.started = True

    def stop(self):
        """Disconnect from coordination backend and stop heartbeat."""
        if self.started:
            self.coordinator.stop()
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


COORDINATOR = Coordinator(prefix='cinder-')


def synchronized(lock_name, blocking=True, coordinator=COORDINATOR):
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

    @decorator.decorator
    def _synchronized(f, *a, **k):
        call_args = inspect.getcallargs(f, *a, **k)
        call_args['f_name'] = f.__name__
        lock = coordinator.get_lock(lock_name.format(**call_args))
        t1 = timeutils.now()
        t2 = None
        try:
            with lock(blocking):
                t2 = timeutils.now()
                LOG.debug('Lock "%(name)s" acquired by "%(function)s" :: '
                          'waited %(wait_secs)0.3fs',
                          {'name': lock.name,
                           'function': f.__name__,
                           'wait_secs': (t2 - t1)})
                return f(*a, **k)
        finally:
            t3 = timeutils.now()
            if t2 is None:
                held_secs = "N/A"
            else:
                held_secs = "%0.3fs" % (t3 - t2)
            LOG.debug('Lock "%(name)s" released by "%(function)s" :: held '
                      '%(held_secs)s',
                      {'name': lock.name,
                       'function': f.__name__,
                       'held_secs': held_secs})

    return _synchronized
