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

import json

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume.drivers.huawei import constants

LOG = logging.getLogger(__name__)


class SmartQos(object):
    def __init__(self, client):
        self.client = client

    def _check_qos_consistency(self, policy, qos):
        for key in [k.upper() for k in constants.QOS_SPEC_KEYS]:
            if qos.get(key, '0') != policy.get(key, '0'):
                return False
        return True

    def _change_lun_priority(self, qos, lun_id):
        for key in qos:
            if key.startswith('MIN') or key.startswith('LATENCY'):
                data = {"IOPRIORITY": "3"}
                self.client.update_lun(lun_id, data)
                break

    @utils.synchronized('huawei_qos', external=True)
    def add(self, qos, lun_id):
        self._change_lun_priority(qos, lun_id)
        qos_id = self.client.create_qos(qos, lun_id)
        try:
            self.client.activate_deactivate_qos(qos_id, True)
        except exception.VolumeBackendAPIException:
            self.remove(qos_id, lun_id)
            raise

        return qos_id

    @utils.synchronized('huawei_qos', external=True)
    def remove(self, qos_id, lun_id, qos_info=None):
        if not qos_info:
            qos_info = self.client.get_qos_info(qos_id)
        lun_list = json.loads(qos_info['LUNLIST'])
        if lun_id in lun_list:
            lun_list.remove(lun_id)

        if len(lun_list) == 0:
            if qos_info['RUNNINGSTATUS'] != constants.QOS_INACTIVATED:
                self.client.activate_deactivate_qos(qos_id, False)
            self.client.delete_qos(qos_id)
        else:
            self.client.update_qos_luns(qos_id, lun_list)

    def update(self, qos_id, new_qos, lun_id):
        qos_info = self.client.get_qos_info(qos_id)
        if self._check_qos_consistency(qos_info, new_qos):
            return

        self.remove(qos_id, lun_id, qos_info)
        self.add(new_qos, lun_id)


class SmartPartition(object):
    def __init__(self, client):
        self.client = client

    def add(self, partitionname, lun_id):
        partition_id = self.client.get_partition_id_by_name(partitionname)
        if not partition_id:
            msg = _('Cannot find partition by name %s.') % partitionname
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        self.client.add_lun_to_partition(lun_id, partition_id)
        return partition_id

    def remove(self, partition_id, lun_id):
        self.client.remove_lun_from_partition(lun_id, partition_id)

    def update(self, partition_id, partitionname, lun_id):
        partition_info = self.client.get_partition_info_by_id(partition_id)
        if partition_info['NAME'] == partitionname:
            return

        self.remove(partition_id, lun_id)
        self.add(partitionname, lun_id)

    def check_partition_valid(self, partitionname):
        partition_id = self.client.get_partition_id_by_name(partitionname)
        if not partition_id:
            msg = _("Partition %s doesn't exist.") % partitionname
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)


class SmartCache(object):
    def __init__(self, client):
        self.client = client

    def add(self, cachename, lun_id):
        cache_id = self.client.get_cache_id_by_name(cachename)
        if not cache_id:
            msg = _('Cannot find cache by name %s.') % cachename
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        self.client.add_lun_to_cache(lun_id, cache_id)
        return cache_id

    def remove(self, cache_id, lun_id):
        self.client.remove_lun_from_cache(lun_id, cache_id)

    def update(self, cache_id, cachename, lun_id):
        cache_info = self.client.get_cache_info_by_id(cache_id)
        if cache_info['NAME'] == cachename:
            return

        self.remove(cache_id, lun_id)
        self.add(cachename, lun_id)

    def check_cache_valid(self, cachename):
        cache_id = self.client.get_cache_id_by_name(cachename)
        if not cache_id:
            msg = _("Cache %s doesn't exit.") % cachename
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)
