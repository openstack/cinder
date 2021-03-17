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
"""This is the driver that allows openstack to talk to DS8K.

All volumes are thin provisioned by default, if the machine is licensed for it.
This can be overridden by creating a volume type and specifying a key like so:

.. code:: console

  #> cinder type-create my_type
  #> cinder type-key my_type set drivers:thin_provision=False
  #> cinder create --volume-type my_type 123


Sample settings for cinder.conf:

.. code:: ini

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

"""
import ast
import json

import eventlet
from oslo_config import cfg
from oslo_log import log as logging
import six

from cinder import context
from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import fields
from cinder.volume import configuration
import cinder.volume.drivers.ibm.ibm_storage as storage
from cinder.volume.drivers.ibm.ibm_storage import (
    ds8k_replication as replication)
from cinder.volume.drivers.ibm.ibm_storage import ds8k_helper as helper
from cinder.volume.drivers.ibm.ibm_storage import ds8k_restclient as restclient
from cinder.volume.drivers.ibm.ibm_storage import proxy
from cinder.volume.drivers.ibm.ibm_storage import strings
from cinder.volume import volume_types
from cinder.volume import volume_utils

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
    'os400': '',
    'storage_pool_ids': '',
    'storage_lss_ids': '',
    'async_clone': False,
    'multiattach': False
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
CONF.register_opts(ds8k_opts, group=configuration.SHARED_CONF_GROUP)


class Lun(object):
    """provide volume information for driver from volume db object.

    Version history:

    .. code-block:: none

        1.0.0 - initial revision.
        2.1.0 - Added support for specify pool and lss, also improve the code.
        2.1.1 - Added support for replication consistency group.
        2.1.2 - Added support for cloning volume asynchronously.
        2.3.0 - Added support for reporting backend state.
        2.5.0 - Added support for revert to snapshot operation.
    """

    VERSION = "2.5.0"

    class FakeLun(object):

        def __init__(self, lun, **overrides):
            self.size = lun.size
            self.os_id = lun.os_id
            self.cinder_name = lun.cinder_name
            self.is_snapshot = lun.is_snapshot
            self.ds_name = lun.ds_name
            self.ds_id = lun.ds_id
            self.type_thin = lun.type_thin
            self.type_os400 = lun.type_os400
            self.data_type = lun.data_type
            self.type_replication = lun.type_replication
            self.group = lun.group
            self.specified_pool = lun.specified_pool
            self.specified_lss = lun.specified_lss
            self.async_clone = lun.async_clone
            self.multiattach = lun.multiattach
            self.status = lun.status
            if not self.is_snapshot:
                self.replica_ds_name = lun.replica_ds_name
                self.replication_driver_data = (
                    lun.replication_driver_data.copy())
                self.replication_status = lun.replication_status
            self.pool_lss_pair = lun.pool_lss_pair

        def update_volume(self, lun):
            lun.data_type = self.data_type
            volume_update = lun.get_volume_update()
            volume_update['provider_location'] = six.text_type({
                'vol_hex_id': self.ds_id})
            if self.type_replication:
                volume_update['replication_driver_data'] = json.dumps(
                    self.replication_driver_data)
                volume_update['metadata']['replication'] = six.text_type(
                    self.replication_driver_data)
            else:
                volume_update.pop('replication_driver_data', None)
                volume_update['metadata'].pop('replication', None)
            volume_update['metadata']['vol_hex_id'] = self.ds_id
            volume_update['multiattach'] = self.multiattach

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
        ).upper() == 'TRUE'
        self.type_replication = self.specs.get(
            'replication_enabled',
            '<is> %s' % EXTRA_SPECS_DEFAULTS['replication_enabled']
        ).upper() == strings.METADATA_IS_TRUE
        self.specified_pool = self.specs.get(
            'drivers:storage_pool_ids',
            EXTRA_SPECS_DEFAULTS['storage_pool_ids']
        )
        self.specified_lss = self.specs.get(
            'drivers:storage_lss_ids',
            EXTRA_SPECS_DEFAULTS['storage_lss_ids']
        )
        self.multiattach = self.specs.get(
            'multiattach', '<is> %s' % EXTRA_SPECS_DEFAULTS['multiattach']
        ).upper() == strings.METADATA_IS_TRUE

        if volume.provider_location:
            provider_location = ast.literal_eval(volume.provider_location)
            self.ds_id = provider_location['vol_hex_id']
        else:
            self.ds_id = None
        self.cinder_name = volume.name
        self.pool_lss_pair = {}
        self.is_snapshot = is_snapshot
        if self.is_snapshot:
            self.group = (Group(volume.group_snapshot, True)
                          if volume.group_snapshot else None)
            self.size = volume.volume_size
            # ds8k supports at most 16 chars
            self.ds_name = helper.filter_alnum(self.cinder_name)[:16]
            self.metadata = self._get_snapshot_metadata(volume)
            self.source_volid = volume.volume_id
        else:
            self.group = Group(volume.group) if volume.group else None
            self.size = volume.size
            self.ds_name = helper.filter_alnum(self.cinder_name)[:16]
            self.replica_ds_name = helper.filter_alnum(self.cinder_name)[:16]
            self.previous_status = volume.previous_status
            self.replication_status = volume.replication_status
            self.replication_driver_data = (
                json.loads(volume.replication_driver_data)
                if volume.replication_driver_data else {})
            if self.replication_driver_data:
                # now only support one replication target.
                replication_target = sorted(
                    self.replication_driver_data.values())[0]
                self.replica_ds_id = replication_target['vol_hex_id']
                self.pool_lss_pair = {
                    'source': (None, self.ds_id[0:2]),
                    'target': (None, self.replica_ds_id[0:2])
                }
                # Don't use self.replication_status to judge if volume has
                # been failed over or not, because when user fail over a
                # group, replication_status of each volume in group is
                # failing over.
                self.failed_over = (True if 'default' in
                                    self.replication_driver_data.keys()
                                    else False)
            else:
                self.failed_over = False
            self.metadata = self._get_volume_metadata(volume)
            self.source_volid = volume.source_volid
        self.async_clone = self.metadata.get(
            'async_clone',
            '%s' % EXTRA_SPECS_DEFAULTS['async_clone']
        ).upper() == 'TRUE'

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
        if not self.is_snapshot:
            if self.type_replication:
                self.metadata['replication'] = six.text_type(
                    self.replication_driver_data)
            else:
                self.metadata.pop('replication', None)
            volume_update['replication_driver_data'] = json.dumps(
                self.replication_driver_data)
            volume_update['replication_status'] = (
                self.replication_status or
                fields.ReplicationStatus.NOT_CAPABLE)
            volume_update['multiattach'] = self.multiattach

        self.metadata['data_type'] = (self.data_type or
                                      self.metadata['data_type'])
        self.metadata['vol_hex_id'] = self.ds_id
        volume_update['metadata'] = self.metadata

        # need to update volume size for OS400
        if self.type_os400:
            volume_update['size'] = self.size

        return volume_update


class Group(object):
    """provide group information for driver from group db object."""

    def __init__(self, group, is_snapshot=False):
        self.id = group.id
        self.host = group.host
        self.consisgroup_snapshot_enabled = (
            volume_utils.is_group_a_cg_snapshot_type(group))
        self.group_replication_enabled = (
            volume_utils.is_group_a_type(
                group, "group_replication_enabled"))
        self.consisgroup_replication_enabled = (
            volume_utils.is_group_a_type(
                group, "consistent_group_replication_enabled"))
        if is_snapshot:
            self.snapshots = group.snapshots
        else:
            self.failed_over = (
                group.replication_status ==
                fields.ReplicationStatus.FAILED_OVER)
            # create_volume needs to check volumes in the group,
            # so get it from volume.group object.
            self.volumes = group.volumes


class DS8KProxy(proxy.IBMStorageProxy):
    prefix = "[IBM DS8K STORAGE]:"

    def __init__(self, storage_info, logger, exception, driver,
                 active_backend_id=None, HTTPConnectorObject=None, host=None):
        proxy.IBMStorageProxy.__init__(
            self, storage_info, logger, exception, driver, active_backend_id)
        self._helper = None
        self._replication = None
        self._connector_obj = HTTPConnectorObject
        self._host = host
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
        # checking volumes which are still in clone process.
        self._check_async_cloned_volumes()

    @proxy.logger
    def _check_async_cloned_volumes(self):
        ctxt = context.get_admin_context()
        volumes = objects.VolumeList.get_all_by_host(ctxt, self._host)
        src_luns = []
        tgt_luns = []
        for volume in volumes:
            tgt_lun = Lun(volume)
            if tgt_lun.metadata.get('flashcopy') == 'started':
                try:
                    src_vol = objects.Volume.get_by_id(
                        ctxt, tgt_lun.source_volid)
                except exception.VolumeNotFound:
                    LOG.error("Failed to get source volume %(src)s for "
                              "target volume %(tgt)s",
                              {'src': tgt_lun.source_volid,
                               'tgt': tgt_lun.ds_id})
                else:
                    src_luns.append(Lun(src_vol))
                    tgt_luns.append(tgt_lun)
        if src_luns and tgt_luns:
            eventlet.spawn(self._wait_flashcopy, src_luns, tgt_luns)

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
            self._replication.switch_source_and_target_client()
        self._replication_enabled = True

    @staticmethod
    def _b2gb(b):
        return b // (2 ** 30)

    @proxy._trace_time
    def _update_stats(self):
        if self._helper:
            storage_pools = self._helper.get_pools()
        else:
            raise exception.VolumeDriverException(
                message=(_('Backend %s is not initialized.')
                         % self.configuration.volume_backend_name))

        stats = {
            "volume_backend_name":
                self.configuration.volume_backend_name,
            "serial_number": self._helper.backend['storage_unit'],
            "reserved_percentage":
                self.configuration.reserved_percentage,
            "consistent_group_snapshot_enabled": True,
            "group_replication_enabled": True,
            "consistent_group_replication_enabled": True,
            "multiattach": True,
            "vendor_name": 'IBM',
            "driver_version": self.full_version,
            "storage_protocol": self._helper.get_connection_type(),
            "extent_pools": 'None',
            "total_capacity_gb": 0,
            "free_capacity_gb": 0,
            "backend_state": 'up'
        }
        if not len(storage_pools):
            msg = _('No pools found - make sure san_clustername '
                    'is defined in the config file and that the '
                    'pools exist on the storage.')
            LOG.error(msg)
            stats.update({
                "extent_pools": 'None',
                "total_capacity_gb": 0,
                "free_capacity_gb": 0,
                "backend_state": 'down'
            })
        else:
            self._helper.update_storage_pools(storage_pools)
            stats.update({
                "extent_pools": ','.join(p for p in storage_pools.keys()),
                "total_capacity_gb": self._b2gb(
                    sum(p['cap'] for p in storage_pools.values())),
                "free_capacity_gb": self._b2gb(
                    sum(p['capavail'] for p in storage_pools.values())),
                "backend_state": 'up'
            })
        if self._replication_enabled:
            stats['replication_enabled'] = self._replication_enabled

        self.meta['stat'] = stats

    def _assert(self, assert_condition, exception_message=''):
        if not assert_condition:
            LOG.error(exception_message)
            raise exception.VolumeDriverException(message=exception_message)

    @proxy.logger
    def _create_lun_helper(self, lun, pool=None, find_new_pid=True):
        connection_type = self._helper.get_connection_type()
        if connection_type == storage.XIV_CONNECTION_TYPE_FC_ECKD:
            if lun.type_thin:
                if self._helper.get_thin_provision():
                    msg = (_("Backend %s can not support ECKD ESE volume.")
                           % self._helper.backend['storage_unit'])
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)
                if lun.type_replication:
                    target_helper = self._replication.get_target_helper()
                    # PPRC can not copy from ESE volume to standard volume
                    # or vice versa.
                    if target_helper.get_thin_provision():
                        msg = (_("Secondary storage %s can not support ECKD "
                                 "ESE volume.")
                               % target_helper.backend['storage_unit'])
                        LOG.error(msg)
                        raise exception.VolumeDriverException(message=msg)
        # There is a time gap between find available LSS slot and
        # lun actually occupies it.
        excluded_lss = set()
        while True:
            try:
                if lun.specified_pool or lun.specified_lss:
                    lun.pool_lss_pair = {
                        'source': self._find_pool_lss_pair_from_spec(
                            lun, excluded_lss)}
                elif lun.group and (lun.group.consisgroup_snapshot_enabled or
                                    lun.group.consisgroup_replication_enabled):
                    lun.pool_lss_pair = (
                        self._find_pool_lss_pair_for_cg(lun, excluded_lss))
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
                excluded_lss.add(lun.pool_lss_pair['source'][1])
                if lun.group and (lun.group.consisgroup_snapshot_enabled or
                                  lun.group.consisgroup_replication_enabled):
                    msg = _("The reserve LSS for CG is full. "
                            "Volume can not be created on it.")
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)
                else:
                    LOG.warning("LSS %s is full, find another one.",
                                lun.pool_lss_pair['source'][1])

    def _find_pool_lss_pair_from_spec(self, lun, excluded_lss):
        if lun.group and (lun.group.consisgroup_snapshot_enabled or
           lun.group.consisgroup_replication_enabled):
            msg = _("No support for specifying pool or lss for "
                    "volumes that belong to consistency group.")
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        else:
            pool, lss = self._helper.find_biggest_pool_and_lss(
                excluded_lss, (lun.specified_pool, lun.specified_lss))
        return (pool, lss)

    @coordination.synchronized('{self.prefix}-consistency-group')
    def _find_pool_lss_pair_for_cg(self, lun, excluded_lss):
        # NOTE: a group may have multiple LSSs.
        lss_pairs_in_cache = self.consisgroup_cache.get(lun.group.id, set())
        if not lss_pairs_in_cache:
            lss_pairs_in_group = self._get_lss_pairs_in_group(lun.group,
                                                              lun.is_snapshot)
            LOG.debug("LSSs used by group %(grp)s are %(lss_pair)s.",
                      {'grp': lun.group.id, 'lss_pair': lss_pairs_in_group})
            available_lss_pairs = set(pair for pair in lss_pairs_in_group
                                      if pair[0] != excluded_lss)
        else:
            available_lss_pairs = set(pair for pair in lss_pairs_in_cache
                                      if pair[0] != excluded_lss)
        if not available_lss_pairs:
            available_lss_pairs = self._find_lss_pair_for_cg(lun.group,
                                                             excluded_lss,
                                                             lun.is_snapshot)

        pool_lss_pair, lss_pair = self._find_pool_for_lss(available_lss_pairs)
        if pool_lss_pair:
            lss_pairs_in_cache.add(lss_pair)
            self.consisgroup_cache[lun.group.id] = lss_pairs_in_cache
        else:
            raise exception.VolumeDriverException(
                message=(_('There are still some available LSSs %s for CG, '
                           'but they are not in the same node as pool.')
                         % available_lss_pairs))
        return pool_lss_pair

    def _get_lss_pairs_in_group(self, group, is_snapshot=False):
        lss_pairs_in_group = set()
        if is_snapshot:
            luns = [Lun(snapshot, is_snapshot=True)
                    for snapshot in group.snapshots]
        else:
            luns = [Lun(volume) for volume in group.volumes]
        if group.consisgroup_replication_enabled and not is_snapshot:
            lss_pairs_in_group = set((lun.ds_id[:2], lun.replica_ds_id[:2])
                                     for lun in luns if lun.ds_id and
                                     lun.replica_ds_id)
        else:
            lss_pairs_in_group = set((lun.ds_id[:2], None)
                                     for lun in luns if lun.ds_id)
        return lss_pairs_in_group

    def _find_lss_pair_for_cg(self, group, excluded_lss, is_snapshot):
        lss_pairs_used = set()
        ctxt = context.get_admin_context()
        filters_groups = {'host': group.host, 'status': 'available'}
        groups = objects.GroupList.get_all(ctxt, filters=filters_groups)
        for grp in groups:
            grp = Group(grp)
            if (grp.consisgroup_snapshot_enabled or
                    grp.consisgroup_replication_enabled):
                lss_pairs_used |= self._get_lss_pairs_in_group(grp)
                filters_group_snapshots = {'status': 'available'}
                group_snapshots = objects.GroupSnapshotList.get_all_by_group(
                    ctxt, grp.id, filters=filters_group_snapshots)
                for sgrp in group_snapshots:
                    sgrp = Group(sgrp, True)
                    if (sgrp.consisgroup_snapshot_enabled or
                            sgrp.consisgroup_replication_enabled):
                        lss_pairs_used |= self._get_lss_pairs_in_group(sgrp,
                                                                       True)
        # in order to keep one-to-one pprc mapping relationship, zip LSSs
        # which reserved by user.
        if not is_snapshot:
            if group.consisgroup_replication_enabled:
                target_helper = self._replication.get_target_helper()
                source_lss_for_cg = self._helper.backend['lss_ids_for_cg']
                target_lss_for_cg = target_helper.backend['lss_ids_for_cg']
                available_lss_pairs = zip(source_lss_for_cg, target_lss_for_cg)
            else:
                available_lss_pairs = [(lss, None) for lss in
                                       self._helper.backend['lss_ids_for_cg']]

            source_lss_used = set()
            for lss_pair in lss_pairs_used:
                source_lss_used.add(lss_pair[0])
            # in concurrency case, lss may be reversed in cache but the group
            # has not been committed into DB.
            for lss_pairs_set in self.consisgroup_cache.values():
                source_lss_used |= set(
                    lss_pair[0] for lss_pair in lss_pairs_set)

            available_lss_pairs = [lss_pair for lss_pair in available_lss_pairs
                                   if lss_pair[0] not in source_lss_used]
            self._assert(available_lss_pairs,
                         "All LSSs reserved for CG have been used out, "
                         "please reserve more LSS for CG if there are still "
                         "some empty LSSs left.")
        else:
            available_lss_pairs = set()
            excluded_lss |= lss_pairs_used
            for node in (0, 1):
                available_lss_pairs |= {(self._helper._find_lss(
                    node, excluded_lss), None)}
            if not available_lss_pairs:
                raise restclient.LssIDExhaustError(
                    message=_('All LSS/LCU IDs for configured pools '
                              'on storage are exhausted.'))
        LOG.debug('_find_lss_pair_for_cg: available LSSs for consistency '
                  'group are %s', available_lss_pairs)
        return available_lss_pairs

    @proxy.logger
    def _find_pool_for_lss(self, available_lss_pairs):
        # all LSS pairs have target LSS or do not have.
        for src_lss, tgt_lss in available_lss_pairs:
            src_pid = self._helper.get_pool(src_lss)
            if not src_pid:
                continue
            if tgt_lss:
                target_helper = self._replication.get_target_helper()
                tgt_pid = target_helper.get_pool(tgt_lss)
                if tgt_pid:
                    return ({'source': (src_pid, src_lss),
                             'target': (tgt_pid, tgt_lss)},
                            (src_lss, tgt_lss))
            else:
                return {'source': (src_pid, src_lss)}, (src_lss, tgt_lss)
        raise exception.VolumeDriverException(
            message=(_("Can not find pool for LSSs %s.")
                     % available_lss_pairs))

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

        vol_pairs = [{
            "source_volume": src_lun.ds_id,
            "target_volume": tgt_lun.ds_id
        }]
        try:
            self._helper.start_flashcopy(vol_pairs)
            if ((tgt_lun.type_thin and tgt_lun.size > src_lun.size) or
               (not tgt_lun.async_clone)):
                self._helper.wait_flashcopy_finished([src_lun], [tgt_lun])
                if (tgt_lun.status == 'available' and
                   tgt_lun.type_thin and
                   tgt_lun.size > src_lun.size):
                    param = {
                        'cap': self._helper._gb2b(tgt_lun.size),
                        'captype': 'bytes'
                    }
                    self._helper.change_lun(tgt_lun.ds_id, param)
            else:
                LOG.info("Clone volume %(tgt)s from volume %(src)s "
                         "in the background.",
                         {'src': src_lun.ds_id, 'tgt': tgt_lun.ds_id})
                tgt_lun.metadata['flashcopy'] = "started"
                eventlet.spawn(self._wait_flashcopy, [src_lun], [tgt_lun])
        finally:
            if not tgt_lun.async_clone and tgt_lun.status == 'error':
                self._helper.delete_lun(tgt_lun)
        return tgt_lun

    def _wait_flashcopy(self, src_luns, tgt_luns):
        # please note that the order of volumes should be fixed.
        self._helper.wait_flashcopy_finished(src_luns, tgt_luns)
        for src_lun, tgt_lun in zip(src_luns, tgt_luns):
            if tgt_lun.status == 'available':
                tgt_lun.volume.metadata['flashcopy'] = 'success'
            elif tgt_lun.status == 'error':
                tgt_lun.volume.metadata['flashcopy'] = "error"
                tgt_lun.volume.metadata['error_msg'] = (
                    "FlashCopy from source volume %(src)s to target volume "
                    "%(tgt)s fails, the state of target volume %(id)s is set "
                    "to error." % {'src': src_lun.ds_id,
                                   'tgt': tgt_lun.ds_id,
                                   'id': tgt_lun.os_id})
                tgt_lun.volume.status = 'error'
                self._helper.delete_lun(tgt_lun)
            else:
                self._helper.delete_lun(tgt_lun)
                raise exception.VolumeDriverException(
                    message=_("Volume %(id)s is in unexpected state "
                              "%(state)s.") % {'id': tgt_lun.ds_id,
                                               'state': tgt_lun.status})
            tgt_lun.volume.save()

    def _ensure_vol_not_fc_target(self, vol_hex_id):
        for cp in self._helper.get_flashcopy(vol_hex_id):
            if cp['targetvolume']['id'] == vol_hex_id:
                raise restclient.APIException(
                    data=(_('Volume %s is currently a target of another '
                            'FlashCopy operation') % vol_hex_id))

    def _create_replica_helper(self, lun):
        if not lun.pool_lss_pair.get('target'):
            lun = self._replication.establish_replication(lun, True)
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
                raise exception.VolumeDriverException(
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
        lun = Lun(volume)
        if lun.type_replication:
            raise exception.VolumeDriverException(
                message=_('Driver does not support migrate replicated '
                          'volume, it can be done via retype.'))
        stats = self.meta['stat']
        if backend['capabilities']['vendor_name'] != stats['vendor_name']:
            raise exception.VolumeDriverException(_(
                'source and destination vendors differ.'))
        if backend['capabilities']['serial_number'] != stats['serial_number']:
            raise exception.VolumeDriverException(_(
                'source and destination serial numbers differ.'))
        new_pools = self._helper.get_pools(
            backend['capabilities']['extent_pools'])

        cur_pool_id = self._helper.get_lun_pool(lun.ds_id)['id']
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
        def _check_extra_specs(key, value=None):
            extra_specs = diff.get('extra_specs')
            specific_type = extra_specs.get(key) if extra_specs else None
            old_type = None
            new_type = None
            if specific_type:
                old_type, new_type = specific_type
                if value:
                    old_type = (True if old_type and old_type.upper() == value
                                else False)
                    new_type = (True if new_type and new_type.upper() == value
                                else False)
            return old_type, new_type

        lun = Lun(volume)
        # check user specify pool or lss or not
        old_specified_pool, new_specified_pool = _check_extra_specs(
            'drivers:storage_pool_ids')
        old_specified_lss, new_specified_lss = _check_extra_specs(
            'drivers:storage_lss_ids')

        # check thin or thick
        old_type_thick, new_type_thick = _check_extra_specs(
            'drivers:thin_provision', 'FALSE')

        # check replication capability
        old_type_replication, new_type_replication = _check_extra_specs(
            'replication_enabled', strings.METADATA_IS_TRUE)

        # check multiattach capability
        old_multiattach, new_multiattach = _check_extra_specs(
            'multiattach', strings.METADATA_IS_TRUE)

        # start retype, please note that the order here is important
        # because of rollback problem once failed to retype.
        new_props = {}
        if old_type_thick != new_type_thick:
            new_props['type_thin'] = not new_type_thick

        if (old_specified_pool == new_specified_pool and
           old_specified_lss == new_specified_lss):
            LOG.info("Same pool and lss.")
        elif ((old_specified_pool or old_specified_lss) and
              (new_specified_pool or new_specified_lss)):
            raise exception.VolumeDriverException(
                message=_("Retype does not support to move volume from "
                          "specified pool or lss to another specified "
                          "pool or lss."))
        elif ((old_specified_pool is None and new_specified_pool) or
              (old_specified_lss is None and new_specified_lss)):
            storage_pools = self._helper.get_pools(new_specified_pool)
            self._helper.verify_pools(storage_pools)
            storage_lss = self._helper.verify_lss_ids(new_specified_lss)
            vol_pool = self._helper.get_lun_pool(lun.ds_id)['id']
            vol_lss = lun.ds_id[:2].upper()
            # if old volume is in the specified LSS, but it is needed
            # to be changed from thin to thick or vice versa, driver
            # needs to make sure the new volume will be created in the
            # specified LSS.
            if ((storage_lss and vol_lss not in storage_lss) or
               new_props.get('type_thin')):
                new_props['specified_pool'] = new_specified_pool
                new_props['specified_lss'] = new_specified_lss
            elif vol_pool not in storage_pools.keys():
                vol_node = int(vol_lss, 16) % 2
                new_pool_id = None
                for pool_id, pool in storage_pools.items():
                    if vol_node == pool['node']:
                        new_pool_id = pool_id
                        break
                if new_pool_id:
                    self._helper.change_lun(lun.ds_id, {'pool': new_pool_id})
                else:
                    raise exception.VolumeDriverException(
                        message=_("Can not change the pool volume allocated."))

        new_lun = None
        if new_props:
            new_lun = lun.shallow_copy()
            for key, value in new_props.items():
                setattr(new_lun, key, value)
            self._clone_lun(lun, new_lun)

        volume_update = None
        if new_lun:
            # if new lun meets all requirements of retype successfully,
            # exception happens during clean up can be ignored.
            if new_type_replication:
                new_lun.type_replication = True
                new_lun = self._replication.establish_replication(new_lun,
                                                                  True)
            elif old_type_replication:
                new_lun.type_replication = False
                try:
                    self._replication.delete_replica(lun)
                except Exception:
                    pass
            if new_multiattach:
                new_lun.multiattach = True
            elif old_multiattach:
                new_lun.multiattach = False

            try:
                self._helper.delete_lun(lun)
            except Exception:
                pass
            volume_update = new_lun.update_volume(lun)
        else:
            # if driver does not create new lun, don't delete source
            # lun when failed to enable replication or delete replica.
            if not old_type_replication and new_type_replication:
                lun.type_replication = True
                lun = self._replication.establish_replication(lun)
            elif old_type_replication and not new_type_replication:
                lun = self._replication.delete_replica(lun)
                lun.type_replication = False
            if not old_multiattach and new_multiattach:
                lun.multiattach = True
            elif old_multiattach and not new_multiattach:
                lun.multiattach = False
            volume_update = lun.get_volume_update()
        return True, volume_update

    @proxy._trace_time
    @proxy.logger
    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert volume to snapshot."""
        if snapshot.volume_size != volume.size:
            raise exception.InvalidInput(
                reason=_('Reverting volume is not supported if the volume '
                         'size is not equal to the snapshot size.'))

        vol_lun = Lun(volume)
        snap_lun = Lun(snapshot, is_snapshot=True)
        if vol_lun.type_replication:
            raise exception.VolumeDriverException(
                message=_('Driver does not support revert to snapshot '
                          'of replicated volume.'))

        try:
            self._clone_lun(snap_lun, vol_lun)
        except Exception as err:
            msg = (_("Reverting volume %(vol)s to snapshot %(snap)s failed "
                     "due to: %(err)s.")
                   % {"vol": volume.name, "snap": snapshot.name, "err": err})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    @proxy._trace_time
    @proxy.logger
    def initialize_connection(self, volume, connector, **kwargs):
        """Attach a volume to the host."""
        lun = Lun(volume)
        LOG.info('Attach the volume %s.', lun.ds_id)
        if lun.group and lun.failed_over:
            backend_helper = self._replication.get_target_helper()
        else:
            backend_helper = self._helper
        return backend_helper.initialize_connection(lun.ds_id, connector,
                                                    **kwargs)

    @proxy._trace_time
    @proxy.logger
    def terminate_connection(self, volume, connector, force=False, **kwargs):
        """Detach a volume from a host."""
        ret_info = {
            'driver_volume_type': 'fibre_channel',
            'data': {}
        }
        lun = Lun(volume)
        if (lun.group and lun.failed_over) and not self._active_backend_id:
            backend_helper = self._replication.get_target_helper()
        else:
            backend_helper = self._helper
        if isinstance(backend_helper, helper.DS8KECKDHelper):
            LOG.info('Detach the volume %s.', lun.ds_id)
            return backend_helper.terminate_connection(lun.ds_id, connector,
                                                       force, **kwargs)
        else:
            vol_mapped, host_id, map_info = (
                backend_helper.check_vol_mapped_to_host(connector, lun.ds_id))
            if host_id is None or not vol_mapped:
                if host_id is None and not lun.type_replication:
                    LOG.warning('Failed to find the Host information.')
                    return ret_info
                if host_id and not lun.type_replication and not vol_mapped:
                    LOG.warning("Volume %(vol)s is already not mapped to "
                                "host %(host)s.",
                                {'vol': lun.ds_id, 'host': host_id})
                    return ret_info
                if lun.type_replication:
                    if backend_helper == self._replication.get_target_helper():
                        backend_helper = self._replication.get_source_helper()
                    else:
                        backend_helper = self._replication.get_target_helper()
                    try:
                        if backend_helper.lun_exists(lun.replica_ds_id):
                            LOG.info('Detaching volume %s from the '
                                     'Secondary site.', lun.replica_ds_id)
                            mapped, host_id, map_info = (
                                backend_helper.check_vol_mapped_to_host(
                                    connector, lun.replica_ds_id))
                        else:
                            msg = (_('Failed to find the attached '
                                     'Volume %s.') % lun.ds_id)
                            LOG.error(msg)
                            raise exception.VolumeDriverException(message=msg)
                    except Exception as ex:
                        LOG.warning('Failed to get host mapping for volume '
                                    '%(volume)s in the secondary site. '
                                    'Exception: %(err)s.',
                                    {'volume': lun.replica_ds_id, 'err': ex})
                        return ret_info
                    if not mapped:
                        return ret_info
                    else:
                        LOG.info('Detach the volume %s.', lun.replica_ds_id)
                        return backend_helper.terminate_connection(
                            lun.replica_ds_id, host_id, connector, map_info)
            elif host_id and vol_mapped:
                LOG.info('Detaching volume %s.', lun.ds_id)
                return backend_helper.terminate_connection(lun.ds_id, host_id,
                                                           connector, map_info)

    @proxy.logger
    def create_group(self, ctxt, group):
        """Create consistency group of FlashCopy or RemoteCopy."""
        model_update = {}
        grp = Group(group)
        # verify replication.
        if (grp.group_replication_enabled or
                grp.consisgroup_replication_enabled):
            for volume_type in group.volume_types:
                replication_type = volume_utils.is_replicated_spec(
                    volume_type.extra_specs)
                self._assert(replication_type,
                             'Unable to create group: group %(grp)s '
                             'is for replication type, but volume '
                             '%(vtype)s is a non-replication one.'
                             % {'grp': grp.id, 'vtype': volume_type.id})
            model_update['replication_status'] = (
                fields.ReplicationStatus.ENABLED)
        # verify consistency group.
        if (grp.consisgroup_snapshot_enabled or
                grp.consisgroup_replication_enabled):
            self._assert(self._helper.backend['lss_ids_for_cg'],
                         'No LSS(s) for CG, please make sure you have '
                         'reserved LSS for CG via param lss_range_for_cg.')
            if grp.consisgroup_replication_enabled:
                self._helper.verify_rest_version_for_pprc_cg()
                target_helper = self._replication.get_target_helper()
                target_helper.verify_rest_version_for_pprc_cg()

        # driver will create replication group because base cinder
        # doesn't update replication_status of the group, otherwise
        # base cinder can take over it.
        if (grp.consisgroup_snapshot_enabled or
                grp.consisgroup_replication_enabled or
                grp.group_replication_enabled):
            model_update.update(self._helper.create_group(group))
            return model_update
        else:
            raise NotImplementedError()

    @proxy.logger
    def delete_group(self, ctxt, group, volumes):
        """Delete consistency group and volumes in it."""
        grp = Group(group)
        if grp.consisgroup_snapshot_enabled:
            luns = [Lun(volume) for volume in volumes]
            return self._delete_group_with_lock(group, luns)
        elif grp.consisgroup_replication_enabled:
            self._assert(not grp.failed_over,
                         'Group %s has been failed over, it does '
                         'not support to delete it' % grp.id)
            luns = [Lun(volume) for volume in volumes]
            for lun in luns:
                self._replication.delete_replica(lun)
            return self._delete_group_with_lock(group, luns)
        else:
            raise NotImplementedError()

    @coordination.synchronized('{self.prefix}-consistency-group')
    def _delete_group_with_lock(self, group, luns):
        model_update, volumes_model_update = (
            self._helper.delete_group(group, luns))
        if model_update['status'] == fields.GroupStatus.DELETED:
            self._remove_record_from_consisgroup_cache(group.id)
        return model_update, volumes_model_update

    @proxy.logger
    def delete_group_snapshot(self, ctxt, group_snapshot, snapshots):
        """Delete volume group snapshot."""
        grp = Group(group_snapshot, True)
        if (grp.consisgroup_snapshot_enabled or
                grp.consisgroup_replication_enabled):
            tgt_luns = [Lun(s, is_snapshot=True) for s in snapshots]
            return self._delete_group_snapshot_with_lock(
                group_snapshot, tgt_luns)
        else:
            raise NotImplementedError()

    @coordination.synchronized('{self.prefix}-consistency-group')
    def _delete_group_snapshot_with_lock(self, group_snapshot, tgt_luns):
        model_update, snapshots_model_update = (
            self._helper.delete_group_snapshot(group_snapshot, tgt_luns))
        if model_update['status'] == fields.GroupStatus.DELETED:
            self._remove_record_from_consisgroup_cache(group_snapshot.id)
        return model_update, snapshots_model_update

    @proxy.logger
    def create_group_snapshot(self, ctxt, group_snapshot, snapshots):
        """Create volume group snapshot."""
        tgt_group = Group(group_snapshot, True)
        if (not tgt_group.consisgroup_snapshot_enabled and
                not tgt_group.consisgroup_replication_enabled):
            raise NotImplementedError()

        src_group = Group(group_snapshot.group)
        self._assert(not src_group.failed_over,
                     'Group %s has been failed over, it does not '
                     'support to create group snapshot.' % src_group.id)
        snapshots_model_update = []
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        src_luns = [Lun(snapshot.volume) for snapshot in snapshots]
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
        grp = Group(group)
        if (grp.consisgroup_snapshot_enabled or
                grp.consisgroup_replication_enabled):
            self._assert(not grp.failed_over,
                         'Group %s has been failed over, it does not '
                         'support to update it.' % grp.id)
            return self._update_consisgroup(grp, add_volumes, remove_volumes)
        else:
            raise NotImplementedError()

    def _update_consisgroup(self, grp, add_volumes, remove_volumes):
        add_volumes_update = []
        if add_volumes:
            add_volumes_update = self._add_volumes_into_consisgroup(
                grp, add_volumes)
        remove_volumes_update = []
        if remove_volumes:
            remove_volumes_update = self._remove_volumes_from_consisgroup(
                grp, add_volumes, remove_volumes)
        return None, add_volumes_update, remove_volumes_update

    @proxy.logger
    def _add_volumes_into_consisgroup(self, grp, add_volumes):
        add_volumes_update = []
        for vol in add_volumes:
            if vol.status == 'in-use':
                msg = (_("add volume %(vol)s into group %(grp)s failed "
                         "since this volume is 'in-use' status")
                       % {'vol': vol.id, 'grp': grp.id})
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
        new_add_luns, old_add_luns = (
            self._clone_lun_for_consisgroup(add_volumes, grp))
        for new_add_lun, old_add_lun in zip(new_add_luns, old_add_luns):
            volume_update = new_add_lun.update_volume(old_add_lun)
            volume_update['id'] = new_add_lun.os_id
            add_volumes_update.append(volume_update)
        return add_volumes_update

    @proxy.logger
    @coordination.synchronized('{self.prefix}-consistency-group')
    def _remove_volumes_from_consisgroup(self, grp, add_volumes,
                                         remove_volumes):
        remove_volumes_update = []
        for vol in remove_volumes:
            if vol.status == 'in-use':
                msg = (_("remove volume %(vol)s from group %(grp)s failed "
                         "since this volume is 'in-use' status")
                       % {'vol': vol.id, 'grp': grp.id})
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
        new_remove_luns, old_remove_luns = (
            self._clone_lun_for_consisgroup(remove_volumes))
        for new_remove_lun, old_remove_lun in zip(new_remove_luns,
                                                  old_remove_luns):
            volume_update = new_remove_lun.update_volume(old_remove_lun)
            volume_update['id'] = new_remove_lun.os_id
            remove_volumes_update.append(volume_update)
        if len(remove_volumes) == len(grp.volumes) + len(add_volumes):
            self._remove_record_from_consisgroup_cache(grp.id)
        return remove_volumes_update

    def _clone_lun_for_consisgroup(self, volumes, grp=None):
        new_luns = []
        old_luns = []
        for volume in volumes:
            old_lun = Lun(volume)
            if old_lun.ds_id:
                new_lun = old_lun.shallow_copy()
                new_lun.group = grp
                self._clone_lun(old_lun, new_lun)
                if old_lun.type_replication:
                    new_lun = self._create_replica_helper(new_lun)
                    old_lun = self._replication.delete_replica(old_lun)
                self._helper.delete_lun(old_lun)
                new_luns.append(new_lun)
                old_luns.append(old_lun)
        return new_luns, old_luns

    @proxy.logger
    def _remove_record_from_consisgroup_cache(self, group_id):
        lss_pairs = self.consisgroup_cache.get(group_id)
        if lss_pairs:
            LOG.debug('Consistecy Group %(id)s owns LSS %(lss)s in the cache.',
                      {'id': group_id, 'lss': lss_pairs})
            self.consisgroup_cache.pop(group_id)

    @proxy._trace_time
    def create_group_from_src(self, ctxt, group, volumes, group_snapshot,
                              sorted_snapshots, source_group,
                              sorted_source_vols):
        """Create volume group from volume group or volume group snapshot."""
        grp = Group(group)
        if (not grp.consisgroup_snapshot_enabled and
                not grp.consisgroup_replication_enabled and
                not grp.group_replication_enabled):
            raise NotImplementedError()

        model_update = {
            'status': fields.GroupStatus.AVAILABLE,
            'replication_status': fields.ReplicationStatus.DISABLED
        }
        if (grp.group_replication_enabled or
                grp.consisgroup_replication_enabled):
            model_update['replication_status'] = (
                fields.ReplicationStatus.ENABLED)
        volumes_model_update = []
        if group_snapshot and sorted_snapshots:
            src_luns = [Lun(snapshot, is_snapshot=True)
                        for snapshot in sorted_snapshots]
        elif source_group and sorted_source_vols:
            src_luns = [Lun(source_vol)
                        for source_vol in sorted_source_vols]
            src_group = Group(source_group)
            self._assert(not src_group.failed_over,
                         'Group %s has been failed over, it does not '
                         'support to create a group from it.' % src_group.id)
        else:
            msg = _("_create_group_from_src supports a group snapshot "
                    "source or a group source, other sources can not "
                    "be used.")
            LOG.error(msg)
            raise exception.InvalidInput(message=msg)

        try:
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
                'status': model_update['status'],
                'replication_status': model_update['replication_status']
            })
            volumes_model_update.append(volume_model_update)

        return model_update, volumes_model_update

    def _clone_group(self, src_luns, tgt_luns):
        for src_lun in src_luns:
            self._ensure_vol_not_fc_target(src_lun.ds_id)
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
            if tgt_lun.group.consisgroup_snapshot_enabled:
                self._do_flashcopy_with_freeze(vol_pairs)
            else:
                self._helper.start_flashcopy(vol_pairs)
            self._helper.wait_flashcopy_finished(src_luns, tgt_luns)
        finally:
            # if one of volume failed, delete all volumes.
            error_luns = [lun for lun in tgt_luns if lun.status == 'error']
            if error_luns:
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
    def failover_host(self, ctxt, volumes, secondary_id, groups=None):
        """Fail over the volume back and forth.

        if secondary_id is 'default', volumes will be failed back,
        otherwize failed over.
        """
        volume_update_list = []
        if secondary_id == strings.PRIMARY_BACKEND_ID:
            if not self._active_backend_id:
                LOG.info("Host has been failed back. doesn't need "
                         "to fail back again.")
                return self._active_backend_id, volume_update_list, []
        else:
            if self._active_backend_id:
                LOG.info("Host has been failed over to %s.",
                         self._active_backend_id)
                return self._active_backend_id, volume_update_list, []

            target_helper = self._replication.get_target_helper()
            if secondary_id is None:
                secondary_id = target_helper.backend['id']
            elif secondary_id != target_helper.backend['id']:
                raise exception.InvalidReplicationTarget(
                    message=(_('Invalid secondary_backend_id specified. '
                               'Valid backend id is %s.')
                             % target_helper.backend['id']))

        LOG.debug("Starting failover host to %s.", secondary_id)
        # all volumes passed to failover_host are replicated.
        replicated_luns = [Lun(volume) for volume in volumes if
                           volume.status in ('available', 'in-use')]
        # volumes in group may have been failed over.
        if secondary_id != strings.PRIMARY_BACKEND_ID:
            failover_luns = [lun for lun in replicated_luns if
                             not lun.failed_over]
        else:
            failover_luns = [lun for lun in replicated_luns if
                             lun.failed_over]
        if failover_luns:
            try:
                if secondary_id != strings.PRIMARY_BACKEND_ID:
                    self._replication.start_host_pprc_failover(
                        failover_luns, secondary_id)
                    self._active_backend_id = secondary_id
                else:
                    self._replication.start_host_pprc_failback(
                        failover_luns, secondary_id)
                    self._active_backend_id = ""
                self._helper = self._replication.get_source_helper()
            except restclient.APIException as e:
                raise exception.UnableToFailOver(
                    reason=(_("Unable to failover host to %(id)s. "
                              "Exception= %(ex)s")
                            % {'id': secondary_id, 'ex': six.text_type(e)}))

            for lun in failover_luns:
                volume_update = lun.get_volume_update()
                # failover_host in base cinder has considered previous status
                # of the volume, it doesn't need to return it for update.
                volume_update['replication_status'] = (
                    fields.ReplicationStatus.FAILED_OVER
                    if self._active_backend_id else
                    fields.ReplicationStatus.ENABLED)
                model_update = {'volume_id': lun.os_id,
                                'updates': volume_update}
                volume_update_list.append(model_update)
        else:
            LOG.info("No volume has replication capability.")
            if secondary_id != strings.PRIMARY_BACKEND_ID:
                LOG.info("Switch to the target %s", secondary_id)
                self._replication.switch_source_and_target_client()
                self._active_backend_id = secondary_id
            else:
                LOG.info("Switch to the primary %s", secondary_id)
                self._replication.switch_source_and_target_client()
                self._active_backend_id = ""

        # No group entity in DS8K, so just need to update replication_status
        # of the group.
        group_update_list = []
        groups = [grp for grp in groups if grp.status == 'available']
        if groups:
            if secondary_id != strings.PRIMARY_BACKEND_ID:
                update_groups = [grp for grp in groups
                                 if grp.replication_status ==
                                 fields.ReplicationStatus.ENABLED]
                repl_status = fields.ReplicationStatus.FAILED_OVER
            else:
                update_groups = [grp for grp in groups
                                 if grp.replication_status ==
                                 fields.ReplicationStatus.FAILED_OVER]
                repl_status = fields.ReplicationStatus.ENABLED
            if update_groups:
                for group in update_groups:
                    group_update = {
                        'group_id': group.id,
                        'updates': {'replication_status': repl_status}
                    }
                    group_update_list.append(group_update)

        return secondary_id, volume_update_list, group_update_list

    def enable_replication(self, context, group, volumes):
        """Resume pprc pairs.

        if user wants to adjust group, he/she does not need to pause/resume
        pprc pairs, here just provide a way to resume replicaiton.
        """
        volumes_model_update = []
        model_update = (
            {'replication_status': fields.ReplicationStatus.ENABLED})
        if volumes:
            luns = [Lun(volume) for volume in volumes]
            try:
                self._replication.enable_replication(luns)
            except restclient.APIException as e:
                msg = (_('Failed to enable replication for group %(id)s, '
                         'Exception: %(ex)s.')
                       % {'id': group.id, 'ex': six.text_type(e)})
                LOG.exception(msg)
                raise exception.VolumeDriverException(message=msg)
            for lun in luns:
                volumes_model_update.append(
                    {'id': lun.os_id,
                     'replication_status': fields.ReplicationStatus.ENABLED})
        return model_update, volumes_model_update

    def disable_replication(self, context, group, volumes):
        """Pause pprc pairs.

        if user wants to adjust group, he/she does not need to pause/resume
        pprc pairs, here just provide a way to pause replicaiton.
        """
        volumes_model_update = []
        model_update = (
            {'replication_status': fields.ReplicationStatus.DISABLED})
        if volumes:
            luns = [Lun(volume) for volume in volumes]
            try:
                self._replication.disable_replication(luns)
            except restclient.APIException as e:
                msg = (_('Failed to disable replication for group %(id)s, '
                         'Exception: %(ex)s.')
                       % {'id': group.id, 'ex': six.text_type(e)})
                LOG.exception(msg)
                raise exception.VolumeDriverException(message=msg)
            for lun in luns:
                volumes_model_update.append(
                    {'id': lun.os_id,
                     'replication_status': fields.ReplicationStatus.DISABLED})
        return model_update, volumes_model_update

    def failover_replication(self, context, group, volumes,
                             secondary_backend_id):
        """Fail over replication for a group and volumes in the group."""
        volumes_model_update = []
        model_update = {}
        luns = [Lun(volume) for volume in volumes]
        if secondary_backend_id == strings.PRIMARY_BACKEND_ID:
            if luns:
                if not luns[0].failed_over:
                    LOG.info("Group %s has been failed back. it doesn't "
                             "need to fail back again.", group.id)
                    return model_update, volumes_model_update
            else:
                return model_update, volumes_model_update
        else:
            target_helper = self._replication.get_target_helper()
            backend_id = target_helper.backend['id']
            if secondary_backend_id is None:
                secondary_backend_id = backend_id
            elif secondary_backend_id != backend_id:
                raise exception.InvalidReplicationTarget(
                    message=(_('Invalid secondary_backend_id %(id)s. '
                               'Valid backend ids are %(ids)s.')
                             % {'id': secondary_backend_id,
                                'ids': (strings.PRIMARY_BACKEND_ID,
                                        backend_id)}))
            if luns:
                if luns[0].failed_over:
                    LOG.info("Group %(grp)s has been failed over to %(id)s.",
                             {'grp': group.id, 'id': backend_id})
                    return model_update, volumes_model_update
            else:
                return model_update, volumes_model_update

        LOG.debug("Starting failover group %(grp)s to %(id)s.",
                  {'grp': group.id, 'id': secondary_backend_id})
        try:
            if secondary_backend_id != strings.PRIMARY_BACKEND_ID:
                self._replication.start_group_pprc_failover(
                    luns, secondary_backend_id)
                model_update['replication_status'] = (
                    fields.ReplicationStatus.FAILED_OVER)
            else:
                self._replication.start_group_pprc_failback(
                    luns, secondary_backend_id)
                model_update['replication_status'] = (
                    fields.ReplicationStatus.ENABLED)
        except restclient.APIException as e:
            raise exception.VolumeDriverException(
                message=(_("Unable to failover group %(grp_id)s to "
                           "backend %(bck_id)s. Exception= %(ex)s")
                         % {'grp_id': group.id,
                            'bck_id': secondary_backend_id,
                            'ex': six.text_type(e)}))

        for lun in luns:
            volume_model_update = lun.get_volume_update()
            # base cinder doesn't consider previous status of the volume
            # in failover_replication, so here returns it for update.
            volume_model_update['replication_status'] = (
                model_update['replication_status'])
            volume_model_update['id'] = lun.os_id
            volumes_model_update.append(volume_model_update)
        return model_update, volumes_model_update

    def get_replication_error_status(self, context, groups):
        """Return error info for replicated groups and its volumes.

        all pprc copy related APIs wait until copy is finished, so it does
        not need to check their status afterwards.
        """
        return [], []
