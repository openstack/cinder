# Copyright (c) 2013 - 2016 Huawei Technologies Co., Ltd.
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
"""
Driver for Huawei FusionStorage.
"""

import os
import re

from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.fusionstorage import fspythonapi

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.BoolOpt('dsware_isthin',
                default=False,
                help='The flag of thin storage allocation.'),
    cfg.StrOpt('dsware_manager',
               default='',
               help='Fusionstorage manager ip addr for cinder-volume.'),
    cfg.StrOpt('fusionstorageagent',
               default='',
               help='Fusionstorage agent ip addr range.'),
    cfg.StrOpt('pool_type',
               default='default',
               help = 'Pool type, like sata-2copy.'),
    cfg.ListOpt('pool_id_filter',
                default=[],
                help='Pool id permit to use.'),
    cfg.IntOpt('clone_volume_timeout',
               default=680,
               help='Create clone volume timeout.'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts, group=configuration.SHARED_CONF_GROUP)

OLD_VERSION = 1
NEW_VERSION = 0
VOLUME_ALREADY_ATTACHED = 50151401
VOLUME_NOT_EXIST = '50150005\n'
VOLUME_BEING_DELETED = '50151002\n'
SNAP_NOT_EXIST = '50150006\n'


@interface.volumedriver
class DSWAREDriver(driver.VolumeDriver):
    """Huawei FusionStorage Driver."""
    VERSION = '1.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Huawei_FusionStorage_CI"

    DSWARE_VOLUME_CREATE_SUCCESS_STATUS = 0
    DSWARE_VOLUME_DUPLICATE_VOLUME = 6
    DSWARE_VOLUME_CREATING_STATUS = 7

    def __init__(self, *args, **kwargs):
        super(DSWAREDriver, self).__init__(*args, **kwargs)
        self.dsware_client = fspythonapi.FSPythonApi()
        self.check_cloned_interval = 2
        self.configuration.append_config_values(volume_opts)

    def check_for_setup_error(self):
        # lrk: check config file here.
        if not os.path.exists(fspythonapi.fsc_conf_file):
            msg = _("Dsware config file not exists!")
            LOG.error("Dsware config file: %s not exists!",
                      fspythonapi.fsc_conf_file)
            raise exception.VolumeBackendAPIException(data=msg)

    def do_setup(self, context):
        # lrk: create fsc_conf_file here.
        conf_info = ["manage_ip=%s" % self.configuration.dsware_manager,
                     "\n",
                     "vbs_url=%s" % self.configuration.fusionstorageagent]

        fsc_dir = os.path.dirname(fspythonapi.fsc_conf_file)
        if not os.path.exists(fsc_dir):
            os.makedirs(fsc_dir)

        with open(fspythonapi.fsc_conf_file, 'w') as f:
            f.writelines(conf_info)

        # Get pool type.
        self.pool_type = self.configuration.pool_type
        LOG.debug("Dsware Driver do_setup finish.")

    def _get_dsware_manage_ip(self, volume):
        dsw_manager_ip = volume.provider_id
        if dsw_manager_ip is not None:
            return dsw_manager_ip
        else:
            msg = _("Dsware get manager ip failed, "
                    "volume provider_id is None!")
            raise exception.VolumeBackendAPIException(data=msg)

    def _get_poolid_from_host(self, host):
        # Host format: 'hostid@backend#poolid'.
        # Other formats: return 'default', and the pool id would be zero.
        if host:
            if len(host.split('#', 1)) == 2:
                return host.split('#')[1]
        return self.pool_type

    def _create_volume(self, volume_id, volume_size, is_thin, volume_host):
        pool_id = 0
        result = 1

        # Query Dsware version.
        retcode = self.dsware_client.query_dsware_version()
        # Old version.
        if retcode == OLD_VERSION:
            pool_id = 0
        # New version.
        elif retcode == NEW_VERSION:
            pool_info = self._get_poolid_from_host(volume_host)
            if pool_info != self.pool_type:
                pool_id = int(pool_info)
        # Query Dsware version failed!
        else:
            LOG.error("Query Dsware version fail!")
            msg = (_("Query Dsware version failed! Retcode is %s.") %
                   retcode)
            raise exception.VolumeBackendAPIException(data=msg)

        try:
            result = self.dsware_client.create_volume(
                volume_id, pool_id, volume_size, int(is_thin))
        except Exception as e:
            LOG.exception("Create volume error, details is: %s.", e)
            raise

        if result != 0:
            msg = _("Dsware create volume failed! Result is: %s.") % result
            raise exception.VolumeBackendAPIException(data=msg)

    def create_volume(self, volume):
        # Creates a volume in Dsware.
        LOG.debug("Begin to create volume %s in Dsware.", volume.name)
        volume_id = volume.name
        volume_size = volume.size
        volume_host = volume.host
        is_thin = self.configuration.dsware_isthin
        # Change GB to MB.
        volume_size *= 1024
        self._create_volume(volume_id, volume_size, is_thin, volume_host)

        dsw_manager_ip = self.dsware_client.get_manage_ip()
        return {"provider_id": dsw_manager_ip}

    def _create_volume_from_snap(self, volume_id, volume_size, snapshot_name):
        result = self.dsware_client.create_volume_from_snap(
            volume_id, volume_size, snapshot_name)
        if result != 0:
            msg = (_("Dsware: create volume from snap failed. Result: %s.") %
                   result)
            raise exception.VolumeBackendAPIException(data=msg)

    def create_volume_from_snapshot(self, volume, snapshot):
        # Creates a volume from snapshot.
        volume_id = volume.name
        volume_size = volume.size
        snapshot_name = snapshot.name
        if volume_size < int(snapshot.volume_size):
            msg = _("Dsware: volume size can not be less than snapshot size.")
            raise exception.VolumeBackendAPIException(data=msg)
        # Change GB to MB.
        volume_size *= 1024
        self._create_volume_from_snap(volume_id, volume_size, snapshot_name)

        dsw_manager_ip = self.dsware_client.get_manage_ip()
        return {"provider_id": dsw_manager_ip}

    def create_cloned_volume(self, volume, src_volume):
        """Dispatcher to Dsware client to create volume from volume.

        Wait volume create finished.
        """
        volume_name = volume.name
        volume_size = volume.size
        src_volume_name = src_volume.name
        # Change GB to MB.
        volume_size *= 1024
        result = self.dsware_client.create_volume_from_volume(
            volume_name, volume_size, src_volume_name)
        if result:
            msg = _('Dsware fails to start cloning volume %s.') % volume_name
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('Dsware create volume %(volume_name)s of size '
                  '%(volume_size)s from src volume %(src_volume_name)s start.',
                  {"volume_name": volume_name,
                   "volume_size": volume_size,
                   "src_volume_name": src_volume_name})

        ret = self._wait_for_create_cloned_volume_finish_timer(volume_name)
        if not ret:
            msg = (_('Clone volume %s failed while waiting for success.') %
                   volume_name)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('Dsware create volume from volume ends.')

        dsw_manager_ip = self.dsware_client.get_manage_ip()
        return {"provider_id": dsw_manager_ip}

    def _check_create_cloned_volume_finish(self, new_volume_name):
        LOG.debug('Loopcall: _check_create_cloned_volume_finish(), '
                  'volume-name: %s.', new_volume_name)
        current_volume = self.dsware_client.query_volume(new_volume_name)

        if current_volume:
            status = current_volume['status']
            LOG.debug('Wait clone volume %(volume_name)s, status: %(status)s.',
                      {"volume_name": new_volume_name,
                       "status": status})
            if int(status) == self.DSWARE_VOLUME_CREATING_STATUS or int(
                    status) == self.DSWARE_VOLUME_DUPLICATE_VOLUME:
                self.count += 1
            elif int(status) == self.DSWARE_VOLUME_CREATE_SUCCESS_STATUS:
                raise loopingcall.LoopingCallDone(retvalue=True)
            else:
                msg = _('Clone volume %(new_volume_name)s failed, '
                        'volume status is: %(status)s.')
                LOG.error(msg, {'new_volume_name': new_volume_name,
                                'status': status})
                raise loopingcall.LoopingCallDone(retvalue=False)
            if self.count > self.configuration.clone_volume_timeout:
                msg = _('Dsware clone volume time out. '
                        'Volume: %(new_volume_name)s, status: %(status)s')
                LOG.error(msg, {'new_volume_name': new_volume_name,
                                'status': current_volume['status']})
                raise loopingcall.LoopingCallDone(retvalue=False)
        else:
            LOG.warning('Can not find volume %s from Dsware.',
                        new_volume_name)
            self.count += 1
            if self.count > 10:
                msg = _("Dsware clone volume failed: volume "
                        "can not be found from Dsware.")
                LOG.error(msg)
                raise loopingcall.LoopingCallDone(retvalue=False)

    def _wait_for_create_cloned_volume_finish_timer(self, new_volume_name):
        timer = loopingcall.FixedIntervalLoopingCall(
            self._check_create_cloned_volume_finish, new_volume_name)
        LOG.debug('Call _check_create_cloned_volume_finish: volume-name %s.',
                  new_volume_name)
        self.count = 0
        ret = timer.start(interval=self.check_cloned_interval).wait()
        timer.stop()
        return ret

    def _analyse_output(self, out):
        if out is not None:
            analyse_result = {}
            out_temp = out.split('\n')
            for line in out_temp:
                if re.search('^ret_code=', line):
                    analyse_result['ret_code'] = line[9:]
                elif re.search('^ret_desc=', line):
                    analyse_result['ret_desc'] = line[9:]
                elif re.search('^dev_addr=', line):
                    analyse_result['dev_addr'] = line[9:]
            return analyse_result
        else:
            return None

    def _attach_volume(self, volume_name, dsw_manager_ip):
        cmd = ['vbs_cli', '-c', 'attachwithip', '-v', volume_name, '-i',
               dsw_manager_ip.replace('\n', ''), '-p', 0]
        out, err = self._execute(*cmd, run_as_root=True)
        analyse_result = self._analyse_output(out)
        LOG.debug("Attach volume result is %s.", analyse_result)
        return analyse_result

    def _detach_volume(self, volume_name, dsw_manager_ip):
        cmd = ['vbs_cli', '-c', 'detachwithip', '-v', volume_name, '-i',
               dsw_manager_ip.replace('\n', ''), '-p', 0]
        out, err = self._execute(*cmd, run_as_root=True)
        analyse_result = self._analyse_output(out)
        LOG.debug("Detach volume result is %s.", analyse_result)
        return analyse_result

    def _query_volume_attach(self, volume_name, dsw_manager_ip):
        cmd = ['vbs_cli', '-c', 'querydevwithip', '-v', volume_name, '-i',
               dsw_manager_ip.replace('\n', ''), '-p', 0]
        out, err = self._execute(*cmd, run_as_root=True)
        analyse_result = self._analyse_output(out)
        LOG.debug("Query volume attach result is %s.", analyse_result)
        return analyse_result

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        # Copy image to volume.
        # Step1: attach volume to host.
        LOG.debug("Begin to copy image to volume.")
        dsw_manager_ip = self._get_dsware_manage_ip(volume)
        volume_attach_result = self._attach_volume(volume.name,
                                                   dsw_manager_ip)
        volume_attach_path = ''
        if volume_attach_result is not None and int(
                volume_attach_result['ret_code']) == 0:
            volume_attach_path = volume_attach_result['dev_addr']
            LOG.debug("Volume attach path is %s.", volume_attach_path)
        if volume_attach_path == '':
            msg = _("Host attach volume failed!")
            raise exception.VolumeBackendAPIException(data=msg)
            # Step2: fetch the image from image_service and write it to the
            # volume.
        try:
            image_utils.fetch_to_raw(context,
                                     image_service,
                                     image_id,
                                     volume_attach_path,
                                     self.configuration.volume_dd_blocksize)
        finally:
            # Step3: detach volume from host.
            dsw_manager_ip = self._get_dsware_manage_ip(volume)
            volume_detach_result = self._detach_volume(volume.name,
                                                       dsw_manager_ip)
            if volume_detach_result is not None and int(
                    volume_detach_result['ret_code']) != 0:
                msg = (_("Dsware detach volume from host failed: %s!") %
                       volume_detach_result)
                raise exception.VolumeBackendAPIException(data=msg)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        # Copy volume to image.
        # If volume was not attached, then attach it.

        dsw_manager_ip = self._get_dsware_manage_ip(volume)

        already_attached = False
        _attach_result = self._attach_volume(volume.name, dsw_manager_ip)
        if _attach_result:
            retcode = _attach_result['ret_code']
            if int(retcode) == VOLUME_ALREADY_ATTACHED:
                already_attached = True
                result = self._query_volume_attach(volume.name,
                                                   dsw_manager_ip)
                if not result or int(result['ret_code']) != 0:
                    msg = (_("Query volume attach failed, result=%s.") %
                           result)
                    raise exception.VolumeBackendAPIException(data=msg)

            elif int(retcode) == 0:
                result = _attach_result
            else:
                msg = (_("Attach volume to host failed "
                         "in copy volume to image, retcode: %s.") %
                       retcode)
                raise exception.VolumeBackendAPIException(data=msg)

            volume_attach_path = result['dev_addr']

        else:
            msg = _("Attach_volume failed.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        try:
            image_utils.upload_volume(context,
                                      image_service,
                                      image_meta,
                                      volume_attach_path)
        except Exception as e:
            LOG.error("Upload volume error, details: %s.", e)
            raise
        finally:
            if not already_attached:
                self._detach_volume(volume.name, dsw_manager_ip)

    def _get_volume(self, volume_name):
        result = self.dsware_client.query_volume(volume_name)
        LOG.debug("Dsware query volume result is %s.", result['result'])
        if result['result'] == VOLUME_NOT_EXIST:
            LOG.debug("Dsware volume %s does not exist.", volume_name)
            return False
        elif result['result'] == 0:
            return True
        else:
            msg = _("Dsware query volume %s failed!") % volume_name
            raise exception.VolumeBackendAPIException(data=msg)

    def _delete_volume(self, volume_name):
        # Delete volume in Dsware.
        result = self.dsware_client.delete_volume(volume_name)
        LOG.debug("Dsware delete volume, result is %s.", result)
        if result == VOLUME_NOT_EXIST:
            LOG.debug("Dsware delete volume, volume does not exist.")
            return True
        elif result == VOLUME_BEING_DELETED:
            LOG.debug("Dsware delete volume, volume is being deleted.")
            return True
        elif result == 0:
            return True
        else:
            msg = _("Dsware delete volume failed: %s!") % result
            raise exception.VolumeBackendAPIException(data=msg)

    def delete_volume(self, volume):
        # Delete volume.
        # If volume does not exist, then return.
        LOG.debug("Begin to delete volume in Dsware: %s.", volume.name)
        if not self._get_volume(volume.name):
            return True

        return self._delete_volume(volume.name)

    def _get_snapshot(self, snapshot_name):
        snapshot_info = self.dsware_client.query_snap(snapshot_name)
        LOG.debug("Get snapshot, snapshot_info is : %s.", snapshot_info)
        if snapshot_info['result'] == SNAP_NOT_EXIST:
            LOG.error('Snapshot: %s not found!', snapshot_name)
            return False
        elif snapshot_info['result'] == 0:
            return True
        else:
            msg = _("Dsware get snapshot failed!")
            raise exception.VolumeBackendAPIException(data=msg)

    def _create_snapshot(self, snapshot_id, volume_id):
        LOG.debug("Create snapshot %s to Dsware.", snapshot_id)
        smart_flag = 0
        res = self.dsware_client.create_snapshot(snapshot_id,
                                                 volume_id,
                                                 smart_flag)
        if res != 0:
            msg = _("Dsware Create Snapshot failed! Result: %s.") % res
            raise exception.VolumeBackendAPIException(data=msg)

    def _delete_snapshot(self, snapshot_id):
        LOG.debug("Delete snapshot %s to Dsware.", snapshot_id)
        res = self.dsware_client.delete_snapshot(snapshot_id)
        LOG.debug("Ddelete snapshot result is: %s.", res)
        if res != 0:
            raise exception.SnapshotIsBusy(snapshot_name=snapshot_id)

    def create_snapshot(self, snapshot):
        vol_id = 'volume-%s' % snapshot.volume_id
        snapshot_id = snapshot.name
        if not self._get_volume(vol_id):
            LOG.error('Create Snapshot, but volume: %s not found!', vol_id)
            raise exception.VolumeNotFound(volume_id=vol_id)
        else:
            self._create_snapshot(snapshot_id, vol_id)

    def delete_snapshot(self, snapshot):
        LOG.debug("Delete snapshot %s.", snapshot.name)
        snapshot_id = snapshot.name
        if self._get_snapshot(snapshot_id):
            self._delete_snapshot(snapshot_id)

    def _calculate_pool_info(self, pool_sets):
        filter = False
        pools_status = []
        reserved_percentage = self.configuration.reserved_percentage
        pool_id_filter = self.configuration.pool_id_filter
        LOG.debug("Filtered pool id is %s.", pool_id_filter)
        if pool_id_filter == []:
            for pool_info in pool_sets:
                pool = {}
                pool['pool_name'] = pool_info['pool_id']
                pool['total_capacity_gb'] = float(
                    pool_info['total_capacity']) / 1024
                pool['allocated_capacity_gb'] = float(
                    pool_info['used_capacity']) / 1024
                pool['free_capacity_gb'] = pool['total_capacity_gb'] - pool[
                    'allocated_capacity_gb']
                pool['QoS_support'] = False
                pool['reserved_percentage'] = reserved_percentage
                pools_status.append(pool)
        else:
            for pool_info in pool_sets:
                for pool_id in pool_id_filter:
                    if pool_id == pool_info['pool_id']:
                        filter = True
                        break

                if filter:
                    pool = {}
                    pool['pool_name'] = pool_info['pool_id']
                    pool['total_capacity_gb'] = float(
                        pool_info['total_capacity']) / 1024
                    pool['allocated_capacity_gb'] = float(
                        pool_info['used_capacity']) / 1024
                    pool['free_capacity_gb'] = float(
                        pool['total_capacity_gb'] - pool[
                            'allocated_capacity_gb'])
                    pool['QoS_support'] = False
                    pool['reserved_percentage'] = reserved_percentage
                    pools_status.append(pool)

                filter = False

        return pools_status

    def _update_single_pool_info_status(self):
        """Query pool info when Dsware is single-pool version."""
        status = {}
        status['volume_backend_name'] = self.configuration.volume_backend_name
        status['vendor_name'] = 'Open Source'
        status['driver_version'] = self.VERSION
        status['storage_protocol'] = 'dsware'

        status['total_capacity_gb'] = 0
        status['free_capacity_gb'] = 0
        status['reserved_percentage'] = self.configuration.reserved_percentage
        status['QoS_support'] = False
        pool_id = 0
        pool_info = self.dsware_client.query_pool_info(pool_id)
        result = pool_info['result']
        if result == 0:
            status['total_capacity_gb'] = float(
                pool_info['total_capacity']) / 1024
            status['free_capacity_gb'] = (float(
                pool_info['total_capacity']) - float(
                pool_info['used_capacity'])) / 1024
            LOG.debug("total_capacity_gb is %s, free_capacity_gb is %s.",
                      status['total_capacity_gb'],
                      status['free_capacity_gb'])
            self._stats = status
        else:
            self._stats = None

    def _update_multi_pool_of_same_type_status(self):
        """Query info of multiple pools when Dsware is multi-pool version.

        These pools have the same pool type.
        """
        status = {}
        status['volume_backend_name'] = self.configuration.volume_backend_name
        status['vendor_name'] = 'Open Source'
        status['driver_version'] = self.VERSION
        status['storage_protocol'] = 'dsware'

        (result, pool_sets) = self.dsware_client.query_pool_type(
            self.pool_type)
        if pool_sets == []:
            self._stats = None
        else:
            pools_status = self._calculate_pool_info(pool_sets)
            status['pools'] = pools_status
            self._stats = status

    def get_volume_stats(self, refresh=False):
        if refresh:
            dsware_version = self.dsware_client.query_dsware_version()
            # Old version.
            if dsware_version == OLD_VERSION:
                self._update_single_pool_info_status()
            # New version.
            elif dsware_version == NEW_VERSION:
                self._update_multi_pool_of_same_type_status()
            else:
                msg = _("Dsware query Dsware version failed!")
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        return self._stats

    def extend_volume(self, volume, new_size):
        # Extend volume in Dsware.
        LOG.debug("Begin to extend volume in Dsware: %s.", volume.name)
        volume_id = volume.name
        if volume.size > new_size:
            msg = (_("Dsware extend Volume failed! "
                     "New size %(new_size)s should be greater than "
                     "old size %(old_size)s!")
                   % {'new_size': new_size,
                      'old_size': volume.size})
            raise exception.VolumeBackendAPIException(data=msg)
        # Change GB to MB.
        volume_size = new_size * 1024
        result = self.dsware_client.extend_volume(volume_id, volume_size)
        if result != 0:
            msg = _("Dsware extend Volume failed! Result:%s.") % result
            raise exception.VolumeBackendAPIException(data=msg)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info."""
        LOG.debug("Begin initialize connection.")

        properties = {}
        properties['volume_name'] = volume.name
        properties['volume'] = volume
        properties['dsw_manager_ip'] = self._get_dsware_manage_ip(volume)

        LOG.debug("End initialize connection with properties:%s.", properties)

        return {'driver_volume_type': 'dsware',
                'data': properties}

    def terminate_connection(self, volume, connector, force=False, **kwargs):
        pass

    def create_export(self, context, volume, connector):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass
