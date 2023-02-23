# Copyright 2022 Red Hat, Inc
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
"""NVMet Python Interface using privsep

This file adds the privsep support to the nvmet package so it can be easily
consumed by Cinder nvmet target.

It also:

- Adds some methods to the Root class to be able to get a specific subsystem or
  port directly without having to go through all the existing ones.

- Presents the CFSNotFound exception as a NotFound exception which is easier to
  consume.
"""
import os

import nvmet
from oslo_log import log as logging

from cinder import exception
from cinder import privsep


LOG = logging.getLogger(__name__)


###################
# Helper methods to serialize/deserialize parameters to be sent through privsep
# and to do the instance/class calls on the privsep side.

def serialize(instance):
    """Serialize parameters, specially nvmet instances.

    The idea is to be able to pass an nvmet instance to privsep methods, since
    they are sometimes required as parameters (ie: port.setup) and also to pass
    the instance where do_privsep_call has to call a specific method.

    Instances are passed as a tuple, with the name of the class as the first
    element, and in the second element the kwargs necessary to instantiate the
    instance of that class.

    To differentiate nvmet instances from tuples there is a 'tuple' value that
    can be passed in the first element of the tuple to differentiate them.

    All other instances as passed unaltered.
    """
    if isinstance(instance, nvmet.Root):
        return ('Root', {})

    if isinstance(instance, (nvmet.Subsystem, nvmet.Host)):
        return (type(instance).__name__, {'nqn': instance.nqn,
                                          'mode': 'lookup'})

    if isinstance(instance, nvmet.Namespace):
        return ('Namespace', {'nsid': instance.nsid,
                              'subsystem': serialize(instance.subsystem),
                              'mode': 'lookup'})

    if isinstance(instance, nvmet.Port):
        return ('Port', {'portid': instance.portid, 'mode': 'lookup'})

    if isinstance(instance, nvmet.Referral):
        return ('Referral', {'name': instance.name,
                             'port': serialize(instance.port),
                             'mode': 'lookup'})

    if isinstance(instance, nvmet.ANAGroup):
        return ('ANAGroup', {'grpid': instance.grpid,
                             'port': serialize(instance.port),
                             'mode': 'lookup'})

    if isinstance(instance, tuple):
        return ('tuple', instance)

    return instance


def deserialize(data):
    """Deserialize an instance, specially nvmet instances.

    Reverse operation of the serialize method.  Converts an nvmet instance
    serialized in a tuple into an actual nvmet instance.
    """
    if not isinstance(data, tuple):
        return data

    cls_name, cls_params = data
    if cls_name == 'tuple':
        return cls_params

    # Parameters for the instantiation of the class can be nvmet objects
    # themselves.
    params = {name: deserialize(value) for name, value in cls_params.items()}
    # We don't want the classes from the nvmet method but ours instead
    instance = getattr(nvmet, cls_name)(**params)
    return instance


def deserialize_params(args, kwargs):
    """Deserialize function arguments using deserialize method."""
    args = [deserialize(arg) for arg in args]
    kwargs = {key: deserialize(value) for key, value in kwargs.items()}
    return args, kwargs


def _nvmet_setup_failure(message):
    """Simple error method to use when calling nvmet setup methods."""
    LOG.error(message)
    raise exception.CinderException(message)


@privsep.sys_admin_pctxt.entrypoint
def do_privsep_call(instance, method_name, *args, **kwargs):
    """General privsep method for instance calls.

    Handle privsep method calls by deserializing the instance where we want to
    call a given method with the deserialized parameters.
    """
    LOG.debug('Calling %s on %s with %s - %s',
              method_name, instance, args, kwargs)
    instance = deserialize(instance)
    method = getattr(instance, method_name)
    args, kwargs = deserialize_params(args, kwargs)
    # NOTE: No returning nvmet objects support. If needed add serialization on
    #       the result and deserialization decorator before the entrypoint.
    return method(*args, **kwargs)


@privsep.sys_admin_pctxt.entrypoint
def _privsep_setup(cls_name, *args, **kwargs):
    """Special privsep method for nvmet setup method calls.

    The setup method is a special case because it's a class method (which
    privsep cannot handle) and also requires a function for the error handling.

    This method accepts a class name and reconstructs it, then calls the
    class' setup method passing our own error function.
    """
    LOG.debug('Setup %s with %s - %s', cls_name, args, kwargs)
    cls = getattr(nvmet, cls_name)
    args, kwargs = deserialize_params(args, kwargs)
    kwargs['err_func'] = _nvmet_setup_failure
    return cls.setup(*args, **kwargs)


def privsep_setup(cls_name, *args, **kwargs):
    """Wrapper for _privsep_setup that accepts err_func argument."""
    # err_func parameter hardcoded in _privsep_setup as it cannot be serialized
    if 'err_func' in kwargs:
        err_func = kwargs.pop('err_func')
    else:  # positional is always last argument of the args tuple
        err_func = args[-1]
        args = args[:-1]
    try:
        return _privsep_setup(cls_name, *args, **kwargs)
    except exception.CinderException as exc:
        if not err_func:
            raise
        err_func(exc.msg)


###################
# Classes that don't currently have privsep support

Host = nvmet.Host
Referral = nvmet.Referral
ANAGroup = nvmet.ANAGroup


###################
# Custom classes that divert privileges calls to privsep
# Support in these classes is limited to what's needed by the nvmet target.

# Convenience error class link to nvmet's
NotFound = nvmet.nvme.CFSNotFound


class Namespace(nvmet.Namespace):
    def __init__(self, subsystem, nsid=None, mode='lookup'):
        super().__init__(subsystem=subsystem, nsid=nsid, mode=mode)

    @classmethod
    def setup(cls, subsys, n, err_func=None):
        privsep_setup(cls.__name__, serialize(subsys), n, err_func)

    def delete(self):
        do_privsep_call(serialize(self), 'delete')


class Subsystem(nvmet.Subsystem):
    def __init__(self, nqn=None, mode='lookup'):
        super().__init__(nqn=nqn, mode=mode)

    @classmethod
    def setup(cls, t, err_func=None):
        privsep_setup(cls.__name__, t, err_func)

    def delete(self):
        do_privsep_call(serialize(self), 'delete')

    @property
    def namespaces(self):
        for d in os.listdir(self.path + '/namespaces/'):
            yield Namespace(self, os.path.basename(d))


class Port(nvmet.Port):
    def __init__(self, portid, mode='lookup'):
        super().__init__(portid=portid, mode=mode)

    @classmethod
    def setup(cls, root, n, err_func=None):
        privsep_setup(cls.__name__, serialize(root), n, err_func)

    def add_subsystem(self, nqn):
        do_privsep_call(serialize(self), 'add_subsystem', nqn)

    def remove_subsystem(self, nqn):
        do_privsep_call(serialize(self), 'remove_subsystem', nqn)

    def delete(self):
        do_privsep_call(serialize(self), 'delete')


class Root(nvmet.Root):
    @property
    def ports(self):
        for d in os.listdir(self.path + '/ports/'):
            yield Port(os.path.basename(d))
