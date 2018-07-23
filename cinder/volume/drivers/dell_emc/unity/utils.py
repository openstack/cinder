# Copyright (c) 2016 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from __future__ import division

import contextlib
from distutils import version
import functools
from oslo_log import log as logging
from oslo_utils import fnmatch
from oslo_utils import units
import six

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.volume import utils as vol_utils
from cinder.volume import volume_types
from cinder.zonemanager import utils as zm_utils

LOG = logging.getLogger(__name__)
BACKEND_QOS_CONSUMERS = frozenset(['back-end', 'both'])
QOS_MAX_IOPS = 'maxIOPS'
QOS_MAX_BWS = 'maxBWS'


def dump_provider_location(location_dict):
    sorted_keys = sorted(location_dict.keys())
    return '|'.join('%(k)s^%(v)s' % {'k': k, 'v': location_dict[k]}
                    for k in sorted_keys)


def build_provider_location(system, lun_type, lun_id, version):
    """Builds provider_location for volume or snapshot.

    :param system: Unity serial number
    :param lun_id: LUN ID in Unity
    :param lun_type: 'lun'
    :param version: driver version
    """
    location_dict = {'system': system,
                     'type': lun_type,
                     'id': six.text_type(lun_id),
                     'version': version}
    return dump_provider_location(location_dict)


def extract_provider_location(provider_location, key):
    """Extracts value of the specified field from provider_location string.

    :param provider_location: provider_location string
    :param key: field name of the value that to be extracted
    :return: value of the specified field if it exists, otherwise,
             None is returned
    """
    if provider_location:
        for kvp in provider_location.split('|'):
            fields = kvp.split('^')
            if len(fields) == 2 and fields[0] == key:
                return fields[1]
        else:
            LOG.warning('"%(key)s" is not found in provider '
                        'location "%(location)s."',
                        {'key': key, 'location': provider_location})
    else:
        LOG.warning('Empty provider location received.')


def byte_to_gib(byte):
    return byte / units.Gi


def byte_to_mib(byte):
    return byte / units.Mi


def gib_to_mib(gib):
    return gib * units.Ki


def validate_pool_names(conf_pools, array_pools):
    if not conf_pools:
        LOG.debug('No storage pools are specified. This host will manage '
                  'all the pools on the Unity system.')
        return array_pools

    conf_pools = set(map(lambda i: i.strip(), conf_pools))
    array_pools = set(map(lambda i: i.strip(), array_pools))
    existed = conf_pools & array_pools

    if not existed:
        msg = (_('No storage pools to be managed exist. Please check '
                 'your configuration. The available storage pools on the '
                 'system are %s.') % array_pools)
        raise exception.VolumeBackendAPIException(data=msg)

    return existed


def extract_iscsi_uids(connector):
    if 'initiator' not in connector:
        msg = _("Host %s doesn't have iSCSI initiator.") % connector['host']
        raise exception.VolumeBackendAPIException(data=msg)

    return [connector['initiator']]


def extract_fc_uids(connector):
    if 'wwnns' not in connector or 'wwpns' not in connector:
        msg = _("Host %s doesn't have FC initiators.") % connector['host']
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    wwnns = connector['wwnns']
    wwpns = connector['wwpns']
    wwns = [(node + port).upper() for node, port in zip(wwnns, wwpns)]

    def _to_wwn(wwn):
        # Format the wwn to include the colon
        # For example, convert 1122200000051E55E100 to
        # 11:22:20:00:00:05:1E:55:A1:00
        return ':'.join(wwn[i:i + 2] for i in range(0, len(wwn), 2))

    return list(map(_to_wwn, wwns))


def convert_ip_to_portal(ip):
    return '%s:3260' % ip


def convert_to_itor_tgt_map(zone_mapping):
    """Function to process data from lookup service.

    :param zone_mapping: mapping is the data from the zone lookup service
         with below format

        {
             <San name>: {
                 'initiator_port_wwn_list':
                 ('200000051e55a100', '200000051e55a121'..)
                 'target_port_wwn_list':
                 ('100000051e55a100', '100000051e55a121'..)

             }

        }
    """
    target_wwns = []
    itor_tgt_map = {}
    for san_name in zone_mapping:
        one_map = zone_mapping[san_name]
        for target in one_map['target_port_wwn_list']:
            if target not in target_wwns:
                target_wwns.append(target)
        for initiator in one_map['initiator_port_wwn_list']:
            itor_tgt_map[initiator] = one_map['target_port_wwn_list']
    LOG.debug("target_wwns: %(tgt_wwns)s\n init_targ_map: %(itor_tgt_map)s",
              {'tgt_wwns': target_wwns,
               'itor_tgt_map': itor_tgt_map})
    return target_wwns, itor_tgt_map


def get_pool_name(volume):
    return vol_utils.extract_host(volume.host, 'pool')


def get_extra_spec(volume, spec_key):
    spec_value = None
    type_id = volume.volume_type_id
    if type_id is not None:
        extra_specs = volume_types.get_volume_type_extra_specs(type_id)
        if spec_key in extra_specs:
            spec_value = extra_specs[spec_key]
    return spec_value


def ignore_exception(func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except Exception as ex:
        LOG.warning('Error occurred but ignored. Function: %(func_name)s, '
                    'args: %(args)s, kwargs: %(kwargs)s, '
                    'exception: %(ex)s.',
                    {'func_name': func, 'args': args,
                     'kwargs': kwargs, 'ex': ex})


@contextlib.contextmanager
def assure_cleanup(enter_func, exit_func, use_enter_return):
    """Assures the resource is cleaned up. Used as a context.

    :param enter_func: the function to execute when entering the context.
    :param exit_func: the function to execute when leaving the context.
    :param use_enter_return: the flag indicates whether to pass the return
                             value of enter_func in to the exit_func.
    """

    enter_return = None
    try:
        if isinstance(enter_func, functools.partial):
            enter_func_name = enter_func.func.__name__
        else:
            enter_func_name = enter_func.__name__
        LOG.debug(('Entering context. Function: %(func_name)s, '
                   'use_enter_return: %(use)s.'),
                  {'func_name': enter_func_name,
                   'use': use_enter_return})
        enter_return = enter_func()
        yield enter_return
    finally:
        if isinstance(exit_func, functools.partial):
            exit_func_name = exit_func.func.__name__
        else:
            exit_func_name = exit_func.__name__
        LOG.debug(('Exiting context. Function: %(func_name)s, '
                   'use_enter_return: %(use)s.'),
                  {'func_name': exit_func_name,
                   'use': use_enter_return})
        if enter_return is not None:
            if use_enter_return:
                ignore_exception(exit_func, enter_return)
            else:
                ignore_exception(exit_func)


def create_lookup_service():
    return zm_utils.create_lookup_service()


def get_backend_qos_specs(volume):
    type_id = volume.volume_type_id
    if type_id is None:
        return None

    qos_specs = volume_types.get_volume_type_qos_specs(type_id)
    if qos_specs is None:
        return None

    qos_specs = qos_specs['qos_specs']
    if qos_specs is None:
        return None

    consumer = qos_specs['consumer']
    # Front end QoS specs are handled by nova. We ignore them here.
    if consumer not in BACKEND_QOS_CONSUMERS:
        return None

    max_iops = qos_specs['specs'].get(QOS_MAX_IOPS)
    max_bws = qos_specs['specs'].get(QOS_MAX_BWS)
    if max_iops is None and max_bws is None:
        return None

    return {
        'id': qos_specs['id'],
        QOS_MAX_IOPS: max_iops,
        QOS_MAX_BWS: max_bws,
    }


def remove_empty(option, value_list):
    if value_list:
        value_list = list(filter(None, map(str.strip, value_list)))
        if not value_list:
            raise exception.InvalidConfigurationValue(option=option,
                                                      value=value_list)
        return value_list
    return None


def match_any(full, patterns):
    matched = list(
        filter(lambda x: any(fnmatch.fnmatchcase(x, p) for p in patterns),
               full))
    unmatched = list(
        filter(lambda x: not any(fnmatch.fnmatchcase(x, p) for p in patterns),
               full))
    unmatched_patterns = list(
        filter(lambda p: not any(fnmatch.fnmatchcase(x, p) for x in full),
               patterns))
    return matched, unmatched, unmatched_patterns


def is_before_4_1(ver):
    return version.LooseVersion(ver) < version.LooseVersion('4.1')


def lock_if(condition, lock_name):
    if condition:
        return coordination.synchronized(lock_name)
    else:
        return functools.partial
