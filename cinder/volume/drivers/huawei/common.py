# Copyright (c) 2018 Huawei Technologies Co., Ltd.
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

import collections
import math
import re
import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units
import six

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import fields
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.huawei import constants
from cinder.volume.drivers.huawei import huawei_conf
from cinder.volume.drivers.huawei import huawei_utils
from cinder.volume.drivers.huawei import hypermetro
from cinder.volume.drivers.huawei import replication
from cinder.volume.drivers.huawei import rest_client
from cinder.volume.drivers.huawei import smartx
from cinder.volume import volume_types
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)

huawei_opts = [
    cfg.StrOpt('cinder_huawei_conf_file',
               default='/etc/cinder/cinder_huawei_conf.xml',
               help='The configuration file for the Cinder Huawei driver.'),
    cfg.StrOpt('hypermetro_devices',
               default=None,
               help='The remote device hypermetro will use.'),
    cfg.StrOpt('metro_san_user',
               default=None,
               help='The remote metro device san user.'),
    cfg.StrOpt('metro_san_password',
               default=None,
               secret=True,
               help='The remote metro device san password.'),
    cfg.StrOpt('metro_domain_name',
               default=None,
               help='The remote metro device domain name.'),
    cfg.StrOpt('metro_san_address',
               default=None,
               help='The remote metro device request url.'),
    cfg.StrOpt('metro_storage_pools',
               default=None,
               help='The remote metro device pool names.'),
]

CONF = cfg.CONF
CONF.register_opts(huawei_opts, group=configuration.SHARED_CONF_GROUP)

snap_attrs = ('id', 'volume_id', 'volume', 'provider_location')
Snapshot = collections.namedtuple('Snapshot', snap_attrs)
vol_attrs = ('id', 'lun_type', 'provider_location', 'metadata')
Volume = collections.namedtuple('Volume', vol_attrs)


class HuaweiBaseDriver(driver.VolumeDriver):

    # ThirdPartySytems wiki page
    CI_WIKI_NAME = "Huawei_volume_CI"

    def __init__(self, *args, **kwargs):
        super(HuaweiBaseDriver, self).__init__(*args, **kwargs)

        if not self.configuration:
            msg = _('Configuration is not found.')
            raise exception.InvalidInput(reason=msg)

        self.active_backend_id = kwargs.get('active_backend_id')

        self.configuration.append_config_values(huawei_opts)
        self.huawei_conf = huawei_conf.HuaweiConf(self.configuration)
        self.support_func = None
        self.metro_flag = False
        self.replica = None

    @staticmethod
    def get_driver_options():
        return huawei_opts

    def check_func_support(self, obj_name):
        try:
            self.client._get_object_count(obj_name)
            return True
        except Exception:
            return False

    def get_local_and_remote_dev_conf(self):
        self.loc_dev_conf = {
            'san_address': self.configuration.san_address,
            'san_user': self.configuration.san_user,
            'san_password': self.configuration.san_password,
            'storage_pools': self.configuration.storage_pools,
            'iscsi_info': self.configuration.iscsi_info,
        }

        # Now just support one replication device.
        self.replica_dev_conf = self.configuration.replication

    def get_local_and_remote_client_conf(self):
        if self.active_backend_id:
            return self.replica_dev_conf, self.loc_dev_conf
        else:
            return self.loc_dev_conf, self.replica_dev_conf

    def do_setup(self, context):
        """Instantiate common class and login storage system."""
        # Set huawei private configuration into Configuration object.
        self.huawei_conf.update_config_value()

        self.get_local_and_remote_dev_conf()
        client_conf, replica_client_conf = (
            self.get_local_and_remote_client_conf())

        # init local client
        if not client_conf:
            msg = _('Get active client failed.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        self.client = rest_client.RestClient(self.configuration,
                                             **client_conf)
        self.client.login()

        # init remote client
        metro_san_address = self.configuration.safe_get("metro_san_address")
        metro_san_user = self.configuration.safe_get("metro_san_user")
        metro_san_password = self.configuration.safe_get("metro_san_password")
        if metro_san_address and metro_san_user and metro_san_password:
            metro_san_address = metro_san_address.split(";")
            self.rmt_client = rest_client.RestClient(self.configuration,
                                                     metro_san_address,
                                                     metro_san_user,
                                                     metro_san_password)

            self.rmt_client.login()
            self.metro_flag = True
        else:
            self.metro_flag = False
            LOG.warning("Remote device not configured in cinder.conf")
        # init replication manager
        if replica_client_conf:
            self.replica_client = rest_client.RestClient(self.configuration,
                                                         **replica_client_conf)
            self.replica_client.try_login()
            self.replica = replication.ReplicaPairManager(self.client,
                                                          self.replica_client,
                                                          self.configuration)

    def check_for_setup_error(self):
        pass

    def _get_volume_stats(self, refresh=False):
        """Get volume status and reload huawei config file."""
        self.huawei_conf.update_config_value()
        stats = self.client.update_volume_stats()
        stats = self.update_support_capability(stats)
        backend_name = self.configuration.safe_get('volume_backend_name')
        stats['volume_backend_name'] = backend_name or self.__class__.__name__
        stats['vendor_name'] = 'Huawei'

        if self.replica:
            stats = self.replica.update_replica_capability(stats)
            targets = [self.replica_dev_conf['backend_id']]
            stats['replication_targets'] = targets
            stats['replication_enabled'] = True

        return stats

    def update_support_capability(self, stats):
        for pool in stats['pools']:
            pool['smartpartition'] = (
                self.check_func_support("SMARTCACHEPARTITION"))
            pool['smartcache'] = self.check_func_support("smartcachepool")
            pool['QoS_support'] = self.check_func_support("ioclass")
            pool['splitmirror'] = self.check_func_support("splitmirror")
            pool['luncopy'] = self.check_func_support("luncopy")
            pool['thick_provisioning_support'] = True
            pool['thin_provisioning_support'] = True
            pool['smarttier'] = True
            pool['consistencygroup_support'] = True
            pool['consistent_group_snapshot_enabled'] = True

            if self.configuration.san_product == "Dorado":
                pool['smarttier'] = False
                pool['thick_provisioning_support'] = False

            if self.metro_flag:
                pool['hypermetro'] = self.check_func_support("HyperMetroPair")

            # assign the support function to global parameter.
            self.support_func = pool

        return stats

    def _get_volume_type(self, volume):
        volume_type = None
        type_id = volume.volume_type_id
        if type_id:
            ctxt = context.get_admin_context()
            volume_type = volume_types.get_volume_type(ctxt, type_id)

        return volume_type

    def _get_lun_params(self, volume, opts):
        pool_name = volume_utils.extract_host(volume.host, level='pool')
        params = {
            'TYPE': '11',
            'NAME': huawei_utils.encode_name(volume.id),
            'PARENTTYPE': '216',
            'PARENTID': self.client.get_pool_id(pool_name),
            'DESCRIPTION': volume.name,
            'ALLOCTYPE': opts.get('LUNType', self.configuration.lun_type),
            'CAPACITY': int(volume.size) * constants.CAPACITY_UNIT,
            'READCACHEPOLICY': self.configuration.lun_read_cache_policy,
            'WRITECACHEPOLICY': self.configuration.lun_write_cache_policy,
        }

        if hasattr(self.configuration, 'write_type'):
            params['WRITEPOLICY'] = self.configuration.write_type
        if hasattr(self.configuration, 'prefetch_type'):
            params['PREFETCHPOLICY'] = self.configuration.prefetch_type
        if hasattr(self.configuration, 'prefetch_value'):
            params['PREFETCHVALUE'] = self.configuration.prefetch_value
        if opts.get('policy'):
            params['DATATRANSFERPOLICY'] = opts['policy']

        LOG.info('volume: %(volume)s, lun params: %(params)s.',
                 {'volume': volume.id, 'params': params})
        return params

    def _create_volume(self, lun_params):
        # Create LUN on the array.
        lun_info = self.client.create_lun(lun_params)
        metadata = {'huawei_lun_id': lun_info['ID'],
                    'huawei_lun_wwn': lun_info['WWN']}
        model_update = {'metadata': metadata}

        return lun_info, model_update

    def _create_base_type_volume(self, opts, volume):
        """Create volume and add some base type.

        Base type is the service type which doesn't conflict with the other.
        """
        lun_params = self._get_lun_params(volume, opts)
        lun_info, model_update = self._create_volume(lun_params)
        lun_id = lun_info['ID']

        try:
            if opts.get('qos'):
                smartqos = smartx.SmartQos(self.client)
                smartqos.add(opts['qos'], lun_id)

            if opts.get('smartpartition'):
                smartpartition = smartx.SmartPartition(self.client)
                smartpartition.add(opts['partitionname'], lun_id)

            if opts.get('smartcache'):
                smartcache = smartx.SmartCache(self.client)
                smartcache.add(opts['cachename'], lun_id)
        except Exception as err:
            self._delete_lun_with_check(lun_id)
            msg = _('Create volume error. Because %s.') % six.text_type(err)
            raise exception.VolumeBackendAPIException(data=msg)

        return lun_params, lun_info, model_update

    def _add_extend_type_to_volume(self, opts, lun_params, lun_info,
                                   model_update):
        """Add the extend type.

        Extend type is the service type which may conflict with the other.
        So add it after those services.
        """
        lun_id = lun_info['ID']
        if opts.get('hypermetro'):
            metro = hypermetro.HuaweiHyperMetro(self.client,
                                                self.rmt_client,
                                                self.configuration)
            try:
                metro_info = metro.create_hypermetro(lun_id, lun_params)
                model_update['metadata'].update(metro_info)
            except exception.VolumeBackendAPIException as err:
                LOG.error('Create hypermetro error: %s.', err)
                self._delete_lun_with_check(lun_id)
                raise

        if opts.get('replication_enabled'):
            replica_model = opts.get('replication_type')
            try:
                replica_info = self.replica.create_replica(lun_info,
                                                           replica_model)
                model_update.update(replica_info)
            except Exception:
                LOG.exception('Create replication volume error.')
                self._delete_lun_with_check(lun_id)
                raise

        return model_update

    def create_volume(self, volume):
        """Create a volume."""
        opts = huawei_utils.get_volume_params(volume)
        if opts.get('hypermetro') and opts.get('replication_enabled'):
            err_msg = _("Hypermetro and Replication can not be "
                        "used in the same volume_type.")
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        lun_params, lun_info, model_update = self._create_base_type_volume(
            opts, volume)

        model_update = self._add_extend_type_to_volume(opts, lun_params,
                                                       lun_info, model_update)

        model_update['provider_location'] = huawei_utils.to_string(
            **model_update.pop('metadata'))

        return model_update

    def _delete_volume(self, volume):
        lun_info = huawei_utils.get_lun_info(self.client, volume)
        if not lun_info:
            return

        lun_id = lun_info['ID']
        lun_group_ids = self.client.get_lungroupids_by_lunid(lun_id)
        if lun_group_ids and len(lun_group_ids) == 1:
            self.client.remove_lun_from_lungroup(lun_group_ids[0], lun_id)

        self.client.delete_lun(lun_id)

    def delete_volume(self, volume):
        """Delete a volume.

        Three steps:
        Firstly, remove associate from lungroup.
        Secondly, remove associate from QoS policy.
        Thirdly, remove the lun.
        """
        lun_id = self._check_volume_exist_on_array(
            volume, constants.VOLUME_NOT_EXISTS_WARN)
        if not lun_id:
            return

        if self.support_func.get('QoS_support'):
            qos_id = self.client.get_qosid_by_lunid(lun_id)
            if qos_id:
                smart_qos = smartx.SmartQos(self.client)
                smart_qos.remove(qos_id, lun_id)

        metadata = huawei_utils.get_volume_private_data(volume)
        if metadata.get('hypermetro_id'):
            metro = hypermetro.HuaweiHyperMetro(self.client,
                                                self.rmt_client,
                                                self.configuration)
            try:
                metro.delete_hypermetro(volume)
            except exception.VolumeBackendAPIException as err:
                LOG.error('Delete hypermetro error: %s.', err)
                # We have checked the LUN WWN above,
                # no need to check again here.
                self._delete_volume(volume)
                raise

        # Delete a replication volume
        replica_data = volume.replication_driver_data
        if replica_data:
            try:
                self.replica.delete_replica(volume)
            except exception.VolumeBackendAPIException:
                with excutils.save_and_reraise_exception():
                    LOG.exception("Delete replication error.")
                    self._delete_volume(volume)

        self._delete_volume(volume)

    def _delete_lun_with_check(self, lun_id, lun_wwn=None):
        if not lun_id:
            return

        if self.client.check_lun_exist(lun_id, lun_wwn):
            if self.support_func.get('QoS_support'):
                qos_id = self.client.get_qosid_by_lunid(lun_id)
                if qos_id:
                    smart_qos = smartx.SmartQos(self.client)
                    smart_qos.remove(qos_id, lun_id)

            self.client.delete_lun(lun_id)

    def _is_lun_migration_complete(self, src_id, dst_id):
        result = self.client.get_lun_migration_task()
        found_migration_task = False
        if 'data' not in result:
            return False

        for item in result['data']:
            if (src_id == item['PARENTID'] and dst_id == item['TARGETLUNID']):
                found_migration_task = True
                if constants.MIGRATION_COMPLETE == item['RUNNINGSTATUS']:
                    return True
                if constants.MIGRATION_FAULT == item['RUNNINGSTATUS']:
                    msg = _("Lun migration error.")
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

        if not found_migration_task:
            err_msg = _("Cannot find migration task.")
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        return False

    def _is_lun_migration_exist(self, src_id, dst_id):
        try:
            result = self.client.get_lun_migration_task()
        except Exception:
            LOG.error("Get LUN migration error.")
            return False

        if 'data' in result:
            for item in result['data']:
                if (src_id == item['PARENTID']
                        and dst_id == item['TARGETLUNID']):
                    return True
        return False

    def _migrate_lun(self, src_id, dst_id):
        try:
            self.client.create_lun_migration(src_id, dst_id)

            def _is_lun_migration_complete():
                return self._is_lun_migration_complete(src_id, dst_id)

            wait_interval = constants.MIGRATION_WAIT_INTERVAL
            huawei_utils.wait_for_condition(_is_lun_migration_complete,
                                            wait_interval,
                                            self.configuration.lun_timeout)
        # Clean up if migration failed.
        except Exception as ex:
            raise exception.VolumeBackendAPIException(data=ex)
        finally:
            if self._is_lun_migration_exist(src_id, dst_id):
                self.client.delete_lun_migration(src_id, dst_id)
            self._delete_lun_with_check(dst_id)

        LOG.debug("Migrate lun %s successfully.", src_id)
        return True

    def _wait_volume_ready(self, lun_id):
        wait_interval = self.configuration.lun_ready_wait_interval

        def _volume_ready():
            result = self.client.get_lun_info(lun_id)
            if (result['HEALTHSTATUS'] == constants.STATUS_HEALTH
               and result['RUNNINGSTATUS'] == constants.STATUS_VOLUME_READY):
                return True
            return False

        huawei_utils.wait_for_condition(_volume_ready,
                                        wait_interval,
                                        wait_interval * 10)

    def _get_original_status(self, volume):
        return 'in-use' if volume.volume_attachment else 'available'

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status=None):
        orig_lun_name = huawei_utils.encode_name(volume.id)
        new_lun_info = huawei_utils.get_lun_info(
            self.client, new_volume)
        if not new_lun_info:
            msg = _("Volume %s doesn't exist.") % volume.id
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        new_lun_id = new_lun_info['ID']
        new_metadata = huawei_utils.get_volume_private_data(new_volume)
        model_update = {
            'provider_location': huawei_utils.to_string(**new_metadata),
        }

        try:
            self.client.rename_lun(new_lun_id, orig_lun_name)
        except exception.VolumeBackendAPIException:
            LOG.error('Unable to rename lun %s on array.', new_lun_id)
            model_update['_name_id'] = new_volume.name_id
        else:
            LOG.debug("Renamed lun %(id)s to %(name)s successfully.",
                      {'id': new_lun_id,
                       'name': orig_lun_name})
            model_update['_name_id'] = None

        return model_update

    def migrate_volume(self, ctxt, volume, host):
        """Migrate a volume within the same array."""
        self._check_volume_exist_on_array(volume,
                                          constants.VOLUME_NOT_EXISTS_RAISE)

        # NOTE(jlc): Replication volume can't migrate. But retype
        # can remove replication relationship first then do migrate.
        # So don't add this judgement into _check_migration_valid().
        opts = huawei_utils.get_volume_params(volume)
        if opts.get('replication_enabled'):
            return (False, None)

        return self._migrate_volume(volume, host)

    def _check_migration_valid(self, host, volume):
        if 'pool_name' not in host['capabilities']:
            return False

        target_device = host['capabilities']['location_info']

        # Source and destination should be on same array.
        if target_device != self.client.device_id:
            return False

        # Same protocol should be used if volume is in-use.
        protocol = self.configuration.san_protocol
        if (host['capabilities']['storage_protocol'] != protocol
                and self._get_original_status(volume) == 'in-use'):
            return False

        pool_name = host['capabilities']['pool_name']
        if len(pool_name) == 0:
            return False

        return True

    def _migrate_volume(self, volume, host, new_type=None):
        if not self._check_migration_valid(host, volume):
            return (False, None)

        pool_name = host['capabilities']['pool_name']
        pools = self.client.get_all_pools()
        pool_info = self.client.get_pool_info(pool_name, pools)
        dst_volume_name = six.text_type(uuid.uuid4())

        lun_info = huawei_utils.get_lun_info(self.client, volume)
        if not lun_info:
            msg = _("Volume %s doesn't exist.") % volume.id
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        src_id = lun_info['ID']

        if new_type:
            # If new type exists, use new type.
            opts = huawei_utils.get_volume_type_params(new_type)
        else:
            opts = huawei_utils.get_volume_params(volume)

        if opts['policy']:
            policy = opts['policy']
        else:
            policy = lun_info.get('DATATRANSFERPOLICY',
                                  self.configuration.lun_policy)

        lun_params = {
            'NAME': huawei_utils.encode_name(dst_volume_name),
            'PARENTID': pool_info['ID'],
            'DESCRIPTION': lun_info['DESCRIPTION'],
            'ALLOCTYPE': opts.get('LUNType', lun_info['ALLOCTYPE']),
            'CAPACITY': lun_info['CAPACITY'],
            'WRITEPOLICY': lun_info['WRITEPOLICY'],
            'PREFETCHPOLICY': lun_info['PREFETCHPOLICY'],
            'PREFETCHVALUE': lun_info['PREFETCHVALUE'],
            'DATATRANSFERPOLICY': policy,
            'READCACHEPOLICY': lun_info.get(
                'READCACHEPOLICY',
                self.configuration.lun_read_cache_policy),
            'WRITECACHEPOLICY': lun_info.get(
                'WRITECACHEPOLICY',
                self.configuration.lun_write_cache_policy),
            'OWNINGCONTROLLER': lun_info['OWNINGCONTROLLER'], }

        for item in lun_params:
            if lun_params.get(item) == '--':
                del lun_params[item]

        lun_info = self.client.create_lun(lun_params)
        lun_id = lun_info['ID']

        if opts.get('qos'):
            SmartQos = smartx.SmartQos(self.client)
            SmartQos.add(opts['qos'], lun_id)
        if opts.get('smartpartition'):
            smartpartition = smartx.SmartPartition(self.client)
            smartpartition.add(opts['partitionname'], lun_id)
        if opts.get('smartcache'):
            smartcache = smartx.SmartCache(self.client)
            smartcache.add(opts['cachename'], lun_id)

        dst_id = lun_info['ID']
        self._wait_volume_ready(dst_id)
        moved = self._migrate_lun(src_id, dst_id)

        return moved, {}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot.

        We use LUNcopy to copy a new volume from snapshot.
        The time needed increases as volume size does.
        """
        opts = huawei_utils.get_volume_params(volume)
        if opts.get('hypermetro') and opts.get('replication_enabled'):
            msg = _("Hypermetro and Replication can not be "
                    "used in the same volume_type.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        snapshot_info = huawei_utils.get_snapshot_info(self.client, snapshot)
        if not snapshot_info:
            msg = _('create_volume_from_snapshot: Snapshot %(name)s '
                    'does not exist.') % {'name': snapshot.id}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        snapshot_id = snapshot_info['ID']

        lun_params, lun_info, model_update = self._create_base_type_volume(
            opts, volume)

        tgt_lun_id = lun_info['ID']
        luncopy_name = huawei_utils.encode_name(volume.id)
        LOG.info(
            'create_volume_from_snapshot: src_lun_id: %(src_lun_id)s, '
            'tgt_lun_id: %(tgt_lun_id)s, copy_name: %(copy_name)s.',
            {'src_lun_id': snapshot_id,
             'tgt_lun_id': tgt_lun_id,
             'copy_name': luncopy_name})

        wait_interval = self.configuration.lun_ready_wait_interval

        def _volume_ready():
            result = self.client.get_lun_info(tgt_lun_id)

            if (result['HEALTHSTATUS'] == constants.STATUS_HEALTH
               and result['RUNNINGSTATUS'] == constants.STATUS_VOLUME_READY):
                return True
            return False

        huawei_utils.wait_for_condition(_volume_ready,
                                        wait_interval,
                                        wait_interval * 10)

        self._copy_volume(volume, luncopy_name,
                          snapshot_id, tgt_lun_id)

        # NOTE(jlc): Actually, we just only support replication here right
        # now, not hypermetro.
        model_update = self._add_extend_type_to_volume(opts, lun_params,
                                                       lun_info, model_update)
        model_update['provider_location'] = huawei_utils.to_string(
            **model_update.pop('metadata'))

        return model_update

    def create_cloned_volume(self, volume, src_vref):
        """Clone a new volume from an existing volume."""
        self._check_volume_exist_on_array(src_vref,
                                          constants.VOLUME_NOT_EXISTS_RAISE)

        # Form the snapshot structure.
        snapshot = Snapshot(id=uuid.uuid4().__str__(),
                            volume_id=src_vref.id,
                            volume=src_vref,
                            provider_location=None)

        # Create snapshot.
        self.create_snapshot(snapshot)

        try:
            # Create volume from snapshot.
            model_update = self.create_volume_from_snapshot(volume, snapshot)
        finally:
            try:
                # Delete snapshot.
                self.delete_snapshot(snapshot)
            except exception.VolumeBackendAPIException:
                LOG.warning(
                    'Failure deleting the snapshot %(snapshot_id)s '
                    'of volume %(volume_id)s.',
                    {'snapshot_id': snapshot.id,
                     'volume_id': src_vref.id},)

        return model_update

    def _check_volume_exist_on_array(self, volume, action):
        """Check whether the volume exists on the array.

        If the volume exists on the array, return the LUN ID.
        If not exists, raise or log warning.
        """
        lun_info = huawei_utils.get_lun_info(self.client, volume)
        if not lun_info:
            msg = _("Volume %s does not exist on the array.") % volume.id
            if action == constants.VOLUME_NOT_EXISTS_WARN:
                LOG.warning(msg)
            if action == constants.VOLUME_NOT_EXISTS_RAISE:
                raise exception.VolumeBackendAPIException(data=msg)
            return

        return lun_info['ID']

    def extend_volume(self, volume, new_size):
        """Extend a volume."""
        lun_id = self._check_volume_exist_on_array(
            volume, constants.VOLUME_NOT_EXISTS_RAISE)

        opts = huawei_utils.get_volume_params(volume)
        if opts.get('replication_enabled'):
            msg = (_("Can't extend replication volume, volume: %(id)s") %
                   {"id": volume.id})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        lun_info = self.client.get_lun_info(lun_id)
        old_size = int(lun_info.get('CAPACITY'))

        new_size = int(new_size) * units.Gi / 512

        if new_size == old_size:
            LOG.info("New size is equal to the real size from backend"
                     " storage, no need to extend."
                     " realsize: %(oldsize)s, newsize: %(newsize)s.",
                     {'oldsize': old_size,
                      'newsize': new_size})
            return
        if new_size < old_size:
            msg = (_("New size should be bigger than the real size from "
                     "backend storage."
                     " realsize: %(oldsize)s, newsize: %(newsize)s."),
                   {'oldsize': old_size,
                    'newsize': new_size})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.info('Extend volume: %(id)s, oldsize: %(oldsize)s, '
                 'newsize: %(newsize)s.',
                 {'id': volume.id,
                  'oldsize': old_size,
                  'newsize': new_size})

        self.client.extend_lun(lun_id, new_size)

    def _create_snapshot_base(self, snapshot):
        lun_info = huawei_utils.get_lun_info(self.client, snapshot.volume)
        if not lun_info:
            msg = _("Parent volume of snapshot %s doesn't exist."
                    ) % snapshot.id
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        snapshot_name = huawei_utils.encode_name(snapshot.id)
        snapshot_description = snapshot.id
        snapshot_info = self.client.create_snapshot(lun_info['ID'],
                                                    snapshot_name,
                                                    snapshot_description)
        snapshot_id = snapshot_info['ID']
        return snapshot_id

    def create_snapshot(self, snapshot):
        snapshot_id = self._create_snapshot_base(snapshot)
        try:
            self.client.activate_snapshot(snapshot_id)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Active snapshot %s failed, now deleting it.",
                          snapshot_id)
                self.client.delete_snapshot(snapshot_id)

        snapshot_info = self.client.get_snapshot_info(snapshot_id)
        location = huawei_utils.to_string(
            huawei_snapshot_id=snapshot_id,
            huawei_snapshot_wwn=snapshot_info['WWN'])
        return {'provider_location': location}

    def delete_snapshot(self, snapshot):
        LOG.info('Delete snapshot %s.', snapshot.id)

        snapshot_info = huawei_utils.get_snapshot_info(self.client, snapshot)
        if snapshot_info:
            self.client.stop_snapshot(snapshot_info['ID'])
            self.client.delete_snapshot(snapshot_info['ID'])
        else:
            LOG.warning("Can't find snapshot on the array.")

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        LOG.debug("Enter retype: id=%(id)s, new_type=%(new_type)s, "
                  "diff=%(diff)s, host=%(host)s.", {'id': volume.id,
                                                    'new_type': new_type,
                                                    'diff': diff,
                                                    'host': host})
        self._check_volume_exist_on_array(
            volume, constants.VOLUME_NOT_EXISTS_RAISE)

        # Check what changes are needed
        migration, change_opts, lun_id = self.determine_changes_when_retype(
            volume, new_type, host)

        model_update = {}
        replica_enabled_change = change_opts.get('replication_enabled')
        replica_type_change = change_opts.get('replication_type')
        if replica_enabled_change and replica_enabled_change[0]:
            try:
                self.replica.delete_replica(volume)
                model_update.update({'replication_status': 'disabled',
                                     'replication_driver_data': None})
            except exception.VolumeBackendAPIException:
                LOG.exception('Retype volume error. '
                              'Delete replication failed.')
                return False

        try:
            if migration:
                LOG.debug("Begin to migrate LUN(id: %(lun_id)s) with "
                          "change %(change_opts)s.",
                          {"lun_id": lun_id, "change_opts": change_opts})
                if not self._migrate_volume(volume, host, new_type):
                    LOG.warning("Storage-assisted migration failed during "
                                "retype.")
                    return False
            else:
                # Modify lun to change policy
                self.modify_lun(lun_id, change_opts)
        except exception.VolumeBackendAPIException:
            LOG.exception('Retype volume error.')
            return False

        if replica_enabled_change and replica_enabled_change[1]:
            try:
                # If replica_enabled_change is not None, the
                # replica_type_change won't be None. See function
                # determine_changes_when_retype.
                lun_info = self.client.get_lun_info(lun_id)
                replica_info = self.replica.create_replica(
                    lun_info, replica_type_change[1])
                model_update.update(replica_info)
            except exception.VolumeBackendAPIException:
                LOG.exception('Retype volume error. '
                              'Create replication failed.')
                return False

        return (True, model_update)

    def modify_lun(self, lun_id, change_opts):
        if change_opts.get('partitionid'):
            old, new = change_opts['partitionid']
            old_id = old[0]
            old_name = old[1]
            new_id = new[0]
            new_name = new[1]
            if old_id:
                self.client.remove_lun_from_partition(lun_id, old_id)
            if new_id:
                self.client.add_lun_to_partition(lun_id, new_id)
            LOG.info("Retype LUN(id: %(lun_id)s) smartpartition from "
                     "(name: %(old_name)s, id: %(old_id)s) to "
                     "(name: %(new_name)s, id: %(new_id)s) success.",
                     {"lun_id": lun_id,
                      "old_id": old_id, "old_name": old_name,
                      "new_id": new_id, "new_name": new_name})

        if change_opts.get('cacheid'):
            old, new = change_opts['cacheid']
            old_id = old[0]
            old_name = old[1]
            new_id = new[0]
            new_name = new[1]
            if old_id:
                self.client.remove_lun_from_cache(lun_id, old_id)
            if new_id:
                self.client.add_lun_to_cache(lun_id, new_id)
            LOG.info("Retype LUN(id: %(lun_id)s) smartcache from "
                     "(name: %(old_name)s, id: %(old_id)s) to "
                     "(name: %(new_name)s, id: %(new_id)s) successfully.",
                     {'lun_id': lun_id,
                      'old_id': old_id, "old_name": old_name,
                      'new_id': new_id, "new_name": new_name})

        if change_opts.get('policy'):
            old_policy, new_policy = change_opts['policy']
            self.client.change_lun_smarttier(lun_id, new_policy)
            LOG.info("Retype LUN(id: %(lun_id)s) smarttier policy from "
                     "%(old_policy)s to %(new_policy)s success.",
                     {'lun_id': lun_id,
                      'old_policy': old_policy,
                      'new_policy': new_policy})

        if change_opts.get('qos'):
            old_qos, new_qos = change_opts['qos']
            old_qos_id = old_qos[0]
            old_qos_value = old_qos[1]
            if old_qos_id:
                smart_qos = smartx.SmartQos(self.client)
                smart_qos.remove(old_qos_id, lun_id)
            if new_qos:
                smart_qos = smartx.SmartQos(self.client)
                smart_qos.add(new_qos, lun_id)
            LOG.info("Retype LUN(id: %(lun_id)s) smartqos from "
                     "%(old_qos_value)s to %(new_qos)s success.",
                     {'lun_id': lun_id,
                      'old_qos_value': old_qos_value,
                      'new_qos': new_qos})

    def get_lun_specs(self, lun_id):
        lun_opts = {
            'policy': None,
            'partitionid': None,
            'cacheid': None,
            'LUNType': None,
        }

        lun_info = self.client.get_lun_info(lun_id)
        lun_opts['LUNType'] = int(lun_info['ALLOCTYPE'])
        if lun_info.get('DATATRANSFERPOLICY'):
            lun_opts['policy'] = lun_info['DATATRANSFERPOLICY']
        if lun_info.get('SMARTCACHEPARTITIONID'):
            lun_opts['cacheid'] = lun_info['SMARTCACHEPARTITIONID']
        if lun_info.get('CACHEPARTITIONID'):
            lun_opts['partitionid'] = lun_info['CACHEPARTITIONID']

        return lun_opts

    def _check_capability_support(self, new_opts, new_type):
        new_cache_name = new_opts['cachename']
        if new_cache_name:
            if not self.support_func.get('smartcache'):
                msg = (_(
                    "Can't support cache on the array, cache name is: "
                    "%(name)s.") % {'name': new_cache_name})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        new_partition_name = new_opts['partitionname']
        if new_partition_name:
            if not self.support_func.get('smartpartition'):
                msg = (_(
                    "Can't support partition on the array, partition name is: "
                    "%(name)s.") % {'name': new_partition_name})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        if new_opts['policy']:
            if (not self.support_func.get('smarttier')
                    and new_opts['policy'] != '0'):
                msg = (_("Can't support tier on the array."))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        if new_opts['qos']:
            if not self.support_func.get('QoS_support'):
                msg = (_("Can't support qos on the array."))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def _check_needed_changes(self, lun_id, old_opts, new_opts, change_opts):
        new_cache_id = None
        new_cache_name = new_opts['cachename']
        if new_cache_name:
            if self.support_func.get('smartcache'):
                new_cache_id = self.client.get_cache_id_by_name(
                    new_cache_name)
            if new_cache_id is None:
                msg = (_(
                    "Can't find cache name on the array, cache name is: "
                    "%(name)s.") % {'name': new_cache_name})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        new_partition_id = None
        new_partition_name = new_opts['partitionname']
        if new_partition_name:
            if self.support_func.get('smartpartition'):
                new_partition_id = self.client.get_partition_id_by_name(
                    new_partition_name)
            if new_partition_id is None:
                msg = (_(
                    "Can't find partition name on the array, partition name "
                    "is: %(name)s.") % {'name': new_partition_name})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        # smarttier
        if old_opts['policy'] != new_opts['policy']:
            if not (old_opts['policy'] == '--'
                    and new_opts['policy'] is None):
                change_opts['policy'] = (old_opts['policy'],
                                         new_opts['policy'])

        # smartcache
        old_cache_id = old_opts['cacheid']
        if old_cache_id == '--':
            old_cache_id = None
        if old_cache_id != new_cache_id:
            old_cache_name = None
            if self.support_func.get('smartcache'):
                if old_cache_id:
                    cache_info = self.client.get_cache_info_by_id(
                        old_cache_id)
                    old_cache_name = cache_info['NAME']
            change_opts['cacheid'] = ([old_cache_id, old_cache_name],
                                      [new_cache_id, new_cache_name])

        # smartpartition
        old_partition_id = old_opts['partitionid']
        if old_partition_id == '--':
            old_partition_id = None
        if old_partition_id != new_partition_id:
            old_partition_name = None
            if self.support_func.get('smartpartition'):
                if old_partition_id:
                    partition_info = self.client.get_partition_info_by_id(
                        old_partition_id)
                    old_partition_name = partition_info['NAME']

            change_opts['partitionid'] = ([old_partition_id,
                                           old_partition_name],
                                          [new_partition_id,
                                           new_partition_name])

        # smartqos
        new_qos = new_opts.get('qos')
        if not self.support_func.get('QoS_support'):
            if new_qos:
                msg = (_("Can't support qos on the array."))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        else:
            old_qos_id = self.client.get_qosid_by_lunid(lun_id)
            old_qos = self._get_qos_specs_from_array(old_qos_id)
            if old_qos != new_qos:
                change_opts['qos'] = ([old_qos_id, old_qos], new_qos)

        return change_opts

    def determine_changes_when_retype(self, volume, new_type, host):
        migration = False
        change_opts = {
            'policy': None,
            'partitionid': None,
            'cacheid': None,
            'qos': None,
            'host': None,
            'LUNType': None,
            'replication_enabled': None,
            'replication_type': None,
        }

        lun_info = huawei_utils.get_lun_info(self.client, volume)
        if not lun_info:
            msg = _("Volume %s doesn't exist.") % volume.id
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        lun_id = lun_info['ID']
        old_opts = self.get_lun_specs(lun_id)

        new_opts = huawei_utils.get_volume_type_params(new_type)

        if 'LUNType' not in new_opts:
            new_opts['LUNType'] = self.configuration.lun_type

        if volume.host != host['host']:
            migration = True
            change_opts['host'] = (volume.host, host['host'])
        if old_opts['LUNType'] != new_opts['LUNType']:
            migration = True
            change_opts['LUNType'] = (old_opts['LUNType'], new_opts['LUNType'])

        volume_opts = huawei_utils.get_volume_params(volume)
        if (volume_opts['replication_enabled'] or
                new_opts['replication_enabled']):
            # If replication_enabled changes,
            # then replication_type in change_opts will be set.
            change_opts['replication_enabled'] = (
                volume_opts['replication_enabled'],
                new_opts['replication_enabled'])

            change_opts['replication_type'] = (volume_opts['replication_type'],
                                               new_opts['replication_type'])

        change_opts = self._check_needed_changes(lun_id, old_opts, new_opts,
                                                 change_opts)

        LOG.debug("Determine changes when retype. Migration: "
                  "%(migration)s, change_opts: %(change_opts)s.",
                  {'migration': migration, 'change_opts': change_opts})
        return migration, change_opts, lun_id

    def _get_qos_specs_from_array(self, qos_id):
        qos = {}
        qos_info = {}
        if qos_id:
            qos_info = self.client.get_qos_info(qos_id)

        for key, value in qos_info.items():
            key = key.upper()
            if key in constants.QOS_KEYS:
                if key == 'LATENCY' and value == '0':
                    continue
                else:
                    qos[key] = value
        return qos

    def create_export(self, context, volume, connector):
        """Export a volume."""
        pass

    def ensure_export(self, context, volume):
        """Synchronously recreate an export for a volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a volume."""
        pass

    def create_export_snapshot(self, context, snapshot, connector):
        """Export a snapshot."""
        pass

    def remove_export_snapshot(self, context, snapshot):
        """Remove an export for a snapshot."""
        pass

    def _copy_volume(self, volume, copy_name, src_lun, tgt_lun):
        metadata = huawei_utils.get_volume_metadata(volume)
        copyspeed = metadata.get('copyspeed')
        luncopy_id = self.client.create_luncopy(copy_name,
                                                src_lun,
                                                tgt_lun,
                                                copyspeed)
        wait_interval = self.configuration.lun_copy_wait_interval

        try:
            self.client.start_luncopy(luncopy_id)

            def _luncopy_complete():
                luncopy_info = self.client.get_luncopy_info(luncopy_id)
                if luncopy_info['status'] == constants.STATUS_LUNCOPY_READY:
                    # luncopy_info['status'] means for the running status of
                    # the luncopy. If luncopy_info['status'] is equal to '40',
                    # this luncopy is completely ready.
                    return True
                elif luncopy_info['state'] != constants.STATUS_HEALTH:
                    # luncopy_info['state'] means for the healthy status of the
                    # luncopy. If luncopy_info['state'] is not equal to '1',
                    # this means that an error occurred during the LUNcopy
                    # operation and we should abort it.
                    err_msg = (_(
                        'An error occurred during the LUNcopy operation. '
                        'LUNcopy name: %(luncopyname)s. '
                        'LUNcopy status: %(luncopystatus)s. '
                        'LUNcopy state: %(luncopystate)s.')
                        % {'luncopyname': luncopy_id,
                           'luncopystatus': luncopy_info['status'],
                           'luncopystate': luncopy_info['state']},)
                    LOG.error(err_msg)
                    raise exception.VolumeBackendAPIException(data=err_msg)
            huawei_utils.wait_for_condition(_luncopy_complete,
                                            wait_interval,
                                            self.configuration.lun_timeout)

        except Exception:
            with excutils.save_and_reraise_exception():
                self.client.delete_luncopy(luncopy_id)
                self.delete_volume(volume)

        self.client.delete_luncopy(luncopy_id)

    def _check_lun_valid_for_manage(self, lun_info, external_ref):
        lun_id = lun_info.get('ID')
        lun_name = lun_info.get('NAME')

        # Check whether the LUN is already in LUN group.
        if lun_info.get('ISADD2LUNGROUP') == 'true':
            msg = (_("Can't import LUN %s to Cinder. Already exists in a LUN "
                     "group.") % lun_id)
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

        # Check whether the LUN is Normal.
        if lun_info.get('HEALTHSTATUS') != constants.STATUS_HEALTH:
            msg = _("Can't import LUN %s to Cinder. LUN status is not "
                    "normal.") % lun_id
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

        # Check whether the LUN exists in a HyperMetroPair.
        if self.support_func.get('hypermetro'):
            try:
                hypermetro_pairs = self.client.get_hypermetro_pairs()
            except exception.VolumeBackendAPIException:
                hypermetro_pairs = []
                LOG.debug("Can't get hypermetro info, pass the check.")

            for pair in hypermetro_pairs:
                if pair.get('LOCALOBJID') == lun_id:
                    msg = (_("Can't import LUN %s to Cinder. Already exists "
                             "in a HyperMetroPair.") % lun_id)
                    raise exception.ManageExistingInvalidReference(
                        existing_ref=external_ref, reason=msg)

        # Check whether the LUN exists in a SplitMirror.
        if self.support_func.get('splitmirror'):
            try:
                split_mirrors = self.client.get_split_mirrors()
            except exception.VolumeBackendAPIException as ex:
                if re.search('License is unavailable', ex.msg):
                    # Can't check whether the LUN has SplitMirror with it,
                    # just pass the check and log it.
                    split_mirrors = []
                    LOG.warning('No license for SplitMirror.')
                else:
                    msg = _("Failed to get SplitMirror.")
                    raise exception.VolumeBackendAPIException(data=msg)

            for mirror in split_mirrors:
                try:
                    target_luns = self.client.get_target_luns(mirror.get('ID'))
                except exception.VolumeBackendAPIException:
                    msg = _("Failed to get target LUN of SplitMirror.")
                    raise exception.VolumeBackendAPIException(data=msg)

                if ((mirror.get('PRILUNID') == lun_id)
                        or (lun_id in target_luns)):
                    msg = (_("Can't import LUN %s to Cinder. Already exists "
                             "in a SplitMirror.") % lun_id)
                    raise exception.ManageExistingInvalidReference(
                        existing_ref=external_ref, reason=msg)

        # Check whether the LUN exists in a migration task.
        try:
            migration_tasks = self.client.get_migration_task()
        except exception.VolumeBackendAPIException as ex:
            if re.search('License is unavailable', ex.msg):
                # Can't check whether the LUN has migration task with it,
                # just pass the check and log it.
                migration_tasks = []
                LOG.warning('No license for migration.')
            else:
                msg = _("Failed to get migration task.")
                raise exception.VolumeBackendAPIException(data=msg)

        for migration in migration_tasks:
            if lun_id in (migration.get('PARENTID'),
                          migration.get('TARGETLUNID')):
                msg = (_("Can't import LUN %s to Cinder. Already exists in a "
                         "migration task.") % lun_id)
                raise exception.ManageExistingInvalidReference(
                    existing_ref=external_ref, reason=msg)

        # Check whether the LUN exists in a LUN copy task.
        if self.support_func.get('luncopy'):
            lun_copy = lun_info.get('LUNCOPYIDS')
            if lun_copy and lun_copy[1:-1]:
                msg = (_("Can't import LUN %s to Cinder. Already exists in "
                         "a LUN copy task.") % lun_id)
                raise exception.ManageExistingInvalidReference(
                    existing_ref=external_ref, reason=msg)

        # Check whether the LUN exists in a remote replication task.
        rmt_replication = lun_info.get('REMOTEREPLICATIONIDS')
        if rmt_replication and rmt_replication[1:-1]:
            msg = (_("Can't import LUN %s to Cinder. Already exists in "
                     "a remote replication task.") % lun_id)
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

        # Check whether the LUN exists in a LUN mirror.
        if self.client.is_lun_in_mirror(lun_name):
            msg = (_("Can't import LUN %s to Cinder. Already exists in "
                     "a LUN mirror.") % lun_name)
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

    def manage_existing(self, volume, external_ref):
        """Manage an existing volume on the backend storage."""
        # Check whether the LUN is belonged to the specified pool.
        pool = volume_utils.extract_host(volume.host, 'pool')
        LOG.debug("Pool specified is: %s.", pool)
        lun_info = self._get_lun_info_by_ref(external_ref)
        lun_id = lun_info.get('ID')
        description = lun_info.get('DESCRIPTION', '')
        if len(description) <= (
                constants.MAX_VOL_DESCRIPTION - len(volume.name) - 1):
            description = volume.name + ' ' + description

        lun_pool = lun_info.get('PARENTNAME')
        LOG.debug("Storage pool of existing LUN %(lun)s is %(pool)s.",
                  {"lun": lun_id, "pool": lun_pool})
        if pool != lun_pool:
            msg = (_("The specified LUN does not belong to the given "
                     "pool: %s.") % pool)
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

        # Check other stuffs to determine whether this LUN can be imported.
        self._check_lun_valid_for_manage(lun_info, external_ref)
        type_id = volume.volume_type_id
        new_opts = None
        if type_id:
            # Handle volume type if specified.
            old_opts = self.get_lun_specs(lun_id)
            volume_type = volume_types.get_volume_type(None, type_id)
            new_opts = huawei_utils.get_volume_type_params(volume_type)
            if ('LUNType' in new_opts and
                    old_opts['LUNType'] != new_opts['LUNType']):
                msg = (_("Can't import LUN %(lun_id)s to Cinder. "
                         "LUN type mismatched.") % lun_id)
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)
            if volume_type:
                self._check_capability_support(new_opts, volume_type)

                change_opts = {'policy': None, 'partitionid': None,
                               'cacheid': None, 'qos': None}

                change_opts = self._check_needed_changes(
                    lun_id, old_opts, new_opts, change_opts)
                self.modify_lun(lun_id, change_opts)

        # Rename the LUN to make it manageable for Cinder.
        new_name = huawei_utils.encode_name(volume.id)
        LOG.debug("Rename LUN %(old_name)s to %(new_name)s.",
                  {'old_name': lun_info.get('NAME'),
                   'new_name': new_name})
        self.client.rename_lun(lun_id, new_name, description)

        location = huawei_utils.to_string(huawei_lun_id=lun_id,
                                          huawei_lun_wwn=lun_info['WWN'])
        model_update = {'provider_location': location}

        if new_opts and new_opts.get('replication_enabled'):
            LOG.debug("Manage volume need to create replication.")
            try:
                lun_info = self.client.get_lun_info(lun_id)
                replica_info = self.replica.create_replica(
                    lun_info, new_opts.get('replication_type'))
                model_update.update(replica_info)
            except exception.VolumeBackendAPIException:
                with excutils.save_and_reraise_exception():
                    LOG.exception("Manage exist volume failed.")

        return model_update

    def _get_lun_info_by_ref(self, external_ref):
        LOG.debug("Get external_ref: %s", external_ref)
        name = external_ref.get('source-name')
        id = external_ref.get('source-id')
        if not (name or id):
            msg = _('Must specify source-name or source-id.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

        lun_id = id or self.client.get_lun_id_by_name(name)
        if not lun_id:
            msg = _("Can't find LUN on the array, please check the "
                    "source-name or source-id.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

        lun_info = self.client.get_lun_info(lun_id)
        return lun_info

    def unmanage(self, volume):
        """Export Huawei volume from Cinder."""
        LOG.debug("Unmanage volume: %s.", volume.id)

    def manage_existing_get_size(self, volume, external_ref):
        """Get the size of the existing volume."""
        lun_info = self._get_lun_info_by_ref(external_ref)
        size = int(math.ceil(float(lun_info.get('CAPACITY')) /
                             constants.CAPACITY_UNIT))
        return size

    def _check_snapshot_valid_for_manage(self, snapshot_info, external_ref):
        snapshot_id = snapshot_info.get('ID')

        # Check whether the snapshot is normal.
        if snapshot_info.get('HEALTHSTATUS') != constants.STATUS_HEALTH:
            msg = _("Can't import snapshot %s to Cinder. "
                    "Snapshot status is not normal"
                    " or running status is not online.") % snapshot_id
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

        if snapshot_info.get('EXPOSEDTOINITIATOR') != 'false':
            msg = _("Can't import snapshot %s to Cinder. "
                    "Snapshot is exposed to initiator.") % snapshot_id
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

    def _get_snapshot_info_by_ref(self, external_ref):
        LOG.debug("Get snapshot external_ref: %s.", external_ref)
        name = external_ref.get('source-name')
        id = external_ref.get('source-id')
        if not (name or id):
            msg = _('Must specify snapshot source-name or source-id.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

        snapshot_id = id or self.client.get_snapshot_id_by_name(name)
        if not snapshot_id:
            msg = _("Can't find snapshot on array, please check the "
                    "source-name or source-id.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

        snapshot_info = self.client.get_snapshot_info(snapshot_id)
        return snapshot_info

    def manage_existing_snapshot(self, snapshot, existing_ref):
        snapshot_info = self._get_snapshot_info_by_ref(existing_ref)
        snapshot_id = snapshot_info.get('ID')

        parent_lun_info = huawei_utils.get_lun_info(
            self.client, snapshot.volume)
        if (not parent_lun_info or
                parent_lun_info['ID'] != snapshot_info.get('PARENTID')):
            msg = (_("Can't import snapshot %s to Cinder. "
                     "Snapshot doesn't belong to volume."), snapshot_id)
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=msg)

        # Check whether this snapshot can be imported.
        self._check_snapshot_valid_for_manage(snapshot_info, existing_ref)

        # Rename the snapshot to make it manageable for Cinder.
        description = snapshot.id
        snapshot_name = huawei_utils.encode_name(snapshot.id)
        self.client.rename_snapshot(snapshot_id, snapshot_name, description)
        if snapshot_info.get('RUNNINGSTATUS') != constants.STATUS_ACTIVE:
            self.client.activate_snapshot(snapshot_id)

        LOG.debug("Rename snapshot %(old_name)s to %(new_name)s.",
                  {'old_name': snapshot_info.get('NAME'),
                   'new_name': snapshot_name})

        location = huawei_utils.to_string(huawei_snapshot_id=snapshot_id)
        return {'provider_location': location}

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Get the size of the existing snapshot."""
        snapshot_info = self._get_snapshot_info_by_ref(existing_ref)
        size = int(math.ceil(float(snapshot_info.get('USERCAPACITY')) /
                             constants.CAPACITY_UNIT))
        return size

    def unmanage_snapshot(self, snapshot):
        """Unmanage the specified snapshot from Cinder management."""
        LOG.debug("Unmanage snapshot: %s.", snapshot.id)

    def remove_host_with_check(self, host_id):
        wwns_in_host = (
            self.client.get_host_fc_initiators(host_id))
        iqns_in_host = (
            self.client.get_host_iscsi_initiators(host_id))
        if not (wwns_in_host or iqns_in_host or
           self.client.is_host_associated_to_hostgroup(host_id)):
            self.client.remove_host(host_id)

    def _get_group_type(self, group):
        opts = []
        for vol_type in group.volume_types:
            opts.append(huawei_utils.get_volume_type_params(vol_type))

        return opts

    def _check_group_type_support(self, opts, vol_type):
        if not opts:
            return False

        for opt in opts:
            if opt.get(vol_type) == 'true':
                return True

        return False

    def _get_group_type_value(self, opts, vol_type):
        if not opts:
            return

        for opt in opts:
            if vol_type in opt:
                return opt[vol_type]

    def create_group(self, context, group):
        """Creates a group."""
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        model_update = {'status': fields.GroupStatus.AVAILABLE}
        opts = self._get_group_type(group)

        if self._check_group_type_support(opts, 'hypermetro'):
            if not self.check_func_support("HyperMetro_ConsistentGroup"):
                msg = _("Can't create consistency group, array does not "
                        "support hypermetro consistentgroup, "
                        "group id: %(group_id)s."
                        ) % {"group_id": group.id}
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            metro = hypermetro.HuaweiHyperMetro(self.client,
                                                self.rmt_client,
                                                self.configuration)
            metro.create_consistencygroup(group)
            return model_update

        return model_update

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        model_update = self.create_group(context, group)
        volumes_model_update = []
        delete_snapshots = False

        if not snapshots and source_vols:
            snapshots = []
            for src_vol in source_vols:
                vol_kwargs = {
                    'id': src_vol.id,
                    'provider_location': src_vol.provider_location,
                }
                snapshot_kwargs = {'id': six.text_type(uuid.uuid4()),
                                   'volume': objects.Volume(**vol_kwargs)}
                snapshot = objects.Snapshot(**snapshot_kwargs)
                snapshots.append(snapshot)

            snapshots_model_update = self._create_group_snapshot(snapshots)
            for i, model in enumerate(snapshots_model_update):
                snapshot = snapshots[i]
                snapshot.provider_location = model['provider_location']

            delete_snapshots = True

        if snapshots:
            for i, vol in enumerate(volumes):
                snapshot = snapshots[i]
                vol_model_update = self.create_volume_from_snapshot(
                    vol, snapshot)
                vol_model_update.update({'id': vol.id})
                volumes_model_update.append(vol_model_update)

        if delete_snapshots:
            self._delete_group_snapshot(snapshots)

        return model_update, volumes_model_update

    def delete_group(self, context, group, volumes):
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        opts = self._get_group_type(group)
        model_update = {'status': fields.GroupStatus.DELETED}
        volumes_model_update = []

        if self._check_group_type_support(opts, 'hypermetro'):
            metro = hypermetro.HuaweiHyperMetro(self.client,
                                                self.rmt_client,
                                                self.configuration)
            metro.delete_consistencygroup(context, group, volumes)

        for volume in volumes:
            volume_model_update = {'id': volume.id}
            try:
                self.delete_volume(volume)
            except Exception:
                LOG.exception('Delete volume %s failed.', volume)
                volume_model_update.update({'status': 'error_deleting'})
            else:
                volume_model_update.update({'status': 'deleted'})

            volumes_model_update.append(volume_model_update)

        return model_update, volumes_model_update

    def update_group(self, context, group,
                     add_volumes=None, remove_volumes=None):
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        model_update = {'status': fields.GroupStatus.AVAILABLE}
        opts = self._get_group_type(group)
        if self._check_group_type_support(opts, 'hypermetro'):
            metro = hypermetro.HuaweiHyperMetro(self.client,
                                                self.rmt_client,
                                                self.configuration)
            metro.update_consistencygroup(context, group,
                                          add_volumes,
                                          remove_volumes)
            return model_update, None, None

        for volume in add_volumes:
            self._check_volume_exist_on_array(
                volume, constants.VOLUME_NOT_EXISTS_RAISE)

        return model_update, None, None

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Create group snapshot."""
        if not volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()

        LOG.info('Create group snapshot for group: %(group_id)s',
                 {'group_id': group_snapshot.group_id})

        snapshots_model_update = self._create_group_snapshot(snapshots)
        model_update = {'status': fields.GroupSnapshotStatus.AVAILABLE}
        return model_update, snapshots_model_update

    def _create_group_snapshot(self, snapshots):
        snapshots_model_update = []
        added_snapshots_info = []

        try:
            for snapshot in snapshots:
                snapshot_id = self._create_snapshot_base(snapshot)
                info = self.client.get_snapshot_info(snapshot_id)
                location = huawei_utils.to_string(
                    huawei_snapshot_id=info['ID'],
                    huawei_snapshot_wwn=info['WWN'])
                snapshot_model_update = {
                    'id': snapshot.id,
                    'status': fields.SnapshotStatus.AVAILABLE,
                    'provider_location': location,
                }
                snapshots_model_update.append(snapshot_model_update)
                added_snapshots_info.append(info)
        except Exception:
            with excutils.save_and_reraise_exception():
                for added_snapshot in added_snapshots_info:
                    self.client.delete_snapshot(added_snapshot['ID'])

        snapshot_ids = [added_snapshot['ID']
                        for added_snapshot in added_snapshots_info]
        try:
            self.client.activate_snapshot(snapshot_ids)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Active group snapshots %s failed.", snapshot_ids)
                for snapshot_id in snapshot_ids:
                    self.client.delete_snapshot(snapshot_id)

        return snapshots_model_update

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Delete group snapshot."""
        if not volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()

        LOG.info('Delete group snapshot %(snap_id)s for group: '
                 '%(group_id)s',
                 {'snap_id': group_snapshot.id,
                  'group_id': group_snapshot.group_id})

        try:
            snapshots_model_update = self._delete_group_snapshot(snapshots)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Delete group snapshots failed. "
                          "Group snapshot id: %s", group_snapshot.id)

        model_update = {'status': fields.GroupSnapshotStatus.DELETED}
        return model_update, snapshots_model_update

    def _delete_group_snapshot(self, snapshots):
        snapshots_model_update = []
        for snapshot in snapshots:
            self.delete_snapshot(snapshot)
            snapshot_model_update = {
                'id': snapshot.id,
                'status': fields.SnapshotStatus.DELETED
            }
            snapshots_model_update.append(snapshot_model_update)

        return snapshots_model_update

    def _classify_volume(self, volumes):
        normal_volumes = []
        replica_volumes = []

        for v in volumes:
            opts = huawei_utils.get_volume_params(v)
            if opts.get('replication_enabled'):
                replica_volumes.append(v)
            else:
                normal_volumes.append(v)

        return normal_volumes, replica_volumes

    def _failback_normal_volumes(self, volumes):
        volumes_update = []
        for v in volumes:
            v_update = {}
            v_update['volume_id'] = v.id
            metadata = huawei_utils.get_volume_metadata(v)
            old_status = 'available'
            if 'old_status' in metadata:
                old_status = metadata.pop('old_status')
            v_update['updates'] = {'status': old_status,
                                   'metadata': metadata}
            volumes_update.append(v_update)

        return volumes_update

    def _failback(self, volumes):
        if self.active_backend_id in ('', None):
            return 'default', []

        normal_volumes, replica_volumes = self._classify_volume(volumes)
        volumes_update = []

        replica_volumes_update = self.replica.failback(replica_volumes)
        volumes_update.extend(replica_volumes_update)

        normal_volumes_update = self._failback_normal_volumes(normal_volumes)
        volumes_update.extend(normal_volumes_update)

        self.active_backend_id = ""
        secondary_id = 'default'

        # Switch array connection.
        self.client, self.replica_client = self.replica_client, self.client
        self.replica = replication.ReplicaPairManager(self.client,
                                                      self.replica_client,
                                                      self.configuration)
        return secondary_id, volumes_update

    def _failover_normal_volumes(self, volumes):
        volumes_update = []

        for v in volumes:
            v_update = {}
            v_update['volume_id'] = v.id
            metadata = huawei_utils.get_volume_metadata(v)
            metadata.update({'old_status': v.status})
            v_update['updates'] = {'status': 'error',
                                   'metadata': metadata}
            volumes_update.append(v_update)

        return volumes_update

    def _failover(self, volumes):
        if self.active_backend_id not in ('', None):
            return self.replica_dev_conf['backend_id'], []

        normal_volumes, replica_volumes = self._classify_volume(volumes)
        volumes_update = []

        replica_volumes_update = self.replica.failover(replica_volumes)
        volumes_update.extend(replica_volumes_update)

        normal_volumes_update = self._failover_normal_volumes(normal_volumes)
        volumes_update.extend(normal_volumes_update)

        self.active_backend_id = self.replica_dev_conf['backend_id']
        secondary_id = self.active_backend_id

        # Switch array connection.
        self.client, self.replica_client = self.replica_client, self.client
        self.replica = replication.ReplicaPairManager(self.client,
                                                      self.replica_client,
                                                      self.configuration)
        return secondary_id, volumes_update

    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Failover all volumes to secondary."""
        if secondary_id == 'default':
            secondary_id, volumes_update = self._failback(volumes)
        elif (secondary_id == self.replica_dev_conf['backend_id']
                or secondary_id is None):
            secondary_id, volumes_update = self._failover(volumes)
        else:
            msg = _("Invalid secondary id %s.") % secondary_id
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return secondary_id, volumes_update, []

    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        """Map a snapshot to a host and return target iSCSI information."""
        # From the volume structure.
        volume = Volume(id=snapshot.id,
                        provider_location=snapshot.provider_location,
                        lun_type=constants.SNAPSHOT_TYPE,
                        metadata=None)

        return self.initialize_connection(volume, connector)

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        """Delete map between a snapshot and a host."""
        # From the volume structure.
        volume = Volume(id=snapshot.id,
                        provider_location=snapshot.provider_location,
                        lun_type=constants.SNAPSHOT_TYPE,
                        metadata=None)

        return self.terminate_connection(volume, connector)

    def get_lun_id_and_type(self, volume):
        if hasattr(volume, 'lun_type'):
            metadata = huawei_utils.get_snapshot_private_data(volume)
            lun_id = metadata['huawei_snapshot_id']
            lun_type = constants.SNAPSHOT_TYPE
        else:
            lun_id = self._check_volume_exist_on_array(
                volume, constants.VOLUME_NOT_EXISTS_RAISE)
            lun_type = constants.LUN_TYPE

        return lun_id, lun_type
