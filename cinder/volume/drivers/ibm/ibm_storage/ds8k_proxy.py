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
replication_device = backend_id: bar,
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
import json
import six

from oslo_config import cfg
from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _, _LI, _LW, _LE
from cinder.objects import fields
from cinder.utils import synchronized
import cinder.volume.drivers.ibm.ibm_storage as storage
from cinder.volume.drivers.ibm.ibm_storage import ds8k_helper as helper
from cinder.volume.drivers.ibm.ibm_storage \
    import ds8k_replication as replication
from cinder.volume.drivers.ibm.ibm_storage import ds8k_restclient as restclient
from cinder.volume.drivers.ibm.ibm_storage import proxy
from cinder.volume.drivers.ibm.ibm_storage import strings
from cinder.volume import group_types
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
    'os400': '',
    'consistent_group_replication_enabled': False,
    'group_replication_enabled': False,
    'consistent_group_snapshot_enabled': False,
}

ds8k_opts = [
    cfg.StrOpt(
        'ds8k_devadd_unitadd_mapping',
        default='',
        help='Mapping between IODevice address and unit address.'),
    cfg.StrOpt(
        'ds8k_ssid_prefix',
        default='FF',
        help='Set the first two digits of SSID'),
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
            if not self.is_snapshot and self.type_replication:
                self.replica_ds_name = lun.replica_ds_name
                self.replication_driver_data = lun.replication_driver_data
                self.replication_status = lun.replication_status
            self.lss_pair = lun.lss_pair

        def update_volume(self, lun):
            volume_update = lun.get_volume_update()
            volume_update['provider_location'] = six.text_type({
                'vol_hex_id': self.ds_id})
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
            self.ds_id = provider_location[six.text_type('vol_hex_id')]
        else:
            self.ds_id = None
        self.cinder_name = volume.display_name
        self.lss_pair = {}
        self.is_snapshot = is_snapshot
        if self.is_snapshot:
            self.size = volume.volume_size
            # ds8k supports at most 16 chars
            self.ds_name = (
                "OS%s:%s" % ('snap', helper.filter_alnum(self.cinder_name))
            )[:16]
        else:
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
                replica_id = replication_target[six.text_type('vol_hex_id')]
                self.lss_pair = {
                    'source': (None, self.ds_id[0:2]),
                    'target': (None, replica_id[0:2])
                }

        if os400:
            if os400 not in VALID_OS400_VOLUME_TYPES.keys():
                msg = (_("The OS400 volume type provided, %s, is not "
                         "a valid volume type.") % os400)
                raise restclient.APIException(data=msg)
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

    def __init__(self, group):
        gid = group.get('group_type_id')
        specs = group_types.get_group_type_specs(gid) if gid else {}
        self.type_cg_snapshot = specs.get(
            'consistent_group_snapshot_enabled', '<is> %s' %
            EXTRA_SPECS_DEFAULTS['consistent_group_snapshot_enabled']
        ).upper() == strings.METADATA_IS_TRUE


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

    @proxy._trace_time
    def setup(self, ctxt):
        LOG.info(_LI("Initiating connection to IBM DS8K storage system."))
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
            err = (_("Param [connection_type] %s is invalid.")
                   % connection_type)
            raise exception.InvalidParameterValue(err=err)

        if replication_devices:
            self._do_replication_setup(replication_devices, self._helper)

    @proxy.logger
    def _do_replication_setup(self, devices, src_helper):
        if len(devices) >= 2:
            err = _("Param [replication_device] is invalid, Driver "
                    "support only one replication target.")
            raise exception.InvalidParameterValue(err=err)

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
            msg = (_('Backend %s is not initialized.')
                   % self.configuration.volume_backend_name)
            raise exception.CinderException(data=msg)

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
            "consistencygroup_support": True,
            "consistent_group_snapshot_enabled": True,
            "multiattach": True
        }

        if self._replication_enabled:
            stats['replication_enabled'] = self._replication_enabled

        self.meta['stat'] = stats

    def _assert(self, assert_condition, exception_message=''):
        if not assert_condition:
            LOG.error(exception_message)
            raise restclient.APIException(data=exception_message)

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
        excluded_lss = []
        while True:
            try:
                if lun.type_replication and not lun.is_snapshot:
                    lun.lss_pair = self._replication.find_available_lss_pair(
                        excluded_lss)
                else:
                    lun.lss_pair['source'] = self._helper.find_available_lss(
                        pool, find_new_pid, excluded_lss)
                return self._helper.create_lun(lun)
            except restclient.LssFullException:
                msg = _LW("LSS %s is full, find another one.")
                LOG.warning(msg, lun.lss_pair['source'][1])
                excluded_lss.append(lun.lss_pair['source'][1])

    @proxy.logger
    def _clone_lun(self, src_lun, tgt_lun):
        self._assert(src_lun.size <= tgt_lun.size,
                     _('Target volume should be bigger or equal '
                       'to the Source volume in size.'))
        self._ensure_vol_not_fc_target(src_lun.ds_id)
        # volume ID of src_lun and tgt_lun will be the same one if tgt_lun is
        # image-volume, because _clone_image_volume in manager.py does not pop
        # the provider_location.
        if (tgt_lun.ds_id is None) or (src_lun.ds_id == tgt_lun.ds_id):
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
                msg = (_('Volume %s is currently a target of another '
                         'FlashCopy operation') % vol_hex_id)
                raise restclient.APIException(data=msg)

    @proxy._trace_time
    def create_volume(self, volume):
        lun = self._create_lun_helper(Lun(volume))
        if lun.type_replication:
            lun = self._replication.create_replica(lun)
        return lun.get_volume_update()

    @proxy._trace_time
    def create_cloned_volume(self, target_vol, source_vol):
        lun = self._clone_lun(Lun(source_vol), Lun(target_vol))
        if lun.type_replication:
            lun = self._replication.create_replica(lun)
        return lun.get_volume_update()

    @proxy._trace_time
    def create_volume_from_snapshot(self, volume, snapshot):
        lun = self._clone_lun(Lun(snapshot, is_snapshot=True), Lun(volume))
        if lun.type_replication:
            lun = self._replication.create_replica(lun)
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
                msg = (_("The volume %s has been failed over, it is "
                         "not suggested to extend it.") % lun.ds_id)
                raise exception.CinderException(data=msg)
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
                    msg = (_("The volume %s is in replication relationship, "
                             "it is not supported to retype from thin to "
                             "thick or vice versus.") % lun.ds_id)
                    raise exception.CinderException(msg)
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

    @synchronized('OpenStackCinderIBMDS8KMutexConnect-', external=True)
    @proxy._trace_time
    @proxy.logger
    def initialize_connection(self, volume, connector, **kwargs):
        """Attach a volume to the host."""
        vol_id = Lun(volume).ds_id
        LOG.info(_LI('Attach the volume %s.'), vol_id)
        return self._helper.initialize_connection(vol_id, connector, **kwargs)

    @synchronized('OpenStackCinderIBMDS8KMutexConnect-', external=True)
    @proxy._trace_time
    @proxy.logger
    def terminate_connection(self, volume, connector, force=False, **kwargs):
        """Detach a volume from a host."""
        vol_id = Lun(volume).ds_id
        LOG.info(_LI('Detach the volume %s.'), vol_id)
        return self._helper.terminate_connection(vol_id, connector,
                                                 force, **kwargs)

    @proxy.logger
    def create_consistencygroup(self, ctxt, group):
        """Create a consistency group."""
        return self._helper.create_group(ctxt, group)

    @proxy.logger
    def delete_consistencygroup(self, ctxt, group, volumes):
        """Delete a consistency group."""
        luns = [Lun(volume) for volume in volumes]
        return self._helper.delete_group(ctxt, group, luns)

    @proxy._trace_time
    def create_cgsnapshot(self, ctxt, cgsnapshot, snapshots):
        """Create a consistency group snapshot."""
        return self._create_group_snapshot(ctxt, cgsnapshot, snapshots, True)

    def _create_group_snapshot(self, ctxt, cgsnapshot, snapshots,
                               cg_enabled=False):
        snapshots_model_update = []
        model_update = {'status': fields.GroupStatus.AVAILABLE}

        src_luns = [Lun(snapshot['volume']) for snapshot in snapshots]
        tgt_luns = [Lun(snapshot, is_snapshot=True) for snapshot in snapshots]

        try:
            if src_luns and tgt_luns:
                self._clone_group(src_luns, tgt_luns, cg_enabled)
        except restclient.APIException:
            model_update['status'] = fields.GroupStatus.ERROR
            LOG.exception(_LE('Failed to create group snapshot.'))

        for tgt_lun in tgt_luns:
            snapshot_model_update = tgt_lun.get_volume_update()
            snapshot_model_update.update({
                'id': tgt_lun.os_id,
                'status': model_update['status']
            })
            snapshots_model_update.append(snapshot_model_update)

        return model_update, snapshots_model_update

    @proxy._trace_time
    @proxy.logger
    def delete_cgsnapshot(self, ctxt, cgsnapshot, snapshots):
        """Delete a consistency group snapshot."""
        return self._delete_group_snapshot(ctxt, cgsnapshot, snapshots)

    def _delete_group_snapshot(self, ctxt, group_snapshot, snapshots):
        snapshots_model_update = []
        model_update = {'status': fields.GroupStatus.DELETED}

        snapshots = [Lun(s, is_snapshot=True) for s in snapshots]
        if snapshots:
            try:
                self._helper.delete_lun(snapshots)
            except restclient.APIException as e:
                model_update['status'] = fields.GroupStatus.ERROR_DELETING
                LOG.error(_LE("Failed to delete group snapshot. "
                              "Error: %(err)s"),
                          {'err': e})

        for snapshot in snapshots:
            snapshots_model_update.append({
                'id': snapshot.os_id,
                'status': model_update['status']
            })
        return model_update, snapshots_model_update

    @proxy.logger
    def update_consistencygroup(self, ctxt, group,
                                add_volumes, remove_volumes):
        """Add or remove volume(s) to/from an existing consistency group."""
        return self._helper.update_group(ctxt, group,
                                         add_volumes, remove_volumes)

    @proxy._trace_time
    def create_consistencygroup_from_src(self, ctxt, group, volumes,
                                         cgsnapshot, snapshots,
                                         source_cg, sorted_source_vols):
        """Create a consistencygroup from source.

        :param ctxt: the context of the caller.
        :param group: the dictionary of the consistency group to be created.
        :param volumes: a list of volume dictionaries in the group.
        :param cgsnapshot: the dictionary of the cgsnapshot as source.
        :param snapshots: a list of snapshot dictionaries in the cgsnapshot.
        :param source_cg: the dictionary of the consisgroup as source.
        :param sorted_source_vols: a list of volume dictionaries
                                   in the consisgroup.
        :return model_update, volumes_model_update
        """
        return self._create_group_from_src(ctxt, group, volumes, cgsnapshot,
                                           snapshots, source_cg,
                                           sorted_source_vols, True)

    def _create_group_from_src(self, ctxt, group, volumes, cgsnapshot,
                               snapshots, source_cg, sorted_source_vols,
                               cg_enabled=False):
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        volumes_model_update = []

        if cgsnapshot and snapshots:
            src_luns = [Lun(snapshot, is_snapshot=True)
                        for snapshot in snapshots]
        elif source_cg and sorted_source_vols:
            src_luns = [Lun(source_vol)
                        for source_vol in sorted_source_vols]
        else:
            msg = _("_create_group_from_src supports a group snapshot "
                    "source or a group source, other sources can not "
                    "be used.")
            LOG.error(msg)
            raise exception.InvalidInput(message=msg)

        try:
            tgt_luns = [Lun(volume) for volume in volumes]
            if src_luns and tgt_luns:
                self._clone_group(src_luns, tgt_luns, cg_enabled)
        except restclient.APIException:
            model_update['status'] = fields.GroupStatus.ERROR
            msg = _LE("Failed to create group from group snapshot.")
            LOG.exception(msg)

        for tgt_lun in tgt_luns:
            volume_model_update = tgt_lun.get_volume_update()
            volume_model_update.update({
                'id': tgt_lun.os_id,
                'status': model_update['status']
            })
            volumes_model_update.append(volume_model_update)

        return model_update, volumes_model_update

    def _clone_group(self, src_luns, tgt_luns, cg_enabled):
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
            if cg_enabled:
                self._do_flashcopy_with_freeze(vol_pairs)
            else:
                self._helper.start_flashcopy(vol_pairs)
            finished = self._helper.wait_flashcopy_finished(src_luns, tgt_luns)
        finally:
            if not finished:
                self._helper.delete_lun(tgt_luns)

    @synchronized('OpenStackCinderIBMDS8KMutex-CG-', external=True)
    @proxy._trace_time
    def _do_flashcopy_with_freeze(self, vol_pairs):
        # issue flashcopy with freeze
        self._helper.start_flashcopy(vol_pairs, True)
        # unfreeze the LSS where source volumes are in
        lss_ids = list(set(p['source_volume'][0:2] for p in vol_pairs))
        LOG.debug('Unfreezing the LSS: %s', ','.join(lss_ids))
        self._helper.unfreeze_lss(lss_ids)

    @proxy.logger
    def create_group(self, ctxt, group):
        """Create generic volume group."""
        return self._helper.create_group(ctxt, group)

    @proxy.logger
    def delete_group(self, ctxt, group, volumes):
        """Delete group and the volumes in the group."""
        luns = [Lun(volume) for volume in volumes]
        return self._helper.delete_group(ctxt, group, luns)

    @proxy.logger
    def update_group(self, ctxt, group, add_volumes, remove_volumes):
        """Update generic volume group."""
        return self._helper.update_group(ctxt, group,
                                         add_volumes, remove_volumes)

    @proxy.logger
    def create_group_snapshot(self, ctxt, group_snapshot, snapshots):
        """Create volume group snapshot."""
        snapshot_group = Group(group_snapshot)
        cg_enabled = True if snapshot_group.type_cg_snapshot else False
        return self._create_group_snapshot(ctxt, group_snapshot,
                                           snapshots, cg_enabled)

    @proxy.logger
    def delete_group_snapshot(self, ctxt, group_snapshot, snapshots):
        """Delete volume group snapshot."""
        return self._delete_group_snapshot(ctxt, group_snapshot, snapshots)

    @proxy._trace_time
    def create_group_from_src(self, ctxt, group, volumes, group_snapshot,
                              sorted_snapshots, source_group,
                              sorted_source_vols):
        """Create volume group from volume group or volume group snapshot."""
        volume_group = Group(group)
        cg_enabled = True if volume_group.type_cg_snapshot else False
        return self._create_group_from_src(ctxt, group, volumes,
                                           group_snapshot, sorted_snapshots,
                                           source_group, sorted_source_vols,
                                           cg_enabled)

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
                msg = _LI("Host has been failed back. doesn't need "
                          "to fail back again.")
                LOG.info(msg)
                return self._active_backend_id, volume_update_list
        else:
            if self._active_backend_id:
                msg = _LI("Host has been failed over to %s.")
                LOG.info(msg, self._active_backend_id)
                return self._active_backend_id, volume_update_list

            backend_id = self._replication._target_helper.backend['id']
            if secondary_id is None:
                secondary_id = backend_id
            elif secondary_id != backend_id:
                msg = (_('Invalid secondary_backend_id specified. '
                         'Valid backend id is %s.') % backend_id)
                raise exception.InvalidReplicationTarget(message=msg)

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
                msg = (_("Unable to failover host to %(id)s. "
                         "Exception= %(ex)s")
                       % {'id': secondary_id, 'ex': six.text_type(e)})
                raise exception.UnableToFailOver(reason=msg)

            for lun in replicated_luns:
                volume_update = lun.get_volume_update()
                volume_update['replication_status'] = (
                    'failed-over' if self._active_backend_id else 'enabled')
                model_update = {'volume_id': lun.os_id,
                                'updates': volume_update}
                volume_update_list.append(model_update)
        else:
            LOG.info(_LI("No volume has replication capability."))
            if secondary_id != strings.PRIMARY_BACKEND_ID:
                LOG.info(_LI("Switch to the target %s"), secondary_id)
                self._switch_backend_connection(secondary_id)
                self._active_backend_id = secondary_id
            else:
                LOG.info(_LI("Switch to the primary %s"), secondary_id)
                self._switch_backend_connection(self._active_backend_id)
                self._active_backend_id = ""

        return secondary_id, volume_update_list
