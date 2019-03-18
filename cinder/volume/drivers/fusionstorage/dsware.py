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

import json

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.fusionstorage import fs_client
from cinder.volume.drivers.fusionstorage import fs_conf
from cinder.volume.drivers.san import san
from cinder.volume import utils as volume_utils

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.BoolOpt("dsware_isthin",
                default=False,
                help='The flag of thin storage allocation.',
                deprecated_for_removal=True,
                deprecated_since='14.0.0',
                deprecated_reason='FusionStorage cinder driver refactored the '
                                  'code with Restful method and the old CLI '
                                  'mode has been abandon. So those '
                                  'configuration items are no longer used.'),
    cfg.StrOpt("dsware_manager",
               default='',
               help='Fusionstorage manager ip addr for cinder-volume.',
               deprecated_for_removal=True,
               deprecated_since='14.0.0',
               deprecated_reason='FusionStorage cinder driver refactored the '
                                 'code with Restful method and the old CLI '
                                 'mode has been abandon. So those '
                                 'configuration items are no longer used.'),
    cfg.StrOpt('fusionstorageagent',
               default='',
               help='Fusionstorage agent ip addr range',
               deprecated_for_removal=True,
               deprecated_since='14.0.0',
               deprecated_reason='FusionStorage cinder driver refactored the '
                                 'code with Restful method and the old CLI '
                                 'mode has been abandon. So those '
                                 'configuration items are no longer used.'),
    cfg.StrOpt('pool_type',
               default='default',
               help='Pool type, like sata-2copy',
               deprecated_for_removal=True,
               deprecated_since='14.0.0',
               deprecated_reason='FusionStorage cinder driver refactored the '
                                 'code with Restful method and the old CLI '
                                 'mode has been abandon. So those '
                                 'configuration items are no longer used.'),
    cfg.ListOpt('pool_id_filter',
                default=[],
                help='Pool id permit to use',
                deprecated_for_removal=True,
                deprecated_since='14.0.0',
                deprecated_reason='FusionStorage cinder driver refactored the '
                                  'code with Restful method and the old CLI '
                                  'mode has been abandon. So those '
                                  'configuration items are no longer used.'),
    cfg.IntOpt('clone_volume_timeout',
               default=680,
               help='Create clone volume timeout',
               deprecated_for_removal=True,
               deprecated_since='14.0.0',
               deprecated_reason='FusionStorage cinder driver refactored the '
                                 'code with Restful method and the old CLI '
                                 'mode has been abandon. So those '
                                 'configuration items are no longer used.'),
    cfg.DictOpt('manager_ips',
                default={},
                help='This option is to support the FSA to mount across the '
                     'different nodes. The parameters takes the standard dict '
                     'config form, manager_ips = host1:ip1, host2:ip2...'),
    cfg.StrOpt('dsware_rest_url',
               default='',
               help='The address of FusionStorage array. For example, '
                    '"dsware_rest_url=xxx"'),
    cfg.StrOpt('dsware_storage_pools',
               default="",
               help='The list of pools on the FusionStorage array, the '
                    'semicolon(;) was used to split the storage pools, '
                    '"dsware_storage_pools = xxx1; xxx2; xxx3"')
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)


@interface.volumedriver
class DSWAREDriver(driver.VolumeDriver):
    VERSION = '2.0'
    CI_WIKI_NAME = 'Huawei_FusionStorage_CI'

    def __init__(self, *args, **kwargs):
        super(DSWAREDriver, self).__init__(*args, **kwargs)

        if not self.configuration:
            msg = _('Configuration is not found.')
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        self.configuration.append_config_values(volume_opts)
        self.configuration.append_config_values(san.san_opts)
        self.conf = fs_conf.FusionStorageConf(self.configuration, self.host)
        self.client = None

    @staticmethod
    def get_driver_options():
        return volume_opts

    def do_setup(self, context):
        self.conf.update_config_value()
        url_str = self.configuration.san_address
        url_user = self.configuration.san_user
        url_password = self.configuration.san_password

        self.client = fs_client.RestCommon(
            fs_address=url_str, fs_user=url_user,
            fs_password=url_password)
        self.client.login()

    def check_for_setup_error(self):
        all_pools = self.client.query_pool_info()
        all_pools_name = [p['poolName'] for p in all_pools
                          if p.get('poolName')]

        for pool in self.configuration.pools_name:
            if pool not in all_pools_name:
                msg = _('Storage pool %(pool)s does not exist '
                        'in the FusionStorage.') % {'pool': pool}
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

    def _update_pool_stats(self):
        backend_name = self.configuration.safe_get(
            'volume_backend_name') or self.__class__.__name__
        data = {"volume_backend_name": backend_name,
                "driver_version": "2.0.9",
                "QoS_support": False,
                "thin_provisioning_support": False,
                "pools": [],
                "vendor_name": "Huawei"
                }
        all_pools = self.client.query_pool_info()

        for pool in all_pools:
            if pool['poolName'] in self.configuration.pools_name:
                single_pool_info = self._update_single_pool_info_status(pool)
                data['pools'].append(single_pool_info)
        return data

    def _get_capacity(self, pool_info):
        pool_capacity = {}

        total = float(pool_info['totalCapacity']) / units.Ki
        free = (float(pool_info['totalCapacity']) -
                float(pool_info['usedCapacity'])) / units.Ki
        pool_capacity['total_capacity_gb'] = total
        pool_capacity['free_capacity_gb'] = free

        return pool_capacity

    def _update_single_pool_info_status(self, pool_info):
        status = {}
        capacity = self._get_capacity(pool_info=pool_info)
        status.update({
            "pool_name": pool_info['poolName'],
            "total_capacity_gb": capacity['total_capacity_gb'],
            "free_capacity_gb": capacity['free_capacity_gb'],
        })
        return status

    def get_volume_stats(self, refresh=False):
        self.client.keep_alive()
        stats = self._update_pool_stats()
        return stats

    def _check_volume_exist(self, volume):
        vol_name = self._get_vol_name(volume)
        result = self.client.query_volume_by_name(vol_name=vol_name)
        if result:
            return result

    def _raise_exception(self, msg):
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    def _get_pool_id(self, volume):
        pool_id = None
        pool_name = volume_utils.extract_host(volume.host, level='pool')
        all_pools = self.client.query_pool_info()
        for pool in all_pools:
            if pool_name == pool['poolName']:
                pool_id = pool['poolId']

        if pool_id is None:
            msg = _('Storage pool %(pool)s does not exist on the array. '
                    'Please check.') % {"pool": pool_id}
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)
        return pool_id

    def _get_vol_name(self, volume):
        provider_location = volume.get("provider_location", None)
        if provider_location:
            vol_name = json.loads(provider_location).get("name")
        else:
            vol_name = volume.name
        return vol_name

    def create_volume(self, volume):
        pool_id = self._get_pool_id(volume)
        vol_name = volume.name
        vol_size = volume.size
        vol_size *= units.Ki
        self.client.create_volume(
            pool_id=pool_id, vol_name=vol_name, vol_size=vol_size)

    def delete_volume(self, volume):
        vol_name = self._get_vol_name(volume)
        if self._check_volume_exist(volume):
            self.client.delete_volume(vol_name=vol_name)

    def extend_volume(self, volume, new_size):
        vol_name = self._get_vol_name(volume)
        if not self._check_volume_exist(volume):
            msg = _("Volume: %(vol_name)s does not exist!"
                    ) % {"vol_name": vol_name}
            self._raise_exception(msg)
        else:
            new_size *= units.Ki
            self.client.expand_volume(vol_name, new_size)

    def _check_snapshot_exist(self, volume, snapshot):
        pool_id = self._get_pool_id(volume)
        snapshot_name = self._get_snapshot_name(snapshot)
        result = self.client.query_snapshot_by_name(
            pool_id=pool_id, snapshot_name=snapshot_name)
        if result.get('totalNum'):
            return result

    def _get_snapshot_name(self, snapshot):
        provider_location = snapshot.get("provider_location", None)
        if provider_location:
            snapshot_name = json.loads(provider_location).get("name")
        else:
            snapshot_name = snapshot.name
        return snapshot_name

    def create_volume_from_snapshot(self, volume, snapshot):
        vol_name = self._get_vol_name(volume)
        snapshot_name = self._get_snapshot_name(snapshot)
        vol_size = volume.size

        if not self._check_snapshot_exist(snapshot.volume, snapshot):
            msg = _("Snapshot: %(name)s does not exist!"
                    ) % {"name": snapshot_name}
            self._raise_exception(msg)
        elif self._check_volume_exist(volume):
            msg = _("Volume: %(vol_name)s already exists!"
                    ) % {'vol_name': vol_name}
            self._raise_exception(msg)
        else:
            vol_size *= units.Ki
            self.client.create_volume_from_snapshot(
                snapshot_name=snapshot_name, vol_name=vol_name,
                vol_size=vol_size)

    def create_cloned_volume(self, volume, src_volume):
        vol_name = self._get_vol_name(volume)
        src_vol_name = self._get_vol_name(src_volume)

        vol_size = volume.size
        vol_size *= units.Ki

        if not self._check_volume_exist(src_volume):
            msg = _("Volume: %(vol_name)s does not exist!"
                    ) % {"vol_name": src_vol_name}
            self._raise_exception(msg)
        else:
            self.client.create_volume_from_volume(
                vol_name=vol_name, vol_size=vol_size,
                src_vol_name=src_vol_name)

    def create_snapshot(self, snapshot):
        snapshot_name = self._get_snapshot_name(snapshot)
        vol_name = self._get_vol_name(snapshot.volume)

        self.client.create_snapshot(
            snapshot_name=snapshot_name, vol_name=vol_name)

    def delete_snapshot(self, snapshot):
        snapshot_name = self._get_snapshot_name(snapshot)

        if self._check_snapshot_exist(snapshot.volume, snapshot):
            self.client.delete_snapshot(snapshot_name=snapshot_name)

    def _get_manager_ip(self, context):
        if self.configuration.manager_ips.get(context['host']):
            return self.configuration.manager_ips.get(context['host'])
        else:
            msg = _("The required host: %(host)s and its manager ip are not "
                    "included in the configuration file."
                    ) % {"host": context['host']}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)

    def _attach_volume(self, context, volume, properties, remote=False):
        vol_name = self._get_vol_name(volume)
        if not self._check_volume_exist(volume):
            msg = _("Volume: %(vol_name)s does not exist!"
                    ) % {"vol_name": vol_name}
            self._raise_exception(msg)
        manager_ip = self._get_manager_ip(properties)
        result = self.client.attach_volume(vol_name, manager_ip)
        attach_path = result[vol_name][0]['devName'].encode('unicode-escape')
        attach_info = dict()
        attach_info['device'] = dict()
        attach_info['device']['path'] = attach_path
        if attach_path == '':
            msg = _("Host attach volume failed!")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return attach_info, volume

    def _detach_volume(self, context, attach_info, volume, properties,
                       force=False, remote=False, ignore_errors=False):
        vol_name = self._get_vol_name(volume)
        if self._check_volume_exist(volume):
            manager_ip = self._get_manager_ip(properties)
            self.client.detach_volume(vol_name, manager_ip)

    def initialize_connection(self, volume, connector):
        vol_name = self._get_vol_name(volume)
        manager_ip = self._get_manager_ip(connector)
        if not self._check_volume_exist(volume):
            msg = _("Volume: %(vol_name)s does not exist!"
                    ) % {"vol_name": vol_name}
            self._raise_exception(msg)
        self.client.attach_volume(vol_name, manager_ip)
        volume_info = self.client.query_volume_by_name(vol_name=vol_name)
        vol_wwn = volume_info.get('wwn')
        by_id_path = "/dev/disk/by-id/" + "wwn-0x%s" % vol_wwn
        properties = {'device_path': by_id_path}
        return {'driver_volume_type': 'local',
                'data': properties}

    def terminate_connection(self, volume, connector, **kwargs):
        if self._check_volume_exist(volume):
            manager_ip = self._get_manager_ip(connector)
            vol_name = self._get_vol_name(volume)
            self.client.detach_volume(vol_name, manager_ip)

    def create_export(self, context, volume, connector):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass
