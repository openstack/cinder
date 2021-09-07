# Copyright (C) 2020, Hitachi, Ltd.
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

import re

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from cinder import coordination
from cinder import exception
from cinder.volume import configuration
from cinder.volume.drivers.hitachi import hbsd_utils as utils
from cinder.volume import volume_utils

VERSION = '2.1.0'

_STR_VOLUME = 'volume'
_STR_SNAPSHOT = 'snapshot'

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
    cfg.StrOpt(
        'hitachi_pool',
        default=None,
        help='Pool number or pool name of the DP pool.'),
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
]

_REQUIRED_COMMON_OPTS = [
    'hitachi_storage_id',
    'hitachi_pool',
]

CONF = cfg.CONF
CONF.register_opts(COMMON_VOLUME_OPTS, group=configuration.SHARED_CONF_GROUP)

LOG = logging.getLogger(__name__)
MSG = utils.HBSDMsg


def _str2int(num):
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
            'wwns': {},
            'portals': {},
        }

    def create_ldev(self, size):
        """Create an LDEV and return its LDEV number."""
        raise NotImplementedError()

    def modify_ldev_name(self, ldev, name):
        """Modify LDEV name."""
        raise NotImplementedError()

    def create_volume(self, volume):
        """Create a volume and return its properties."""
        try:
            ldev = self.create_ldev(volume['size'])
        except Exception:
            with excutils.save_and_reraise_exception():
                utils.output_log(MSG.CREATE_LDEV_FAILED)
        self.modify_ldev_name(ldev, volume['id'].replace("-", ""))
        return {
            'provider_location': str(ldev),
        }

    def get_ldev_info(self, keys, ldev, **kwargs):
        """Return a dictionary of LDEV-related items."""
        raise NotImplementedError()

    def create_pair_on_storage(self, pvol, svol, is_snapshot=False):
        """Create a copy pair on the storage."""
        raise NotImplementedError()

    def _copy_on_storage(self, pvol, size, is_snapshot=False):
        """Create a copy of the specified LDEV on the storage."""
        ldev_info = self.get_ldev_info(['status', 'attributes'], pvol)
        if ldev_info['status'] != 'NML':
            msg = utils.output_log(MSG.INVALID_LDEV_STATUS_FOR_COPY, ldev=pvol)
            raise utils.HBSDError(msg)
        svol = self.create_ldev(size)
        try:
            self.create_pair_on_storage(pvol, svol, is_snapshot)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self.delete_ldev(svol)
                except utils.HBSDError:
                    utils.output_log(MSG.DELETE_LDEV_FAILED, ldev=svol)
        return svol

    def create_volume_from_src(self, volume, src, src_type):
        """Create a volume from a volume or snapshot and return its properties.

        """
        ldev = utils.get_ldev(src)
        if ldev is None:
            msg = utils.output_log(
                MSG.INVALID_LDEV_FOR_VOLUME_COPY, type=src_type, id=src['id'])
            raise utils.HBSDError(msg)

        size = volume['size']
        new_ldev = self._copy_on_storage(ldev, size)
        self.modify_ldev_name(new_ldev, volume['id'].replace("-", ""))

        return {
            'provider_location': str(new_ldev),
        }

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume and return its properties."""
        return self.create_volume_from_src(volume, src_vref, _STR_VOLUME)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot and return its properties."""
        return self.create_volume_from_src(volume, snapshot, _STR_SNAPSHOT)

    def delete_pair_based_on_svol(self, pvol, svol_info):
        """Disconnect all volume pairs to which the specified S-VOL belongs."""
        raise NotImplementedError()

    def get_pair_info(self, ldev):
        """Return volume pair info(LDEV number, pair status and pair type)."""
        raise NotImplementedError()

    def delete_pair(self, ldev):
        """Disconnect all volume pairs to which the specified LDEV belongs."""
        pair_info = self.get_pair_info(ldev)
        if not pair_info:
            return
        if pair_info['pvol'] == ldev:
            utils.output_log(
                MSG.UNABLE_TO_DELETE_PAIR, pvol=pair_info['pvol'])
            raise utils.HBSDBusy()
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

    def delete_ldev(self, ldev):
        """Delete the specified LDEV."""
        self.delete_pair(ldev)
        self.unmap_ldev_from_storage(ldev)
        self.delete_ldev_from_storage(ldev)

    def delete_volume(self, volume):
        """Delete the specified volume."""
        ldev = utils.get_ldev(volume)
        if ldev is None:
            utils.output_log(
                MSG.INVALID_LDEV_FOR_DELETION,
                method='delete_volume', id=volume['id'])
            return
        try:
            self.delete_ldev(ldev)
        except utils.HBSDBusy:
            raise exception.VolumeIsBusy(volume_name=volume['name'])

    def create_snapshot(self, snapshot):
        """Create a snapshot from a volume and return its properties."""
        src_vref = snapshot.volume
        ldev = utils.get_ldev(src_vref)
        if ldev is None:
            msg = utils.output_log(
                MSG.INVALID_LDEV_FOR_VOLUME_COPY,
                type='volume', id=src_vref['id'])
            raise utils.HBSDError(msg)
        size = snapshot['volume_size']
        new_ldev = self._copy_on_storage(ldev, size, True)
        return {
            'provider_location': str(new_ldev),
        }

    def delete_snapshot(self, snapshot):
        """Delete the specified snapshot."""
        ldev = utils.get_ldev(snapshot)
        if ldev is None:
            utils.output_log(
                MSG.INVALID_LDEV_FOR_DELETION, method='delete_snapshot',
                id=snapshot['id'])
            return
        try:
            self.delete_ldev(ldev)
        except utils.HBSDBusy:
            raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])

    def get_pool_info(self):
        """Return the total and free capacity of the storage pool."""
        raise NotImplementedError()

    def update_volume_stats(self):
        """Update properties, capabilities and current states of the driver."""
        data = {}
        backend_name = (self.conf.safe_get('volume_backend_name') or
                        self.driver_info['volume_backend_name'])
        data = {
            'volume_backend_name': backend_name,
            'vendor_name': 'Hitachi',
            'driver_version': VERSION,
            'storage_protocol': self.storage_info['protocol'],
            'pools': [],
        }
        single_pool = {}
        single_pool.update(dict(
            pool_name=data['volume_backend_name'],
            reserved_percentage=self.conf.safe_get('reserved_percentage'),
            QoS_support=False,
            thick_provisioning_support=False,
            multiattach=True,
            consistencygroup_support=True,
            consistent_group_snapshot_enabled=True
        ))
        try:
            (total_capacity, free_capacity,
             provisioned_capacity) = self.get_pool_info()
        except utils.HBSDError:
            single_pool.update(dict(
                provisioned_capacity_gb=0,
                backend_state='down'))
            data["pools"].append(single_pool)
            LOG.debug("Updating volume status. (%s)", data)
            utils.output_log(
                MSG.POOL_INFO_RETRIEVAL_FAILED,
                pool=self.conf.hitachi_pool)
            return data
        single_pool.update(dict(
            total_capacity_gb=total_capacity,
            free_capacity_gb=free_capacity,
            provisioned_capacity_gb=provisioned_capacity,
            max_over_subscription_ratio=(
                volume_utils.get_max_over_subscription_ratio(
                    self.conf.safe_get('max_over_subscription_ratio'),
                    True)),
            thin_provisioning_support=True
        ))
        single_pool.update(dict(backend_state='up'))
        data["pools"].append(single_pool)
        LOG.debug("Updating volume status. (%s)", data)
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
        ldev = utils.get_ldev(volume)
        if ldev is None:
            msg = utils.output_log(MSG.INVALID_LDEV_FOR_EXTENSION,
                                   volume_id=volume['id'])
            raise utils.HBSDError(msg)
        if self.check_pair_svol(ldev):
            msg = utils.output_log(MSG.INVALID_VOLUME_TYPE_FOR_EXTEND,
                                   volume_id=volume['id'])
            raise utils.HBSDError(msg)
        self.delete_pair(ldev)
        self.extend_ldev(ldev, volume['size'], new_size)

    def get_ldev_by_name(self, name):
        """Get the LDEV number from the given name."""
        raise NotImplementedError()

    def check_ldev_manageability(self, ldev, existing_ref):
        """Check if the LDEV meets the criteria for being managed."""
        raise NotImplementedError()

    def manage_existing(self, volume, existing_ref):
        """Return volume properties which Cinder needs to manage the volume."""
        if 'source-name' in existing_ref:
            ldev = self.get_ldev_by_name(
                existing_ref.get('source-name').replace('-', ''))
        elif 'source-id' in existing_ref:
            ldev = _str2int(existing_ref.get('source-id'))
        self.check_ldev_manageability(ldev, existing_ref)
        self.modify_ldev_name(ldev, volume['id'].replace("-", ""))
        return {
            'provider_location': str(ldev),
        }

    def get_ldev_size_in_gigabyte(self, ldev, existing_ref):
        """Return the size[GB] of the specified LDEV."""
        raise NotImplementedError()

    def manage_existing_get_size(self, existing_ref):
        """Return the size[GB] of the specified volume."""
        ldev = None
        if 'source-name' in existing_ref:
            ldev = self.get_ldev_by_name(
                existing_ref.get('source-name').replace("-", ""))
        elif 'source-id' in existing_ref:
            ldev = _str2int(existing_ref.get('source-id'))
        if ldev is None:
            msg = utils.output_log(MSG.INVALID_LDEV_FOR_MANAGE)
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=msg)
        return self.get_ldev_size_in_gigabyte(ldev, existing_ref)

    def unmanage(self, volume):
        """Prepare the volume for removing it from Cinder management."""
        ldev = utils.get_ldev(volume)
        if ldev is None:
            utils.output_log(MSG.INVALID_LDEV_FOR_DELETION, method='unmanage',
                             id=volume['id'])
            return
        if self.check_pair_svol(ldev):
            utils.output_log(
                MSG.INVALID_LDEV_TYPE_FOR_UNMANAGE, volume_id=volume['id'],
                volume_type=utils.NORMAL_LDEV_TYPE)
            raise exception.VolumeIsBusy(volume_name=volume['name'])
        try:
            self.delete_pair(ldev)
        except utils.HBSDBusy:
            raise exception.VolumeIsBusy(volume_name=volume['name'])

    def _range2list(self, param):
        """Analyze a 'xxx-xxx' string and return a list of two integers."""
        values = [_str2int(value) for value in
                  self.conf.safe_get(param).split('-')]
        if len(values) != 2 or None in values or values[0] > values[1]:
            msg = utils.output_log(MSG.INVALID_PARAMETER, param=param)
            raise utils.HBSDError(msg)
        return values

    def check_param_iscsi(self):
        """Check iSCSI-related parameter values and consistency among them."""
        if self.conf.use_chap_auth:
            if not self.conf.chap_username:
                msg = utils.output_log(MSG.INVALID_PARAMETER,
                                       param='chap_username')
                raise utils.HBSDError(msg)
            if not self.conf.chap_password:
                msg = utils.output_log(MSG.INVALID_PARAMETER,
                                       param='chap_password')
                raise utils.HBSDError(msg)

    def check_param(self):
        """Check parameter values and consistency among them."""
        utils.check_opt_value(self.conf, _INHERITED_VOLUME_OPTS)
        utils.check_opts(self.conf, COMMON_VOLUME_OPTS)
        utils.check_opts(self.conf, self.driver_info['volume_opts'])
        if self.conf.hitachi_ldev_range:
            self.storage_info['ldev_range'] = self._range2list(
                'hitachi_ldev_range')
        if (not self.conf.hitachi_target_ports and
                not self.conf.hitachi_compute_target_ports):
            msg = utils.output_log(
                MSG.INVALID_PARAMETER,
                param='hitachi_target_ports or '
                'hitachi_compute_target_ports')
            raise utils.HBSDError(msg)
        if (self.conf.hitachi_group_delete and
                not self.conf.hitachi_group_create):
            msg = utils.output_log(
                MSG.INVALID_PARAMETER,
                param='hitachi_group_delete or '
                'hitachi_group_create')
            raise utils.HBSDError(msg)
        for opt in _REQUIRED_COMMON_OPTS:
            if not self.conf.safe_get(opt):
                msg = utils.output_log(MSG.INVALID_PARAMETER, param=opt)
                raise utils.HBSDError(msg)
        if self.storage_info['protocol'] == 'iSCSI':
            self.check_param_iscsi()

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
        """Check the pool id of hitachi_pool and hitachi_snap_pool."""
        raise NotImplementedError()

    def connect_storage(self):
        """Prepare for using the storage."""
        self.check_pool_id()
        utils.output_log(MSG.SET_CONFIG_VALUE, object='DP Pool ID',
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
        msg = utils.output_log(MSG.RESOURCE_NOT_FOUND,
                               resource=self.driver_info['hba_id_type'])
        raise utils.HBSDError(msg)

    def create_target_to_storage(self, port, connector, hba_ids):
        """Create a host group or an iSCSI target on the specified port."""
        raise NotImplementedError()

    def set_target_mode(self, port, gid):
        """Configure the target to meet the environment."""
        raise NotImplementedError()

    def set_hba_ids(self, port, gid, hba_ids):
        """Connect all specified HBAs with the specified port."""
        raise NotImplementedError()

    def delete_target_from_storage(self, port, gid):
        """Delete the host group or the iSCSI target from the port."""
        raise NotImplementedError()

    def _create_target(self, targets, port, connector, hba_ids):
        """Create a host group or an iSCSI target on the storage port."""
        target_name, gid = self.create_target_to_storage(
            port, connector, hba_ids)
        utils.output_log(MSG.OBJECT_CREATED, object='a target',
                         details='port: %(port)s, gid: %(gid)s, target_name: '
                         '%(target)s' %
                         {'port': port, 'gid': gid, 'target': target_name})
        try:
            self.set_target_mode(port, gid)
            self.set_hba_ids(port, gid, hba_ids)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.delete_target_from_storage(port, gid)
        targets['info'][port] = True
        targets['list'].append((port, gid))

    def create_mapping_targets(self, targets, connector):
        """Create server-storage connection for all specified storage ports."""
        hba_ids = self.get_hba_ids_from_connector(connector)
        for port in targets['info'].keys():
            if targets['info'][port]:
                continue

            try:
                self._create_target(targets, port, connector, hba_ids)
            except utils.HBSDError:
                utils.output_log(
                    self.driver_info['msg_id']['target'], port=port)

        # When other threads created a host group at same time, need to
        # re-find targets.
        if not targets['list']:
            self.find_targets_from_storage(
                targets, connector, targets['info'].keys())

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

            utils.require_target_existed(targets)

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
            msg = utils.output_log(MSG.RESOURCE_NOT_FOUND,
                                   resource="Target ports")
            raise utils.HBSDError(msg)
        if (self.conf.hitachi_compute_target_ports and
                not self.storage_info['compute_ports']):
            msg = utils.output_log(MSG.RESOURCE_NOT_FOUND,
                                   resource="Compute target ports")
            raise utils.HBSDError(msg)
        utils.output_log(MSG.SET_CONFIG_VALUE, object='target port list',
                         value=self.storage_info['controller_ports'])
        utils.output_log(MSG.SET_CONFIG_VALUE,
                         object='compute target port list',
                         value=self.storage_info['compute_ports'])

    def attach_ldev(self, volume, ldev, connector, targets):
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
    @coordination.synchronized('hbsd-host-{self.conf.hitachi_storage_id}-'
                               '{connector[host]}')
    def initialize_connection(self, volume, connector):
        """Initialize connection between the server and the volume."""
        targets = {
            'info': {},
            'list': [],
            'lun': {},
            'iqns': {},
            'target_map': {},
        }
        ldev = utils.get_ldev(volume)
        if ldev is None:
            msg = utils.output_log(MSG.INVALID_LDEV_FOR_CONNECTION,
                                   volume_id=volume['id'])
            raise utils.HBSDError(msg)

        target_lun = self.attach_ldev(volume, ldev, connector, targets)

        return {
            'driver_volume_type': self.driver_info['volume_type'],
            'data': self.get_properties(targets, target_lun, connector),
        }

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
        ldev = utils.get_ldev(volume)
        if ldev is None:
            utils.output_log(MSG.INVALID_LDEV_FOR_UNMAPPING,
                             volume_id=volume['id'])
            return
        # If a fake connector is generated by nova when the host
        # is down, then the connector will not have a host property,
        # In this case construct the lock without the host property
        # so that all the fake connectors to an SVC are serialized
        if 'host' not in connector:
            port_hostgroup_map = self.get_port_hostgroup_map(ldev)
            if not port_hostgroup_map:
                utils.output_log(MSG.NO_LUN, ldev=ldev)
                return
            self.set_terminate_target(connector, port_hostgroup_map)

        # A synchronization to prevent conflicts between host group creation
        # and deletion.
        @coordination.synchronized(
            'hbsd-host-%(storage_id)s-%(host)s' % {
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

    def unmanage_snapshot(self, snapshot):
        """Output error message and raise NotImplementedError."""
        utils.output_log(
            MSG.SNAPSHOT_UNMANAGE_FAILED, snapshot_id=snapshot['id'])
        raise NotImplementedError()

    def retype(self):
        return False

    def has_snap_pair(self, pvol, svol):
        """Check if the volume have the pair of the snapshot."""
        raise NotImplementedError()

    def restore_ldev(self, pvol, svol):
        """Restore a pair of the specified LDEV."""
        raise NotImplementedError()

    def revert_to_snapshot(self, volume, snapshot):
        """Rollback the specified snapshot."""
        pvol = utils.get_ldev(volume)
        svol = utils.get_ldev(snapshot)
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
