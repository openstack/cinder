# Copyright 2013 Red Hat, Inc.
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

__all__ = [
    'init',
    'cleanup',
    'set_defaults',
    'add_extra_exmods',
    'clear_extra_exmods',
    'get_allowed_exmods',
    'RequestContextSerializer',
    'get_client',
    'get_server',
    'get_notifier',
    'TRANSPORT_ALIASES',
]

from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_utils import importutils
profiler = importutils.try_import('osprofiler.profiler')

import cinder.context
import cinder.exception
from cinder.i18n import _LE, _LI
from cinder import objects
from cinder.objects import base

CONF = cfg.CONF
LOG = logging.getLogger(__name__)
TRANSPORT = None
NOTIFICATION_TRANSPORT = None
NOTIFIER = None

ALLOWED_EXMODS = [
    cinder.exception.__name__,
]
EXTRA_EXMODS = []

# NOTE(flaper87): The cinder.openstack.common.rpc entries are
# for backwards compat with Havana rpc_backend configuration
# values. The cinder.rpc entries are for compat with Folsom values.
TRANSPORT_ALIASES = {
    'cinder.openstack.common.rpc.impl_kombu': 'rabbit',
    'cinder.openstack.common.rpc.impl_qpid': 'qpid',
    'cinder.openstack.common.rpc.impl_zmq': 'zmq',
    'cinder.rpc.impl_kombu': 'rabbit',
    'cinder.rpc.impl_qpid': 'qpid',
    'cinder.rpc.impl_zmq': 'zmq',
}


def init(conf):
    global TRANSPORT, NOTIFICATION_TRANSPORT, NOTIFIER
    exmods = get_allowed_exmods()
    TRANSPORT = messaging.get_transport(conf,
                                        allowed_remote_exmods=exmods,
                                        aliases=TRANSPORT_ALIASES)
    NOTIFICATION_TRANSPORT = messaging.get_notification_transport(
        conf,
        allowed_remote_exmods=exmods,
        aliases=TRANSPORT_ALIASES)

    serializer = RequestContextSerializer(JsonPayloadSerializer())
    NOTIFIER = messaging.Notifier(NOTIFICATION_TRANSPORT,
                                  serializer=serializer)


def initialized():
    return None not in [TRANSPORT, NOTIFIER]


def cleanup():
    global TRANSPORT, NOTIFICATION_TRANSPORT, NOTIFIER
    if NOTIFIER is None:
        LOG.exception(_LE("RPC cleanup: NOTIFIER is None"))
    TRANSPORT.cleanup()
    NOTIFICATION_TRANSPORT.cleanup()
    TRANSPORT = NOTIFICATION_TRANSPORT = NOTIFIER = None


def set_defaults(control_exchange):
    messaging.set_transport_defaults(control_exchange)


def add_extra_exmods(*args):
    EXTRA_EXMODS.extend(args)


def clear_extra_exmods():
    del EXTRA_EXMODS[:]


def get_allowed_exmods():
    return ALLOWED_EXMODS + EXTRA_EXMODS


class JsonPayloadSerializer(messaging.NoOpSerializer):
    @staticmethod
    def serialize_entity(context, entity):
        return jsonutils.to_primitive(entity, convert_instances=True)


class RequestContextSerializer(messaging.Serializer):

    def __init__(self, base):
        self._base = base

    def serialize_entity(self, context, entity):
        if not self._base:
            return entity
        return self._base.serialize_entity(context, entity)

    def deserialize_entity(self, context, entity):
        if not self._base:
            return entity
        return self._base.deserialize_entity(context, entity)

    def serialize_context(self, context):
        _context = context.to_dict()
        if profiler is not None:
            prof = profiler.get()
            if prof:
                trace_info = {
                    "hmac_key": prof.hmac_key,
                    "base_id": prof.get_base_id(),
                    "parent_id": prof.get_id()
                }
                _context.update({"trace_info": trace_info})
        return _context

    def deserialize_context(self, context):
        trace_info = context.pop("trace_info", None)
        if trace_info:
            if profiler is not None:
                profiler.init(**trace_info)

        return cinder.context.RequestContext.from_dict(context)


def get_client(target, version_cap=None, serializer=None):
    assert TRANSPORT is not None
    serializer = RequestContextSerializer(serializer)
    return messaging.RPCClient(TRANSPORT,
                               target,
                               version_cap=version_cap,
                               serializer=serializer)


def get_server(target, endpoints, serializer=None):
    assert TRANSPORT is not None
    serializer = RequestContextSerializer(serializer)
    return messaging.get_rpc_server(TRANSPORT,
                                    target,
                                    endpoints,
                                    executor='eventlet',
                                    serializer=serializer)


def get_notifier(service=None, host=None, publisher_id=None):
    assert NOTIFIER is not None
    if not publisher_id:
        publisher_id = "%s.%s" % (service, host or CONF.host)
    return NOTIFIER.prepare(publisher_id=publisher_id)


LAST_RPC_VERSIONS = {}
LAST_OBJ_VERSIONS = {}


class RPCAPI(object):
    """Mixin class aggregating methods related to RPC API compatibility."""

    RPC_API_VERSION = '1.0'
    TOPIC = ''
    BINARY = ''

    def __init__(self):
        target = messaging.Target(topic=self.TOPIC,
                                  version=self.RPC_API_VERSION)
        obj_version_cap = self.determine_obj_version_cap()
        serializer = base.CinderObjectSerializer(obj_version_cap)

        rpc_version_cap = self.determine_rpc_version_cap()
        self.client = get_client(target, version_cap=rpc_version_cap,
                                 serializer=serializer)

    def _compat_ver(self, current, *legacy):
        versions = (current,) + legacy
        for version in versions[:-1]:
            if self.client.can_send_version(version):
                return version
        return versions[-1]

    @classmethod
    def determine_rpc_version_cap(cls):
        global LAST_RPC_VERSIONS
        if cls.BINARY in LAST_RPC_VERSIONS:
            return LAST_RPC_VERSIONS[cls.BINARY]

        version_cap = objects.Service.get_minimum_rpc_version(
            cinder.context.get_admin_context(), cls.BINARY)
        if not version_cap:
            # If there is no service we assume they will come up later and will
            # have the same version as we do.
            version_cap = cls.RPC_API_VERSION
        LOG.info(_LI('Automatically selected %(binary)s RPC version '
                     '%(version)s as minimum service version.'),
                 {'binary': cls.BINARY, 'version': version_cap})
        LAST_RPC_VERSIONS[cls.BINARY] = version_cap
        return version_cap

    @classmethod
    def determine_obj_version_cap(cls):
        global LAST_OBJ_VERSIONS
        if cls.BINARY in LAST_OBJ_VERSIONS:
            return LAST_OBJ_VERSIONS[cls.BINARY]

        version_cap = objects.Service.get_minimum_obj_version(
            cinder.context.get_admin_context(), cls.BINARY)
        # If there is no service we assume they will come up later and will
        # have the same version as we do.
        if not version_cap:
            version_cap = base.OBJ_VERSIONS.get_current()
        LOG.info(_LI('Automatically selected %(binary)s objects version '
                     '%(version)s as minimum service version.'),
                 {'binary': cls.BINARY, 'version': version_cap})
        LAST_OBJ_VERSIONS[cls.BINARY] = version_cap
        return version_cap
