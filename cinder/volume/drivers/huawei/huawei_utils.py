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

import hashlib
import json
import six
import time

from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.volume.drivers.huawei import constants
from cinder.volume import utils

LOG = logging.getLogger(__name__)


def encode_name(id):
    encoded_name = hashlib.md5(id.encode('utf-8')).hexdigest()
    prefix = id.split('-')[0] + '-'
    postfix = encoded_name[:constants.MAX_NAME_LENGTH - len(prefix)]
    return prefix + postfix


def old_encode_name(id):
    pre_name = id.split("-")[0]
    vol_encoded = six.text_type(hash(id))
    if vol_encoded.startswith('-'):
        newuuid = pre_name + vol_encoded
    else:
        newuuid = pre_name + '-' + vol_encoded
    return newuuid


def encode_host_name(name):
    if name and len(name) > constants.MAX_NAME_LENGTH:
        encoded_name = hashlib.md5(name.encode('utf-8')).hexdigest()
        return encoded_name[:constants.MAX_NAME_LENGTH]
    return name


def old_encode_host_name(name):
    if name and len(name) > constants.MAX_NAME_LENGTH:
        name = six.text_type(hash(name))
    return name


def wait_for_condition(func, interval, timeout):
    start_time = time.time()

    def _inner():
        try:
            res = func()
        except Exception as ex:
            raise exception.VolumeBackendAPIException(data=ex)

        if res:
            raise loopingcall.LoopingCallDone()

        if int(time.time()) - start_time > timeout:
            msg = (_('wait_for_condition: %s timed out.')
                   % func.__name__)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    timer = loopingcall.FixedIntervalLoopingCall(_inner)
    timer.start(interval=interval).wait()


def get_volume_size(volume):
    """Calculate the volume size.

    We should divide the given volume size by 512 for the 18000 system
    calculates volume size with sectors, which is 512 bytes.
    """
    volume_size = units.Gi / 512  # 1G
    if int(volume.size) != 0:
        volume_size = int(volume.size) * units.Gi / 512

    return volume_size


def get_volume_metadata(volume):
    if type(volume) is objects.Volume:
        return volume.metadata

    if 'volume_metadata' in volume:
        metadata = volume.get('volume_metadata')
        return {item['key']: item['value'] for item in metadata}

    return {}


def get_admin_metadata(volume):
    admin_metadata = {}
    if 'admin_metadata' in volume:
        admin_metadata = volume.admin_metadata
    elif 'volume_admin_metadata' in volume:
        metadata = volume.get('volume_admin_metadata', [])
        admin_metadata = {item['key']: item['value'] for item in metadata}

    LOG.debug("Volume ID: %(id)s, admin_metadata: %(admin_metadata)s.",
              {"id": volume.id, "admin_metadata": admin_metadata})
    return admin_metadata


def get_snapshot_metadata_value(snapshot):
    if type(snapshot) is objects.Snapshot:
        return snapshot.metadata

    if 'snapshot_metadata' in snapshot:
        metadata = snapshot.snapshot_metadata
        return {item['key']: item['value'] for item in metadata}

    return {}


def check_whether_operate_consistency_group(func):
    def wrapper(self, context, group, *args, **kwargs):
        if not utils.is_group_a_cg_snapshot_type(group):
            msg = _("%s, the group or group snapshot is not cg or "
                    "cg_snapshot") % func.__name__
            LOG.debug(msg)
            raise NotImplementedError(msg)
        return func(self, context, group, *args, **kwargs)
    return wrapper


def to_string(**kwargs):
    return json.dumps(kwargs) if kwargs else ''


def get_lun_metadata(volume):
    if not volume.provider_location:
        return {}

    info = json.loads(volume.provider_location)
    if isinstance(info, dict):
        return info

    # To keep compatible with old driver version
    admin_metadata = get_admin_metadata(volume)
    metadata = get_volume_metadata(volume)
    return {'huawei_lun_id': six.text_type(info),
            'huawei_lun_wwn': admin_metadata.get('huawei_lun_wwn'),
            'hypermetro_id': metadata.get('hypermetro_id'),
            'remote_lun_id': metadata.get('remote_lun_id')
            }


def get_snapshot_metadata(snapshot):
    if not snapshot.provider_location:
        return {}

    info = json.loads(snapshot.provider_location)
    if isinstance(info, dict):
        return info

    # To keep compatible with old driver version
    return {'huawei_snapshot_id': six.text_type(info)}


def get_volume_lun_id(client, volume):
    metadata = get_lun_metadata(volume)
    lun_id = metadata.get('huawei_lun_id')

    # First try the new encoded way.
    if not lun_id:
        volume_name = encode_name(volume.id)
        lun_id = client.get_lun_id_by_name(volume_name)

    # If new encoded way not found, try the old encoded way.
    if not lun_id:
        volume_name = old_encode_name(volume.id)
        lun_id = client.get_lun_id_by_name(volume_name)

    return lun_id, metadata.get('huawei_lun_wwn')


def get_snapshot_id(client, snapshot):
    metadata = get_snapshot_metadata(snapshot)
    snapshot_id = metadata.get('huawei_snapshot_id')

    # First try the new encoded way.
    if not snapshot_id:
        name = encode_name(snapshot.id)
        snapshot_id = client.get_snapshot_id_by_name(name)

    # If new encoded way not found, try the old encoded way.
    if not snapshot_id:
        name = old_encode_name(snapshot.id)
        snapshot_id = client.get_snapshot_id_by_name(name)

    return snapshot_id


def get_host_id(client, host_name):
    encoded_name = encode_host_name(host_name)
    host_id = client.get_host_id_by_name(encoded_name)
    if not host_id:
        encoded_name = old_encode_host_name(host_name)
        host_id = client.get_host_id_by_name(encoded_name)

    return host_id
