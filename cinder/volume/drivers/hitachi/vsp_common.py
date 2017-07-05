# Copyright (C) 2016, Hitachi, Ltd.
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
"""Common module for Hitachi VSP Driver."""

import abc
import re

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units
import six

from cinder import coordination
from cinder import exception
from cinder import utils as cinder_utils
from cinder.volume import configuration
from cinder.volume.drivers.hitachi import vsp_utils as utils
from cinder.volume import utils as volume_utils


VERSION = '1.0.0'

_COPY_METHOD = set(['FULL', 'THIN'])

_INHERITED_VOLUME_OPTS = [
    'volume_backend_name',
    'volume_driver',
    'reserved_percentage',
    'use_multipath_for_image_xfer',
    'enforce_multipath_for_image_xfer',
    'num_volume_device_scan_tries',
]

common_opts = [
    cfg.StrOpt(
        'vsp_storage_id',
        help='Product number of the storage system.'),
    cfg.StrOpt(
        'vsp_pool',
        help='Pool number or pool name of the DP pool.'),
    cfg.StrOpt(
        'vsp_thin_pool',
        help='Pool number or pool name of the Thin Image pool.'),
    cfg.StrOpt(
        'vsp_ldev_range',
        help='Range of the LDEV numbers in the format of \'xxxx-yyyy\' that '
             'can be used by the driver. Values can be in decimal format '
             '(e.g. 1000) or in colon-separated hexadecimal format '
             '(e.g. 00:03:E8).'),
    cfg.StrOpt(
        'vsp_default_copy_method',
        default='FULL',
        choices=['FULL', 'THIN'],
        help='Method of volume copy. FULL indicates full data copy by '
             'Shadow Image and THIN indicates differential data copy by Thin '
             'Image.'),
    cfg.IntOpt(
        'vsp_copy_speed',
        min=1,
        max=15,
        default=3,
        help='Speed at which data is copied by Shadow Image. 1 or 2 indicates '
             'low speed, 3 indicates middle speed, and a value between 4 and '
             '15 indicates high speed.'),
    cfg.IntOpt(
        'vsp_copy_check_interval',
        min=1,
        max=600,
        default=3,
        help='Interval in seconds at which volume pair synchronization status '
             'is checked when volume pairs are created.'),
    cfg.IntOpt(
        'vsp_async_copy_check_interval',
        min=1,
        max=600,
        default=10,
        help='Interval in seconds at which volume pair synchronization status '
             'is checked when volume pairs are deleted.'),
    cfg.ListOpt(
        'vsp_target_ports',
        help='IDs of the storage ports used to attach volumes to the '
             'controller node. To specify multiple ports, connect them by '
             'commas (e.g. CL1-A,CL2-A).'),
    cfg.ListOpt(
        'vsp_compute_target_ports',
        help='IDs of the storage ports used to attach volumes to compute '
             'nodes. To specify multiple ports, connect them by commas '
             '(e.g. CL1-A,CL2-A).'),
    cfg.BoolOpt(
        'vsp_group_request',
        default=False,
        help='If True, the driver will create host groups or iSCSI targets on '
             'storage ports as needed.'),
]

_REQUIRED_COMMON_OPTS = [
    'vsp_storage_id',
    'vsp_pool',
]

CONF = cfg.CONF
CONF.register_opts(common_opts, group=configuration.SHARED_CONF_GROUP)

LOG = logging.getLogger(__name__)
MSG = utils.VSPMsg


def _str2int(num):
    """Convert a string into an integer."""
    if not num:
        return None
    if num.isdigit():
        return int(num)
    if not re.match(r'\w\w:\w\w:\w\w', num):
        return None
    try:
        return int(num.replace(':', ''), 16)
    except ValueError:
        return None


@six.add_metaclass(abc.ABCMeta)
class VSPCommon(object):
    """Common class for Hitachi VSP Driver."""

    def __init__(self, conf, driverinfo, db):
        """Initialize instance variables."""
        self.conf = conf
        self.db = db
        self.ctxt = None
        self.lock = {}
        self.driver_info = driverinfo
        self.storage_info = {
            'protocol': driverinfo['proto'],
            'pool_id': None,
            'ldev_range': [],
            'controller_ports': [],
            'compute_ports': [],
            'pair_ports': [],
            'wwns': {},
            'portals': {},
            'output_first': True,
        }

        self._stats = {}

    def run_and_verify_storage_cli(self, *cmd, **kwargs):
        """Run storage CLI and return the result or raise an exception."""
        do_raise = kwargs.pop('do_raise', True)
        ignore_error = kwargs.get('ignore_error')
        success_code = kwargs.get('success_code', set([0]))
        (ret, stdout, stderr) = self.run_storage_cli(*cmd, **kwargs)
        if (ret not in success_code and
                not utils.check_ignore_error(ignore_error, stderr)):
            msg = utils.output_log(
                MSG.STORAGE_COMMAND_FAILED, cmd=utils.mask_password(cmd),
                ret=ret, out=' '.join(stdout.splitlines()),
                err=' '.join(stderr.splitlines()))
            if do_raise:
                raise exception.VSPError(msg)
        return ret, stdout, stderr

    @abc.abstractmethod
    def run_storage_cli(self, *cmd, **kwargs):
        """Run storage CLI."""
        raise NotImplementedError()

    def get_copy_method(self, metadata):
        """Return copy method(FULL or THIN)."""
        method = metadata.get(
            'copy_method', self.conf.vsp_default_copy_method)
        if method not in _COPY_METHOD:
            msg = utils.output_log(MSG.INVALID_PARAMETER_VALUE,
                                   meta='copy_method')
            raise exception.VSPError(msg)
        if method == 'THIN' and not self.conf.vsp_thin_pool:
            msg = utils.output_log(MSG.INVALID_PARAMETER,
                                   param='vsp_thin_pool')
            raise exception.VSPError(msg)
        return method

    def create_volume(self, volume):
        """Create a volume and return its properties."""
        try:
            ldev = self.create_ldev(volume['size'])
        except exception.VSPError:
            with excutils.save_and_reraise_exception():
                utils.output_log(MSG.CREATE_LDEV_FAILED)
        return {
            'provider_location': six.text_type(ldev),
        }

    def create_ldev(self, size, is_vvol=False):
        """Create an LDEV and return its LDEV number."""
        ldev = self.get_unused_ldev()
        self.create_ldev_on_storage(ldev, size, is_vvol)
        LOG.debug('Created logical device. (LDEV: %s)', ldev)
        return ldev

    @abc.abstractmethod
    def create_ldev_on_storage(self, ldev, size, is_vvol):
        """Create an LDEV on the storage system."""
        raise NotImplementedError()

    @abc.abstractmethod
    def get_unused_ldev(self):
        """Find an unused LDEV and return its LDEV number."""
        raise NotImplementedError()

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot and return its properties."""
        ldev = utils.get_ldev(snapshot)
        # When 'ldev' is 0, it should be true.
        # Therefore, it cannot remove 'is None'.
        if ldev is None:
            msg = utils.output_log(
                MSG.INVALID_LDEV_FOR_VOLUME_COPY, type='snapshot',
                id=snapshot['id'])
            raise exception.VSPError(msg)
        size = volume['size']
        metadata = utils.get_volume_metadata(volume)
        if size < snapshot['volume_size']:
            msg = utils.output_log(
                MSG.INVALID_VOLUME_SIZE_FOR_COPY, type='snapshot',
                volume_id=volume['id'])
            raise exception.VSPError(msg)
        elif (size > snapshot['volume_size'] and not self.check_vvol(ldev) and
              self.get_copy_method(metadata) == "THIN"):
            msg = utils.output_log(MSG.INVALID_VOLUME_SIZE_FOR_TI,
                                   copy_method=utils.THIN,
                                   type='snapshot', volume_id=volume['id'])
            raise exception.VSPError(msg)
        sync = size > snapshot['volume_size']
        new_ldev = self._copy_ldev(
            ldev, snapshot['volume_size'], metadata, sync)
        if sync:
            self.delete_pair(new_ldev)
            self.extend_ldev(new_ldev, snapshot['volume_size'], size)
        return {
            'provider_location': six.text_type(new_ldev),
        }

    def _copy_ldev(self, ldev, size, metadata, sync=False):
        """Create a copy of the specified volume and return its properties."""
        try:
            return self.copy_on_storage(ldev, size, metadata, sync)
        except exception.VSPNotSupported:
            return self._copy_on_host(ldev, size)

    def _copy_on_host(self, src_ldev, size):
        """Create a copy of the specified LDEV via host."""
        dest_ldev = self.create_ldev(size)
        try:
            self._copy_with_dd(src_ldev, dest_ldev, size)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self._delete_ldev(dest_ldev)
                except exception.VSPError:
                    utils.output_log(MSG.DELETE_LDEV_FAILED, ldev=dest_ldev)
        return dest_ldev

    def _copy_with_dd(self, src_ldev, dest_ldev, size):
        """Copy the content of a volume by dd command."""
        src_info = None
        dest_info = None
        properties = cinder_utils.brick_get_connector_properties(
            multipath=self.conf.use_multipath_for_image_xfer,
            enforce_multipath=self.conf.enforce_multipath_for_image_xfer)
        try:
            dest_info = self._attach_ldev(dest_ldev, properties)
            src_info = self._attach_ldev(src_ldev, properties)
            volume_utils.copy_volume(
                src_info['device']['path'], dest_info['device']['path'],
                size * units.Ki, self.conf.volume_dd_blocksize)
        finally:
            if src_info:
                self._detach_ldev(src_info, src_ldev, properties)
            if dest_info:
                self._detach_ldev(dest_info, dest_ldev, properties)
        self.discard_zero_page({'provider_location': six.text_type(dest_ldev)})

    def _attach_ldev(self, ldev, properties):
        """Attach the specified LDEV to the server."""
        volume = {
            'provider_location': six.text_type(ldev),
        }
        conn = self.initialize_connection(volume, properties)
        try:
            connector = cinder_utils.brick_get_connector(
                conn['driver_volume_type'],
                use_multipath=self.conf.use_multipath_for_image_xfer,
                device_scan_attempts=self.conf.num_volume_device_scan_tries,
                conn=conn)
            device = connector.connect_volume(conn['data'])
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                utils.output_log(MSG.CONNECT_VOLUME_FAILED, ldev=ldev,
                                 reason=six.text_type(ex))
                self._terminate_connection(volume, properties)
        return {
            'conn': conn,
            'device': device,
            'connector': connector,
        }

    def _detach_ldev(self, attach_info, ldev, properties):
        """Detach the specified LDEV from the server."""
        volume = {
            'provider_location': six.text_type(ldev),
        }
        connector = attach_info['connector']
        try:
            connector.disconnect_volume(
                attach_info['conn']['data'], attach_info['device'])
        except Exception as ex:
            utils.output_log(MSG.DISCONNECT_VOLUME_FAILED, ldev=ldev,
                             reason=six.text_type(ex))
        self._terminate_connection(volume, properties)

    def _terminate_connection(self, volume, connector):
        """Disconnect the specified volume from the server."""
        try:
            self.terminate_connection(volume, connector)
        except exception.VSPError:
            utils.output_log(MSG.UNMAP_LDEV_FAILED,
                             ldev=utils.get_ldev(volume))

    def copy_on_storage(self, pvol, size, metadata, sync):
        """Create a copy of the specified LDEV on the storage."""
        is_thin = self.get_copy_method(metadata) == "THIN"
        svol = self.create_ldev(size, is_vvol=is_thin)
        try:
            self.create_pair_on_storage(pvol, svol, is_thin)
            if sync:
                self.wait_full_copy_completion(pvol, svol)
        except exception.VSPError:
            with excutils.save_and_reraise_exception():
                try:
                    self._delete_ldev(svol)
                except exception.VSPError:
                    utils.output_log(MSG.DELETE_LDEV_FAILED, ldev=svol)
        return svol

    @abc.abstractmethod
    def create_pair_on_storage(self, pvol, svol, is_thin):
        """Create a copy pair on the storage."""
        raise NotImplementedError()

    def _delete_ldev(self, ldev):
        """Delete the specified LDEV."""
        self.delete_pair(ldev)
        self.unmap_ldev_from_storage(ldev)
        self.delete_ldev_from_storage(ldev)

    def unmap_ldev_from_storage(self, ldev):
        """Delete the connection between the specified LDEV and servers."""
        targets = {
            'list': [],
        }
        self.find_all_mapped_targets_from_storage(targets, ldev)
        self.unmap_ldev(targets, ldev)

    @abc.abstractmethod
    def find_all_mapped_targets_from_storage(self, targets, ldev):
        """Add all port-gids connected with the LDEV to the list."""
        raise NotImplementedError()

    def delete_pair(self, ldev, all_split=True):
        """Disconnect all volume pairs to which the specified LDEV belongs."""
        pair_info = self.get_pair_info(ldev)
        if not pair_info:
            return
        if pair_info['pvol'] == ldev:
            self.delete_pair_based_on_pvol(pair_info, all_split)
        else:
            self.delete_pair_based_on_svol(
                pair_info['pvol'], pair_info['svol_info'][0])

    @abc.abstractmethod
    def get_pair_info(self, ldev):
        """Return volume pair info(LDEV number, pair status and pair type)."""
        raise NotImplementedError()

    @abc.abstractmethod
    def delete_pair_based_on_pvol(self, pair_info, all_split):
        """Disconnect all volume pairs to which the specified P-VOL belongs."""
        raise NotImplementedError()

    @abc.abstractmethod
    def delete_pair_based_on_svol(self, pvol, svol_info):
        """Disconnect all volume pairs to which the specified S-VOL belongs."""
        raise NotImplementedError()

    @abc.abstractmethod
    def delete_pair_from_storage(self, pvol, svol, is_thin):
        """Disconnect the volume pair that consists of the specified LDEVs."""
        raise NotImplementedError()

    @abc.abstractmethod
    def delete_ldev_from_storage(self, ldev):
        """Delete the specified LDEV from the storage."""
        raise NotImplementedError()

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume and return its properties."""
        ldev = utils.get_ldev(src_vref)
        # When 'ldev' is 0, it should be true.
        # Therefore, it cannot remove 'is not None'.
        if ldev is None:
            msg = utils.output_log(MSG.INVALID_LDEV_FOR_VOLUME_COPY,
                                   type='volume', id=src_vref['id'])
            raise exception.VSPError(msg)
        size = volume['size']
        metadata = utils.get_volume_metadata(volume)
        if size < src_vref['size']:
            msg = utils.output_log(MSG.INVALID_VOLUME_SIZE_FOR_COPY,
                                   type='volume', volume_id=volume['id'])
            raise exception.VSPError(msg)
        elif (size > src_vref['size'] and not self.check_vvol(ldev) and
              self.get_copy_method(metadata) == "THIN"):
            msg = utils.output_log(MSG.INVALID_VOLUME_SIZE_FOR_TI,
                                   copy_method=utils.THIN, type='volume',
                                   volume_id=volume['id'])
            raise exception.VSPError(msg)
        sync = size > src_vref['size']
        new_ldev = self._copy_ldev(ldev, src_vref['size'], metadata, sync)
        if sync:
            self.delete_pair(new_ldev)
            self.extend_ldev(new_ldev, src_vref['size'], size)
        return {
            'provider_location': six.text_type(new_ldev),
        }

    def delete_volume(self, volume):
        """Delete the specified volume."""
        ldev = utils.get_ldev(volume)
        # When 'ldev' is 0, it should be true.
        # Therefore, it cannot remove 'is not None'.
        if ldev is None:
            utils.output_log(MSG.INVALID_LDEV_FOR_DELETION,
                             method='delete_volume', id=volume['id'])
            return
        try:
            self._delete_ldev(ldev)
        except exception.VSPBusy:
            raise exception.VolumeIsBusy(volume_name=volume['name'])

    def create_snapshot(self, snapshot):
        """Create a snapshot from a volume and return its properties."""
        src_vref = snapshot.volume
        ldev = utils.get_ldev(src_vref)
        # When 'ldev' is 0, it should be true.
        # Therefore, it cannot remove 'is None'.
        if ldev is None:
            msg = utils.output_log(MSG.INVALID_LDEV_FOR_VOLUME_COPY,
                                   type='volume', id=src_vref['id'])
            raise exception.VSPError(msg)
        size = snapshot['volume_size']
        metadata = utils.get_volume_metadata(src_vref)
        new_ldev = self._copy_ldev(ldev, size, metadata)
        return {
            'provider_location': six.text_type(new_ldev),
        }

    def delete_snapshot(self, snapshot):
        """Delete the specified snapshot."""
        ldev = utils.get_ldev(snapshot)
        # When 'ldev' is 0, it should be true.
        # Therefore, it cannot remove 'is None'.
        if ldev is None:
            utils.output_log(
                MSG.INVALID_LDEV_FOR_DELETION, method='delete_snapshot',
                id=snapshot['id'])
            return
        try:
            self._delete_ldev(ldev)
        except exception.VSPBusy:
            raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])

    def get_volume_stats(self, refresh=False):
        """Return properties, capabilities and current states of the driver."""
        if refresh:
            if self.storage_info['output_first']:
                self.storage_info['output_first'] = False
                utils.output_log(MSG.DRIVER_READY_FOR_USE,
                                 config_group=self.conf.config_group)
            self._update_volume_stats()
        return self._stats

    def _update_volume_stats(self):
        """Update properties, capabilities and current states of the driver."""
        data = {}
        backend_name = self.conf.safe_get('volume_backend_name')
        data['volume_backend_name'] = (
            backend_name or self.driver_info['volume_backend_name'])
        data['vendor_name'] = 'Hitachi'
        data['driver_version'] = VERSION
        data['storage_protocol'] = self.storage_info['protocol']
        try:
            total_gb, free_gb = self.get_pool_info()
        except exception.VSPError:
            utils.output_log(MSG.POOL_INFO_RETRIEVAL_FAILED,
                             pool=self.conf.vsp_pool)
            return
        data['total_capacity_gb'] = total_gb
        data['free_capacity_gb'] = free_gb
        data['reserved_percentage'] = self.conf.safe_get('reserved_percentage')
        data['QoS_support'] = False
        data['multiattach'] = False
        LOG.debug("Updating volume status. (%s)", data)
        self._stats = data

    @abc.abstractmethod
    def get_pool_info(self):
        """Return the total and free capacity of the storage pool."""
        raise NotImplementedError()

    @abc.abstractmethod
    def discard_zero_page(self, volume):
        """Return the volume's no-data pages to the storage pool."""
        raise NotImplementedError()

    def extend_volume(self, volume, new_size):
        """Extend the specified volume to the specified size."""
        ldev = utils.get_ldev(volume)
        # When 'ldev' is 0, it should be true.
        # Therefore, it cannot remove 'is None'.
        if ldev is None:
            msg = utils.output_log(MSG.INVALID_LDEV_FOR_EXTENSION,
                                   volume_id=volume['id'])
            raise exception.VSPError(msg)
        if self.check_vvol(ldev):
            msg = utils.output_log(MSG.INVALID_VOLUME_TYPE_FOR_EXTEND,
                                   volume_id=volume['id'])
            raise exception.VSPError(msg)
        self.delete_pair(ldev)
        self.extend_ldev(ldev, volume['size'], new_size)

    @abc.abstractmethod
    def check_vvol(self, ldev):
        """Return True if the specified LDEV is V-VOL, False otherwise."""
        raise NotImplementedError()

    @abc.abstractmethod
    def extend_ldev(self, ldev, old_size, new_size):
        """Extend the specified LDEV to the specified new size."""
        raise NotImplementedError()

    def manage_existing(self, existing_ref):
        """Return volume properties which Cinder needs to manage the volume."""
        ldev = _str2int(existing_ref.get('source-id'))
        return {
            'provider_location': six.text_type(ldev),
        }

    def manage_existing_get_size(self, existing_ref):
        """Return the size[GB] of the specified volume."""
        ldev = _str2int(existing_ref.get('source-id'))
        # When 'ldev' is 0, it should be true.
        # Therefore, it cannot remove 'is None'.
        if ldev is None:
            msg = utils.output_log(MSG.INVALID_LDEV_FOR_MANAGE)
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=msg)
        return self.get_ldev_size_in_gigabyte(ldev, existing_ref)

    @abc.abstractmethod
    def get_ldev_size_in_gigabyte(self, ldev, existing_ref):
        """Return the size[GB] of the specified LDEV."""
        raise NotImplementedError()

    def unmanage(self, volume):
        """Prepare the volume for removing it from Cinder management."""
        ldev = utils.get_ldev(volume)
        # When 'ldev' is 0, it should be true.
        # Therefore, it cannot remove 'is None'.
        if ldev is None:
            utils.output_log(MSG.INVALID_LDEV_FOR_DELETION, method='unmanage',
                             id=volume['id'])
            return
        if self.check_vvol(ldev):
            utils.output_log(
                MSG.INVALID_LDEV_TYPE_FOR_UNMANAGE, volume_id=volume['id'],
                volume_type=utils.NORMAL_LDEV_TYPE)
            raise exception.VolumeIsBusy(volume_name=volume['name'])
        try:
            self.delete_pair(ldev)
        except exception.VSPBusy:
            raise exception.VolumeIsBusy(volume_name=volume['name'])

    def do_setup(self, context):
        """Prepare for the startup of the driver."""
        self.ctxt = context

        self.check_param()
        self.config_lock()
        self.connect_storage()
        self.init_cinder_hosts()
        self.output_param_to_log()

    def check_param(self):
        """Check parameter values and consistency among them."""
        utils.check_opt_value(self.conf, _INHERITED_VOLUME_OPTS)
        utils.check_opts(self.conf, common_opts)
        utils.check_opts(self.conf, self.driver_info['volume_opts'])
        if (self.conf.vsp_default_copy_method == 'THIN' and
                not self.conf.vsp_thin_pool):
            msg = utils.output_log(MSG.INVALID_PARAMETER,
                                   param='vsp_thin_pool')
            raise exception.VSPError(msg)
        if self.conf.vsp_ldev_range:
            self.storage_info['ldev_range'] = self._range2list(
                'vsp_ldev_range')
        if (not self.conf.vsp_target_ports and
                not self.conf.vsp_compute_target_ports):
            msg = utils.output_log(MSG.INVALID_PARAMETER,
                                   param='vsp_target_ports or '
                                   'vsp_compute_target_ports')
            raise exception.VSPError(msg)
        for opt in _REQUIRED_COMMON_OPTS:
            if not self.conf.safe_get(opt):
                msg = utils.output_log(MSG.INVALID_PARAMETER, param=opt)
                raise exception.VSPError(msg)
        if self.storage_info['protocol'] == 'iSCSI':
            self.check_param_iscsi()

    def check_param_iscsi(self):
        """Check iSCSI-related parameter values and consistency among them."""
        if self.conf.vsp_use_chap_auth:
            if not self.conf.vsp_auth_user:
                msg = utils.output_log(MSG.INVALID_PARAMETER,
                                       param='vsp_auth_user')
                raise exception.VSPError(msg)
            if not self.conf.vsp_auth_password:
                msg = utils.output_log(MSG.INVALID_PARAMETER,
                                       param='vsp_auth_password')
                raise exception.VSPError(msg)

    def _range2list(self, param):
        """Analyze a 'xxx-xxx' string and return a list of two integers."""
        values = [_str2int(value) for value in
                  self.conf.safe_get(param).split('-')]
        if (len(values) != 2 or
                values[0] is None or values[1] is None or
                values[0] > values[1]):
            msg = utils.output_log(MSG.INVALID_PARAMETER, param=param)
            raise exception.VSPError(msg)
        return values

    @abc.abstractmethod
    def config_lock(self):
        """Initialize lock resource names."""
        raise NotImplementedError()

    def connect_storage(self):
        """Prepare for using the storage."""
        self.storage_info['pool_id'] = self.get_pool_id()
        # When 'pool_id' is 0, it should be true.
        # Therefore, it cannot remove 'is None'.
        if self.storage_info['pool_id'] is None:
            msg = utils.output_log(MSG.POOL_NOT_FOUND, pool=self.conf.vsp_pool)
            raise exception.VSPError(msg)
        utils.output_log(MSG.SET_CONFIG_VALUE, object='DP Pool ID',
                         value=self.storage_info['pool_id'])

    def check_ports_info(self):
        """Check if available storage ports exist."""
        if (self.conf.vsp_target_ports and
                not self.storage_info['controller_ports']):
            msg = utils.output_log(MSG.RESOURCE_NOT_FOUND,
                                   resource="Target ports")
            raise exception.VSPError(msg)
        if (self.conf.vsp_compute_target_ports and
                not self.storage_info['compute_ports']):
            msg = utils.output_log(MSG.RESOURCE_NOT_FOUND,
                                   resource="Compute target ports")
            raise exception.VSPError(msg)
        utils.output_log(MSG.SET_CONFIG_VALUE, object='target port list',
                         value=self.storage_info['controller_ports'])
        utils.output_log(MSG.SET_CONFIG_VALUE,
                         object='compute target port list',
                         value=self.storage_info['compute_ports'])

    def get_pool_id(self):
        """Return the storage pool ID as integer."""
        pool = self.conf.vsp_pool
        if pool.isdigit():
            return int(pool)
        return None

    def init_cinder_hosts(self, **kwargs):
        """Initialize server-storage connection."""
        targets = kwargs.pop('targets', {'info': {}, 'list': [], 'iqns': {}})
        connector = cinder_utils.brick_get_connector_properties(
            multipath=self.conf.use_multipath_for_image_xfer,
            enforce_multipath=self.conf.enforce_multipath_for_image_xfer)
        target_ports = self.storage_info['controller_ports']

        if target_ports:
            if (self.find_targets_from_storage(
                    targets, connector, target_ports) and
                    self.conf.vsp_group_request):
                self.create_mapping_targets(targets, connector)

            utils.require_target_existed(targets)

    @abc.abstractmethod
    def find_targets_from_storage(self, targets, connector, target_ports):
        """Find mapped ports, memorize them and return unmapped port count."""
        raise NotImplementedError()

    def create_mapping_targets(self, targets, connector):
        """Create server-storage connection for all specified storage ports."""
        hba_ids = self.get_hba_ids_from_connector(connector)
        for port in targets['info'].keys():
            if targets['info'][port]:
                continue

            try:
                self._create_target(targets, port, connector, hba_ids)
            except exception.VSPError:
                utils.output_log(
                    self.driver_info['msg_id']['target'], port=port)

        if not targets['list']:
            self.find_targets_from_storage(
                targets, connector, targets['info'].keys())

    def get_hba_ids_from_connector(self, connector):
        """Return the HBA ID stored in the connector."""
        if self.driver_info['hba_id'] in connector:
            return connector[self.driver_info['hba_id']]
        msg = utils.output_log(MSG.RESOURCE_NOT_FOUND,
                               resource=self.driver_info['hba_id_type'])
        raise exception.VSPError(msg)

    def _create_target(self, targets, port, connector, hba_ids):
        """Create a host group or an iSCSI target on the storage port."""
        target_name, gid = self.create_target_to_storage(port, connector,
                                                         hba_ids)
        utils.output_log(MSG.OBJECT_CREATED, object='a target',
                         details='port: %(port)s, gid: %(gid)s, target_name: '
                         '%(target)s' %
                         {'port': port, 'gid': gid, 'target': target_name})
        try:
            self.set_target_mode(port, gid)
            self.set_hba_ids(port, gid, hba_ids)
        except exception.VSPError:
            with excutils.save_and_reraise_exception():
                self.delete_target_from_storage(port, gid)
        targets['info'][port] = True
        targets['list'].append((port, gid))

    @abc.abstractmethod
    def create_target_to_storage(self, port, connector, hba_ids):
        """Create a host group or an iSCSI target on the specified port."""
        raise NotImplementedError()

    @abc.abstractmethod
    def set_target_mode(self, port, gid):
        """Configure the target to meet the environment."""
        raise NotImplementedError()

    @abc.abstractmethod
    def set_hba_ids(self, port, gid, hba_ids):
        """Connect all specified HBAs with the specified port."""
        raise NotImplementedError()

    @abc.abstractmethod
    def delete_target_from_storage(self, port, gid):
        """Delete the host group or the iSCSI target from the port."""
        raise NotImplementedError()

    def output_param_to_log(self):
        """Output configuration parameter values to the log file."""
        utils.output_log(MSG.OUTPUT_PARAMETER_VALUES,
                         config_group=self.conf.config_group)
        name, version = self.get_storage_cli_info()
        utils.output_storage_cli_info(name, version)
        utils.output_opt_info(self.conf, _INHERITED_VOLUME_OPTS)
        utils.output_opts(self.conf, common_opts)
        utils.output_opts(self.conf, self.driver_info['volume_opts'])

    @abc.abstractmethod
    def get_storage_cli_info(self):
        """Return a tuple of the storage CLI name and its version."""
        raise NotImplementedError()

    @coordination.synchronized('vsp-host-{self.conf.vsp_storage_id}-'
                               '{connector[host]}')
    def initialize_connection(self, volume, connector):
        """Initialize connection between the server and the volume."""
        targets = {
            'info': {},
            'list': [],
            'lun': {},
            'iqns': {},
        }
        ldev = utils.get_ldev(volume)
        # When 'ldev' is 0, it should be true.
        # Therefore, it cannot remove 'is None'.
        if ldev is None:
            msg = utils.output_log(MSG.INVALID_LDEV_FOR_CONNECTION,
                                   volume_id=volume['id'])
            raise exception.VSPError(msg)

        target_ports = self.get_target_ports(connector)
        if (self.find_targets_from_storage(
                targets, connector, target_ports) and
                self.conf.vsp_group_request):
            self.create_mapping_targets(targets, connector)

        utils.require_target_existed(targets)

        targets['list'].sort()
        for port in target_ports:
            targets['lun'][port] = False
        target_lun = int(self.map_ldev(targets, ldev))

        return {
            'driver_volume_type': self.driver_info['volume_type'],
            'data': self.get_properties(targets, connector, target_lun),
        }

    def get_target_ports(self, connector):
        """Return a list of ports corresponding to the specified connector."""
        if 'ip' in connector and connector['ip'] == CONF.my_ip:
            return self.storage_info['controller_ports']
        return (self.storage_info['compute_ports'] or
                self.storage_info['controller_ports'])

    @abc.abstractmethod
    def map_ldev(self, targets, ldev):
        """Create the path between the server and the LDEV and return LUN."""
        raise NotImplementedError()

    def get_properties(self, targets, connector, target_lun=None):
        """Return server-LDEV connection info."""
        multipath = connector.get('multipath', False)
        if self.storage_info['protocol'] == 'FC':
            data = self.get_properties_fc(targets)
        elif self.storage_info['protocol'] == 'iSCSI':
            data = self.get_properties_iscsi(targets, multipath)
        if target_lun is not None:
            data['target_discovered'] = False
            if not multipath or self.storage_info['protocol'] == 'FC':
                data['target_lun'] = target_lun
            else:
                target_luns = []
                for target in targets['list']:
                    if targets['lun'][target[0]]:
                        target_luns.append(target_lun)
                data['target_luns'] = target_luns
        return data

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
            data['target_portals'] = [
                self.storage_info['portals'][target[0]] for target in
                targets['list'] if targets['lun'][target[0]]]
            data['target_iqns'] = [
                targets['iqns'][target] for target in targets['list']
                if targets['lun'][target[0]]]
        if self.conf.vsp_use_chap_auth:
            data['auth_method'] = 'CHAP'
            data['auth_username'] = self.conf.vsp_auth_user
            data['auth_password'] = self.conf.vsp_auth_password
        return data

    @coordination.synchronized('vsp-host-{self.conf.vsp_storage_id}-'
                               '{connector[host]}')
    def terminate_connection(self, volume, connector):
        """Terminate connection between the server and the volume."""
        targets = {
            'info': {},
            'list': [],
            'iqns': {},
        }
        mapped_targets = {
            'list': [],
        }
        unmap_targets = {}

        ldev = utils.get_ldev(volume)
        if ldev is None:
            utils.output_log(MSG.INVALID_LDEV_FOR_UNMAPPING,
                             volume_id=volume['id'])
            return
        target_ports = self.get_target_ports(connector)
        self.find_targets_from_storage(targets, connector, target_ports)
        if not targets['list']:
            utils.output_log(MSG.NO_CONNECTED_TARGET)
        self.find_mapped_targets_from_storage(
            mapped_targets, ldev, target_ports)

        unmap_targets['list'] = self.get_unmap_targets_list(
            targets['list'], mapped_targets['list'])
        unmap_targets['list'].sort(reverse=True)
        self.unmap_ldev(unmap_targets, ldev)

        if self.storage_info['protocol'] == 'FC':
            target_wwn = [
                self.storage_info['wwns'][port_gid[:utils.PORT_ID_LENGTH]]
                for port_gid in unmap_targets['list']]
            return {'driver_volume_type': self.driver_info['volume_type'],
                    'data': {'target_wwn': target_wwn}}

    @abc.abstractmethod
    def find_mapped_targets_from_storage(self, targets, ldev, target_ports):
        """Find and store IDs of ports used for server-LDEV connection."""
        raise NotImplementedError()

    @abc.abstractmethod
    def get_unmap_targets_list(self, target_list, mapped_list):
        """Return a list of IDs of ports that need to be disconnected."""
        raise NotImplementedError()

    @abc.abstractmethod
    def unmap_ldev(self, targets, ldev):
        """Delete the LUN between the specified LDEV and port-gid."""
        raise NotImplementedError()

    @abc.abstractmethod
    def wait_full_copy_completion(self, pvol, svol):
        """Wait until FULL copy is completed."""
        raise NotImplementedError()
