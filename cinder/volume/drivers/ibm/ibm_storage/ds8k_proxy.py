#  Copyright (c) 2016 IBM Corporation
#  All Rights Reserved.
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
"""
This is the driver that allows openstack to talk to DS8K.

All volumes are thin provisioned by default, if the machine is licensed for it.
This can be overridden by creating a volume type and specifying a key like so:
#> cinder type-create my_type
#> cinder type-key my_type set drivers:thin_provision=False
#> cinder create --volume-type my_type 123


Sample settings for cinder.conf:
--->
enabled_backends = ibm_ds8k_1, ibm_ds8k_2
[ibm_ds8k_1]
proxy = cinder.volume.drivers.ibm.ibm_storage.ds8k_proxy.DS8KProxy
volume_backend_name = ibm_ds8k_1
san_clustername = P2,P3
san_password = actual_password
san_login = actual_username
san_ip = foo.com
volume_driver =
    cinder.volume.drivers.ibm.ibm_storage.ibm_storage.IBMStorageDriver
chap = disabled
connection_type = fibre_channel
replication_device = connection_type: fibre_channel, backend_id: bar,
                     san_ip: bar.com, san_login: actual_username,
                     san_password: actual_password, san_clustername: P4,
                     port_pairs: I0236-I0306; I0237-I0307

[ibm_ds8k_2]
proxy = cinder.volume.drivers.ibm.ibm_storage.ds8k_proxy.DS8KProxy
volume_backend_name = ibm_ds8k_2
san_clustername = P4,P5
san_password = actual_password
san_login = actual_username
san_ip = bar.com
volume_driver =
    cinder.volume.drivers.ibm.ibm_storage.ibm_storage.IBMStorageDriver
chap = disabled
connection_type = fibre_channel
<---

"""
import ast
import collections
import json
import six

from oslo_config import cfg
from oslo_log import log as logging

from cinder import context
from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import fields
import cinder.volume.drivers.ibm.ibm_storage as storage
from cinder.volume.drivers.ibm.ibm_storage import (
    ds8k_replication as replication)
from cinder.volume.drivers.ibm.ibm_storage import ds8k_helper as helper
from cinder.volume.drivers.ibm.ibm_storage import ds8k_restclient as restclient
from cinder.volume.drivers.ibm.ibm_storage import proxy
from cinder.volume.drivers.ibm.ibm_storage import strings
from cinder.volume import utils
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

VALID_OS400_VOLUME_TYPES = {
    'A01': 8, 'A02': 17, 'A04': 66,
    'A05': 33, 'A06': 132, 'A07': 263,
    'A81': 8, 'A82': 17, 'A84': 66,
    'A85': 33, 'A86': 132, 'A87': 263,
    '050': '', '099': ''
}

EXTRA_SPECS_DEFAULTS = {
    'thin': True,
    'replication_enabled': False,
    'consistency': False,
    'os400': ''
}

ds8k_opts = [
    cfg.StrOpt(
        'ds8k_devadd_unitadd_mapping',
        default='',
        help='Mapping between IODevice address and unit address.'),
    cfg.StrOpt(
        'ds8k_ssid_prefix',
        default='FF',
        help='Set the first two digits of SSID.'),
    cfg.StrOpt(
        'lss_range_for_cg',
        default='',
        help='Reserve LSSs for consistency group.'),
    cfg.StrOpt(
        'ds8k_host_type',
        default='auto',
        help='Set to zLinux if your OpenStack version is prior to '
             'Liberty and you\'re connecting to zLinux systems. '
             'Otherwise set to auto. Valid values for this parameter '
             'are: %s.' % six.text_type(helper.VALID_HOST_TYPES)[1:-1])
]

CONF = cfg.CONF
CONF.register_opts(ds8k_opts)


class Lun(object):
    """provide volume information for driver from volume db object."""

    class FakeLun(object):

        def __init__(self, lun, **overrides):
            self.size = lun.size
            self.os_id = 'fake_os_id'
            self.cinder_name = lun.cinder_name
            self.is_snapshot = lun.is_snapshot
            self.ds_name = lun.ds_name
            self.ds_id = None
            self.type_thin = lun.type_thin
            self.type_os400 = lun.type_os400
            self.data_type = lun.data_type
            self.type_replication = lun.type_replication
            self.group = lun.group
            if not self.is_snapshot and self.type_replication:
                self.replica_ds_name = lun.replica_ds_name
                self.replication_driver_data = (
                    lun.replication_driver_data.copy())
                self.replication_status = lun.replication_status
            self.pool_lss_pair = lun.pool_lss_pair

        def update_volume(self, lun):
            volume_update = lun.get_volume_update()
            volume_update['provider_location'] = six.text_type({
                'vol_hex_id': self.ds_id})
            if self.type_replication:
                volume_update['replication_driver_data'] = json.dumps(
                    self.replication_driver_data)
                volume_update['metadata']['replication'] = six.text_type(
                    self.replication_driver_data)
            volume_update['metadata']['vol_hex_id'] = self.ds_id
            return volume_update

    def __init__(self, volume, is_snapshot=False):
        volume_type_id = volume.get('volume_type_id')
        self.specs = volume_types.get_volume_type_extra_specs(
            volume_type_id) if volume_type_id else {}
        os400 = self.specs.get(
            'drivers:os400', EXTRA_SPECS_DEFAULTS['os400']
        ).strip().upper()
        self.type_thin = self.specs.get(
            'drivers:thin_provision', '%s' % EXTRA_SPECS_DEFAULTS['thin']
        ).upper() == 'True'.upper()
        self.type_replication = self.specs.get(
            'replication_enabled',
            '<is> %s' % EXTRA_SPECS_DEFAULTS['replication_enabled']
        ).upper() == strings.METADATA_IS_TRUE

        if volume.provider_location:
            provider_location = ast.literal_eval(volume.provider_location)
            self.ds_id = provider_location['vol_hex_id']
        else:
            self.ds_id = None
        self.cinder_name = volume.display_name
        self.pool_lss_pair = {}
        self.is_snapshot = is_snapshot
        if self.is_snapshot:
            self.group = (Group(volume.group_snapshot, True)
                          if volume.group_snapshot else None)
            self.size = volume.volume_size
            # ds8k supports at most 16 chars
            self.ds_name = (
                "OS%s:%s" % ('snap', helper.filter_alnum(self.cinder_name))
            )[:16]
        else:
            self.group = Group(volume.group) if volume.group else None
            self.size = volume.size
            self.ds_name = (
                "OS%s:%s" % ('vol', helper.filter_alnum(self.cinder_name))
            )[:16]
            self.replica_ds_name = (
                "OS%s:%s" % ('Replica', helper.filter_alnum(self.cinder_name))
            )[:16]
            self.replication_status = volume.replication_status
            self.replication_driver_data = (
                json.loads(volume.replication_driver_data)
                if volume.replication_driver_data else {})
            if self.replication_driver_data:
                # now only support one replication target.
                replication_target = sorted(
                    self.replication_driver_data.values())[0]
                replica_id = replication_target['vol_hex_id']
                self.pool_lss_pair = {
                    'source': (None, self.ds_id[0:2]),
                    'target': (None, replica_id[0:2])
                }

        if os400:
            if os400 not in VALID_OS400_VOLUME_TYPES.keys():
                raise restclient.APIException(
                    data=(_("The OS400 volume type provided, %s, is not "
                            "a valid volume type.") % os400))
            self.type_os400 = os400
            if os400 not in ['050', '099']:
                self.size = VALID_OS400_VOLUME_TYPES[os400]
        else:
            self.type_os400 = EXTRA_SPECS_DEFAULTS['os400']

        self.data_type = self._create_datatype(self.type_os400)
        self.os_id = volume.id
        self.status = volume.status
        self.volume = volume

    def _get_volume_metadata(self, volume):
        if 'volume_metadata' in volume:
            metadata = volume.volume_metadata
            return {m['key']: m['value'] for m in metadata}
        if 'metadata' in volume:
            return volume.metadata

        return {}

    def _get_snapshot_metadata(self, snapshot):
        if 'snapshot_metadata' in snapshot:
            metadata = snapshot.snapshot_metadata
            return {m['key']: m['value'] for m in metadata}
        if 'metadata' in snapshot:
            return snapshot.metadata

        return {}

    def shallow_copy(self, **overrides):
        return Lun.FakeLun(self, **overrides)

    def _create_datatype(self, t):
        if t[0:2] == 'A0':
            datatype = t + ' FB 520P'
        elif t[0:2] == 'A8':
            datatype = t + ' FB 520U'
        elif t == '050':
            datatype = t + ' FB 520UV'
        elif t == '099':
            datatype = t + ' FB 520PV'
        else:
            datatype = None
        return datatype

    # Note: updating metadata in vol related funcs deletes all prior metadata
    def get_volume_update(self):
        volume_update = {}
        volume_update['provider_location'] = six.text_type(
            {'vol_hex_id': self.ds_id})

        # update metadata
        if self.is_snapshot:
            metadata = self._get_snapshot_metadata(self.volume)
        else:
            metadata = self._get_volume_metadata(self.volume)
            if self.type_replication:
                metadata['replication'] = six.text_type(
                    self.replication_driver_data)
            else:
                metadata.pop('replication', None)
            volume_update['replication_driver_data'] = json.dumps(
                self.replication_driver_data)
            volume_update['replication_status'] = self.replication_status

        metadata['data_type'] = (self.data_type if self.data_type else
                                 metadata['data_type'])
        metadata['vol_hex_id'] = self.ds_id
        volume_update['metadata'] = metadata

        # need to update volume size for OS400
        if self.type_os400:
            volume_update['size'] = self.size

        return volume_update


class Group(object):
    """provide group information for driver from group db object."""

    def __init__(self, group, is_snapshot=False):
        self.id = group.id
        self.host = group.host
        if is_snapshot:
            self.snapshots = group.snapshots
        else:
            self.volumes = group.volumes
        self.consisgroup_enabled = utils.is_group_a_cg_snapshot_type(group)


class DS8KProxy(proxy.IBMStorageProxy):
    prefix = "[IBM DS8K STORAGE]:"

    def __init__(self, storage_info, logger, exception, driver,
                 active_backend_id=None, HTTPConnectorObject=None):
        proxy.IBMStorageProxy.__init__(
            self, storage_info, logger, exception, driver, active_backend_id)
        self._helper = None
        self._replication = None
        self._connector_obj = HTTPConnectorObject
        self._replication_enabled = False
        self._active_backend_id = active_backend_id
        self.configuration = driver.configuration
        self.configuration.append_config_values(ds8k_opts)
        # TODO(jiamin): this cache is used to handle concurrency issue, but it
        # hurts HA, we will find whether is it possible to store it in storage.
        self.consisgroup_cache = {}

    @proxy._trace_time
    def setup(self, ctxt):
        LOG.info("Initiating connection to IBM DS8K storage system.")
        connection_type = self.configuration.safe_get('connection_type')
        replication_devices = self.configuration.safe_get('replication_device')
        if connection_type == storage.XIV_CONNECTION_TYPE_FC:
            if not replication_devices:
                self._helper = helper.DS8KCommonHelper(self.configuration,
                                                       self._connector_obj)
            else:
                self._helper = (
                    helper.DS8KReplicationSourceHelper(self.configuration,
                                                       self._connector_obj))
        elif connection_type == storage.XIV_CONNECTION_TYPE_FC_ECKD:
            self._helper = helper.DS8KECKDHelper(self.configuration,
                                                 self._connector_obj)
        else:
            raise exception.InvalidParameterValue(
                err=(_("Param [connection_type] %s is invalid.")
                     % connection_type))

        if replication_devices:
            self._do_replication_setup(replication_devices, self._helper)

    @proxy.logger
    def _do_replication_setup(self, devices, src_helper):
        if len(devices) >= 2:
            raise exception.InvalidParameterValue(
                err=_("Param [replication_device] is invalid, Driver "
                      "support only one replication target."))

        self._replication = replication.Replication(src_helper, devices[0])
        self._replication.check_physical_links()
        self._replication.check_connection_type()
        if self._active_backend_id:
            self._switch_backend_connection(self._active_backend_id)
        self._replication_enabled = True

    @proxy.logger
    def _switch_backend_connection(self, backend_id, repl_luns=None):
        repl_luns = self._replication.switch_source_and_target(backend_id,
                                                               repl_luns)
        self._helper = self._replication._source_helper
        return repl_luns

    @staticmethod
    def _b2gb(b):
        return b // (2 ** 30)

    @proxy._trace_time
    def _update_stats(self):
        if self._helper:
            storage_pools = self._helper.get_pools()
            if not len(storage_pools):
                msg = _('No pools found - make sure san_clustername '
                        'is defined in the config file and that the '
                        'pools exist on the storage.')
                LOG.error(msg)
                raise exception.CinderException(message=msg)
        else:
            raise exception.VolumeDriverException(
                message=(_('Backend %s is not initialized.')
                         % self.configuration.volume_backend_name))

        stats = {
            "volume_backend_name": self.configuration.volume_backend_name,
            "serial_number": self._helper.backend['storage_unit'],
            "extent_pools": self._helper.backend['pools_str'],
            "vendor_name": 'IBM',
            "driver_version": self.full_version,
            "storage_protocol": self._helper.get_connection_type(),
            "total_capacity_gb": self._b2gb(
                sum(p['cap'] for p in storage_pools.values())),
            "free_capacity_gb": self._b2gb(
                sum(p['capavail'] for p in storage_pools.values())),
            "reserved_percentage": self.configuration.reserved_percentage,
            "consistent_group_snapshot_enabled": True,
            "multiattach": False
        }

        if self._replication_enabled:
            stats['replication_enabled'] = self._replication_enabled

        self.meta['stat'] = stats

    def _assert(self, assert_condition, exception_message=''):
        if not assert_condition:
            LOG.error(exception_message)
            raise exception.VolumeDriverException(message=exception_message)

    @proxy.logger
    def _create_lun_helper(self, lun, pool=None, find_new_pid=True):
        # DS8K supports ECKD ESE volume from 8.1
        connection_type = self._helper.get_connection_type()
        if connection_type == storage.XIV_CONNECTION_TYPE_FC_ECKD:
            thin_provision = self._helper.get_thin_provision()
            if lun.type_thin and thin_provision:
                if lun.type_replication:
                    msg = _("The primary or the secondary storage "
                            "can not support ECKD ESE volume.")
                else:
                    msg = _("Backend can not support ECKD ESE volume.")
                LOG.error(msg)
                raise restclient.APIException(message=msg)
        # There is a time gap between find available LSS slot and
        # lun actually occupies it.
        excluded_lss = set()
        while True:
            try:
                if lun.group and lun.group.consisgroup_enabled:
                    lun.pool_lss_pair = {
                        'source': self._find_pool_lss_pair_for_cg(
                            lun, excluded_lss)}
                else:
                    if lun.type_replication and not lun.is_snapshot:
                        lun.pool_lss_pair = (
                            self._replication.find_pool_lss_pair(
                                excluded_lss))
                    else:
                        lun.pool_lss_pair = {
                            'source': self._helper.find_pool_lss_pair(
                                pool, find_new_pid, excluded_lss)}
                return self._helper.create_lun(lun)
            except restclient.LssFullException:
                LOG.warning("LSS %s is full, find another one.",
                            lun.pool_lss_pair['source'][1])
                excluded_lss.add(lun.pool_lss_pair['source'][1])

    @coordination.synchronized('{self.prefix}-consistency-group')
    def _find_pool_lss_pair_for_cg(self, lun, excluded_lss):
        lss_in_cache = self.consisgroup_cache.get(lun.group.id, set())
        if not lss_in_cache:
            lss_in_cg = self._get_lss_in_cg(lun.group, lun.is_snapshot)
            LOG.debug("LSSs used by CG %(cg)s are %(lss)s.",
                      {'cg': lun.group.id, 'lss': ','.join(lss_in_cg)})
            available_lss = lss_in_cg - excluded_lss
        else:
            available_lss = lss_in_cache - excluded_lss
        if not available_lss:
            available_lss = self._find_lss_for_cg()

        pid, lss = self._find_pool_for_lss(available_lss)
        if pid:
            lss_in_cache.add(lss)
            self.consisgroup_cache[lun.group.id] = lss_in_cache
        else:
            raise exception.VolumeDriverException(
                message=_('There are still some available LSSs for CG, '
                          'but they are not in the same node as pool.'))
        return (pid, lss)

    def _get_lss_in_cg(self, group, is_snapshot=False):
        # Driver can not support the case that dedicating LSS for CG while
        # user enable multiple backends which use the same DS8K.
        try:
            volume_backend_name = (
                group.host[group.host.index('@') + 1:group.host.index('#')])
        except ValueError:
            raise exception.VolumeDriverException(
                message=(_('Invalid host %(host)s in group %(group)s')
                         % {'host': group.host, 'group': group.id}))
        lss_in_cg = set()
        if volume_backend_name == self.configuration.volume_backend_name:
            if is_snapshot:
                luns = [Lun(snapshot, is_snapshot=True)
                        for snapshot in group.snapshots]
            else:
                luns = [Lun(volume) for volume in group.volumes]
            lss_in_cg = set(lun.ds_id[:2] for lun in luns if lun.ds_id)
        return lss_in_cg

    def _find_lss_for_cg(self):
        # Unable to get CGs/groups belonging to the current tenant, so
        # get all of them, this function will consume some time if there
        # are so many CGs/groups.
        lss_used = set()
        ctxt = context.get_admin_context()
        existing_groups = objects.GroupList.get_all(
            ctxt, filters={'status': 'available'})
        for group in existing_groups:
            if Group(group).consisgroup_enabled:
                lss_used = lss_used | self._get_lss_in_cg(group)
        existing_groupsnapshots = objects.GroupSnapshotList.get_all(
            ctxt, filters={'status': 'available'})
        for group in existing_groupsnapshots:
            if Group(group, True).consisgroup_enabled:
                lss_used = lss_used | self._get_lss_in_cg(group, True)
        available_lss = set(self._helper.backend['lss_ids_for_cg']) - lss_used
        for lss_set in self.consisgroup_cache.values():
            available_lss -= lss_set
        self._assert(available_lss,
                     "All LSSs reserved for CG have been used out, "
                     "please reserve more LSS for CG if there are still"
                     "some empty LSSs left.")
        LOG.debug('_find_lss_for_cg: available LSSs for consistency '
                  'group are %s', ','.join(available_lss))
        return available_lss

    @proxy.logger
    def _find_pool_for_lss(self, available_lss):
        for lss in available_lss:
            pid = self._helper.get_pool(lss)
            if pid:
                return (pid, lss)
        raise exception.VolumeDriverException(
            message=(_("Can not find pool for LSSs %s.")
                     % ','.join(available_lss)))

    @proxy.logger
    def _clone_lun(self, src_lun, tgt_lun):
        self._assert(src_lun.size <= tgt_lun.size,
                     _('Target volume should be bigger or equal '
                       'to the Source volume in size.'))
        self._ensure_vol_not_fc_target(src_lun.ds_id)
        # image volume cache brings two cases for clone lun:
        # 1. volume ID of src_lun and tgt_lun will be the same one because
        #    _clone_image_volume does not pop the provider_location.
        # 2. if creating image volume failed at the first time, tgt_lun will be
        #    deleted, so when it is sent to driver again, it will not exist.
        if (tgt_lun.ds_id is None or
           src_lun.ds_id == tgt_lun.ds_id or
           not self._helper.lun_exists(tgt_lun.ds_id)):
            # It is a preferred practice to locate the FlashCopy target
            # volume on the same DS8000 server as the FlashCopy source volume.
            pool = self._helper.get_pool(src_lun.ds_id[0:2])
            # flashcopy to larger target only works with thick vols, so we
            # emulate for thin by extending after copy
            if tgt_lun.type_thin and tgt_lun.size > src_lun.size:
                tmp_size = tgt_lun.size
                tgt_lun.size = src_lun.size
                self._create_lun_helper(tgt_lun, pool)
                tgt_lun.size = tmp_size
            else:
                self._create_lun_helper(tgt_lun, pool)
        else:
            self._assert(
                src_lun.size == tgt_lun.size,
                _('When target volume is pre-created, it must be equal '
                  'in size to source volume.'))

        finished = False
        try:
            vol_pairs = [{
                "source_volume": src_lun.ds_id,
                "target_volume": tgt_lun.ds_id
            }]
            self._helper.start_flashcopy(vol_pairs)
            fc_finished = self._helper.wait_flashcopy_finished(
                [src_lun], [tgt_lun])
            if (fc_finished and
               tgt_lun.type_thin and
               tgt_lun.size > src_lun.size):
                param = {
                    'cap': self._helper._gb2b(tgt_lun.size),
                    'captype': 'bytes'
                }
                self._helper.change_lun(tgt_lun.ds_id, param)
            finished = fc_finished
        finally:
            if not finished:
                self._helper.delete_lun(tgt_lun)

        return tgt_lun

    def _ensure_vol_not_fc_target(self, vol_hex_id):
        for cp in self._helper.get_flashcopy(vol_hex_id):
            if cp['targetvolume']['id'] == vol_hex_id:
                raise restclient.APIException(
                    data=(_('Volume %s is currently a target of another '
                            'FlashCopy operation') % vol_hex_id))

    def _create_replica_helper(self, lun):
        if not lun.pool_lss_pair.get('target'):
            lun = self._replication.enable_replication(lun, True)
        else:
            lun = self._replication.create_replica(lun)
        return lun

    @proxy._trace_time
    def create_volume(self, volume):
        lun = self._create_lun_helper(Lun(volume))
        if lun.type_replication:
            lun = self._create_replica_helper(lun)
        return lun.get_volume_update()

    @proxy._trace_time
    def create_cloned_volume(self, target_vol, source_vol):
        lun = self._clone_lun(Lun(source_vol), Lun(target_vol))
        if lun.type_replication:
            lun = self._create_replica_helper(lun)
        return lun.get_volume_update()

    @proxy._trace_time
    def create_volume_from_snapshot(self, volume, snapshot):
        lun = self._clone_lun(Lun(snapshot, is_snapshot=True), Lun(volume))
        if lun.type_replication:
            lun = self._create_replica_helper(lun)
        return lun.get_volume_update()

    @proxy._trace_time
    def extend_volume(self, volume, new_size):
        lun = Lun(volume)
        param = {
            'cap': self._helper._gb2b(new_size),
            'captype': 'bytes'
        }
        if lun.type_replication:
            if not self._active_backend_id:
                self._replication.delete_pprc_pairs(lun)
                self._helper.change_lun(lun.ds_id, param)
                self._replication.extend_replica(lun, param)
                self._replication.create_pprc_pairs(lun)
            else:
                raise exception.CinderException(
                    message=(_("The volume %s has been failed over, it is "
                               "not suggested to extend it.") % lun.ds_id))
        else:
            self._helper.change_lun(lun.ds_id, param)

    @proxy._trace_time
    def volume_exists(self, volume):
        return self._helper.lun_exists(Lun(volume).ds_id)

    @proxy._trace_time
    def delete_volume(self, volume):
        lun = Lun(volume)
        if lun.type_replication:
            lun = self._replication.delete_replica(lun)
        self._helper.delete_lun(lun)

    @proxy._trace_time
    def create_snapshot(self, snapshot):
        return self._clone_lun(Lun(snapshot['volume']), Lun(
            snapshot, is_snapshot=True)).get_volume_update()

    @proxy._trace_time
    def delete_snapshot(self, snapshot):
        self._helper.delete_lun(Lun(snapshot, is_snapshot=True))

    @proxy._trace_time
    def migrate_volume(self, ctxt, volume, backend):
        # this and retype is a complete mess, pending cinder changes for fix.
        # currently this is only for migrating between pools on the same
        # physical machine but different cinder.conf backends.
        # volume not allowed to get here if cg or repl
        # should probably check volume['status'] in ['available', 'in-use'],
        # especially for flashcopy
        stats = self.meta['stat']
        if backend['capabilities']['vendor_name'] != stats['vendor_name']:
            raise exception.VolumeDriverException(_(
                'source and destination vendors differ.'))
        if backend['capabilities']['serial_number'] != stats['serial_number']:
            raise exception.VolumeDriverException(_(
                'source and destination serial numbers differ.'))
        new_pools = self._helper.get_pools(
            backend['capabilities']['extent_pools'])

        lun = Lun(volume)
        cur_pool_id = self._helper.get_lun(lun.ds_id)['pool']['id']
        cur_node = self._helper.get_storage_pools()[cur_pool_id]['node']

        # try pools in same rank
        for pid, pool in new_pools.items():
            if pool['node'] == cur_node:
                try:
                    self._helper.change_lun(lun.ds_id, {'pool': pid})
                    return (True, None)
                except Exception:
                    pass

        # try pools in opposite rank
        for pid, pool in new_pools.items():
            if pool['node'] != cur_node:
                try:
                    new_lun = lun.shallow_copy()
                    self._create_lun_helper(new_lun, pid, False)
                    lun.data_type = new_lun.data_type
                    self._clone_lun(lun, new_lun)
                    volume_update = new_lun.update_volume(lun)
                    try:
                        self._helper.delete_lun(lun)
                    except Exception:
                        pass
                    return (True, volume_update)
                except Exception:
                    # will ignore missing ds_id if failed create volume
                    self._helper.delete_lun(new_lun)

        return (False, None)

    @proxy._trace_time
    def retype(self, ctxt, volume, new_type, diff, host):
        """retype the volume.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        def _get_volume_type(key, value):
            extra_specs = diff.get('extra_specs')
            specific_type = extra_specs.get(key) if extra_specs else None
            if specific_type:
                old_type = (True if str(specific_type[0]).upper() == value
                            else False)
                new_type = (True if str(specific_type[1]).upper() == value
                            else False)
            else:
                old_type = None
                new_type = None

            return old_type, new_type

        def _convert_thin_and_thick(lun, new_type):
            new_lun = lun.shallow_copy()
            new_lun.type_thin = new_type
            self._create_lun_helper(new_lun)
            self._clone_lun(lun, new_lun)
            try:
                self._helper.delete_lun(lun)
            except Exception:
                pass
            lun.ds_id = new_lun.ds_id
            lun.data_type = new_lun.data_type
            lun.type_thin = new_type

            return lun

        lun = Lun(volume)
        # check thin or thick
        old_type_thin, new_type_thin = _get_volume_type(
            'drivers:thin_provision', 'True'.upper())

        # check replication capability
        old_type_replication, new_type_replication = _get_volume_type(
            'replication_enabled', strings.METADATA_IS_TRUE)

        # start retype
        if old_type_thin != new_type_thin:
            if old_type_replication:
                if not new_type_replication:
                    lun = self._replication.delete_replica(lun)
                    lun = _convert_thin_and_thick(lun, new_type_thin)
                else:
                    raise exception.CinderException(
                        message=(_("The volume %s is in replication "
                                   "relationship, it is not supported to "
                                   "retype from thin to thick or vice "
                                   "versa.") % lun.ds_id))
            else:
                lun = _convert_thin_and_thick(lun, new_type_thin)
                if new_type_replication:
                    lun.type_replication = True
                    lun = self._replication.enable_replication(lun)
        else:
            if not old_type_replication and new_type_replication:
                lun.type_replication = True
                lun = self._replication.enable_replication(lun)
            elif old_type_replication and not new_type_replication:
                lun = self._replication.delete_replica(lun)
                lun.type_replication = False

        return True, lun.get_volume_update()

    @proxy._trace_time
    @proxy.logger
    def initialize_connection(self, volume, connector, **kwargs):
        """Attach a volume to the host."""
        vol_id = Lun(volume).ds_id
        LOG.info('Attach the volume %s.', vol_id)
        return self._helper.initialize_connection(vol_id, connector, **kwargs)

    @proxy._trace_time
    @proxy.logger
    def terminate_connection(self, volume, connector, force=False, **kwargs):
        """Detach a volume from a host."""
        vol_id = Lun(volume).ds_id
        LOG.info('Detach the volume %s.', vol_id)
        return self._helper.terminate_connection(vol_id, connector,
                                                 force, **kwargs)

    @proxy.logger
    def create_group(self, ctxt, group):
        """Create generic volume group."""
        if Group(group).consisgroup_enabled:
            self._assert(self._helper.backend['lss_ids_for_cg'],
                         'No LSS(s) for CG, please make sure you have '
                         'reserved LSS for CG via param lss_range_for_cg.')
        return self._helper.create_group(group)

    @proxy.logger
    def delete_group(self, ctxt, group, volumes):
        """Delete group and the volumes in the group."""
        luns = [Lun(volume) for volume in volumes]
        if Group(group).consisgroup_enabled:
            return self._delete_group_with_lock(group, luns)
        else:
            return self._helper.delete_group(group, luns)

    @coordination.synchronized('{self.prefix}-consistency-group')
    def _delete_group_with_lock(self, group, luns):
        model_update, volumes_model_update = (
            self._helper.delete_group(group, luns))
        if model_update['status'] == fields.GroupStatus.DELETED:
            self._update_consisgroup_cache(group.id)
        return model_update, volumes_model_update

    @proxy.logger
    def delete_group_snapshot(self, ctxt, group_snapshot, snapshots):
        """Delete volume group snapshot."""
        tgt_luns = [Lun(s, is_snapshot=True) for s in snapshots]
        if Group(group_snapshot, True).consisgroup_enabled:
            return self._delete_group_snapshot_with_lock(
                group_snapshot, tgt_luns)
        else:
            return self._helper.delete_group_snapshot(
                group_snapshot, tgt_luns)

    @coordination.synchronized('{self.prefix}-consistency-group')
    def _delete_group_snapshot_with_lock(self, group_snapshot, tgt_luns):
        model_update, snapshots_model_update = (
            self._helper.delete_group_snapshot(group_snapshot, tgt_luns))
        if model_update['status'] == fields.GroupStatus.DELETED:
            self._update_consisgroup_cache(group_snapshot.id)
        return model_update, snapshots_model_update

    @proxy.logger
    def create_group_snapshot(self, ctxt, group_snapshot, snapshots):
        """Create volume group snapshot."""
        snapshots_model_update = []
        model_update = {'status': fields.GroupStatus.AVAILABLE}

        src_luns = [Lun(snapshot['volume']) for snapshot in snapshots]
        tgt_luns = [Lun(snapshot, is_snapshot=True) for snapshot in snapshots]

        try:
            if src_luns and tgt_luns:
                self._clone_group(src_luns, tgt_luns)
        except restclient.APIException:
            model_update['status'] = fields.GroupStatus.ERROR
            LOG.exception('Failed to create group snapshot.')

        for tgt_lun in tgt_luns:
            snapshot_model_update = tgt_lun.get_volume_update()
            snapshot_model_update.update({
                'id': tgt_lun.os_id,
                'status': model_update['status']
            })
            snapshots_model_update.append(snapshot_model_update)

        return model_update, snapshots_model_update

    @proxy.logger
    def update_group(self, ctxt, group, add_volumes, remove_volumes):
        """Update generic volume group."""
        if Group(group).consisgroup_enabled:
            return self._update_group(group, add_volumes, remove_volumes)
        else:
            return None, None, None

    def _update_group(self, group, add_volumes, remove_volumes):
        add_volumes_update = []
        group_volume_ids = [vol.id for vol in group.volumes]
        add_volumes = [vol for vol in add_volumes
                       if vol.id not in group_volume_ids]
        remove_volumes = [vol for vol in remove_volumes
                          if vol.id in group_volume_ids]
        if add_volumes:
            add_luns = [Lun(vol) for vol in add_volumes]
            lss_in_cg = [Lun(vol).ds_id[:2] for vol in group.volumes]
            if not lss_in_cg:
                lss_in_cg = self._find_lss_for_empty_group(group, add_luns)
            add_volumes_update = self._add_volumes_into_group(
                group, add_luns, lss_in_cg)
        if remove_volumes:
            self._remove_volumes_in_group(group, add_volumes, remove_volumes)
        return None, add_volumes_update, None

    @coordination.synchronized('{self.prefix}-consistency-group')
    def _find_lss_for_empty_group(self, group, luns):
        sorted_lss_ids = collections.Counter([lun.ds_id[:2] for lun in luns])
        available_lss = self._find_lss_for_cg()
        lss_for_cg = None
        for lss_id in sorted_lss_ids:
            if lss_id in available_lss:
                lss_for_cg = lss_id
                break
        if not lss_for_cg:
            lss_for_cg = available_lss.pop()
        self._update_consisgroup_cache(group.id, lss_for_cg)
        return lss_for_cg

    def _add_volumes_into_group(self, group, add_luns, lss_in_cg):
        add_volumes_update = []
        luns = [lun for lun in add_luns if lun.ds_id[:2] not in lss_in_cg]
        for lun in luns:
            if lun.type_replication:
                new_lun = self._clone_lun_for_group(group, lun)
                new_lun.type_replication = True
                new_lun = self._replication.enable_replication(new_lun, True)
                lun = self._replication.delete_replica(lun)
            else:
                new_lun = self._clone_lun_for_group(group, lun)
            self._helper.delete_lun(lun)
            volume_update = new_lun.update_volume(lun)
            volume_update['id'] = lun.os_id
            add_volumes_update.append(volume_update)
        return add_volumes_update

    def _clone_lun_for_group(self, group, lun):
        lun.group = Group(group)
        new_lun = lun.shallow_copy()
        new_lun.type_replication = False
        self._create_lun_helper(new_lun)
        self._clone_lun(lun, new_lun)
        return new_lun

    @coordination.synchronized('{self.prefix}-consistency-group')
    def _remove_volumes_in_group(self, group, add_volumes, remove_volumes):
        if len(remove_volumes) == len(group.volumes) + len(add_volumes):
            self._update_consisgroup_cache(group.id)

    @proxy.logger
    def _update_consisgroup_cache(self, group_id, lss_id=None):
        if lss_id:
            self.consisgroup_cache[group_id] = set([lss_id])
        else:
            if self.consisgroup_cache.get(group_id):
                LOG.debug('Group %(id)s owns LSS %(lss)s in the cache.', {
                    'id': group_id,
                    'lss': ','.join(self.consisgroup_cache[group_id])
                })
                self.consisgroup_cache.pop(group_id)

    @proxy._trace_time
    def create_group_from_src(self, ctxt, group, volumes, group_snapshot,
                              sorted_snapshots, source_group,
                              sorted_source_vols):
        """Create volume group from volume group or volume group snapshot."""
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        volumes_model_update = []

        if group_snapshot and sorted_snapshots:
            src_luns = [Lun(snapshot, is_snapshot=True)
                        for snapshot in sorted_snapshots]
        elif source_group and sorted_source_vols:
            src_luns = [Lun(source_vol)
                        for source_vol in sorted_source_vols]
        else:
            msg = _("_create_group_from_src supports a group snapshot "
                    "source or a group source, other sources can not "
                    "be used.")
            LOG.error(msg)
            raise exception.InvalidInput(message=msg)

        try:
            # Don't use paramter volumes because it has DetachedInstanceError
            # issue frequently. here tries to get and sort new volumes, a lot
            # of cases have been guaranteed by the _sort_source_vols in
            # manange.py, so not verify again.
            sorted_volumes = []
            for vol in volumes:
                found_vols = [v for v in group.volumes if v['id'] == vol['id']]
                sorted_volumes.extend(found_vols)
            volumes = sorted_volumes

            tgt_luns = [Lun(volume) for volume in volumes]
            if src_luns and tgt_luns:
                self._clone_group(src_luns, tgt_luns)
            for tgt_lun in tgt_luns:
                if tgt_lun.type_replication:
                    self._create_replica_helper(tgt_lun)
        except restclient.APIException:
            model_update['status'] = fields.GroupStatus.ERROR
            LOG.exception("Failed to create group from group snapshot.")

        for tgt_lun in tgt_luns:
            volume_model_update = tgt_lun.get_volume_update()
            volume_model_update.update({
                'id': tgt_lun.os_id,
                'status': model_update['status']
            })
            volumes_model_update.append(volume_model_update)

        return model_update, volumes_model_update

    def _clone_group(self, src_luns, tgt_luns):
        for src_lun in src_luns:
            self._ensure_vol_not_fc_target(src_lun.ds_id)
        finished = False
        try:
            vol_pairs = []
            for src_lun, tgt_lun in zip(src_luns, tgt_luns):
                pool = self._helper.get_pool(src_lun.ds_id[0:2])
                if tgt_lun.ds_id is None:
                    self._create_lun_helper(tgt_lun, pool)
                vol_pairs.append({
                    "source_volume": src_lun.ds_id,
                    "target_volume": tgt_lun.ds_id
                })
            if tgt_lun.group.consisgroup_enabled:
                self._do_flashcopy_with_freeze(vol_pairs)
            else:
                self._helper.start_flashcopy(vol_pairs)
            finished = self._helper.wait_flashcopy_finished(src_luns, tgt_luns)
        finally:
            if not finished:
                self._helper.delete_lun(tgt_luns)

    @coordination.synchronized('{self.prefix}-consistency-group')
    @proxy._trace_time
    def _do_flashcopy_with_freeze(self, vol_pairs):
        # issue flashcopy with freeze
        self._helper.start_flashcopy(vol_pairs, True)
        # unfreeze the LSS where source volumes are in
        lss_ids = list(set(p['source_volume'][0:2] for p in vol_pairs))
        LOG.debug('Unfreezing the LSS: %s', ','.join(lss_ids))
        self._helper.unfreeze_lss(lss_ids)

    def freeze_backend(self, ctxt):
        """Notify the backend that it's frozen."""
        pass

    def thaw_backend(self, ctxt):
        """Notify the backend that it's unfrozen/thawed."""
        pass

    @proxy.logger
    @proxy._trace_time
    def failover_host(self, ctxt, volumes, secondary_id):
        """Fail over the volume back and forth.

        if secondary_id is 'default', volumes will be failed back,
        otherwize failed over.
        """
        volume_update_list = []
        if secondary_id == strings.PRIMARY_BACKEND_ID:
            if not self._active_backend_id:
                LOG.info("Host has been failed back. doesn't need "
                         "to fail back again.")
                return self._active_backend_id, volume_update_list
        else:
            if self._active_backend_id:
                LOG.info("Host has been failed over to %s.",
                         self._active_backend_id)
                return self._active_backend_id, volume_update_list

            backend_id = self._replication._target_helper.backend['id']
            if secondary_id is None:
                secondary_id = backend_id
            elif secondary_id != backend_id:
                raise exception.InvalidReplicationTarget(
                    message=(_('Invalid secondary_backend_id specified. '
                               'Valid backend id is %s.') % backend_id))

        LOG.debug("Starting failover to %s.", secondary_id)

        replicated_luns = []
        for volume in volumes:
            lun = Lun(volume)
            if lun.type_replication and lun.status == "available":
                replicated_luns.append(lun)
            else:
                volume_update = (
                    self._replication.failover_unreplicated_volume(lun))
                volume_update_list.append(volume_update)

        if replicated_luns:
            try:
                if secondary_id != strings.PRIMARY_BACKEND_ID:
                    self._replication.do_pprc_failover(replicated_luns,
                                                       secondary_id)
                    self._active_backend_id = secondary_id
                    replicated_luns = self._switch_backend_connection(
                        secondary_id, replicated_luns)
                else:
                    self._replication.start_pprc_failback(
                        replicated_luns, self._active_backend_id)
                    self._active_backend_id = ""
                    self._helper = self._replication._source_helper
            except restclient.APIException as e:
                raise exception.UnableToFailOver(
                    reason=(_("Unable to failover host to %(id)s. "
                              "Exception= %(ex)s")
                            % {'id': secondary_id, 'ex': six.text_type(e)}))

            for lun in replicated_luns:
                volume_update = lun.get_volume_update()
                volume_update['replication_status'] = (
                    'failed-over' if self._active_backend_id else 'enabled')
                model_update = {'volume_id': lun.os_id,
                                'updates': volume_update}
                volume_update_list.append(model_update)
        else:
            LOG.info("No volume has replication capability.")
            if secondary_id != strings.PRIMARY_BACKEND_ID:
                LOG.info("Switch to the target %s", secondary_id)
                self._switch_backend_connection(secondary_id)
                self._active_backend_id = secondary_id
            else:
                LOG.info("Switch to the primary %s", secondary_id)
                self._switch_backend_connection(self._active_backend_id)
                self._active_backend_id = ""

        return secondary_id, volume_update_list
