# Copyright (c) 2015 Huawei Technologies Co., Ltd.
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
import six
import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.huawei import constants
from cinder.volume.drivers.huawei import fc_zone_helper
from cinder.volume.drivers.huawei import huawei_utils
from cinder.volume.drivers.huawei import hypermetro
from cinder.volume.drivers.huawei import rest_client
from cinder.volume.drivers.huawei import smartx
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)

huawei_opts = [
    cfg.StrOpt('cinder_huawei_conf_file',
               default='/etc/cinder/cinder_huawei_conf.xml',
               help='The configuration file for the Cinder Huawei driver.'),
    cfg.StrOpt('hypermetro_devices',
               help='The remote device hypermetro will use.'),
]

CONF = cfg.CONF
CONF.register_opts(huawei_opts)


class HuaweiBaseDriver(driver.VolumeDriver):

    def __init__(self, *args, **kwargs):
        super(HuaweiBaseDriver, self).__init__(*args, **kwargs)
        self.configuration = kwargs.get('configuration')
        if not self.configuration:
            msg = _('_instantiate_driver: configuration not found.')
            raise exception.InvalidInput(reason=msg)

        self.configuration.append_config_values(huawei_opts)
        self.xml_file_path = self.configuration.cinder_huawei_conf_file
        self.hypermetro_devices = self.configuration.hypermetro_devices

    def do_setup(self, context):
        """Instantiate common class and login storage system."""
        self.restclient = rest_client.RestClient(self.configuration)
        return self.restclient.login()

    def check_for_setup_error(self):
        """Check configuration file."""
        return huawei_utils.check_conf_file(self.xml_file_path)

    def get_volume_stats(self, refresh=False):
        """Get volume status."""
        return self.restclient.update_volume_stats()

    @utils.synchronized('huawei', external=True)
    def create_volume(self, volume):
        """Create a volume."""
        opts = huawei_utils.get_volume_params(volume)
        smartx_opts = smartx.SmartX().get_smartx_specs_opts(opts)
        params = huawei_utils.get_lun_params(self.xml_file_path,
                                             smartx_opts)
        pool_name = volume_utils.extract_host(volume['host'],
                                              level='pool')
        pools = self.restclient.find_all_pools()
        pool_info = self.restclient.find_pool_info(pool_name, pools)
        if not pool_info:
            # The following code is to keep compatibility with old version of
            # Huawei driver.
            pool_names = huawei_utils.get_pools(self.xml_file_path)
            for pool_name in pool_names.split(";"):
                pool_info = self.restclient.find_pool_info(pool_name,
                                                           pools)
                if pool_info:
                    break

        volume_name = huawei_utils.encode_name(volume['id'])
        volume_description = volume['name']
        volume_size = huawei_utils.get_volume_size(volume)

        LOG.info(_LI(
            'Create volume: %(volume)s, size: %(size)s.'),
            {'volume': volume_name,
             'size': volume_size})

        params['pool_id'] = pool_info['ID']
        params['volume_size'] = volume_size
        params['volume_description'] = volume_description

        # Prepare LUN parameters.
        lun_param = huawei_utils.init_lun_parameters(volume_name, params)

        # Create LUN on the array.
        lun_info = self.restclient.create_volume(lun_param)
        lun_id = lun_info['ID']

        try:
            qos = huawei_utils.get_volume_qos(volume)
            if qos:
                smart_qos = smartx.SmartQos(self.restclient)
                smart_qos.create_qos(qos, lun_id)
            smartpartition = smartx.SmartPartition(self.restclient)
            smartpartition.add(opts, lun_id)

            smartcache = smartx.SmartCache(self.restclient)
            smartcache.add(opts, lun_id)
        except Exception as err:
            self._delete_lun_with_check(lun_id)
            raise exception.InvalidInput(
                reason=_('Create volume error. Because %s.') % err)

        # Update the metadata.
        LOG.info(_LI('Create volume option: %s.'), opts)
        metadata = huawei_utils.get_volume_metadata(volume)
        if opts.get('hypermetro'):
            hyperm = hypermetro.HuaweiHyperMetro(self.restclient, None,
                                                 self.configuration)
            try:
                metro_id, remote_lun_id = hyperm.create_hypermetro(lun_id,
                                                                   lun_param)
            except exception.VolumeBackendAPIException as err:
                LOG.exception(_LE('Create hypermetro error: %s.'), err)
                self._delete_lun_with_check(lun_id)
                raise

            LOG.info(_LI("Hypermetro id: %(metro_id)s. "
                         "Remote lun id: %(remote_lun_id)s."),
                     {'metro_id': metro_id,
                      'remote_lun_id': remote_lun_id})

            metadata.update({'hypermetro_id': metro_id,
                             'remote_lun_id': remote_lun_id})

        return {'provider_location': lun_id,
                'ID': lun_id,
                'metadata': metadata}

    @utils.synchronized('huawei', external=True)
    def delete_volume(self, volume):
        """Delete a volume.

        Three steps:
        Firstly, remove associate from lungroup.
        Secondly, remove associate from QoS policy.
        Thirdly, remove the lun.
        """
        name = huawei_utils.encode_name(volume['id'])
        lun_id = volume.get('provider_location')
        LOG.info(_LI('Delete volume: %(name)s, array lun id: %(lun_id)s.'),
                 {'name': name, 'lun_id': lun_id},)
        if lun_id:
            if self.restclient.check_lun_exist(lun_id):
                qos_id = self.restclient.get_qosid_by_lunid(lun_id)
                if qos_id:
                    self.remove_qos_lun(lun_id, qos_id)

                metadata = huawei_utils.get_volume_metadata(volume)
                if 'hypermetro_id' in metadata:
                    hyperm = hypermetro.HuaweiHyperMetro(self.restclient, None,
                                                         self.configuration)
                    try:
                        hyperm.delete_hypermetro(volume)
                    except exception.VolumeBackendAPIException as err:
                        LOG.exception(_LE('Delete hypermetro error: %s.'), err)
                        self.restclient.delete_lun(lun_id)
                        raise

                self.restclient.delete_lun(lun_id)
        else:
            LOG.warning(_LW("Can't find lun %s on the array."), lun_id)
            return False

        return True

    def remove_qos_lun(self, lun_id, qos_id):
        lun_list = self.restclient.get_lun_list_in_qos(qos_id)
        lun_count = len(lun_list)
        if lun_count <= 1:
            qos = smartx.SmartQos(self.restclient)
            qos.delete_qos(qos_id)
        else:
            self.restclient.remove_lun_from_qos(lun_id,
                                                lun_list,
                                                qos_id)

    def _delete_lun_with_check(self, lun_id):
        if lun_id:
            if self.restclient.check_lun_exist(lun_id):
                qos_id = self.restclient.get_qosid_by_lunid(lun_id)
                if qos_id:
                    self.remove_qos_lun(lun_id, qos_id)

                self.restclient.delete_lun(lun_id)

    def _is_lun_migration_complete(self, src_id, dst_id):
        result = self.restclient.get_lun_migration_task()
        found_migration_task = False
        if 'data' in result:
            for item in result['data']:
                if (src_id == item['PARENTID']
                        and dst_id == item['TARGETLUNID']):
                    found_migration_task = True
                    if constants.MIGRATION_COMPLETE == item['RUNNINGSTATUS']:
                        return True
                    if constants.MIGRATION_FAULT == item['RUNNINGSTATUS']:
                        err_msg = _('Lun migration error.')
                        LOG.error(err_msg)
                        raise exception.VolumeBackendAPIException(data=err_msg)
        if not found_migration_task:
            err_msg = _("Cannot find migration task.")
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        return False

    def _is_lun_migration_exist(self, src_id, dst_id):
        try:
            result = self.restclient.get_lun_migration_task()
        except Exception:
            LOG.error(_LE("Get LUN migration error."))
            return False
        if 'data' in result:
            for item in result['data']:
                if (src_id == item['PARENTID']
                        and dst_id == item['TARGETLUNID']):
                    return True
        return False

    def _migrate_lun(self, src_id, dst_id):
        try:
            self.restclient.create_lun_migration(src_id, dst_id)

            def _is_lun_migration_complete():
                return self._is_lun_migration_complete(src_id, dst_id)

            wait_interval = constants.MIGRATION_WAIT_INTERVAL
            huawei_utils.wait_for_condition(self.xml_file_path,
                                            _is_lun_migration_complete,
                                            wait_interval)
        # Clean up if migration failed.
        except Exception as ex:
            raise exception.VolumeBackendAPIException(data=ex)
        finally:
            if self._is_lun_migration_exist(src_id, dst_id):
                self.restclient.delete_lun_migration(src_id, dst_id)
            self._delete_lun_with_check(dst_id)

        LOG.debug("Migrate lun %s successfully.", src_id)
        return True

    def _wait_volume_ready(self, lun_id):
        event_type = 'LUNReadyWaitInterval'
        wait_interval = huawei_utils.get_wait_interval(self.xml_file_path,
                                                       event_type)

        def _volume_ready():
            result = self.restclient.get_lun_info(lun_id)
            if (result['HEALTHSTATUS'] == constants.STATUS_HEALTH
               and result['RUNNINGSTATUS'] == constants.STATUS_VOLUME_READY):
                return True
            return False

        huawei_utils.wait_for_condition(self.xml_file_path,
                                        _volume_ready,
                                        wait_interval,
                                        wait_interval * 10)

    def _get_original_status(self, volume):
        if not volume['volume_attachment']:
            return 'available'
        else:
            return 'in-use'

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status=None):
        original_name = huawei_utils.encode_name(volume['id'])
        current_name = huawei_utils.encode_name(new_volume['id'])

        lun_id = self.restclient.get_volume_by_name(current_name)
        try:
            self.restclient.rename_lun(lun_id, original_name)
        except exception.VolumeBackendAPIException:
            LOG.error(_LE('Unable to rename lun %s on array.'), current_name)
            return {'_name_id': new_volume['_name_id'] or new_volume['id']}

        LOG.debug("Rename lun from %(current_name)s to %(original_name)s "
                  "successfully.",
                  {'current_name': current_name,
                   'original_name': original_name})

        model_update = {'_name_id': None}

        return model_update

    def migrate_volume(self, ctxt, volume, host, new_type=None):
        """Migrate a volume within the same array."""
        return self._migrate_volume(volume, host, new_type)

    def _check_migration_valid(self, host, volume):
        if 'pool_name' not in host['capabilities']:
            return False

        target_device = host['capabilities']['location_info']

        # Source and destination should be on same array.
        if target_device != self.restclient.device_id:
            return False

        # Same protocol should be used if volume is in-use.
        protocol = huawei_utils.get_protocol(self.xml_file_path)
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

        type_id = volume['volume_type_id']

        volume_type = None
        if type_id:
            volume_type = volume_types.get_volume_type(None, type_id)

        pool_name = host['capabilities']['pool_name']
        pools = self.restclient.find_all_pools()
        pool_info = self.restclient.find_pool_info(pool_name, pools)
        src_volume_name = huawei_utils.encode_name(volume['id'])
        dst_volume_name = six.text_type(hash(src_volume_name))
        src_id = volume.get('provider_location')

        src_lun_params = self.restclient.get_lun_info(src_id)

        opts = None
        qos = None
        if new_type:
            # If new type exists, use new type.
            opts = huawei_utils._get_extra_spec_value(
                new_type['extra_specs'])
            opts = smartx.SmartX().get_smartx_specs_opts(opts)
            if 'LUNType' not in opts:
                opts['LUNType'] = huawei_utils.find_luntype_in_xml(
                    self.xml_file_path)

            qos = huawei_utils.get_qos_by_volume_type(new_type)
        elif volume_type:
            qos = huawei_utils.get_qos_by_volume_type(volume_type)

        if not opts:
            opts = huawei_utils.get_volume_params(volume)
            opts = smartx.SmartX().get_smartx_specs_opts(opts)

        lun_info = self._create_lun_with_extra_feature(pool_info,
                                                       dst_volume_name,
                                                       src_lun_params,
                                                       opts)
        lun_id = lun_info['ID']

        if qos:
            LOG.info(_LI('QoS: %s.'), qos)
            SmartQos = smartx.SmartQos(self.restclient)
            SmartQos.create_qos(qos, lun_id)
        if opts:
            smartpartition = smartx.SmartPartition(self.restclient)
            smartpartition.add(opts, lun_id)
            smartcache = smartx.SmartCache(self.restclient)
            smartcache.add(opts, lun_id)

        dst_id = lun_info['ID']
        self._wait_volume_ready(dst_id)
        moved = self._migrate_lun(src_id, dst_id)

        return moved, {}

    def _create_lun_with_extra_feature(self, pool_info,
                                       lun_name,
                                       lun_params,
                                       spec_opts):
        LOG.info(_LI('Create a new lun %s for migration.'), lun_name)

        # Prepare lun parameters.
        lunparam = {"TYPE": '11',
                    "NAME": lun_name,
                    "PARENTTYPE": '216',
                    "PARENTID": pool_info['ID'],
                    "ALLOCTYPE": lun_params['ALLOCTYPE'],
                    "CAPACITY": lun_params['CAPACITY'],
                    "WRITEPOLICY": lun_params['WRITEPOLICY'],
                    "MIRRORPOLICY": lun_params['MIRRORPOLICY'],
                    "PREFETCHPOLICY": lun_params['PREFETCHPOLICY'],
                    "PREFETCHVALUE": lun_params['PREFETCHVALUE'],
                    "DATATRANSFERPOLICY": '0',
                    "READCACHEPOLICY": lun_params['READCACHEPOLICY'],
                    "WRITECACHEPOLICY": lun_params['WRITECACHEPOLICY'],
                    "OWNINGCONTROLLER": lun_params['OWNINGCONTROLLER'],
                    }
        if 'LUNType' in spec_opts:
            lunparam['ALLOCTYPE'] = spec_opts['LUNType']
        if spec_opts['policy']:
            lunparam['DATATRANSFERPOLICY'] = spec_opts['policy']

        lun_info = self.restclient.create_volume(lunparam)
        return lun_info

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot.

        We use LUNcopy to copy a new volume from snapshot.
        The time needed increases as volume size does.
        """
        snapshotname = huawei_utils.encode_name(snapshot['id'])

        snapshot_id = snapshot.get('provider_location')
        if snapshot_id is None:
            snapshot_id = self.restclient.get_snapshotid_by_name(snapshotname)
            if snapshot_id is None:
                err_msg = (_(
                    'create_volume_from_snapshot: Snapshot %(name)s '
                    'does not exist.')
                    % {'name': snapshotname})
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)

        lun_info = self.create_volume(volume)

        tgt_lun_id = lun_info['ID']
        luncopy_name = huawei_utils.encode_name(volume['id'])

        LOG.info(_LI(
            'create_volume_from_snapshot: src_lun_id: %(src_lun_id)s, '
            'tgt_lun_id: %(tgt_lun_id)s, copy_name: %(copy_name)s.'),
            {'src_lun_id': snapshot_id,
             'tgt_lun_id': tgt_lun_id,
             'copy_name': luncopy_name})

        event_type = 'LUNReadyWaitInterval'

        wait_interval = huawei_utils.get_wait_interval(self.xml_file_path,
                                                       event_type)

        def _volume_ready():
            result = self.restclient.get_lun_info(tgt_lun_id)

            if (result['HEALTHSTATUS'] == constants.STATUS_HEALTH
               and result['RUNNINGSTATUS'] == constants.STATUS_VOLUME_READY):
                return True
            return False

        huawei_utils.wait_for_condition(self.xml_file_path,
                                        _volume_ready,
                                        wait_interval,
                                        wait_interval * 10)

        self._copy_volume(volume, luncopy_name,
                          snapshot_id, tgt_lun_id)

        return {'ID': lun_info['ID'],
                'lun_info': lun_info}

    def create_cloned_volume(self, volume, src_vref):
        """Clone a new volume from an existing volume."""
        # Form the snapshot structure.
        snapshot = {'id': uuid.uuid4().__str__(),
                    'volume_id': src_vref['id'],
                    'volume': src_vref}

        # Create snapshot.
        self.create_snapshot(snapshot)

        try:
            # Create volume from snapshot.
            lun_info = self.create_volume_from_snapshot(volume, snapshot)
        finally:
            try:
                # Delete snapshot.
                self.delete_snapshot(snapshot)
            except exception.VolumeBackendAPIException:
                LOG.warning(_LW(
                    'Failure deleting the snapshot %(snapshot_id)s '
                    'of volume %(volume_id)s.'),
                    {'snapshot_id': snapshot['id'],
                     'volume_id': src_vref['id']},)

        return {'provider_location': lun_info['ID'],
                'lun_info': lun_info}

    @utils.synchronized('huawei', external=True)
    def extend_volume(self, volume, new_size):
        """Extend a volume."""
        volume_size = huawei_utils.get_volume_size(volume)
        new_volume_size = int(new_size) * units.Gi / 512
        volume_name = huawei_utils.encode_name(volume['id'])

        LOG.info(_LI(
            'Extend volume: %(volumename)s, oldsize:'
            ' %(oldsize)s  newsize: %(newsize)s.'),
            {'volumename': volume_name,
             'oldsize': volume_size,
             'newsize': new_volume_size},)

        lun_id = self.restclient.get_lunid(volume, volume_name)
        luninfo = self.restclient.extend_volume(lun_id, new_volume_size)

        return {'provider_location': luninfo['ID'],
                'lun_info': luninfo}

    @utils.synchronized('huawei', external=True)
    def create_snapshot(self, snapshot):
        snapshot_info = self.restclient.create_snapshot(snapshot)
        snapshot_id = snapshot_info['ID']
        self.restclient.activate_snapshot(snapshot_id)

        return {'provider_location': snapshot_info['ID'],
                'lun_info': snapshot_info}

    @utils.synchronized('huawei', external=True)
    def delete_snapshot(self, snapshot):
        snapshotname = huawei_utils.encode_name(snapshot['id'])
        volume_name = huawei_utils.encode_name(snapshot['volume_id'])

        LOG.info(_LI(
            'stop_snapshot: snapshot name: %(snapshot)s, '
            'volume name: %(volume)s.'),
            {'snapshot': snapshotname,
             'volume': volume_name},)

        snapshot_id = snapshot.get('provider_location')
        if snapshot_id is None:
            snapshot_id = self.restclient.get_snapshotid_by_name(snapshotname)

        if snapshot_id is not None:
            if self.restclient.check_snapshot_exist(snapshot_id):
                self.restclient.stop_snapshot(snapshot_id)
                self.restclient.delete_snapshot(snapshot_id)
            else:
                LOG.warning(_LW("Can't find snapshot on the array."))
        else:
            LOG.warning(_LW("Can't find snapshot on the array."))
            return False

        return True

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        LOG.debug("Enter retype: id=%(id)s, new_type=%(new_type)s, "
                  "diff=%(diff)s, host=%(host)s.", {'id': volume['id'],
                                                    'new_type': new_type,
                                                    'diff': diff,
                                                    'host': host})

        # Check what changes are needed
        migration, change_opts, lun_id = self.determine_changes_when_retype(
            volume, new_type, host)

        try:
            if migration:
                LOG.debug("Begin to migrate LUN(id: %(lun_id)s) with "
                          "change %(change_opts)s.",
                          {"lun_id": lun_id, "change_opts": change_opts})
                if self._migrate_volume(volume, host, new_type):
                    return True
                else:
                    LOG.warning(_LW("Storage-assisted migration failed during "
                                    "retype."))
                    return False
            else:
                # Modify lun to change policy
                self.modify_lun(lun_id, change_opts)
                return True
        except exception.VolumeBackendAPIException:
            LOG.exception(_LE('Retype volume error.'))
            return False

    def modify_lun(self, lun_id, change_opts):
        if change_opts.get('partitionid'):
            old, new = change_opts['partitionid']
            old_id = old[0]
            old_name = old[1]
            new_id = new[0]
            new_name = new[1]
            if old_id:
                self.restclient.remove_lun_from_partition(lun_id, old_id)
            if new_id:
                self.restclient.add_lun_to_partition(lun_id, new_id)
            LOG.info(_LI("Retype LUN(id: %(lun_id)s) smartpartition from "
                         "(name: %(old_name)s, id: %(old_id)s) to "
                         "(name: %(new_name)s, id: %(new_id)s) success."),
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
                self.restclient.remove_lun_from_cache(lun_id, old_id)
            if new_id:
                self.restclient.add_lun_to_cache(lun_id, new_id)
            LOG.info(_LI("Retype LUN(id: %(lun_id)s) smartcache from "
                         "(name: %(old_name)s, id: %(old_id)s) to "
                         "(name: %(new_name)s, id: %(new_id)s) successfully."),
                     {'lun_id': lun_id,
                      'old_id': old_id, "old_name": old_name,
                      'new_id': new_id, "new_name": new_name})

        if change_opts.get('policy'):
            old_policy, new_policy = change_opts['policy']
            self.restclient.change_lun_smarttier(lun_id, new_policy)
            LOG.info(_LI("Retype LUN(id: %(lun_id)s) smarttier policy from "
                         "%(old_policy)s to %(new_policy)s success."),
                     {'lun_id': lun_id,
                      'old_policy': old_policy,
                      'new_policy': new_policy})

        if change_opts.get('qos'):
            old_qos, new_qos = change_opts['qos']
            old_qos_id = old_qos[0]
            old_qos_value = old_qos[1]
            if old_qos_id:
                self.remove_qos_lun(lun_id, old_qos_id)
            if new_qos:
                smart_qos = smartx.SmartQos(self.restclient)
                smart_qos.create_qos(new_qos, lun_id)
            LOG.info(_LI("Retype LUN(id: %(lun_id)s) smartqos from "
                         "%(old_qos_value)s to %(new_qos)s success."),
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

        lun_info = self.restclient.get_lun_info(lun_id)
        lun_opts['LUNType'] = int(lun_info['ALLOCTYPE'])
        if lun_info['DATATRANSFERPOLICY']:
            lun_opts['policy'] = lun_info['DATATRANSFERPOLICY']
        if lun_info['SMARTCACHEPARTITIONID']:
            lun_opts['cacheid'] = lun_info['SMARTCACHEPARTITIONID']
        if lun_info['CACHEPARTITIONID']:
            lun_opts['partitionid'] = lun_info['CACHEPARTITIONID']

        return lun_opts

    def determine_changes_when_retype(self, volume, new_type, host):
        migration = False
        change_opts = {
            'policy': None,
            'partitionid': None,
            'cacheid': None,
            'qos': None,
            'host': None,
            'LUNType': None,
        }

        lun_id = volume.get('provider_location')
        old_opts = self.get_lun_specs(lun_id)

        new_specs = new_type['extra_specs']
        new_opts = huawei_utils._get_extra_spec_value(new_specs)
        new_opts = smartx.SmartX().get_smartx_specs_opts(new_opts)

        if 'LUNType' not in new_opts:
            new_opts['LUNType'] = huawei_utils.find_luntype_in_xml(
                self.xml_file_path)

        if volume['host'] != host['host']:
            migration = True
            change_opts['host'] = (volume['host'], host['host'])
        if old_opts['LUNType'] != new_opts['LUNType']:
            migration = True
            change_opts['LUNType'] = (old_opts['LUNType'], new_opts['LUNType'])

        new_cache_id = None
        new_cache_name = new_opts['cachename']
        if new_cache_name:
            new_cache_id = self.restclient.get_cache_id_by_name(new_cache_name)
            if new_cache_id is None:
                msg = (_(
                    "Can't find cache name on the array, cache name is: "
                    "%(name)s.") % {'name': new_cache_name})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        new_partition_id = None
        new_partition_name = new_opts['partitionname']
        if new_partition_name:
            new_partition_id = self.restclient.get_partition_id_by_name(
                new_partition_name)
            if new_partition_id is None:
                msg = (_(
                    "Can't find partition name on the array, partition name "
                    "is: %(name)s.") % {'name': new_partition_name})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        # smarttier
        if old_opts['policy'] != new_opts['policy']:
            change_opts['policy'] = (old_opts['policy'], new_opts['policy'])

        # smartcache
        old_cache_id = old_opts['cacheid']
        if old_cache_id != new_cache_id:
            old_cache_name = None
            if old_cache_id:
                cache_info = self.restclient.get_cache_info_by_id(old_cache_id)
                old_cache_name = cache_info['NAME']
            change_opts['cacheid'] = ([old_cache_id, old_cache_name],
                                      [new_cache_id, new_cache_name])

        # smartpartition
        old_partition_id = old_opts['partitionid']
        if old_partition_id != new_partition_id:
            old_partition_name = None
            if old_partition_id:
                partition_info = self.restclient.get_partition_info_by_id(
                    old_partition_id)
                old_partition_name = partition_info['NAME']
            change_opts['partitionid'] = ([old_partition_id,
                                           old_partition_name],
                                          [new_partition_id,
                                           new_partition_name])

        # smartqos
        new_qos = huawei_utils.get_qos_by_volume_type(new_type)
        old_qos_id = self.restclient.get_qosid_by_lunid(lun_id)
        old_qos = self._get_qos_specs_from_array(old_qos_id)
        if old_qos != new_qos:
            change_opts['qos'] = ([old_qos_id, old_qos], new_qos)

        LOG.debug("Determine changes when retype. Migration: "
                  "%(migration)s, change_opts: %(change_opts)s.",
                  {'migration': migration, 'change_opts': change_opts})
        return migration, change_opts, lun_id

    def _get_qos_specs_from_array(self, qos_id):
        qos = {}
        qos_info = {}
        if qos_id:
            qos_info = self.restclient.get_qos_info(qos_id)

        for key, value in qos_info.items():
            if key.upper() in constants.QOS_KEYS:
                if key.upper() == 'LATENCY' and value == '0':
                    continue
                else:
                    qos[key.upper()] = value
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

    def _copy_volume(self, volume, copy_name, src_lun, tgt_lun):
        luncopy_id = self.restclient.create_luncopy(copy_name,
                                                    src_lun, tgt_lun)
        event_type = 'LUNcopyWaitInterval'
        wait_interval = huawei_utils.get_wait_interval(self.xml_file_path,
                                                       event_type)

        try:
            self.restclient.start_luncopy(luncopy_id)

            def _luncopy_complete():
                luncopy_info = self.restclient.get_luncopy_info(luncopy_id)
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
            huawei_utils.wait_for_condition(self.xml_file_path,
                                            _luncopy_complete,
                                            wait_interval)

        except Exception:
            with excutils.save_and_reraise_exception():
                self.restclient.delete_luncopy(luncopy_id)
                self.delete_volume(volume)

        self.restclient.delete_luncopy(luncopy_id)


class Huawei18000ISCSIDriver(HuaweiBaseDriver, driver.ISCSIDriver):
    """ISCSI driver for Huawei OceanStor 18000 storage arrays.

    Version history:
        1.0.0 - Initial driver
        1.1.0 - Provide Huawei OceanStor 18000 storage volume driver
        1.1.1 - Code refactor
                CHAP support
                Multiple pools support
                ISCSI multipath support
                SmartX support
                Volume migration support
                Volume retype support
    """

    VERSION = "1.1.1"

    def __init__(self, *args, **kwargs):
        super(Huawei18000ISCSIDriver, self).__init__(*args, **kwargs)

    def get_volume_stats(self, refresh=False):
        """Get volume status."""
        data = HuaweiBaseDriver.get_volume_stats(self, refresh=False)
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['storage_protocol'] = 'iSCSI'
        data['driver_version'] = self.VERSION
        data['vendor_name'] = 'Huawei'
        return data

    @utils.synchronized('huawei', external=True)
    def initialize_connection(self, volume, connector):
        """Map a volume to a host and return target iSCSI information."""
        LOG.info(_LI('Enter initialize_connection.'))
        initiator_name = connector['initiator']
        volume_name = huawei_utils.encode_name(volume['id'])

        LOG.info(_LI(
            'initiator name: %(initiator_name)s, '
            'volume name: %(volume)s.'),
            {'initiator_name': initiator_name,
             'volume': volume_name})

        (iscsi_iqns,
         target_ips,
         portgroup_id) = self.restclient.get_iscsi_params(self.xml_file_path,
                                                          connector)
        LOG.info(_LI('initialize_connection, iscsi_iqn: %(iscsi_iqn)s, '
                     'target_ip: %(target_ip)s, '
                     'portgroup_id: %(portgroup_id)s.'),
                 {'iscsi_iqn': iscsi_iqns,
                  'target_ip': target_ips,
                  'portgroup_id': portgroup_id},)

        # Create hostgroup if not exist.
        host_name = connector['host']
        host_name_before_hash = None
        if host_name and (len(host_name) > constants.MAX_HOSTNAME_LENGTH):
            host_name_before_hash = host_name
            host_name = six.text_type(hash(host_name))
        host_id = self.restclient.add_host_with_check(host_name,
                                                      host_name_before_hash)

        # Add initiator to the host.
        self.restclient.ensure_initiator_added(self.xml_file_path,
                                               initiator_name,
                                               host_id)
        hostgroup_id = self.restclient.add_host_into_hostgroup(host_id)

        lun_id = self.restclient.get_lunid(volume, volume_name)

        # Mapping lungroup and hostgroup to view.
        self.restclient.do_mapping(lun_id, hostgroup_id,
                                   host_id, portgroup_id)

        hostlun_id = self.restclient.find_host_lun_id(host_id, lun_id)

        LOG.info(_LI("initialize_connection, host lun id is: %s."),
                 hostlun_id)

        iscsi_conf = huawei_utils.get_iscsi_conf(self.xml_file_path)
        chapinfo = self.restclient.find_chap_info(iscsi_conf,
                                                  initiator_name)
        # Return iSCSI properties.
        properties = {}
        properties['target_discovered'] = False
        properties['volume_id'] = volume['id']
        multipath = connector.get('multipath', False)
        hostlun_id = int(hostlun_id)
        if not multipath:
            properties['target_portal'] = ('%s:3260' % target_ips[0])
            properties['target_iqn'] = iscsi_iqns[0]
            properties['target_lun'] = hostlun_id
        else:
            properties['target_iqns'] = [iqn for iqn in iscsi_iqns]
            properties['target_portals'] = [
                '%s:3260' % ip for ip in target_ips]
            properties['target_luns'] = [hostlun_id] * len(target_ips)

        # If use CHAP, return CHAP info.
        if chapinfo:
            chap_username, chap_password = chapinfo.split(';')
            properties['auth_method'] = 'CHAP'
            properties['auth_username'] = chap_username
            properties['auth_password'] = chap_password

        LOG.info(_LI("initialize_connection success. Return data: %s."),
                 properties)
        return {'driver_volume_type': 'iscsi', 'data': properties}

    @utils.synchronized('huawei', external=True)
    def terminate_connection(self, volume, connector, **kwargs):
        """Delete map between a volume and a host."""
        initiator_name = connector['initiator']
        volume_name = huawei_utils.encode_name(volume['id'])
        lun_id = volume.get('provider_location')
        host_name = connector['host']
        lungroup_id = None

        LOG.info(_LI(
            'terminate_connection: volume name: %(volume)s, '
            'initiator name: %(ini)s, '
            'lun_id: %(lunid)s.'),
            {'volume': volume_name,
             'ini': initiator_name,
             'lunid': lun_id},)

        iscsi_conf = huawei_utils.get_iscsi_conf(self.xml_file_path)
        portgroup = None
        portgroup_id = None
        view_id = None
        left_lunnum = -1
        for ini in iscsi_conf['Initiator']:
            if ini['Name'] == initiator_name:
                for key in ini:
                    if key == 'TargetPortGroup':
                        portgroup = ini['TargetPortGroup']
                        break

        if portgroup:
            portgroup_id = self.restclient.find_tgt_port_group(portgroup)
        if host_name and (len(host_name) > constants.MAX_HOSTNAME_LENGTH):
            host_name = six.text_type(hash(host_name))
        host_id = self.restclient.find_host(host_name)
        if host_id:
            mapping_view_name = constants.MAPPING_VIEW_PREFIX + host_id
            view_id = self.restclient.find_mapping_view(mapping_view_name)
            if view_id:
                lungroup_id = self.restclient.find_lungroup_from_map(view_id)

        # Remove lun from lungroup.
        if lun_id and self.restclient.check_lun_exist(lun_id):
            if lungroup_id:
                lungroup_ids = self.restclient.get_lungroupids_by_lunid(lun_id)
                if lungroup_id in lungroup_ids:
                    self.restclient.remove_lun_from_lungroup(lungroup_id,
                                                             lun_id)
                else:
                    LOG.warning(_LW("Lun is not in lungroup. "
                                    "Lun id: %(lun_id)s. "
                                    "lungroup id: %(lungroup_id)s."),
                                {"lun_id": lun_id,
                                 "lungroup_id": lungroup_id})
        else:
            LOG.warning(_LW("Can't find lun on the array."))

        # Remove portgroup from mapping view if no lun left in lungroup.
        if lungroup_id:
            left_lunnum = self.restclient.get_lunnum_from_lungroup(lungroup_id)

        if portgroup_id and view_id and (int(left_lunnum) <= 0):
            if self.restclient.is_portgroup_associated_to_view(view_id,
                                                               portgroup_id):
                self.restclient.delete_portgroup_mapping_view(view_id,
                                                              portgroup_id)
        if view_id and (int(left_lunnum) <= 0):
            self.restclient.remove_chap(initiator_name)

            if self.restclient.lungroup_associated(view_id, lungroup_id):
                self.restclient.delete_lungroup_mapping_view(view_id,
                                                             lungroup_id)
            self.restclient.delete_lungroup(lungroup_id)
            if self.restclient.is_initiator_associated_to_host(initiator_name):
                self.restclient.remove_iscsi_from_host(initiator_name)
            hostgroup_name = constants.HOSTGROUP_PREFIX + host_id
            hostgroup_id = self.restclient.find_hostgroup(hostgroup_name)
            if hostgroup_id:
                if self.restclient.hostgroup_associated(view_id, hostgroup_id):
                    self.restclient.delete_hostgoup_mapping_view(view_id,
                                                                 hostgroup_id)
                self.restclient.remove_host_from_hostgroup(hostgroup_id,
                                                           host_id)
                self.restclient.delete_hostgroup(hostgroup_id)
            self.restclient.remove_host(host_id)
            self.restclient.delete_mapping_view(view_id)


class Huawei18000FCDriver(HuaweiBaseDriver, driver.FibreChannelDriver):
    """FC driver for Huawei OceanStor 18000 storage arrays.

    Version history:
        1.0.0 - Initial driver
        1.1.0 - Provide Huawei OceanStor 18000 storage volume driver
        1.1.1 - Code refactor
                Multiple pools support
                SmartX support
                Volume migration support
                Volume retype support
                FC zone enhancement
                Volume hypermetro support
    """

    VERSION = "1.1.1"

    def __init__(self, *args, **kwargs):
        super(Huawei18000FCDriver, self).__init__(*args, **kwargs)
        self.fcsan_lookup_service = None

    def get_volume_stats(self, refresh=False):
        """Get volume status."""
        data = HuaweiBaseDriver.get_volume_stats(self, refresh=False)
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['storage_protocol'] = 'FC'
        data['driver_version'] = self.VERSION
        data['vendor_name'] = 'Huawei'
        return data

    @utils.synchronized('huawei', external=True)
    @fczm_utils.AddFCZone
    def initialize_connection(self, volume, connector):
        wwns = connector['wwpns']
        volume_name = huawei_utils.encode_name(volume['id'])
        LOG.info(_LI(
            'initialize_connection, initiator: %(wwpns)s,'
            ' volume name: %(volume)s.'),
            {'wwpns': wwns,
             'volume': volume_name},)

        lun_id = self.restclient.get_lunid(volume, volume_name)

        host_name_before_hash = None
        host_name = connector['host']
        if host_name and (len(host_name) > constants.MAX_HOSTNAME_LENGTH):
            host_name_before_hash = host_name
            host_name = six.text_type(hash(host_name))

        if not self.fcsan_lookup_service:
            self.fcsan_lookup_service = fczm_utils.create_lookup_service()

        if self.fcsan_lookup_service:
            # Use FC switch.
            host_id = self.restclient.add_host_with_check(
                host_name, host_name_before_hash)
            zone_helper = fc_zone_helper.FCZoneHelper(
                self.fcsan_lookup_service, self.restclient)
            (tgt_port_wwns, init_targ_map) = (
                zone_helper.build_ini_targ_map(wwns))
            for ini in init_targ_map:
                self.restclient.ensure_fc_initiator_added(ini, host_id)
        else:
            # Not use FC switch.
            host_id = self.restclient.add_host_with_check(
                host_name, host_name_before_hash)
            online_wwns_in_host = (
                self.restclient.get_host_online_fc_initiators(host_id))
            online_free_wwns = self.restclient.get_online_free_wwns()
            for wwn in wwns:
                if (wwn not in online_wwns_in_host
                        and wwn not in online_free_wwns):
                    wwns_in_host = (
                        self.restclient.get_host_fc_initiators(host_id))
                    iqns_in_host = (
                        self.restclient.get_host_iscsi_initiators(host_id))
                    if not wwns_in_host and not iqns_in_host:
                        self.restclient.remove_host(host_id)

                    msg = (_('Can not add FC initiator to host.'))
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

            for wwn in wwns:
                if wwn in online_free_wwns:
                    self.restclient.add_fc_port_to_host(host_id, wwn)

            (tgt_port_wwns, init_targ_map) = (
                self.restclient.get_init_targ_map(wwns))

        # Add host into hostgroup.
        hostgroup_id = self.restclient.add_host_into_hostgroup(host_id)
        map_info = self.restclient.do_mapping(lun_id,
                                              hostgroup_id,
                                              host_id)
        host_lun_id = self.restclient.find_host_lun_id(host_id, lun_id)

        # Return FC properties.
        fc_info = {'driver_volume_type': 'fibre_channel',
                   'data': {'target_lun': int(host_lun_id),
                            'target_discovered': True,
                            'target_wwn': tgt_port_wwns,
                            'volume_id': volume['id'],
                            'initiator_target_map': init_targ_map,
                            'map_info': map_info}, }

        loc_tgt_wwn = fc_info['data']['target_wwn']
        local_ini_tgt_map = fc_info['data']['initiator_target_map']

        # Deal with hypermetro connection.
        metadata = huawei_utils.get_volume_metadata(volume)
        LOG.info(_LI("initialize_connection, metadata is: %s."), metadata)
        if 'hypermetro_id' in metadata:
            hyperm = hypermetro.HuaweiHyperMetro(self.restclient, None,
                                                 self.configuration)
            rmt_fc_info = hyperm.connect_volume_fc(volume, connector)

            rmt_tgt_wwn = rmt_fc_info['data']['target_wwn']
            rmt_ini_tgt_map = rmt_fc_info['data']['initiator_target_map']
            fc_info['data']['target_wwn'] = (loc_tgt_wwn + rmt_tgt_wwn)
            wwns = connector['wwpns']
            for wwn in wwns:
                if (wwn in local_ini_tgt_map
                        and wwn in rmt_ini_tgt_map):
                    fc_info['data']['initiator_target_map'][wwn].extend(
                        rmt_ini_tgt_map[wwn])

                elif (wwn not in local_ini_tgt_map
                        and wwn in rmt_ini_tgt_map):
                    fc_info['data']['initiator_target_map'][wwn] = (
                        rmt_ini_tgt_map[wwn])
                # else, do nothing

            loc_map_info = fc_info['data']['map_info']
            rmt_map_info = rmt_fc_info['data']['map_info']
            same_host_id = self._get_same_hostid(loc_map_info,
                                                 rmt_map_info)

            self.restclient.change_hostlun_id(loc_map_info, same_host_id)
            hyperm.rmt_client.change_hostlun_id(rmt_map_info, same_host_id)

            fc_info['data']['target_lun'] = same_host_id
            hyperm.rmt_client.logout()

        LOG.info(_LI("Return FC info is: %s."), fc_info)
        return fc_info

    def _get_same_hostid(self, loc_fc_info, rmt_fc_info):
        loc_aval_luns = loc_fc_info['aval_luns']
        loc_aval_luns = json.loads(loc_aval_luns)

        rmt_aval_luns = rmt_fc_info['aval_luns']
        rmt_aval_luns = json.loads(rmt_aval_luns)
        same_host_id = None

        for i in range(1, 512):
            if i in rmt_aval_luns and i in loc_aval_luns:
                same_host_id = i
                break

        LOG.info(_LI("The same hostid is: %s."), same_host_id)
        if not same_host_id:
            msg = _("Can't find the same host id from arrays.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return same_host_id

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        """Delete map between a volume and a host."""
        wwns = connector['wwpns']
        volume_name = huawei_utils.encode_name(volume['id'])
        lun_id = volume.get('provider_location')
        host_name = connector['host']
        left_lunnum = -1
        lungroup_id = None
        view_id = None
        LOG.info(_LI('terminate_connection: volume name: %(volume)s, '
                     'wwpns: %(wwns)s, '
                     'lun_id: %(lunid)s.'),
                 {'volume': volume_name,
                  'wwns': wwns,
                  'lunid': lun_id},)

        if host_name and len(host_name) > constants.MAX_HOSTNAME_LENGTH:
            host_name = six.text_type(hash(host_name))
        host_id = self.restclient.find_host(host_name)
        if host_id:
            mapping_view_name = constants.MAPPING_VIEW_PREFIX + host_id
            view_id = self.restclient.find_mapping_view(mapping_view_name)
            if view_id:
                lungroup_id = self.restclient.find_lungroup_from_map(view_id)

        if lun_id and self.restclient.check_lun_exist(lun_id):
            if lungroup_id:
                lungroup_ids = self.restclient.get_lungroupids_by_lunid(lun_id)
                if lungroup_id in lungroup_ids:
                    self.restclient.remove_lun_from_lungroup(lungroup_id,
                                                             lun_id)
                else:
                    LOG.warning(_LW("Lun is not in lungroup. "
                                    "Lun id: %(lun_id)s. "
                                    "Lungroup id: %(lungroup_id)s."),
                                {"lun_id": lun_id,
                                 "lungroup_id": lungroup_id})
        else:
            LOG.warning(_LW("Can't find lun on the array."))
        if lungroup_id:
            left_lunnum = self.restclient.get_lunnum_from_lungroup(lungroup_id)
        if int(left_lunnum) > 0:
            fc_info = {'driver_volume_type': 'fibre_channel',
                       'data': {}}
        else:
            if not self.fcsan_lookup_service:
                self.fcsan_lookup_service = fczm_utils.create_lookup_service()

            if self.fcsan_lookup_service:
                zone_helper = fc_zone_helper.FCZoneHelper(
                    self.fcsan_lookup_service, self.restclient)

                (tgt_port_wwns, init_targ_map) = (
                    zone_helper.build_ini_targ_map(wwns))
            else:
                (tgt_port_wwns, init_targ_map) = (
                    self.restclient.get_init_targ_map(wwns))

            for wwn in wwns:
                if self.restclient.is_fc_initiator_associated_to_host(wwn):
                    self.restclient.remove_fc_from_host(wwn)
            if lungroup_id:
                if view_id and self.restclient.lungroup_associated(
                        view_id, lungroup_id):
                    self.restclient.delete_lungroup_mapping_view(view_id,
                                                                 lungroup_id)
                self.restclient.delete_lungroup(lungroup_id)

            if host_id:
                hostgroup_name = constants.HOSTGROUP_PREFIX + host_id
                hostgroup_id = self.restclient.find_hostgroup(hostgroup_name)
                if hostgroup_id:
                    if view_id and self.restclient.hostgroup_associated(
                            view_id, hostgroup_id):
                        self.restclient.delete_hostgoup_mapping_view(
                            view_id, hostgroup_id)
                    self.restclient.remove_host_from_hostgroup(
                        hostgroup_id, host_id)
                    self.restclient.delete_hostgroup(hostgroup_id)

                if not self.restclient.check_fc_initiators_exist_in_host(
                        host_id):
                    self.restclient.remove_host(host_id)

            if view_id:
                self.restclient.delete_mapping_view(view_id)

            fc_info = {'driver_volume_type': 'fibre_channel',
                       'data': {'target_wwn': tgt_port_wwns,
                                'initiator_target_map': init_targ_map}}

        # Deal with hypermetro connection.
        metadata = huawei_utils.get_volume_metadata(volume)
        LOG.info(_LI("Detach Volume, metadata is: %s."), metadata)
        if 'hypermetro_id' in metadata:
            hyperm = hypermetro.HuaweiHyperMetro(self.restclient, None,
                                                 self.configuration)
            hyperm.disconnect_volume_fc(volume, connector)

        LOG.info(_LI("terminate_connection, return data is: %s."),
                 fc_info)

        return fc_info
