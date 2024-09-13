# Copyright (C) 2020, 2024, Hitachi, Ltd.
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
#
"""Common module for Hitachi HBSD Driver."""

from collections import defaultdict
import json
import re

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.volume import configuration
from cinder.volume.drivers.hitachi import hbsd_utils as utils
from cinder.volume import volume_types
from cinder.volume import volume_utils

_GROUP_NAME_MAX_LEN_FC = 64
_GROUP_NAME_MAX_LEN_ISCSI = 32

GROUP_NAME_ALLOWED_CHARS = 'a-zA-Z0-9.@_:-'
GROUP_NAME_VAR_WWN = '{wwn}'
GROUP_NAME_VAR_IP = '{ip}'
GROUP_NAME_VAR_HOST = '{host}'

_GROUP_NAME_VAR_WWN_LEN = 16
_GROUP_NAME_VAR_IP_LEN = 15
_GROUP_NAME_VAR_HOST_LEN = 1
_GROUP_NAME_VAR_LEN = {GROUP_NAME_VAR_WWN: _GROUP_NAME_VAR_WWN_LEN,
                       GROUP_NAME_VAR_IP: _GROUP_NAME_VAR_IP_LEN,
                       GROUP_NAME_VAR_HOST: _GROUP_NAME_VAR_HOST_LEN}

STR_VOLUME = 'volume'
STR_SNAPSHOT = 'snapshot'

_UUID_PATTERN = re.compile(r'^[\da-f]{32}$')

_INHERITED_VOLUME_OPTS = [
    'volume_backend_name',
    'volume_driver',
    'reserved_percentage',
    'use_multipath_for_image_xfer',
    'enforce_multipath_for_image_xfer',
    'max_over_subscription_ratio',
    'use_chap_auth',
    'chap_username',
    'chap_password',
]

COMMON_VOLUME_OPTS = [
    cfg.StrOpt(
        'hitachi_storage_id',
        default=None,
        help='Product number of the storage system.'),
    cfg.ListOpt(
        'hitachi_pools',
        default=[],
        deprecated_name='hitachi_pool',
        help='Pool number[s] or pool name[s] of the DP pool.'),
    cfg.StrOpt(
        'hitachi_snap_pool',
        default=None,
        help='Pool number or pool name of the snapshot pool.'),
    cfg.StrOpt(
        'hitachi_ldev_range',
        default=None,
        help='Range of the LDEV numbers in the format of \'xxxx-yyyy\' that '
             'can be used by the driver. Values can be in decimal format '
             '(e.g. 1000) or in colon-separated hexadecimal format '
             '(e.g. 00:03:E8).'),
    cfg.ListOpt(
        'hitachi_target_ports',
        default=[],
        help='IDs of the storage ports used to attach volumes to the '
             'controller node. To specify multiple ports, connect them by '
             'commas (e.g. CL1-A,CL2-A).'),
    cfg.ListOpt(
        'hitachi_compute_target_ports',
        default=[],
        help='IDs of the storage ports used to attach volumes to compute '
             'nodes. To specify multiple ports, connect them by commas '
             '(e.g. CL1-A,CL2-A).'),
    cfg.BoolOpt(
        'hitachi_group_create',
        default=False,
        help='If True, the driver will create host groups or iSCSI targets on '
             'storage ports as needed.'),
    cfg.BoolOpt(
        'hitachi_group_delete',
        default=False,
        help='If True, the driver will delete host groups or iSCSI targets on '
             'storage ports as needed.'),
    cfg.IntOpt(
        'hitachi_copy_speed',
        default=3,
        min=1, max=15,
        help='Copy speed of storage system. 1 or 2 indicates '
             'low speed, 3 indicates middle speed, and a value between 4 and '
             '15 indicates high speed.'),
    cfg.IntOpt(
        'hitachi_copy_check_interval',
        default=3,
        min=1, max=600,
        help='Interval in seconds to check copying status during a volume '
             'copy.'),
    cfg.IntOpt(
        'hitachi_async_copy_check_interval',
        default=10,
        min=1, max=600,
        help='Interval in seconds to check asynchronous copying status during '
             'a copy pair deletion or data restoration.'),
]

COMMON_PORT_OPTS = [
    cfg.BoolOpt(
        'hitachi_port_scheduler',
        default=False,
        help='Enable port scheduling of WWNs to the configured ports so that '
             'WWNs are registered to ports in a round-robin fashion.'),
]

COMMON_PAIR_OPTS = [
    cfg.IntOpt(
        'hitachi_pair_target_number',
        default=0, min=0, max=99,
        help='Pair target name of the host group or iSCSI target'),
]

COMMON_NAME_OPTS = [
    cfg.StrOpt(
        'hitachi_group_name_format',
        default=None,
        help='Format of host groups, iSCSI targets, and server objects.'),
]

CONF = cfg.CONF
CONF.register_opts(COMMON_VOLUME_OPTS, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(COMMON_PORT_OPTS, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(COMMON_PAIR_OPTS, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(COMMON_NAME_OPTS, group=configuration.SHARED_CONF_GROUP)

LOG = logging.getLogger(__name__)
MSG = utils.HBSDMsg


def str2int(num):
    """Convert a string into an integer."""
    if not num:
        return None
    if num.isdigit():
        return int(num)
    if not re.match(r'[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F]' +
                    '[0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]$', num):
        return None
    try:
        return int(num.replace(':', ''), 16)
    except ValueError:
        return None


class HBSDCommon():
    """Common class for Hitachi HBSD Driver."""

    def __init__(self, conf, driverinfo, db):
        """Initialize instance variables."""
        self.conf = conf
        self.db = db
        self.ctxt = None
        self.lock = {
            'do_setup': 'do_setup',
        }
        self.driver_info = driverinfo
        self.storage_info = {
            'protocol': driverinfo['proto'],
            'pool_id': None,
            'snap_pool_id': None,
            'ldev_range': [],
            'controller_ports': [],
            'compute_ports': [],
            'pair_ports': [],
            'wwns': {},
            'portals': {},
        }
        self.storage_id = None
        if self.storage_info['protocol'] == 'FC':
            self.group_name_format = {
                'group_name_max_len': _GROUP_NAME_MAX_LEN_FC,
                'group_name_var_cnt': {
                    GROUP_NAME_VAR_WWN: [1],
                    GROUP_NAME_VAR_IP: [0],
                    GROUP_NAME_VAR_HOST: [0, 1],
                },
                'group_name_format_default': self.driver_info[
                    'target_prefix'] + '{wwn}',
            }
        if self.storage_info['protocol'] == 'iSCSI':
            self.group_name_format = {
                'group_name_max_len': _GROUP_NAME_MAX_LEN_ISCSI,
                'group_name_var_cnt': {
                    GROUP_NAME_VAR_WWN: [0],
                    GROUP_NAME_VAR_IP: [1],
                    GROUP_NAME_VAR_HOST: [0, 1],
                },
                'group_name_format_default': self.driver_info[
                    'target_prefix'] + '{ip}',
            }
        self.format_info = {
            'group_name_format': self.group_name_format[
                'group_name_format_default'],
            'group_name_format_without_var_len': (
                len(re.sub('|'.join([GROUP_NAME_VAR_WWN,
                    GROUP_NAME_VAR_IP, GROUP_NAME_VAR_HOST]), '',
                    self.group_name_format['group_name_format_default']))),
            'group_name_var_cnt': {
                GROUP_NAME_VAR_WWN: self.group_name_format[
                    'group_name_format_default'].count(GROUP_NAME_VAR_WWN),
                GROUP_NAME_VAR_IP: self.group_name_format[
                    'group_name_format_default'].count(GROUP_NAME_VAR_IP),
                GROUP_NAME_VAR_HOST: self.group_name_format[
                    'group_name_format_default'].count(GROUP_NAME_VAR_HOST),
            }
        }

        self._required_common_opts = [
            self.driver_info['param_prefix'] + '_storage_id',
            self.driver_info['param_prefix'] + '_pools',
        ]
        self.port_index = {}

    def get_pool_id_of_volume(self, volume):
        pools = self._stats['pools']
        if len(pools) == 1:
            return pools[0]['location_info']['pool_id']
        pool_name = volume_utils.extract_host(volume['host'], 'pool')
        for pool in pools:
            if pool['pool_name'] == pool_name:
                return pool['location_info']['pool_id']
        return None

    def create_ldev(
            self, size, extra_specs, pool_id, ldev_range, qos_specs=None):
        """Create an LDEV and return its LDEV number."""
        raise NotImplementedError()

    def modify_ldev_name(self, ldev, name):
        """Modify LDEV name."""
        raise NotImplementedError()

    def create_volume(self, volume):
        """Create a volume and return its properties."""
        extra_specs = self.get_volume_extra_specs(volume)
        pool_id = self.get_pool_id_of_volume(volume)
        ldev_range = self.storage_info['ldev_range']
        qos_specs = utils.get_qos_specs_from_volume(volume)
        try:
            ldev = self.create_ldev(volume['size'], extra_specs, pool_id,
                                    ldev_range, qos_specs=qos_specs)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.output_log(MSG.CREATE_LDEV_FAILED)
        self.modify_ldev_name(ldev, volume['id'].replace("-", ""))
        return {
            'provider_location': str(ldev),
        }

    def get_ldev_info(self, keys, ldev, **kwargs):
        """Return a dictionary of LDEV-related items."""
        raise NotImplementedError()

    def create_pair_on_storage(
            self, pvol, svol, snap_pool_id, is_snapshot=False):
        """Create a copy pair on the storage."""
        raise NotImplementedError()

    def wait_copy_completion(self, pvol, svol):
        """Wait until copy is completed."""
        raise NotImplementedError()

    def copy_on_storage(
            self, pvol, size, extra_specs, pool_id, snap_pool_id, ldev_range,
            is_snapshot=False, sync=False, is_rep=False, qos_specs=None):
        """Create a copy of the specified LDEV on the storage."""
        ldev_info = self.get_ldev_info(['status', 'attributes'], pvol)
        if ldev_info['status'] != 'NML':
            msg = self.output_log(MSG.INVALID_LDEV_STATUS_FOR_COPY, ldev=pvol)
            self.raise_error(msg)
        svol = self.create_ldev(
            size, extra_specs, pool_id, ldev_range, qos_specs=qos_specs)
        try:
            self.create_pair_on_storage(
                pvol, svol, snap_pool_id, is_snapshot=is_snapshot)
            if sync or is_rep:
                self.wait_copy_completion(pvol, svol)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self.delete_ldev(svol)
                except exception.VolumeDriverException:
                    self.output_log(MSG.DELETE_LDEV_FAILED, ldev=svol)
        return svol

    def create_volume_from_src(self, volume, src, src_type, is_rep=False):
        """Create a volume from a volume or snapshot and return its properties.

        """
        ldev = self.get_ldev(src)
        if ldev is None:
            msg = self.output_log(
                MSG.INVALID_LDEV_FOR_VOLUME_COPY, type=src_type, id=src['id'])
            self.raise_error(msg)

        size = volume['size']
        extra_specs = self.get_volume_extra_specs(volume)
        pool_id = self.get_pool_id_of_volume(volume)
        snap_pool_id = self.storage_info['snap_pool_id']
        ldev_range = self.storage_info['ldev_range']
        qos_specs = utils.get_qos_specs_from_volume(volume)
        new_ldev = self.copy_on_storage(ldev, size, extra_specs, pool_id,
                                        snap_pool_id, ldev_range,
                                        is_rep=is_rep, qos_specs=qos_specs)
        self.modify_ldev_name(new_ldev, volume['id'].replace("-", ""))
        if is_rep:
            self.delete_pair(new_ldev)

        return {
            'provider_location': str(new_ldev),
        }

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume and return its properties."""
        return self.create_volume_from_src(volume, src_vref, STR_VOLUME)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot and return its properties."""
        return self.create_volume_from_src(volume, snapshot, STR_SNAPSHOT)

    def delete_pair_based_on_svol(self, pvol, svol_info):
        """Disconnect all volume pairs to which the specified S-VOL belongs."""
        raise NotImplementedError()

    def get_pair_info(self, ldev, ldev_info=None):
        """Return volume pair info(LDEV number, pair status and pair type)."""
        raise NotImplementedError()

    def delete_pair(self, ldev, ldev_info=None):
        """Disconnect all volume pairs to which the specified LDEV belongs.

        :param int ldev: The ID of the LDEV whose TI pair needs be deleted
        :param dict ldev_info: LDEV info
        :return: None
        :raises VolumeDriverException: if the LDEV is a P-VOL of a TI pair
        """
        pair_info = self.get_pair_info(ldev, ldev_info)
        if not pair_info:
            return
        if pair_info['pvol'] == ldev:
            self.output_log(
                MSG.UNABLE_TO_DELETE_PAIR, pvol=pair_info['pvol'])
            self.raise_busy()
        else:
            self.delete_pair_based_on_svol(
                pair_info['pvol'], pair_info['svol_info'][0])

    def find_all_mapped_targets_from_storage(self, targets, ldev):
        """Add all port-gids connected with the LDEV to the list."""
        raise NotImplementedError()

    def unmap_ldev(self, targets, ldev):
        """Delete the LUN between the specified LDEV and port-gid."""
        raise NotImplementedError()

    def unmap_ldev_from_storage(self, ldev):
        """Delete the connection between the specified LDEV and servers."""
        targets = {
            'list': [],
        }
        self.find_all_mapped_targets_from_storage(targets, ldev)
        self.unmap_ldev(targets, ldev)

    def delete_ldev_from_storage(self, ldev):
        """Delete the specified LDEV from the storage."""
        raise NotImplementedError()

    def delete_ldev(self, ldev, ldev_info=None):
        """Delete the specified LDEV.

        :param int ldev: The ID of the LDEV to be deleted
        :param dict ldev_info: LDEV info
        :return: None
        """
        self.delete_pair(ldev, ldev_info)
        self.unmap_ldev_from_storage(ldev)
        self.delete_ldev_from_storage(ldev)

    def is_invalid_ldev(self, ldev, obj, ldev_info_):
        """Check if the specified LDEV corresponds to the specified object.

        If the LDEV label and the object's id or name_id do not match, the LDEV
        was deleted and another LDEV with the same ID was created for another
        volume or snapshot. In this case, we say that the LDEV is invalid.
        If the LDEV label is not set or its format is unexpected, we cannot
        judge if the LDEV corresponds to the object. This can happen if the
        LDEV was created in older versions of this product or if the user
        overwrote the label. In this case, we just say that the LDEV is not
        invalid, although we are not completely sure about it.
        The reason for using name_id rather than id for volumes in comparison
        is that id of the volume that corresponds to the LDEV changes by
        host-assisted migration while that is not the case with name_id and
        that the LDEV label is created from id of the volume when the LDEV is
        created and is never changed after that.
        Because Snapshot objects do not have name_id, we use id instead of
        name_id if the object is a Snapshot. We assume that the object is a
        Snapshot object if hasattr(obj, 'name_id') returns False.
        This method returns False if the LDEV does not exist on the storage.
        The absence of the LDEV on the storage is detected elsewhere.
        :param int ldev: The ID of the LDEV to be checked
        :param obj: The object to be checked
        :type obj: Volume or Snapshot
        :param dict ldev_info_: LDEV info. This is an output area. Data is
        written by this method, but the area must be secured by the caller.
        :return: True if the LDEV does not correspond to the object, False
        otherwise
        :rtype: bool
        """
        ldev_info = self.get_ldev_info(None, ldev)
        # To avoid calling the same REST API multiple times, we pass the LDEV
        # info to the caller.
        ldev_info_.update(ldev_info)
        return ('label' in ldev_info
                and _UUID_PATTERN.match(ldev_info['label'])
                and ldev_info['label'] != (
                    obj.name_id if hasattr(obj, 'name_id') else
                    obj.id).replace('-', ''))

    def delete_volume(self, volume):
        """Delete the specified volume."""
        ldev = self.get_ldev(volume)
        if ldev is None:
            self.output_log(
                MSG.INVALID_LDEV_FOR_DELETION,
                method='delete_volume', id=volume['id'])
            return
        # Check if the LDEV corresponds to the volume.
        # To avoid KeyError when accessing a missing attribute, set the default
        # value to None.
        ldev_info = defaultdict(lambda: None)
        if self.is_invalid_ldev(ldev, volume, ldev_info):
            # If the LDEV is assigned to another object, skip deleting it.
            self.output_log(MSG.SKIP_DELETING_LDEV, obj='volume',
                            obj_id=volume.id, ldev=ldev,
                            ldev_label=ldev_info['label'])
            return
        try:
            self.delete_ldev(ldev, ldev_info)
        except exception.VolumeDriverException as ex:
            if utils.BUSY_MESSAGE in ex.msg:
                raise exception.VolumeIsBusy(volume_name=volume['name'])
            else:
                raise ex

    def create_snapshot(self, snapshot):
        """Create a snapshot from a volume and return its properties."""
        src_vref = snapshot.volume
        ldev = self.get_ldev(src_vref)
        if ldev is None:
            msg = self.output_log(
                MSG.INVALID_LDEV_FOR_VOLUME_COPY,
                type='volume', id=src_vref['id'])
            self.raise_error(msg)
        size = snapshot['volume_size']
        extra_specs = self.get_volume_extra_specs(snapshot['volume'])
        pool_id = self.get_pool_id_of_volume(snapshot['volume'])
        snap_pool_id = self.storage_info['snap_pool_id']
        ldev_range = self.storage_info['ldev_range']
        qos_specs = utils.get_qos_specs_from_volume(snapshot)
        new_ldev = self.copy_on_storage(
            ldev, size, extra_specs, pool_id, snap_pool_id, ldev_range,
            is_snapshot=True, qos_specs=qos_specs)
        self.modify_ldev_name(new_ldev, snapshot.id.replace("-", ""))
        return {
            'provider_location': str(new_ldev),
        }

    def delete_snapshot(self, snapshot):
        """Delete the specified snapshot."""
        ldev = self.get_ldev(snapshot)
        if ldev is None:
            self.output_log(
                MSG.INVALID_LDEV_FOR_DELETION, method='delete_snapshot',
                id=snapshot['id'])
            return
        # Check if the LDEV corresponds to the snapshot.
        # To avoid KeyError when accessing a missing attribute, set the default
        # value to None.
        ldev_info = defaultdict(lambda: None)
        if self.is_invalid_ldev(ldev, snapshot, ldev_info):
            # If the LDEV is assigned to another object, skip deleting it.
            self.output_log(MSG.SKIP_DELETING_LDEV, obj='snapshot',
                            obj_id=snapshot.id, ldev=ldev,
                            ldev_label=ldev_info['label'])
            return
        try:
            self.delete_ldev(ldev, ldev_info)
        except exception.VolumeDriverException as ex:
            if utils.BUSY_MESSAGE in ex.msg:
                raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])
            else:
                raise ex

    def get_pool_info(self, pool_id, result=None):
        """Return the total and free capacity of the storage pool."""
        raise NotImplementedError()

    def get_pool_infos(self, pool_ids):
        """Return the total and free capacity of the storage pools."""
        raise NotImplementedError()

    def _create_single_pool_data(self, pool_id, pool_name, cap_data):
        location_info = {
            'storage_id': self.conf.hitachi_storage_id,
            'pool_id': pool_id,
            'snap_pool_id': self.storage_info['snap_pool_id'],
            'ldev_range': self.storage_info['ldev_range']}
        single_pool = {}
        single_pool.update(dict(
            pool_name=pool_name,
            reserved_percentage=self.conf.safe_get('reserved_percentage'),
            QoS_support=True,
            thin_provisioning_support=True,
            thick_provisioning_support=False,
            multiattach=True,
            consistencygroup_support=True,
            consistent_group_snapshot_enabled=True,
            max_over_subscription_ratio=(
                volume_utils.get_max_over_subscription_ratio(
                    self.conf.safe_get('max_over_subscription_ratio'),
                    True)),
            location_info=location_info
        ))
        if cap_data is None:
            single_pool.update(dict(
                total_capacity_gb=0,
                free_capacity_gb=0,
                provisioned_capacity_gb=0,
                backend_state='down'))
            self.output_log(MSG.POOL_INFO_RETRIEVAL_FAILED, pool=pool_name)
            return single_pool
        total_capacity, free_capacity, provisioned_capacity = cap_data
        single_pool.update(dict(
            total_capacity_gb=total_capacity,
            free_capacity_gb=free_capacity,
            provisioned_capacity_gb=provisioned_capacity
        ))
        single_pool.update(dict(backend_state='up'))
        return single_pool

    def update_volume_stats(self):
        """Update properties, capabilities and current states of the driver."""
        data = {}
        backend_name = (self.conf.safe_get('volume_backend_name') or
                        self.driver_info['volume_backend_name'])
        data = {
            'volume_backend_name': backend_name,
            'vendor_name': self.driver_info['vendor_name'],
            'driver_version': self.driver_info['version'],
            'storage_protocol': self.storage_info['protocol'],
            'pools': [],
        }
        for pool_id, pool_name, cap_data in zip(
                self.storage_info['pool_id'], self.conf.hitachi_pools,
                self.get_pool_infos(self.storage_info['pool_id'])):
            single_pool = self._create_single_pool_data(
                pool_id, pool_name if len(self.conf.hitachi_pools) > 1 else
                data['volume_backend_name'], cap_data)
            data['pools'].append(single_pool)
        LOG.debug("Updating volume status. (%s)", data)
        self._stats = data
        return data

    def discard_zero_page(self, volume):
        """Return the volume's no-data pages to the storage pool."""
        raise NotImplementedError()

    def check_pair_svol(self, ldev):
        """Check if the specified LDEV is S-VOL in a copy pair."""
        raise NotImplementedError()

    def extend_ldev(self, ldev, old_size, new_size):
        """Extend the specified LDEV to the specified new size."""
        raise NotImplementedError()

    def extend_volume(self, volume, new_size):
        """Extend the specified volume to the specified size."""
        ldev = self.get_ldev(volume)
        if ldev is None:
            msg = self.output_log(MSG.INVALID_LDEV_FOR_EXTENSION,
                                  volume_id=volume['id'])
            self.raise_error(msg)
        if self.check_pair_svol(ldev):
            msg = self.output_log(MSG.INVALID_VOLUME_TYPE_FOR_EXTEND,
                                  volume_id=volume['id'])
            self.raise_error(msg)
        self.delete_pair(ldev)
        self.extend_ldev(ldev, volume['size'], new_size)

    def get_ldev_by_name(self, name):
        """Get the LDEV number from the given name."""
        raise NotImplementedError()

    def check_ldev_manageability(self, ldev, existing_ref):
        """Check if the LDEV meets the criteria for being managed."""
        raise NotImplementedError()

    def get_qos_specs_from_ldev(self, ldev):
        raise NotImplementedError()

    def change_qos_specs(self, ldev, old_qos_specs, new_qos_specs):
        raise NotImplementedError()

    def manage_existing(self, volume, existing_ref):
        """Return volume properties which Cinder needs to manage the volume."""
        if 'source-name' in existing_ref:
            ldev = self.get_ldev_by_name(
                existing_ref.get('source-name').replace('-', ''))
        elif 'source-id' in existing_ref:
            ldev = str2int(existing_ref.get('source-id'))
        self.check_ldev_manageability(ldev, existing_ref)
        self.modify_ldev_name(ldev, volume['id'].replace("-", ""))
        new_qos_specs = utils.get_qos_specs_from_volume(volume)
        old_qos_specs = self.get_qos_specs_from_ldev(ldev)
        if old_qos_specs != new_qos_specs:
            self.change_qos_specs(ldev, old_qos_specs, new_qos_specs)
        return {
            'provider_location': str(ldev),
        }

    def get_ldev_size_in_gigabyte(self, ldev, existing_ref):
        """Return the size[GB] of the specified LDEV."""
        raise NotImplementedError()

    def manage_existing_get_size(self, volume, existing_ref):
        """Return the size[GB] of the specified volume."""
        ldev = None
        if 'source-name' in existing_ref:
            ldev = self.get_ldev_by_name(
                existing_ref.get('source-name').replace("-", ""))
        elif 'source-id' in existing_ref:
            ldev = str2int(existing_ref.get('source-id'))
        if ldev is None:
            msg = self.output_log(MSG.INVALID_LDEV_FOR_MANAGE)
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=msg)
        return self.get_ldev_size_in_gigabyte(ldev, existing_ref)

    def unmanage(self, volume):
        """Prepare the volume for removing it from Cinder management."""
        ldev = self.get_ldev(volume)
        if ldev is None:
            self.output_log(MSG.INVALID_LDEV_FOR_DELETION, method='unmanage',
                            id=volume['id'])
            return
        if self.check_pair_svol(ldev):
            self.output_log(
                MSG.INVALID_LDEV_TYPE_FOR_UNMANAGE, volume_id=volume['id'],
                volume_type=utils.NORMAL_LDEV_TYPE)
            raise exception.VolumeIsBusy(volume_name=volume['name'])
        try:
            self.delete_pair(ldev)
        except exception.VolumeDriverException as ex:
            if utils.BUSY_MESSAGE in ex.msg:
                raise exception.VolumeIsBusy(volume_name=volume['name'])
            else:
                raise ex

    def _range2list(self, param):
        """Analyze a 'xxx-xxx' string and return a list of two integers."""
        values = [str2int(value) for value in
                  self.conf.safe_get(param).split('-')]
        if len(values) != 2 or None in values or values[0] > values[1]:
            msg = self.output_log(MSG.INVALID_PARAMETER, param=param)
            self.raise_error(msg)
        return values

    def check_param_fc(self):
        """Check FC-related parameter values and consistency among them."""
        if hasattr(
                self.conf,
                self.driver_info['param_prefix'] + '_port_scheduler'):
            self.check_opts(self.conf, COMMON_PORT_OPTS)
            if (self.conf.hitachi_port_scheduler and
                    not self.conf.hitachi_group_create):
                msg = self.output_log(
                    MSG.INVALID_PARAMETER,
                    param=self.driver_info['param_prefix'] + '_port_scheduler')
                self.raise_error(msg)
            if (self._lookup_service is None and
                    self.conf.hitachi_port_scheduler):
                msg = self.output_log(MSG.ZONE_MANAGER_IS_NOT_AVAILABLE)
                self.raise_error(msg)

    def check_param_iscsi(self):
        """Check iSCSI-related parameter values and consistency among them."""
        if self.conf.use_chap_auth:
            if not self.conf.chap_username:
                msg = self.output_log(MSG.INVALID_PARAMETER,
                                      param='chap_username')
                self.raise_error(msg)
            if not self.conf.chap_password:
                msg = self.output_log(MSG.INVALID_PARAMETER,
                                      param='chap_password')
                self.raise_error(msg)

    def check_param(self):
        """Check parameter values and consistency among them."""
        self.check_opt_value(self.conf, _INHERITED_VOLUME_OPTS)
        self.check_opts(self.conf, COMMON_VOLUME_OPTS)
        if hasattr(
                self.conf,
                self.driver_info['param_prefix'] + '_pair_target_number'):
            self.check_opts(self.conf, COMMON_PAIR_OPTS)
        if hasattr(
                self.conf,
                self.driver_info['param_prefix'] + '_group_name_format'):
            self.check_opts(self.conf, COMMON_NAME_OPTS)
        if self.conf.hitachi_ldev_range:
            self.storage_info['ldev_range'] = self._range2list(
                self.driver_info['param_prefix'] + '_ldev_range')
        if (not self.conf.hitachi_target_ports and
                not self.conf.hitachi_compute_target_ports):
            msg = self.output_log(
                MSG.INVALID_PARAMETER,
                param=self.driver_info['param_prefix'] + '_target_ports or ' +
                self.driver_info['param_prefix'] + '_compute_target_ports')
            self.raise_error(msg)
        self._check_param_group_name_format()
        if (self.conf.hitachi_group_delete and
                not self.conf.hitachi_group_create):
            msg = self.output_log(
                MSG.INVALID_PARAMETER,
                param=self.driver_info['param_prefix'] + '_group_delete or '
                + self.driver_info['param_prefix'] + '_group_create')
            self.raise_error(msg)
        for opt in self._required_common_opts:
            if not self.conf.safe_get(opt):
                msg = self.output_log(MSG.INVALID_PARAMETER, param=opt)
                self.raise_error(msg)
        for pool in self.conf.hitachi_pools:
            if len(pool) == 0:
                msg = self.output_log(
                    MSG.INVALID_PARAMETER,
                    param=self.driver_info['param_prefix'] + '_pools')
                self.raise_error(msg)
        if self.storage_info['protocol'] == 'FC':
            self.check_param_fc()
        if self.storage_info['protocol'] == 'iSCSI':
            self.check_param_iscsi()

    def _check_param_group_name_format(self):
        if not hasattr(
                self.conf,
                self.driver_info['param_prefix'] + '_group_name_format'):
            return
        if self.conf.hitachi_group_name_format is not None:
            error_flag = False
            if re.match(
                    self.driver_info['target_prefix'] + '(' +
                    GROUP_NAME_VAR_WWN + '|' +
                    GROUP_NAME_VAR_IP + '|' + GROUP_NAME_VAR_HOST + '|' + '[' +
                    GROUP_NAME_ALLOWED_CHARS + '])+$',
                    self.conf.hitachi_group_name_format) is None:
                error_flag = True
            if not error_flag:
                for var in _GROUP_NAME_VAR_LEN:
                    self.format_info['group_name_var_cnt'][var] = (
                        self.conf.hitachi_group_name_format.count(var))
                    if (self.format_info[
                            'group_name_var_cnt'][var] not in
                            self.group_name_format['group_name_var_cnt'][var]):
                        error_flag = True
                        break
            if not error_flag:
                group_name_var_replaced = self.conf.hitachi_group_name_format
                for var, length in _GROUP_NAME_VAR_LEN.items():
                    group_name_var_replaced = (
                        group_name_var_replaced.replace(var, '_' * length))
                if len(group_name_var_replaced) > self.group_name_format[
                        'group_name_max_len']:
                    error_flag = True
            if error_flag:
                msg = self.output_log(
                    MSG.INVALID_PARAMETER,
                    param=self.driver_info['param_prefix'] +
                    '_group_name_format')
                self.raise_error(msg)
            self.format_info['group_name_format'] = (
                self.conf.hitachi_group_name_format)
            self.format_info['group_name_format_without_var_len'] = (
                len(re.sub('|'.join(
                    [GROUP_NAME_VAR_WWN, GROUP_NAME_VAR_IP,
                     GROUP_NAME_VAR_HOST]), '',
                    self.format_info['group_name_format'])))

    def need_client_setup(self):
        """Check if the making of the communication client is necessary."""
        raise NotImplementedError()

    def setup_client(self):
        """Initialize RestApiClient."""
        pass

    def enter_keep_session(self):
        """Begin the keeping of the session."""
        pass

    def check_pool_id(self):
        """Check the pool id of hitachi_pools and hitachi_snap_pool."""
        raise NotImplementedError()

    def connect_storage(self):
        """Prepare for using the storage."""
        self.check_pool_id()
        self.output_log(MSG.SET_CONFIG_VALUE, object='DP Pool ID',
                        value=self.storage_info['pool_id'])
        self.storage_info['controller_ports'] = []
        self.storage_info['compute_ports'] = []

    def find_targets_from_storage(self, targets, connector, target_ports):
        """Find mapped ports, memorize them and return unmapped port count."""
        raise NotImplementedError()

    def get_hba_ids_from_connector(self, connector):
        """Return the HBA ID stored in the connector."""
        if self.driver_info['hba_id'] in connector:
            return connector[self.driver_info['hba_id']]
        msg = self.output_log(MSG.RESOURCE_NOT_FOUND,
                              resource=self.driver_info['hba_id_type'])
        self.raise_error(msg)

    def set_device_map(self, targets, hba_ids, volume):
        return None, hba_ids

    def get_port_scheduler_param(self):
        if hasattr(
                self.conf,
                self.driver_info['param_prefix'] + '_port_scheduler'):
            return self.conf.hitachi_port_scheduler
        else:
            return False

    def create_target_by_port_scheduler(
            self, devmap, targets, connector, volume):
        raise NotImplementedError()

    def create_target_to_storage(self, port, connector, hba_ids):
        """Create a host group or an iSCSI target on the specified port."""
        raise NotImplementedError()

    def get_gid_from_targets(self, targets, port):
        for target_port, target_gid in targets['list']:
            if target_port == port:
                return target_gid
        msg = self.output_log(MSG.NO_CONNECTED_TARGET)
        self.raise_error(msg)

    def set_target_mode(self, port, gid):
        """Configure the target to meet the environment."""
        raise NotImplementedError()

    def set_hba_ids(self, port, gid, hba_ids):
        """Connect all specified HBAs with the specified port."""
        raise NotImplementedError()

    def delete_target_from_storage(self, port, gid):
        """Delete the host group or the iSCSI target from the port."""
        raise NotImplementedError()

    def set_target_map_info(self, targets, hba_ids, port):
        pass

    def create_target(self, targets, port, connector, hba_ids):
        """Create a host group or an iSCSI target on the storage port."""
        if port not in targets['info'] or not targets['info'][port]:
            target_name, gid = self.create_target_to_storage(
                port, connector, hba_ids)
            self.output_log(
                MSG.OBJECT_CREATED,
                object='a target',
                details='port: %(port)s, gid: %(gid)s, target_name: '
                        '%(target)s' %
                        {'port': port, 'gid': gid, 'target': target_name})
        else:
            gid = self.get_gid_from_targets(targets, port)
        try:
            if port not in targets['info'] or not targets['info'][port]:
                self.set_target_mode(port, gid)
            self.set_hba_ids(port, gid, hba_ids)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.delete_target_from_storage(port, gid)
        targets['info'][port] = True
        if (port, gid) not in targets['list']:
            targets['list'].append((port, gid))
        self.set_target_map_info(targets, hba_ids, port)

    def create_mapping_targets(self, targets, connector, volume=None):
        """Create server-storage connection for all specified storage ports."""
        active_hba_ids = []
        hba_ids = self.get_hba_ids_from_connector(connector)

        devmap, active_hba_ids = self.set_device_map(targets, hba_ids, volume)

        if self.get_port_scheduler_param():
            self.create_target_by_port_scheduler(
                devmap, targets, connector, volume)
        else:
            for port in targets['info'].keys():
                if targets['info'][port]:
                    continue

                try:
                    self.create_target(
                        targets, port, connector, active_hba_ids)
                except exception.VolumeDriverException:
                    self.output_log(
                        self.driver_info['msg_id']['target'], port=port)

        # When other threads created a host group at same time, need to
        # re-find targets.
        if not targets['list']:
            self.find_targets_from_storage(
                targets, connector, list(targets['info'].keys()))

    def get_port_index_to_be_used(self, ports, network_name):
        backend_name = self.conf.safe_get('volume_backend_name')
        code = (
            str(self.conf.hitachi_storage_id) + backend_name + network_name)
        if code in self.port_index.keys():
            if self.port_index[code] >= len(ports) - 1:
                self.port_index[code] = 0
            else:
                self.port_index[code] += 1
        else:
            self.port_index[code] = 0

        return self.port_index[code]

    def init_cinder_hosts(self, **kwargs):
        """Initialize server-storage connection."""
        targets = kwargs.pop(
            'targets', {'info': {}, 'list': [], 'iqns': {}, 'target_map': {}})
        connector = volume_utils.brick_get_connector_properties(
            multipath=self.conf.use_multipath_for_image_xfer,
            enforce_multipath=self.conf.enforce_multipath_for_image_xfer)
        target_ports = self.storage_info['controller_ports']

        if target_ports:
            if (self.find_targets_from_storage(
                    targets, connector, target_ports) and
                    self.conf.hitachi_group_create):
                self.create_mapping_targets(targets, connector)

            self.require_target_existed(targets)

    def do_setup(self, context):
        """Prepare for the startup of the driver."""

        @coordination.synchronized('{self.lock[do_setup]}')
        def _with_synchronized(self):
            self.connect_storage()
            self.init_cinder_hosts()

        self.ctxt = context
        self.check_param()
        if self.need_client_setup():
            self.setup_client()
            self.enter_keep_session()
        _with_synchronized(self)

    def check_ports_info(self):
        """Check if available storage ports exist."""
        if (self.conf.hitachi_target_ports and
                not self.storage_info['controller_ports']):
            msg = self.output_log(MSG.RESOURCE_NOT_FOUND,
                                  resource="Target ports")
            self.raise_error(msg)
        if (self.conf.hitachi_compute_target_ports and
                not self.storage_info['compute_ports']):
            msg = self.output_log(MSG.RESOURCE_NOT_FOUND,
                                  resource="Compute target ports")
            self.raise_error(msg)
        self.output_log(MSG.SET_CONFIG_VALUE, object='target port list',
                        value=self.storage_info['controller_ports'])
        self.output_log(MSG.SET_CONFIG_VALUE,
                        object='compute target port list',
                        value=self.storage_info['compute_ports'])

    def attach_ldev(
            self, volume, ldev, connector, is_snapshot, targets, lun=None):
        """Initialize connection between the server and the volume."""
        raise NotImplementedError()

    def get_properties_fc(self, targets):
        """Return FC-specific server-LDEV connection info."""
        data = {}
        data['target_wwn'] = [
            self.storage_info['wwns'][target[0]] for target in targets['list']
            if targets['lun'][target[0]]]
        return data

    def get_properties_iscsi(self, targets, multipath):
        """Return iSCSI-specific server-LDEV connection info."""
        data = {}
        primary_target = targets['list'][0]
        if not multipath:
            data['target_portal'] = self.storage_info[
                'portals'][primary_target[0]]
            data['target_iqn'] = targets['iqns'][primary_target]
        else:
            # Set the list of numbers that LUN was added
            data['target_portals'] = [
                self.storage_info['portals'][target[0]] for target in
                targets['list'] if targets['lun'][target[0]]]
            data['target_iqns'] = [
                targets['iqns'][target] for target in targets['list']
                if targets['lun'][target[0]]]
        if self.conf.use_chap_auth:
            data['auth_method'] = 'CHAP'
            data['auth_username'] = self.conf.chap_username
            data['auth_password'] = self.conf.chap_password
        return data

    def get_properties(self, targets, target_lun, connector):
        """Return server-LDEV connection info."""
        multipath = connector.get('multipath', False)
        if self.storage_info['protocol'] == 'FC':
            data = self.get_properties_fc(targets)
        elif self.storage_info['protocol'] == 'iSCSI':
            data = self.get_properties_iscsi(targets, multipath)
        data['target_discovered'] = False
        if not multipath or self.storage_info['protocol'] == 'FC':
            data['target_lun'] = target_lun
        else:
            # Set the list of numbers that LUN was added
            target_luns = []
            for target in targets['list']:
                if targets['lun'][target[0]]:
                    target_luns.append(target_lun)
            data['target_luns'] = target_luns
        return data

    # A synchronization to prevent conflicts between host group creation
    # and deletion.
    @coordination.synchronized(
        '{self.driver_info[driver_file_prefix]}-host-'
        '{self.conf.hitachi_storage_id}-{connector[host]}')
    def initialize_connection(
            self, volume, connector, is_snapshot=False, lun=None):
        """Initialize connection between the server and the volume."""
        targets = {
            'info': {},
            'list': [],
            'lun': {},
            'iqns': {},
            'target_map': {},
        }
        ldev = self.get_ldev(volume)
        if ldev is None:
            msg = self.output_log(MSG.INVALID_LDEV_FOR_CONNECTION,
                                  volume_id=volume['id'])
            self.raise_error(msg)

        target_lun = self.attach_ldev(
            volume, ldev, connector, is_snapshot, targets, lun)

        return {
            'driver_volume_type': self.driver_info['volume_type'],
            'data': self.get_properties(targets, target_lun, connector),
        }, targets['target_map']

    def get_target_ports(self, connector):
        """Return a list of ports corresponding to the specified connector."""
        if 'ip' in connector and connector['ip'] == CONF.my_ip:
            return self.storage_info['controller_ports']
        return (self.storage_info['compute_ports'] or
                self.storage_info['controller_ports'])

    def get_port_hostgroup_map(self, ldev_id):
        """Get the mapping of a port and host group."""
        raise NotImplementedError()

    def set_terminate_target(self, fake_connector, port_hostgroup_map):
        """Set necessary information in connector in terminate."""
        raise NotImplementedError()

    def detach_ldev(self, volume, ldev, connector):
        """Terminate connection between the server and the volume."""
        raise NotImplementedError()

    def terminate_connection(self, volume, connector):
        """Terminate connection between the server and the volume."""
        ldev = self.get_ldev(volume)
        if ldev is None:
            self.output_log(MSG.INVALID_LDEV_FOR_UNMAPPING,
                            volume_id=volume['id'])
            return
        # If a fake connector is generated by nova when the host
        # is down, then the connector will not have a host property,
        # In this case construct the lock without the host property
        # so that all the fake connectors to an SVC are serialized
        if 'host' not in connector:
            port_hostgroup_map = self.get_port_hostgroup_map(ldev)
            if not port_hostgroup_map:
                self.output_log(MSG.NO_LUN, ldev=ldev)
                return
            self.set_terminate_target(connector, port_hostgroup_map)

        # A synchronization to prevent conflicts between host group creation
        # and deletion.
        @coordination.synchronized(
            '%(prefix)s-host-%(storage_id)s-%(host)s' % {
                'prefix': self.driver_info['driver_file_prefix'],
                'storage_id': self.conf.hitachi_storage_id,
                'host': connector.get('host'),
            }
        )
        def inner(self, volume, connector):
            deleted_targets = self.detach_ldev(volume, ldev, connector)
            if self.storage_info['protocol'] == 'FC':
                target_wwn = [
                    self.storage_info['wwns'][target]
                    for target in deleted_targets]
                return {'driver_volume_type': self.driver_info['volume_type'],
                        'data': {'target_wwn': target_wwn}}
        return inner(self, volume, connector)

    def filter_target_ports(self, target_ports, volume, is_snapshot=False):
        specs = self.get_volume_extra_specs(volume) if volume else None
        if not specs:
            return target_ports
        if self.driver_info.get('driver_dir_name'):
            if getattr(self, 'is_secondary', False):
                tps_name = self.driver_info[
                    'driver_dir_name'] + ':remote_target_ports'
            else:
                tps_name = self.driver_info[
                    'driver_dir_name'] + ':target_ports'
        else:
            return target_ports

        tps = specs.get(tps_name)
        if tps is None:
            return target_ports

        tpsset = set([s.strip() for s in tps.split(',')])
        filtered_tps = list(tpsset.intersection(target_ports))
        if is_snapshot:
            volume = volume['volume']
        for port in tpsset:
            if port not in target_ports:
                self.output_log(
                    MSG.INVALID_EXTRA_SPEC_KEY_PORT,
                    port=port, target_ports_param=tps_name,
                    volume_type=volume['volume_type']['name'])

        return filtered_tps

    def clean_mapping_targets(self, targets):
        raise NotImplementedError()

    def unmanage_snapshot(self, snapshot):
        """Output error message and raise NotImplementedError."""
        self.output_log(
            MSG.SNAPSHOT_UNMANAGE_FAILED, snapshot_id=snapshot['id'])
        raise NotImplementedError()

    def migrate_volume(self, volume, host):
        """Migrate the specified volume."""
        return False

    def update_migrated_volume(self, new_volume):
        """Return model update for migrated volume."""
        return {'_name_id': new_volume.name_id,
                'provider_location': new_volume.provider_location}

    def retype(self, ctxt, volume, new_type, diff, host):
        """Retype the specified volume."""
        return False

    def has_snap_pair(self, pvol, svol):
        """Check if the volume have the pair of the snapshot."""
        raise NotImplementedError()

    def restore_ldev(self, pvol, svol):
        """Restore a pair of the specified LDEV."""
        raise NotImplementedError()

    def revert_to_snapshot(self, volume, snapshot):
        """Rollback the specified snapshot."""
        pvol = self.get_ldev(volume)
        svol = self.get_ldev(snapshot)
        if (pvol is not None and
                svol is not None and
                self.has_snap_pair(pvol, svol)):
            self.restore_ldev(pvol, svol)
        else:
            raise NotImplementedError()

    def create_group(self):
        raise NotImplementedError()

    def delete_group(self, group, volumes):
        raise NotImplementedError()

    def create_group_from_src(
            self, context, group, volumes, snapshots=None, source_vols=None):
        raise NotImplementedError()

    def update_group(self, group, add_volumes=None):
        raise NotImplementedError()

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        raise NotImplementedError()

    def delete_group_snapshot(self, group_snapshot, snapshots):
        raise NotImplementedError()

    def output_log(self, msg_enum, **kwargs):
        if self.storage_id is not None:
            return utils.output_log(
                msg_enum, storage_id=self.storage_id, **kwargs)
        else:
            return utils.output_log(msg_enum, **kwargs)

    def get_ldev(self, obj, both=False):
        if not obj:
            return None
        provider_location = obj.get('provider_location')
        if not provider_location:
            return None
        if provider_location.isdigit() and not getattr(self, 'is_secondary',
                                                       False):
            # This format implies that the value is the ID of an LDEV in the
            # primary storage. Therefore, the secondary instance should not
            # retrieve this value.
            return int(provider_location)
        if provider_location.startswith('{'):
            loc = json.loads(provider_location)
            if isinstance(loc, dict):
                if getattr(self, 'is_primary', False) or (
                        hasattr(self, 'primary_storage_id') and not both):
                    return None if 'pldev' not in loc else int(loc['pldev'])
                elif getattr(self, 'is_secondary', False):
                    return None if 'sldev' not in loc else int(loc['sldev'])
                if hasattr(self, 'primary_storage_id'):
                    return {key: loc.get(key) for key in ['pldev', 'sldev']}
        return None

    def check_opt_value(self, conf, names):
        """Check if the parameter names and values are valid."""
        for name in names:
            try:
                getattr(conf, name)
            except (cfg.NoSuchOptError, cfg.ConfigFileValueError):
                with excutils.save_and_reraise_exception():
                    self.output_log(MSG.INVALID_PARAMETER, param=name)

    def check_opts(self, conf, opts):
        """Check if the specified configuration is valid."""
        names = []
        for opt in opts:
            if opt.required and not conf.safe_get(opt.name):
                msg = self.output_log(MSG.INVALID_PARAMETER, param=opt.name)
                self.raise_error(msg)
            names.append(opt.name)
        self.check_opt_value(conf, names)

    def get_volume_extra_specs(self, volume):
        if volume is None:
            return {}
        type_id = volume.get('volume_type_id', None)
        if type_id is None:
            return {}

        return volume_types.get_volume_type_extra_specs(type_id)

    def require_target_existed(self, targets):
        """Check if the target list includes one or more members."""
        if not targets['list']:
            msg = self.output_log(MSG.NO_CONNECTED_TARGET)
            self.raise_error(msg)

    def raise_error(self, msg):
        """Raise a VolumeDriverException by driver error message."""
        message = _(
            '%(prefix)s error occurred. %(msg)s' % {
                'prefix': self.driver_info['driver_prefix'],
                'msg': msg,
            }
        )
        raise exception.VolumeDriverException(message)

    def raise_busy(self):
        """Raise a VolumeDriverException by driver busy message."""
        message = _(utils.BUSY_MESSAGE)
        raise exception.VolumeDriverException(message)

    def is_controller(self, connector):
        return True if (
            'ip' in connector and connector['ip'] == CONF.my_ip) else False
