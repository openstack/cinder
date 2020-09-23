# Copyright (c) 2016 Huawei Technologies Co., Ltd.
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

import json
import math

from oslo_log import log as logging
from oslo_utils.secretutils import md5
from oslo_utils import strutils
import six

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import fields
from cinder import utils
from cinder.volume.drivers.huawei import constants
from cinder.volume import qos_specs
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)


def encode_name(name):
    encoded_name = md5(name.encode('utf-8'),
                       usedforsecurity=False).hexdigest()
    prefix = name.split('-')[0] + '-'
    postfix = encoded_name[:constants.MAX_NAME_LENGTH - len(prefix)]
    return prefix + postfix


def old_encode_name(name):
    pre_name = name.split("-")[0]
    vol_encoded = six.text_type(hash(name))
    if vol_encoded.startswith('-'):
        newuuid = pre_name + vol_encoded
    else:
        newuuid = pre_name + '-' + vol_encoded
    return newuuid


def encode_host_name(name):
    if name and len(name) > constants.MAX_NAME_LENGTH:
        encoded_name = md5(name.encode('utf-8'),
                           usedforsecurity=False).hexdigest()
        return encoded_name[:constants.MAX_NAME_LENGTH]
    return name


def old_encode_host_name(name):
    if name and len(name) > constants.MAX_NAME_LENGTH:
        name = six.text_type(hash(name))
    return name


def wait_for_condition(func, interval, timeout):
    """Wait for ``func`` to return True.

    This retries running func until it either returns True or raises an
    exception.
    :param func: The function to call.
    :param interval: The interval to wait in seconds between calls.
    :param timeout: The maximum time in seconds to wait.
    """
    if interval == 0:
        interval = 1
    if timeout == 0:
        timeout = 1

    @utils.retry(exception.VolumeDriverException,
                 interval=interval,
                 backoff_rate=1,
                 retries=(math.ceil(timeout / interval)))
    def _retry_call():
        result = func()
        if not result:
            raise exception.VolumeDriverException(
                _('Timed out waiting for condition.'))

    _retry_call()


def _get_volume_type(volume):
    if volume.volume_type:
        return volume.volume_type
    if volume.volume_type_id:
        return volume_types.get_volume_type(None, volume.volume_type_id)


def get_volume_params(volume):
    volume_type = _get_volume_type(volume)
    return get_volume_type_params(volume_type)


def get_volume_type_params(volume_type):
    specs = {}
    if isinstance(volume_type, dict) and volume_type.get('extra_specs'):
        specs = volume_type['extra_specs']
    elif isinstance(volume_type, objects.VolumeType
                    ) and volume_type.extra_specs:
        specs = volume_type.extra_specs

    vol_params = get_volume_params_from_specs(specs)
    vol_params['qos'] = None

    if isinstance(volume_type, dict) and volume_type.get('qos_specs_id'):
        vol_params['qos'] = _get_qos_specs(volume_type['qos_specs_id'])
    elif isinstance(volume_type, objects.VolumeType
                    ) and volume_type.qos_specs_id:
        vol_params['qos'] = _get_qos_specs(volume_type.qos_specs_id)

    LOG.info('volume opts %s.', vol_params)
    return vol_params


def get_volume_params_from_specs(specs):
    opts = _get_opts_from_specs(specs)

    _verify_smartcache_opts(opts)
    _verify_smartpartition_opts(opts)
    _verify_smartthin_opts(opts)

    return opts


def _get_opts_from_specs(specs):
    """Get the well defined extra specs."""
    opts = {}

    def _get_bool_param(k, v):
        words = v.split()
        if len(words) == 2 and words[0] == '<is>':
            return strutils.bool_from_string(words[1], strict=True)

        msg = _("%(k)s spec must be specified as %(k)s='<is> True' "
                "or '<is> False'.") % {'k': k}
        LOG.error(msg)
        raise exception.InvalidInput(reason=msg)

    def _get_replication_type_param(k, v):
        words = v.split()
        if len(words) == 2 and words[0] == '<in>':
            REPLICA_SYNC_TYPES = {'sync': constants.REPLICA_SYNC_MODEL,
                                  'async': constants.REPLICA_ASYNC_MODEL}
            sync_type = words[1].lower()
            if sync_type in REPLICA_SYNC_TYPES:
                return REPLICA_SYNC_TYPES[sync_type]

        msg = _("replication_type spec must be specified as "
                "replication_type='<in> sync' or '<in> async'.")
        LOG.error(msg)
        raise exception.InvalidInput(reason=msg)

    def _get_string_param(k, v):
        if not v:
            msg = _("%s spec must be specified as a string.") % k
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)
        return v

    opts_capability = {
        'capabilities:smarttier': (_get_bool_param, False),
        'capabilities:smartcache': (_get_bool_param, False),
        'capabilities:smartpartition': (_get_bool_param, False),
        'capabilities:thin_provisioning_support': (_get_bool_param, False),
        'capabilities:thick_provisioning_support': (_get_bool_param, False),
        'capabilities:hypermetro': (_get_bool_param, False),
        'capabilities:replication_enabled': (_get_bool_param, False),
        'replication_type': (_get_replication_type_param,
                             constants.REPLICA_ASYNC_MODEL),
        'smarttier:policy': (_get_string_param, None),
        'smartcache:cachename': (_get_string_param, None),
        'smartpartition:partitionname': (_get_string_param, None),
        'huawei_controller:controllername': (_get_string_param, None),
        'capabilities:dedup': (_get_bool_param, None),
        'capabilities:compression': (_get_bool_param, None),
    }

    def _get_opt_key(spec_key):
        key_split = spec_key.split(':')
        if len(key_split) == 1:
            return key_split[0]
        else:
            return key_split[1]

    for spec_key in opts_capability:
        opt_key = _get_opt_key(spec_key)
        opts[opt_key] = opts_capability[spec_key][1]

    for key, value in six.iteritems(specs):
        if key not in opts_capability:
            continue
        func = opts_capability[key][0]
        opt_key = _get_opt_key(key)
        opts[opt_key] = func(key, value)

    return opts


def _get_qos_specs(qos_specs_id):
    ctxt = context.get_admin_context()
    specs = qos_specs.get_qos_specs(ctxt, qos_specs_id)
    if specs is None:
        return {}

    if specs.get('consumer') == 'front-end':
        return {}

    kvs = specs.get('specs', {})
    LOG.info('The QoS specs is: %s.', kvs)

    qos = {'IOTYPE': kvs.pop('IOType', None)}

    if qos['IOTYPE'] not in constants.QOS_IOTYPES:
        msg = _('IOType must be in %(types)s.'
                ) % {'types': constants.QOS_IOTYPES}
        LOG.error(msg)
        raise exception.InvalidInput(reason=msg)

    for k, v in kvs.items():
        if k not in constants.QOS_SPEC_KEYS:
            msg = _('QoS key %s is not valid.') % k
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        if int(v) <= 0:
            msg = _('QoS value for %s must > 0.') % k
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        qos[k.upper()] = v

    if len(qos) < 2:
        msg = _('QoS policy must specify both IOType and one another '
                'qos spec, got policy: %s.') % qos
        LOG.error(msg)
        raise exception.InvalidInput(reason=msg)

    qos_keys = set(qos.keys())
    if (qos_keys & set(constants.UPPER_LIMIT_KEYS) and
            qos_keys & set(constants.LOWER_LIMIT_KEYS)):
        msg = _('QoS policy upper limit and lower limit '
                'conflict, QoS policy: %s.') % qos
        LOG.error(msg)
        raise exception.InvalidInput(reason=msg)

    return qos


def _verify_smartthin_opts(opts):
    if (opts['thin_provisioning_support'] and
            opts['thick_provisioning_support']):
        msg = _('Cannot set thin and thick at the same time.')
        LOG.error(msg)
        raise exception.InvalidInput(reason=msg)
    elif opts['thin_provisioning_support']:
        opts['LUNType'] = constants.THIN_LUNTYPE
    elif opts['thick_provisioning_support']:
        opts['LUNType'] = constants.THICK_LUNTYPE


def _verify_smartcache_opts(opts):
    if opts['smartcache'] and not opts['cachename']:
        msg = _('Cache name is not specified, please set '
                'smartcache:cachename in extra specs.')
        LOG.error(msg)
        raise exception.InvalidInput(reason=msg)


def _verify_smartpartition_opts(opts):
    if opts['smartpartition'] and not opts['partitionname']:
        msg = _('Partition name is not specified, please set '
                'smartpartition:partitionname in extra specs.')
        LOG.error(msg)
        raise exception.InvalidInput(reason=msg)


def wait_lun_online(client, lun_id, wait_interval=None, wait_timeout=None):
    def _lun_online():
        result = client.get_lun_info_by_id(lun_id)
        if result['HEALTHSTATUS'] != constants.STATUS_HEALTH:
            err_msg = _('LUN %s is abnormal.') % lun_id
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        if result['RUNNINGSTATUS'] == constants.LUN_INITIALIZING:
            return False

        return True

    if not wait_interval:
        wait_interval = constants.DEFAULT_WAIT_INTERVAL
    if not wait_timeout:
        wait_timeout = wait_interval * 10

    wait_for_condition(_lun_online, wait_interval, wait_timeout)


def is_not_exist_exc(exc):
    msg = getattr(exc, 'msg', '')
    return 'not exist' in msg


def to_string(**kwargs):
    return json.dumps(kwargs) if kwargs else ''


def to_dict(text):
    return json.loads(text) if text else {}


def get_volume_private_data(volume):
    if not volume.provider_location:
        return {}

    try:
        info = json.loads(volume.provider_location)
    except Exception:
        LOG.exception("Decode volume provider_location error")
        return {}

    if isinstance(info, dict):
        return info

    # To keep compatible with old driver version
    return {'huawei_lun_id': six.text_type(info),
            'huawei_lun_wwn': volume.admin_metadata.get('huawei_lun_wwn'),
            'huawei_sn': volume.metadata.get('huawei_sn'),
            'hypermetro_id': volume.metadata.get('hypermetro_id'),
            'remote_lun_id': volume.metadata.get('remote_lun_id')
            }


def get_volume_metadata(volume):
    if isinstance(volume, objects.Volume):
        return volume.metadata
    if volume.get('volume_metadata'):
        return {item['key']: item['value'] for item in
                volume['volume_metadata']}
    return {}


def get_replication_data(volume):
    if not volume.replication_driver_data:
        return {}

    return json.loads(volume.replication_driver_data)


def get_snapshot_private_data(snapshot):
    if not snapshot.provider_location:
        return {}

    info = json.loads(snapshot.provider_location)
    if isinstance(info, dict):
        return info

    # To keep compatible with old driver version
    return {'huawei_snapshot_id': six.text_type(info),
            'huawei_snapshot_wwn': snapshot.metadata.get(
                'huawei_snapshot_wwn'),
            }


def get_external_lun_info(client, external_ref):
    lun_info = None
    if 'source-id' in external_ref:
        lun = client.get_lun_info_by_id(external_ref['source-id'])
        lun_info = client.get_lun_info_by_name(lun['NAME'])
    elif 'source-name' in external_ref:
        lun_info = client.get_lun_info_by_name(external_ref['source-name'])

    return lun_info


def get_external_snapshot_info(client, external_ref):
    snapshot_info = None
    if 'source-id' in external_ref:
        snapshot_info = client.get_snapshot_info_by_id(
            external_ref['source-id'])
    elif 'source-name' in external_ref:
        snapshot_info = client.get_snapshot_info_by_name(
            external_ref['source-name'])

    return snapshot_info


def get_lun_info(client, volume):
    metadata = get_volume_private_data(volume)

    volume_name = encode_name(volume.id)
    lun_info = client.get_lun_info_by_name(volume_name)

    # If new encoded way not found, try the old encoded way.
    if not lun_info:
        volume_name = old_encode_name(volume.id)
        lun_info = client.get_lun_info_by_name(volume_name)

    if not lun_info and metadata.get('huawei_lun_id'):
        lun_info = client.get_lun_info_by_id(metadata['huawei_lun_id'])

    if lun_info and ('huawei_lun_wwn' in metadata and
                     lun_info.get('WWN') != metadata['huawei_lun_wwn']):
        return None

    return lun_info


def get_snapshot_info(client, snapshot):
    name = encode_name(snapshot.id)
    snapshot_info = client.get_snapshot_info_by_name(name)

    # If new encoded way not found, try the old encoded way.
    if not snapshot_info:
        name = old_encode_name(snapshot.id)
        snapshot_info = client.get_snapshot_info_by_name(name)

    return snapshot_info


def get_host_id(client, host_name):
    encoded_name = encode_host_name(host_name)
    host_id = client.get_host_id_by_name(encoded_name)
    if encoded_name == host_name:
        return host_id

    if not host_id:
        encoded_name = old_encode_host_name(host_name)
        host_id = client.get_host_id_by_name(encoded_name)

    return host_id


def get_hypermetro_group(client, group_id):
    encoded_name = encode_name(group_id)
    group = client.get_metrogroup_by_name(encoded_name)
    if not group:
        encoded_name = old_encode_name(group_id)
        group = client.get_metrogroup_by_name(encoded_name)
    return group


def get_replication_group(client, group_id):
    encoded_name = encode_name(group_id)
    group = client.get_replication_group_by_name(encoded_name)
    if not group:
        encoded_name = old_encode_name(group_id)
        group = client.get_replication_group_by_name(encoded_name)
    return group


def get_volume_model_update(volume, **kwargs):
    private_data = get_volume_private_data(volume)

    if kwargs.get('hypermetro_id'):
        private_data['hypermetro_id'] = kwargs.get('hypermetro_id')
    elif 'hypermetro_id' in private_data:
        private_data.pop('hypermetro_id')

    if 'huawei_lun_id' in kwargs:
        private_data['huawei_lun_id'] = kwargs['huawei_lun_id']
    if 'huawei_lun_wwn' in kwargs:
        private_data['huawei_lun_wwn'] = kwargs['huawei_lun_wwn']
    if 'huawei_sn' in kwargs:
        private_data['huawei_sn'] = kwargs['huawei_sn']

    model_update = {'provider_location': to_string(**private_data)}

    if kwargs.get('replication_id'):
        model_update['replication_driver_data'] = to_string(
            pair_id=kwargs.get('replication_id'))
        model_update['replication_status'] = fields.ReplicationStatus.ENABLED
    else:
        model_update['replication_driver_data'] = None
        model_update['replication_status'] = fields.ReplicationStatus.DISABLED

    return model_update


def get_group_type_params(group):
    opts = []
    for volume_type in group.volume_types:
        opt = get_volume_type_params(volume_type)
        opts.append(opt)
    return opts
