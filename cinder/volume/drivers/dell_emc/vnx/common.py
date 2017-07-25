# Copyright (c) 2016 EMC Corporation.
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
"""
VNX Common Utils
"""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils

from cinder import exception
from cinder.i18n import _
from cinder.volume import configuration
from cinder.volume.drivers.dell_emc.vnx import const
from cinder.volume import group_types
from cinder.volume import volume_types

storops = importutils.try_import('storops')
CONF = cfg.CONF

LOG = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60 * 60 * 24 * 365

INTERVAL_5_SEC = 5
INTERVAL_20_SEC = 20
INTERVAL_30_SEC = 30
INTERVAL_60_SEC = 60

SNAP_EXPIRATION_HOUR = '1h'


BACKEND_QOS_CONSUMERS = frozenset(['back-end', 'both'])
QOS_MAX_IOPS = 'maxIOPS'
QOS_MAX_BWS = 'maxBWS'


VNX_OPTS = [
    cfg.StrOpt('storage_vnx_authentication_type',
               default='global',
               help='VNX authentication scope type. '
               'By default, the value is global.'),
    cfg.StrOpt('storage_vnx_security_file_dir',
               help='Directory path that contains the VNX security file. '
               'Make sure the security file is generated first.'),
    cfg.StrOpt('naviseccli_path',
               help='Naviseccli Path.'),
    cfg.ListOpt('storage_vnx_pool_names',
                help='Comma-separated list of storage pool names to be used.'),
    cfg.IntOpt('default_timeout',
               default=DEFAULT_TIMEOUT,
               help='Default timeout for CLI operations in minutes. '
               'For example, LUN migration is a typical long '
               'running operation, which depends on the LUN size and '
               'the load of the array. '
               'An upper bound in the specific deployment can be set to '
               'avoid unnecessary long wait. '
               'By default, it is 365 days long.'),
    cfg.IntOpt('max_luns_per_storage_group',
               default=255,
               help='Default max number of LUNs in a storage group.'
               ' By default, the value is 255.'),
    cfg.BoolOpt('destroy_empty_storage_group',
                default=False,
                help='To destroy storage group '
                'when the last LUN is removed from it. '
                'By default, the value is False.'),
    # iscsi_initiators is a dict which key is string and value is a list.
    # This could be a DictOpt. Unfortunately DictOpt doesn't support the value
    # of list type.
    cfg.StrOpt('iscsi_initiators',
               help='Mapping between hostname and '
               'its iSCSI initiator IP addresses.'),
    cfg.ListOpt('io_port_list',
                help='Comma separated iSCSI or FC ports '
                'to be used in Nova or Cinder.'),
    cfg.BoolOpt('initiator_auto_registration',
                default=False,
                help='Automatically register initiators. '
                'By default, the value is False.'),
    cfg.BoolOpt('initiator_auto_deregistration',
                default=False,
                help='Automatically deregister initiators after the related '
                'storage group is destroyed. '
                'By default, the value is False.'),
    cfg.BoolOpt('check_max_pool_luns_threshold',
                default=False,
                help='Report free_capacity_gb as 0 when the limit to '
                'maximum number of pool LUNs is reached. '
                'By default, the value is False.'),
    cfg.BoolOpt('force_delete_lun_in_storagegroup',
                default=False,
                help='Delete a LUN even if it is in Storage Groups. '
                'By default, the value is False.'),
    cfg.BoolOpt('ignore_pool_full_threshold',
                default=False,
                help='Force LUN creation even if '
                'the full threshold of pool is reached. '
                'By default, the value is False.')
]

CONF.register_opts(VNX_OPTS, group=configuration.SHARED_CONF_GROUP)


PROTOCOL_FC = 'fc'
PROTOCOL_ISCSI = 'iscsi'


class ExtraSpecs(object):
    _provision_key = 'provisioning:type'
    _tier_key = 'storagetype:tiering'
    _replication_key = 'replication_enabled'

    PROVISION_DEFAULT = const.PROVISION_THICK
    TIER_DEFAULT = None

    def __init__(self, extra_specs, group_specs=None):
        self.specs = extra_specs
        self._provision = self._get_provision()
        self.provision = self._provision
        self._tier = self._get_tier()
        self.tier = self._tier
        self.apply_default_values()
        self.group_specs = group_specs if group_specs else {}

    def apply_default_values(self):
        self.provision = (ExtraSpecs.PROVISION_DEFAULT
                          if self.provision is None
                          else self.provision)
        # Can not set Tier when provision is set to deduped. So don't set the
        # tier default when provision is deduped.
        if self.provision != storops.VNXProvisionEnum.DEDUPED:
            self.tier = (ExtraSpecs.TIER_DEFAULT if self.tier is None
                         else self.tier)

    @classmethod
    def set_defaults(cls, provision_default, tier_default):
        cls.PROVISION_DEFAULT = provision_default
        cls.TIER_DEFAULT = tier_default

    def _get_provision(self):
        value = self._parse_to_enum(self._provision_key,
                                    storops.VNXProvisionEnum)
        return value

    def _get_tier(self):
        return self._parse_to_enum(self._tier_key, storops.VNXTieringEnum)

    @property
    def is_replication_enabled(self):
        return self.specs.get('replication_enabled', '').lower() == '<is> true'

    @property
    def is_group_replication_enabled(self):
        return self.group_specs.get(
            'consistent_group_replication_enabled', '').lower() == '<is> true'

    def _parse_to_enum(self, key, enum_class):
        value = (self.specs[key]
                 if key in self.specs else None)
        if value is not None:
            try:
                value = enum_class.parse(value)
            except ValueError:
                reason = (_("The value %(value)s for key %(key)s in extra "
                            "specs is invalid.") %
                          {'key': key, 'value': value})
                raise exception.InvalidVolumeType(reason=reason)
        return value

    @classmethod
    def from_volume(cls, volume):
        specs = {}
        type_id = volume['volume_type_id']
        if type_id is not None:
            specs = volume_types.get_volume_type_extra_specs(type_id)

        return cls(specs)

    @classmethod
    def from_group(cls, group):
        group_specs = {}

        if group and group.group_type_id:
            group_specs = group_types.get_group_type_specs(
                group.group_type_id)

        return cls(extra_specs={}, group_specs=group_specs)

    @classmethod
    def from_volume_type(cls, type):
        return cls(type['extra_specs'])

    @classmethod
    def from_lun(cls, lun):
        ex = cls({})
        ex.provision = lun.provision
        ex.tier = (lun.tier
                   if lun.provision != storops.VNXProvisionEnum.DEDUPED
                   else None)
        return ex

    def match_with_lun(self, lun):
        ex = ExtraSpecs.from_lun(lun)
        return (self.provision == ex.provision and
                self.tier == ex.tier)

    def validate(self, enabler_status):
        """Checks whether the extra specs are valid.

        :param enabler_status: Instance of VNXEnablerStatus
        """
        if "storagetype:pool" in self.specs:
            LOG.warning("Extra spec key 'storagetype:pool' is obsoleted "
                        "since driver version 5.1.0. This key will be "
                        "ignored.")

        if (self._provision == storops.VNXProvisionEnum.DEDUPED and
                self._tier is not None):
            msg = _("Can not set tiering policy for a deduplicated volume. "
                    "Set the tiering policy on the pool where the "
                    "deduplicated volume locates.")
            raise exception.InvalidVolumeType(reason=msg)

        if (self._provision == storops.VNXProvisionEnum.COMPRESSED
                and not enabler_status.compression_enabled):
            msg = _("Compression Enabler is not installed. "
                    "Can not create compressed volume.")
            raise exception.InvalidVolumeType(reason=msg)

        if (self._provision == storops.VNXProvisionEnum.DEDUPED
                and not enabler_status.dedup_enabled):
            msg = _("Deduplication Enabler is not installed. "
                    "Can not create deduplicated volume.")
            raise exception.InvalidVolumeType(reason=msg)

        if (self._provision in [storops.VNXProvisionEnum.THIN,
                                storops.VNXProvisionEnum.COMPRESSED,
                                storops.VNXProvisionEnum.DEDUPED]
                and not enabler_status.thin_enabled):
            msg = _("ThinProvisioning Enabler is not installed. "
                    "Can not create thin volume.")
            raise exception.InvalidVolumeType(reason=msg)

        if (self._tier is not None
                and not enabler_status.fast_enabled):
            msg = _("FAST VP Enabler is not installed. "
                    "Can not set tiering policy for the volume.")
            raise exception.InvalidVolumeType(reason=msg)
        return True

    def __len__(self):
        return len(self.specs)

    def __getitem__(self, key):
        return self.specs[key]

    def __iter__(self):
        return iter(self.specs)

    def __contains__(self, item):
        return item in self.specs

    def __eq__(self, other):
        if isinstance(other, ExtraSpecs):
            return self.specs == other.specs
        elif isinstance(other, dict):
            return self.specs == other
        else:
            return False

    def __hash__(self):
        return self.specs.__hash__()


class LUNState(object):
    INITIALIZING = 'Initializing'
    READY = 'Ready'
    FAULTED = 'Faulted'


class PoolState(object):
    INITIALIZING = 'Initializing'
    OFFLINE = 'Offline'
    DELETING = 'Deleting'
    VALID_CREATE_LUN_STATE = (INITIALIZING, OFFLINE, DELETING)


class VNXEnablerStatus(object):

    def __init__(self,
                 dedup=False,
                 compression=False,
                 fast=False,
                 thin=False,
                 snap=False):
        self.dedup_enabled = dedup
        self.compression_enabled = compression
        self.fast_enabled = fast
        self.thin_enabled = thin
        self.snap_enabled = snap


class WaitUtilTimeoutException(exception.VolumeDriverException):
    """Raised when timeout occurs in wait_until."""
    # TODO(Ryan) put this exception under Cinder shared module.
    pass


class Host(object):
    """The model of a host which acts as an initiator to access the storage."""

    def __init__(self, name, initiators, ip=None, wwpns=None):
        # ip and wwpns are optional.
        self.name = name
        if not self.name:
            raise ValueError(('Name of host cannot be empty.'))
        self.initiators = initiators
        if not self.initiators:
            raise ValueError(_('Initiators of host cannot be empty.'))
        self.ip = ip
        self.wwpns = wwpns


class Volume(object):
    """The internal volume which is used to pass in method call."""

    def __init__(self, name, id, vnx_lun_id=None):
        self.name = name
        self.id = id
        self.vnx_lun_id = vnx_lun_id


class ISCSITargetData(dict):
    def __init__(self, volume_id, is_discovered, iqn='unknown', iqns=None,
                 portal='unknown', portals=None, lun='unknown', luns=None):
        data = {'volume_id': volume_id, 'target_discovered': is_discovered,
                'target_iqn': iqn, 'target_iqns': iqns,
                'target_portal': portal, 'target_portals': portals,
                'target_lun': lun, 'target_luns': luns}
        self['driver_volume_type'] = 'iscsi'
        self['data'] = data

    def to_dict(self):
        """Converts to the dict.

        It helps serialize and deserialize the data before returning to nova.
        """
        return {key: value for (key, value) in self.items()}


class FCTargetData(dict):
    def __init__(self, volume_id, is_discovered, wwn=None, lun=None,
                 initiator_target_map=None):
        data = {'volume_id': volume_id, 'target_discovered': is_discovered,
                'target_lun': lun, 'target_wwn': wwn,
                'initiator_target_map': initiator_target_map}
        self['driver_volume_type'] = 'fibre_channel'
        self['data'] = data

    def to_dict(self):
        """Converts to the dict.

        It helps serialize and deserialize the data before returning to nova.
        """
        return {key: value for (key, value) in self.items()}


class ReplicationDevice(object):
    def __init__(self, replication_device):
        self.replication_device = replication_device

    @property
    def backend_id(self):
        return self.replication_device.get('backend_id')

    @property
    def san_ip(self):
        return self.replication_device.get('san_ip')

    @property
    def san_login(self):
        return self.replication_device.get('san_login')

    @property
    def san_password(self):
        return self.replication_device.get('san_password')

    @property
    def storage_vnx_authentication_type(self):
        return self.replication_device.get(
            'storage_vnx_authentication_type',
            'global')

    @property
    def storage_vnx_security_file_dir(self):
        return self.replication_device.get('storage_vnx_security_file_dir')

    @property
    def pool_name(self):
        return self.replication_device.get('pool_name', None)


class ReplicationDeviceList(list):
    """Replication devices configured in cinder.conf

    Cinder supports multiple replication_device,  while VNX driver
    only support one replication_device for now.
    """

    def __init__(self, configuration):
        self.list = []
        self.configuration = configuration
        self._device_map = dict()
        self.parse_configuration()

    def parse_configuration(self):
        if self.configuration.replication_device:
            for replication_device in self.configuration.replication_device:
                rd = ReplicationDevice(replication_device)
                if not rd.backend_id or not rd.san_ip:
                    msg = _('backend_id or san_ip cannot be empty for '
                            'replication_device.')
                    raise exception.InvalidInput(reason=msg)
                self._device_map[rd.backend_id] = rd
                self.list.append(rd)
        return self._device_map

    def get_device(self, backend_id):
        try:
            device = self._device_map[backend_id]
        except KeyError:
            device = None
            LOG.warning('Unable to find secondary device named: %s',
                        backend_id)
        return device

    @property
    def devices(self):
        return self._device_map.values()

    def __len__(self):
        return len(self.list)

    def __iter__(self):
        self._iter = self.list.__iter__()
        return self

    def next(self):
        return next(self._iter)

    def __next__(self):
        return self.next()

    def __getitem__(self, item):
        return self.list[item]

    @classmethod
    def get_backend_ids(cls, config):
        """Returns all configured device_id."""
        rep_list = cls(config)
        backend_ids = []
        for item in rep_list.devices:
            backend_ids.append(item.backend_id)
        return backend_ids


class VNXMirrorView(object):
    def __init__(self, primary_client, secondary_client):
        self.primary_client = primary_client
        self.secondary_client = secondary_client

    def create_mirror(self, name, primary_lun_id):
        self.primary_client.create_mirror(name, primary_lun_id)

    def create_secondary_lun(self, pool_name, lun_name, size, provision, tier):
        return self.secondary_client.create_lun(
            pool_name, lun_name, size, provision, tier)

    def delete_secondary_lun(self, lun_name):
        self.secondary_client.delete_lun(lun_name)

    def delete_mirror(self, mirror_name):
        self.primary_client.delete_mirror(mirror_name)

    def add_image(self, mirror_name, secondary_lun_id):
        sp_ip = self.secondary_client.get_available_ip()
        self.primary_client.add_image(mirror_name, sp_ip, secondary_lun_id)

    def remove_image(self, mirror_name):
        self.primary_client.remove_image(mirror_name)

    def fracture_image(self, mirror_name):
        self.primary_client.fracture_image(mirror_name)

    def promote_image(self, mirror_name):
        """Promote the image on the secondary array."""
        self.secondary_client.promote_image(mirror_name)

    def destroy_mirror(self, mirror_name, secondary_lun_name):
        """Destroy the mirror view's related VNX objects.

        NOTE: primary lun will not be deleted here.
        :param mirror_name: name of mirror to be destroyed
        :param secondary_lun_name: name of LUN name
        """
        mv = self.primary_client.get_mirror(mirror_name)
        if not mv.existed:
            # We will skip the mirror operations if not existed
            LOG.warning('Mirror view %s was deleted already.',
                        mirror_name)
            return
        self.fracture_image(mirror_name)
        self.remove_image(mirror_name)
        self.delete_mirror(mirror_name)
        self.delete_secondary_lun(lun_name=secondary_lun_name)

    def create_mirror_group(self, group_name):
        return self.primary_client.create_mirror_group(group_name)

    def delete_mirror_group(self, group_name):
        return self.primary_client.delete_mirror_group(group_name)

    def add_mirror(self, group_name, mirror_name):
        return self.primary_client.add_mirror(group_name, mirror_name)

    def remove_mirror(self, group_name, mirror_name):
        return self.primary_client.remove_mirror(group_name, mirror_name)

    def sync_mirror_group(self, group_name):
        return self.primary_client.sync_mirror_group(group_name)

    def promote_mirror_group(self, group_name):
        """Promote the mirror group on the secondary array."""
        return self.secondary_client.promote_mirror_group(group_name)

    def fracture_mirror_group(self, group_name):
        return self.primary_client.fracture_mirror_group(group_name)
