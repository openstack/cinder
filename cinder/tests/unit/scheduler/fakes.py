# Copyright 2011 OpenStack Foundation
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
Fakes For Scheduler tests.
"""
import copy

from oslo_utils import timeutils
from oslo_utils import uuidutils

from cinder.scheduler import filter_scheduler
from cinder.scheduler import host_manager
from cinder.volume import utils


UTC_NOW = timeutils.utcnow()

SERVICE_STATES = {
    'host1': {'total_capacity_gb': 1024,
              'free_capacity_gb': 1024,
              'allocated_capacity_gb': 0,
              'provisioned_capacity_gb': 0,
              'max_over_subscription_ratio': '1.0',
              'thin_provisioning_support': False,
              'thick_provisioning_support': True,
              'reserved_percentage': 10,
              'volume_backend_name': 'lvm1',
              'timestamp': UTC_NOW,
              'multiattach': True,
              'online_extend_support': True,
              'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'},
    'host2': {'total_capacity_gb': 2048,
              'free_capacity_gb': 300,
              'allocated_capacity_gb': 1748,
              'provisioned_capacity_gb': 1748,
              'max_over_subscription_ratio': '1.5',
              'thin_provisioning_support': True,
              'thick_provisioning_support': False,
              'reserved_percentage': 10,
              'volume_backend_name': 'lvm2',
              'timestamp': UTC_NOW,
              'online_extend_support': False,
              'uuid': '4200b32b-0bf9-436c-86b2-0675f6ac218e'},
    'host3': {'total_capacity_gb': 512,
              'free_capacity_gb': 256,
              'allocated_capacity_gb': 256,
              'provisioned_capacity_gb': 256,
              'max_over_subscription_ratio': '2.0',
              'thin_provisioning_support': False,
              'thick_provisioning_support': True,
              'reserved_percentage': 0,
              'volume_backend_name': 'lvm3',
              'timestamp': UTC_NOW,
              'uuid': '6d91e7f5-ca17-4e3b-bf4f-19ca77166dd7'},
    'host4': {'total_capacity_gb': 2048,
              'free_capacity_gb': 200,
              'allocated_capacity_gb': 1848,
              'provisioned_capacity_gb': 2047,
              'max_over_subscription_ratio': '1.0',
              'thin_provisioning_support': True,
              'thick_provisioning_support': False,
              'reserved_percentage': 5,
              'volume_backend_name': 'lvm4',
              'timestamp': UTC_NOW,
              'consistent_group_snapshot_enabled': True,
              'uuid': '18417850-2ca9-43d1-9619-ae16bfb0f655'},
    'host5': {'total_capacity_gb': 'infinite',
              'free_capacity_gb': 'unknown',
              'allocated_capacity_gb': 1548,
              'provisioned_capacity_gb': 1548,
              'max_over_subscription_ratio': '1.0',
              'thin_provisioning_support': True,
              'thick_provisioning_support': False,
              'reserved_percentage': 5,
              'timestamp': UTC_NOW,
              'uuid': 'f838f35c-4035-464f-9792-ce60e390c13d'},
}

SERVICE_STATES_WITH_POOLS = {
    'host1@BackendA': {
        'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824',
        'replication_enabled': False,
        'driver_version': '1.0.0',
        'volume_backend_name': 'BackendA',
        'pools': [
            {
                'total_capacity_gb': 1024,
                'free_capacity_gb': 1024,
                'allocated_capacity_gb': 0,
                'provisioned_capacity_gb': 0,
                'max_over_subscription_ratio': '1.0',
                'thin_provisioning_support': False,
                'thick_provisioning_support': True,
                'reserved_percentage': 15,
                'pool_name': 'openstack_iscsi_1',
            },
            {
                'total_capacity_gb': 2048,
                'free_capacity_gb': 1008,
                'allocated_capacity_gb': 0,
                'provisioned_capacity_gb': 0,
                'max_over_subscription_ratio': '1.0',
                'thin_provisioning_support': True,
                'thick_provisioning_support': False,
                'reserved_percentage': 15,
                'pool_name': 'openstack_iscsi_2',
            },

        ],
        'storage_protocol': 'iSCSI',
        'timestamp': UTC_NOW,
    },
    'host1@BackendB': {
        'replication_enabled': True,
        'driver_version': '1.5.0',
        'volume_backend_name': 'BackendB',
        'uuid': '4200b32b-0bf9-436c-86b2-0675f6ac218e',
        'pools': [
            {
                'total_capacity_gb': 2048,
                'free_capacity_gb': 300,
                'allocated_capacity_gb': 1748,
                'provisioned_capacity_gb': 1748,
                'max_over_subscription_ratio': '1.5',
                'thin_provisioning_support': True,
                'thick_provisioning_support': False,
                'reserved_percentage': 10,
                'pool_name': 'openstack_nfs_1',
            },
            {
                'total_capacity_gb': 512,
                'free_capacity_gb': 256,
                'allocated_capacity_gb': 256,
                'provisioned_capacity_gb': 256,
                'max_over_subscription_ratio': '2.0',
                'thin_provisioning_support': True,
                'thick_provisioning_support': False,
                'reserved_percentage': 10,
                'pool_name': 'openstack_nfs_2',
            },

        ],
        'storage_protocol': 'nfs',
        'timestamp': UTC_NOW,
    },
    'host2@BackendX': {
        'replication_enabled': False,
        'driver_version': '3.5.1',
        'total_capacity_gb': 512,
        'free_capacity_gb': 256,
        'allocated_capacity_gb': 256,
        'provisioned_capacity_gb': 256,
        'max_over_subscription_ratio': '2.0',
        'thin_provisioning_support': False,
        'thick_provisioning_support': True,
        'reserved_percentage': 0,
        'volume_backend_name': 'BackendX',
        'storage_protocol': 'iSCSI',
        'timestamp': UTC_NOW,
        'uuid': '6d91e7f5-ca17-4e3b-bf4f-19ca77166dd7'
    },
    'host3@BackendY': {
        'replication_enabled': True,
        'driver_version': '1.5.0',
        'volume_backend_name': 'BackendY',
        'uuid': '18417850-2ca9-43d1-9619-ae16bfb0f655',
        'pools': [
            {
                'total_capacity_gb': 'infinite',
                'free_capacity_gb': 'unknown',
                'allocated_capacity_gb': 170,
                'provisioned_capacity_gb': 170,
                'max_over_subscription_ratio': '1.0',
                'thin_provisioning_support': False,
                'thick_provisioning_support': True,
                'QoS_support': True,
                'reserved_percentage': 0,
                'pool_name': 'openstack_fcp_1',
            },
            {
                'total_capacity_gb': 'infinite',
                'free_capacity_gb': 'unknown',
                'allocated_capacity_gb': 1548,
                'provisioned_capacity_gb': 1548,
                'max_over_subscription_ratio': '1.0',
                'thin_provisioning_support': True,
                'thick_provisioning_support': False,
                'QoS_support': True,
                'reserved_percentage': 0,
                'pool_name': 'openstack_fcp_2',
            },

        ],
        'storage_protocol': 'fc',
        'timestamp': UTC_NOW,
    }
}


class FakeFilterScheduler(filter_scheduler.FilterScheduler):
    def __init__(self, *args, **kwargs):
        super(FakeFilterScheduler, self).__init__(*args, **kwargs)
        self.host_manager = host_manager.HostManager()


class FakeHostManager(host_manager.HostManager):
    def __init__(self, multibackend_with_pools=False):
        super(FakeHostManager, self).__init__()

        self.service_states = copy.deepcopy(
            SERVICE_STATES_WITH_POOLS if multibackend_with_pools
            else SERVICE_STATES
        )


class FakeBackendState(host_manager.BackendState):
    def __init__(self, host, attribute_dict):
        super(FakeBackendState, self).__init__(host, None)
        for (key, val) in attribute_dict.items():
            setattr(self, key, val)


class FakeNovaClient(object):
    class Server(object):
        def __init__(self, host):
            self.uuid = uuidutils.generate_uuid()
            self.host = host
            setattr(self, 'OS-EXT-SRV-ATTR:host', host)

    class ServerManager(object):
        def __init__(self):
            self._servers = []

        def create(self, host):
            self._servers.append(FakeNovaClient.Server(host))
            return self._servers[-1].uuid

        def get(self, server_uuid):
            for s in self._servers:
                if s.uuid == server_uuid:
                    return s
            return None

        def list(self, detailed=True, search_opts=None):
            matching = list(self._servers)
            if search_opts:
                for opt, val in search_opts.items():
                    matching = [m for m in matching
                                if getattr(m, opt, None) == val]
            return matching

    class ListExtResource(object):
        def __init__(self, ext_name):
            self.name = ext_name

    class ListExtManager(object):
        def __init__(self, ext_srv_attr=True):
            self.ext_srv_attr = ext_srv_attr

        def show_all(self):
            if self.ext_srv_attr:
                return [
                    FakeNovaClient.ListExtResource('ExtendedServerAttributes')]
            return []

    def __init__(self, ext_srv_attr=True):
        self.servers = FakeNovaClient.ServerManager()
        self.list_extensions = FakeNovaClient.ListExtManager(
            ext_srv_attr=ext_srv_attr)


def mock_host_manager_db_calls(mock_obj, backends_with_pools=False,
                               disabled=None):
    service_states = (
        SERVICE_STATES_WITH_POOLS if backends_with_pools else SERVICE_STATES
    )
    services = []
    az_map = {
        'host1': 'zone1',
        'host2': 'zone1',
        'host3': 'zone2',
        'host4': 'zone3',
        'host5': 'zone3',
    }
    sid = 0
    for svc, state in service_states.items():
        sid += 1
        services.append(
            {
                'id': sid,
                'host': svc,
                'availability_zone': az_map[utils.extract_host(svc, 'host')],
                'topic': 'volume',
                'disabled': False,
                'updated_at': timeutils.utcnow(),
                'uuid': state.get('uuid', uuidutils.generate_uuid()),
            }
        )

    if disabled is None:
        mock_obj.return_value = services
    else:
        mock_obj.return_value = [service for service in services
                                 if service['disabled'] == disabled]
