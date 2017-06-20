# Copyright (c) 2016 Huawei Technologies Co., Ltd.
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
#

import json

from oslo_log import log as logging
from oslo_utils import excutils

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.huawei import constants
from cinder.volume.drivers.huawei import huawei_utils

LOG = logging.getLogger(__name__)


class AbsReplicaOp(object):
    def __init__(self, client):
        self.client = client

    def create(self, **kwargs):
        pass

    def delete(self, replica_id):
        pass

    def protect_second(self, replica_id):
        pass

    def unprotect_second(self, replica_id):
        pass

    def sync(self, replica_id):
        pass

    def split(self, replica_id):
        pass

    def switch(self, replica_id):
        pass

    def is_primary(self, replica_info):
        flag = replica_info.get('ISPRIMARY')
        if flag and flag.lower() == 'true':
            return True
        return False

    def get_replica_info(self, replica_id):
        return {}

    def _is_status(self, status_key, status, replica_info):
        if type(status) in (list, tuple):
            return replica_info.get(status_key, '') in status
        if type(status) is str:
            return replica_info.get(status_key, '') == status

        return False

    def is_running_status(self, status, replica_info):
        return self._is_status(constants.REPLICA_RUNNING_STATUS_KEY,
                               status, replica_info)

    def is_health_status(self, status, replica_info):
        return self._is_status(constants.REPLICA_HEALTH_STATUS_KEY,
                               status, replica_info)


class PairOp(AbsReplicaOp):
    def create(self, local_lun_id, rmt_lun_id, rmt_dev_id,
               rmt_dev_name, replica_model,
               speed=constants.REPLICA_SPEED,
               period=constants.REPLICA_PERIOD,
               **kwargs):
        super(PairOp, self).create(**kwargs)

        params = {
            "LOCALRESID": local_lun_id,
            "LOCALRESTYPE": '11',
            "REMOTEDEVICEID": rmt_dev_id,
            "REMOTEDEVICENAME": rmt_dev_name,
            "REMOTERESID": rmt_lun_id,
            "REPLICATIONMODEL": replica_model,
            # recovery policy. 1: auto, 2: manual
            "RECOVERYPOLICY": '1',
            "SPEED": speed,
        }

        if replica_model == constants.REPLICA_ASYNC_MODEL:
            # Synchronize type values:
            # 1, manual
            # 2, timed wait when synchronization begins
            # 3, timed wait when synchronization ends
            params['SYNCHRONIZETYPE'] = '2'
            params['TIMINGVAL'] = period

        try:
            pair_info = self.client.create_pair(params)
        except Exception as err:
            msg = _('Create replication pair failed. Error: %s.') % err
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return pair_info

    def split(self, pair_id):
        self.client.split_pair(pair_id)

    def delete(self, pair_id, force=False):
        self.client.delete_pair(pair_id, force)

    def protect_second(self, pair_id):
        self.client.set_pair_second_access(pair_id,
                                           constants.REPLICA_SECOND_RO)

    def unprotect_second(self, pair_id):
        self.client.set_pair_second_access(pair_id,
                                           constants.REPLICA_SECOND_RW)

    def sync(self, pair_id):
        self.client.sync_pair(pair_id)

    def switch(self, pair_id):
        self.client.switch_pair(pair_id)

    def get_replica_info(self, pair_id):
        return self.client.get_pair_by_id(pair_id)


class CGOp(AbsReplicaOp):
    pass


class ReplicaCommonDriver(object):
    def __init__(self, conf, replica_op):
        self.conf = conf
        self.op = replica_op

    def protect_second(self, replica_id):
        info = self.op.get_replica_info(replica_id)
        if info.get('SECRESACCESS') == constants.REPLICA_SECOND_RO:
            return

        self.op.protect_second(replica_id)
        self.wait_second_access(replica_id, constants.REPLICA_SECOND_RO)

    def unprotect_second(self, replica_id):
        info = self.op.get_replica_info(replica_id)
        if info.get('SECRESACCESS') == constants.REPLICA_SECOND_RW:
            return

        self.op.unprotect_second(replica_id)
        self.wait_second_access(replica_id, constants.REPLICA_SECOND_RW)

    def sync(self, replica_id, wait_complete=False):
        self.protect_second(replica_id)

        expect_status = (constants.REPLICA_RUNNING_STATUS_NORMAL,
                         constants.REPLICA_RUNNING_STATUS_SYNC,
                         constants.REPLICA_RUNNING_STATUS_INITIAL_SYNC)
        info = self.op.get_replica_info(replica_id)

        # When running status is synchronizing or normal,
        # it's not necessary to do synchronize again.
        if (info.get('REPLICATIONMODEL') == constants.REPLICA_SYNC_MODEL
                and self.op.is_running_status(expect_status, info)):
            return

        self.op.sync(replica_id)
        self.wait_expect_state(replica_id, expect_status)

        if wait_complete:
            self.wait_replica_ready(replica_id)

    def split(self, replica_id):
        running_status = (constants.REPLICA_RUNNING_STATUS_SPLIT,
                          constants.REPLICA_RUNNING_STATUS_INVALID,
                          constants.REPLICA_RUNNING_STATUS_ERRUPTED)
        info = self.op.get_replica_info(replica_id)
        if self.op.is_running_status(running_status, info):
            return

        try:
            self.op.split(replica_id)
        except Exception as err:
            LOG.warning('Split replication exception: %s.', err)

        try:
            self.wait_expect_state(replica_id, running_status)
        except Exception as err:
            msg = _('Split replication failed.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def enable(self, replica_id, wait_sync_complete=False):
        info = self.op.get_replica_info(replica_id)
        if not self.op.is_primary(info):
            self.switch(replica_id)
        self.sync(replica_id)
        return None

    def switch(self, replica_id):
        self.split(replica_id)
        self.unprotect_second(replica_id)
        self.op.switch(replica_id)

        # Wait to be primary
        def _wait_switch_to_primary():
            info = self.op.get_replica_info(replica_id)
            if self.op.is_primary(info):
                return True
            return False

        interval = constants.DEFAULT_REPLICA_WAIT_INTERVAL
        timeout = constants.DEFAULT_REPLICA_WAIT_TIMEOUT
        huawei_utils.wait_for_condition(_wait_switch_to_primary,
                                        interval,
                                        timeout)

    def failover(self, replica_id):
        """Failover replication.

        Purpose:
            1. Split replication.
            2. Set secondary access read & write.
        """
        info = self.op.get_replica_info(replica_id)
        if self.op.is_primary(info):
            msg = _('We should not do switch over on primary array.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        sync_status_set = (constants.REPLICA_RUNNING_STATUS_SYNC,
                           constants.REPLICA_RUNNING_STATUS_INITIAL_SYNC)
        if self.op.is_running_status(sync_status_set, info):
            self.wait_replica_ready(replica_id)

        self.split(replica_id)
        self.op.unprotect_second(replica_id)

    def wait_replica_ready(self, replica_id, interval=None, timeout=None):
        LOG.debug('Wait synchronize complete.')
        running_status_normal = (constants.REPLICA_RUNNING_STATUS_NORMAL,
                                 constants.REPLICA_RUNNING_STATUS_SYNCED)
        running_status_sync = (constants.REPLICA_RUNNING_STATUS_SYNC,
                               constants.REPLICA_RUNNING_STATUS_INITIAL_SYNC)
        health_status_normal = constants.REPLICA_HEALTH_STATUS_NORMAL

        def _replica_ready():
            info = self.op.get_replica_info(replica_id)
            if (self.op.is_running_status(running_status_normal, info)
                    and self.op.is_health_status(health_status_normal, info)):
                return True

            if not self.op.is_running_status(running_status_sync, info):
                msg = (_('Wait synchronize failed. Running status: %s.') %
                       info.get(constants.REPLICA_RUNNING_STATUS_KEY))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            return False

        if not interval:
            interval = constants.DEFAULT_WAIT_INTERVAL
        if not timeout:
            timeout = constants.DEFAULT_WAIT_TIMEOUT

        huawei_utils.wait_for_condition(_replica_ready,
                                        interval,
                                        timeout)

    def wait_second_access(self, replica_id, access_level):
        def _check_access():
            info = self.op.get_replica_info(replica_id)
            if info.get('SECRESACCESS') == access_level:
                return True
            return False

        interval = constants.DEFAULT_REPLICA_WAIT_INTERVAL
        timeout = constants.DEFAULT_REPLICA_WAIT_TIMEOUT
        huawei_utils.wait_for_condition(_check_access,
                                        interval,
                                        timeout)

    def wait_expect_state(self, replica_id,
                          running_status, health_status=None,
                          interval=None, timeout=None):
        def _check_state():
            info = self.op.get_replica_info(replica_id)
            if self.op.is_running_status(running_status, info):
                if (not health_status
                        or self.op.is_health_status(health_status, info)):
                    return True
            return False

        if not interval:
            interval = constants.DEFAULT_REPLICA_WAIT_INTERVAL
        if not timeout:
            timeout = constants.DEFAULT_REPLICA_WAIT_TIMEOUT

        huawei_utils.wait_for_condition(_check_state, interval, timeout)


def get_replication_driver_data(volume):
    if volume.replication_driver_data:
        return json.loads(volume.replication_driver_data)
    return {}


def to_string(dict_data):
    if dict_data:
        return json.dumps(dict_data)
    return ''


class ReplicaPairManager(object):
    def __init__(self, local_client, rmt_client, conf):
        self.local_client = local_client
        self.rmt_client = rmt_client
        self.conf = conf

        # Now just support one remote pool.
        self.rmt_pool = self.rmt_client.storage_pools[0]

        self.local_op = PairOp(self.local_client)
        self.local_driver = ReplicaCommonDriver(self.conf, self.local_op)
        self.rmt_op = PairOp(self.rmt_client)
        self.rmt_driver = ReplicaCommonDriver(self.conf, self.rmt_op)

    def try_get_remote_wwn(self):
        try:
            info = self.rmt_client.get_array_info()
            return info.get('wwn')
        except Exception as err:
            LOG.warning('Get remote array wwn failed. Error: %s.', err)
            return None

    def get_remote_device_by_wwn(self, wwn):
        devices = {}
        try:
            devices = self.local_client.get_remote_devices()
        except Exception as err:
            LOG.warning('Get remote devices failed. Error: %s.', err)

        for device in devices:
            if device.get('WWN') == wwn:
                return device

        return {}

    def check_remote_available(self):
        # We get device wwn in every check time.
        # If remote array changed, we can run normally.
        wwn = self.try_get_remote_wwn()
        if not wwn:
            return False

        device = self.get_remote_device_by_wwn(wwn)
        # Check remote device is available to use.
        # If array type is replication, 'ARRAYTYPE' == '1'.
        # If health status is normal, 'HEALTHSTATUS' == '1'.
        if (device and device.get('ARRAYTYPE') == '1'
                and device.get('HEALTHSTATUS') == '1'
                and device.get('RUNNINGSTATUS') == constants.STATUS_RUNNING):
            return True

        return False

    def update_replica_capability(self, stats):
        is_rmt_dev_available = self.check_remote_available()
        if not is_rmt_dev_available:
            LOG.warning('Remote device is unavailable.')
            return stats

        for pool in stats['pools']:
            pool['replication_enabled'] = True
            pool['replication_type'] = ['sync', 'async']

        return stats

    def get_rmt_dev_info(self):
        wwn = self.try_get_remote_wwn()
        if not wwn:
            return None, None

        device = self.get_remote_device_by_wwn(wwn)
        if not device:
            return None, None

        return device.get('ID'), device.get('NAME')

    def build_rmt_lun_params(self, local_lun_info):
        params = {
            'TYPE': '11',
            'NAME': local_lun_info['NAME'],
            'PARENTTYPE': '216',
            'PARENTID': self.rmt_client.get_pool_id(self.rmt_pool),
            'DESCRIPTION': local_lun_info['DESCRIPTION'],
            'ALLOCTYPE': local_lun_info['ALLOCTYPE'],
            'CAPACITY': local_lun_info['CAPACITY'],
            'WRITEPOLICY': self.conf.lun_write_type,
            'PREFETCHPOLICY': self.conf.lun_prefetch_type,
            'PREFETCHVALUE': self.conf.lun_prefetch_value,
            'DATATRANSFERPOLICY': self.conf.lun_policy,
            'READCACHEPOLICY': self.conf.lun_read_cache_policy,
            'WRITECACHEPOLICY': self.conf.lun_write_cache_policy,
        }

        LOG.debug('Remote lun params: %s.', params)
        return params

    def wait_volume_online(self, client, lun_info,
                           interval=None, timeout=None):
        online_status = constants.STATUS_VOLUME_READY
        if lun_info.get('RUNNINGSTATUS') == online_status:
            return

        lun_id = lun_info['ID']

        def _wait_online():
            info = client.get_lun_info(lun_id)
            return info.get('RUNNINGSTATUS') == online_status

        if not interval:
            interval = constants.DEFAULT_REPLICA_WAIT_INTERVAL
        if not timeout:
            timeout = constants.DEFAULT_REPLICA_WAIT_TIMEOUT

        huawei_utils.wait_for_condition(_wait_online,
                                        interval,
                                        timeout)

    def create_rmt_lun(self, local_lun_info):
        # Create on rmt array. If failed, raise exception.
        lun_params = self.build_rmt_lun_params(local_lun_info)
        lun_info = self.rmt_client.create_lun(lun_params)
        try:
            self.wait_volume_online(self.rmt_client, lun_info)
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                self.rmt_client.delete_lun(lun_info['ID'])

        return lun_info

    def create_replica(self, local_lun_info, replica_model):
        """Create remote LUN and replication pair.

        Purpose:
            1. create remote lun
            2. create replication pair
            3. enable replication pair
        """
        LOG.debug(('Create replication, local lun info: %(info)s, '
                   'replication model: %(model)s.'),
                  {'info': local_lun_info, 'model': replica_model})

        local_lun_id = local_lun_info['ID']
        self.wait_volume_online(self.local_client, local_lun_info)

        # step1, create remote lun
        rmt_lun_info = self.create_rmt_lun(local_lun_info)
        rmt_lun_id = rmt_lun_info['ID']

        # step2, get remote device info
        rmt_dev_id, rmt_dev_name = self.get_rmt_dev_info()
        if not rmt_lun_id or not rmt_dev_name:
            self._delete_rmt_lun(rmt_lun_id)
            msg = _('Get remote device info failed.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # step3, create replication pair
        try:
            pair_info = self.local_op.create(local_lun_id,
                                             rmt_lun_id, rmt_dev_id,
                                             rmt_dev_name, replica_model)
            pair_id = pair_info['ID']
        except Exception as err:
            with excutils.save_and_reraise_exception():
                LOG.error('Create pair failed. Error: %s.', err)
                self._delete_rmt_lun(rmt_lun_id)

        # step4, start sync manually. If replication type is sync,
        # then wait for sync complete.
        wait_complete = (replica_model == constants.REPLICA_SYNC_MODEL)
        try:
            self.local_driver.sync(pair_id, wait_complete)
        except Exception as err:
            with excutils.save_and_reraise_exception():
                LOG.error('Start synchronization failed. Error: %s.', err)
                self._delete_pair(pair_id)
                self._delete_rmt_lun(rmt_lun_id)

        model_update = {}
        driver_data = {'pair_id': pair_id,
                       'rmt_lun_id': rmt_lun_id,
                       'rmt_lun_wwn': rmt_lun_info['WWN']}
        model_update['replication_driver_data'] = to_string(driver_data)
        model_update['replication_status'] = 'available'
        LOG.debug('Create replication, return info: %s.', model_update)
        return model_update

    def _delete_pair(self, pair_id):
        if (not pair_id
                or not self.local_client.check_pair_exist(pair_id)):
            return

        self.local_driver.split(pair_id)
        self.local_op.delete(pair_id)

    def _delete_rmt_lun(self, lun_id):
        if lun_id and self.rmt_client.check_lun_exist(lun_id):
            self.rmt_client.delete_lun(lun_id)

    def delete_replica(self, volume):
        """Delete replication pair and remote lun.

        Purpose:
            1. delete replication pair
            2. delete remote_lun
        """
        LOG.debug('Delete replication, volume: %s.', volume.id)
        info = get_replication_driver_data(volume)
        pair_id = info.get('pair_id')
        if pair_id:
            self._delete_pair(pair_id)

        # Delete remote_lun
        rmt_lun_id = info.get('rmt_lun_id')
        if rmt_lun_id:
            self._delete_rmt_lun(rmt_lun_id)

    def failback(self, volumes):
        """Failover volumes back to primary backend.

        The main steps:
        1. Switch the role of replication pairs.
        2. Copy the second LUN data back to primary LUN.
        3. Split replication pairs.
        4. Switch the role of replication pairs.
        5. Enable replications.
        """
        volumes_update = []
        for v in volumes:
            v_update = {}
            v_update['volume_id'] = v.id
            drv_data = get_replication_driver_data(v)
            pair_id = drv_data.get('pair_id')
            if not pair_id:
                LOG.warning("No pair id in volume %s.", v.id)
                v_update['updates'] = {'replication_status': 'error'}
                volumes_update.append(v_update)
                continue

            rmt_lun_id = drv_data.get('rmt_lun_id')
            if not rmt_lun_id:
                LOG.warning("No remote lun id in volume %s.", v.id)
                v_update['updates'] = {'replication_status': 'error'}
                volumes_update.append(v_update)
                continue

            # Switch replication pair role, and start synchronize.
            self.local_driver.enable(pair_id)

            # Wait for synchronize complete.
            self.local_driver.wait_replica_ready(pair_id)

            # Split replication pair again
            self.rmt_driver.failover(pair_id)

            # Switch replication pair role, and start synchronize.
            self.rmt_driver.enable(pair_id)

            local_metadata = huawei_utils.get_lun_metadata(v)
            new_drv_data = to_string(
                {'pair_id': pair_id,
                 'rmt_lun_id': local_metadata.get('huawei_lun_id'),
                 'rmt_lun_wwn': local_metadata.get('huawei_lun_wwn')})
            location = huawei_utils.to_string(
                huawei_lun_id=rmt_lun_id,
                huawei_lun_wwn=drv_data.get('rmt_lun_wwn'))

            v_update['updates'] = {'provider_location': location,
                                   'replication_status': 'available',
                                   'replication_driver_data': new_drv_data}
            volumes_update.append(v_update)

        return volumes_update

    def failover(self, volumes):
        """Failover volumes back to secondary array.

        Split the replication pairs and make the secondary LUNs R&W.
        """
        volumes_update = []
        for v in volumes:
            v_update = {}
            v_update['volume_id'] = v.id
            drv_data = get_replication_driver_data(v)
            pair_id = drv_data.get('pair_id')
            if not pair_id:
                LOG.warning("No pair id in volume %s.", v.id)
                v_update['updates'] = {'replication_status': 'error'}
                volumes_update.append(v_update)
                continue

            rmt_lun_id = drv_data.get('rmt_lun_id')
            if not rmt_lun_id:
                LOG.warning("No remote lun id in volume %s.", v.id)
                v_update['updates'] = {'replication_status': 'error'}
                volumes_update.append(v_update)
                continue

            self.rmt_driver.failover(pair_id)

            local_metadata = huawei_utils.get_lun_metadata(v)
            new_drv_data = to_string(
                {'pair_id': pair_id,
                 'rmt_lun_id': local_metadata.get('huawei_lun_id'),
                 'rmt_lun_wwn': local_metadata.get('huawei_lun_wwn')})
            location = huawei_utils.to_string(
                huawei_lun_id=rmt_lun_id,
                huawei_lun_wwn=drv_data.get('rmt_lun_wwn'))

            v_update['updates'] = {'provider_location': location,
                                   'replication_status': 'failed-over',
                                   'replication_driver_data': new_drv_data}
            volumes_update.append(v_update)

        return volumes_update


def get_replication_opts(opts):
    if opts.get('replication_type') == 'sync':
        opts['replication_type'] = constants.REPLICA_SYNC_MODEL
    else:
        opts['replication_type'] = constants.REPLICA_ASYNC_MODEL

    return opts
