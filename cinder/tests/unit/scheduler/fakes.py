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

from oslo_utils import timeutils
from oslo_utils import uuidutils

from cinder.scheduler import filter_scheduler
from cinder.scheduler import host_manager


UTC_NOW = timeutils.utcnow()


class FakeFilterScheduler(filter_scheduler.FilterScheduler):
    def __init__(self, *args, **kwargs):
        super(FakeFilterScheduler, self).__init__(*args, **kwargs)
        self.host_manager = host_manager.HostManager()


class FakeHostManager(host_manager.HostManager):
    def __init__(self):
        super(FakeHostManager, self).__init__()

        self.service_states = {
            'host1': {'total_capacity_gb': 1024,
                      'free_capacity_gb': 1024,
                      'allocated_capacity_gb': 0,
                      'provisioned_capacity_gb': 0,
                      'max_over_subscription_ratio': 1.0,
                      'thin_provisioning_support': False,
                      'thick_provisioning_support': True,
                      'reserved_percentage': 10,
                      'volume_backend_name': 'lvm1',
                      'timestamp': UTC_NOW,
                      'multiattach': True},
            'host2': {'total_capacity_gb': 2048,
                      'free_capacity_gb': 300,
                      'allocated_capacity_gb': 1748,
                      'provisioned_capacity_gb': 1748,
                      'max_over_subscription_ratio': 1.5,
                      'thin_provisioning_support': True,
                      'thick_provisioning_support': False,
                      'reserved_percentage': 10,
                      'volume_backend_name': 'lvm2',
                      'timestamp': UTC_NOW},
            'host3': {'total_capacity_gb': 512,
                      'free_capacity_gb': 256,
                      'allocated_capacity_gb': 256,
                      'provisioned_capacity_gb': 256,
                      'max_over_subscription_ratio': 2.0,
                      'thin_provisioning_support': False,
                      'thick_provisioning_support': True,
                      'reserved_percentage': 0,
                      'volume_backend_name': 'lvm3',
                      'timestamp': UTC_NOW},
            'host4': {'total_capacity_gb': 2048,
                      'free_capacity_gb': 200,
                      'allocated_capacity_gb': 1848,
                      'provisioned_capacity_gb': 2047,
                      'max_over_subscription_ratio': 1.0,
                      'thin_provisioning_support': True,
                      'thick_provisioning_support': False,
                      'reserved_percentage': 5,
                      'volume_backend_name': 'lvm4',
                      'timestamp': UTC_NOW,
                      'consistent_group_snapshot_enabled': True},
            'host5': {'total_capacity_gb': 'infinite',
                      'free_capacity_gb': 'unknown',
                      'allocated_capacity_gb': 1548,
                      'provisioned_capacity_gb': 1548,
                      'max_over_subscription_ratio': 1.0,
                      'thin_provisioning_support': True,
                      'thick_provisioning_support': False,
                      'reserved_percentage': 5,
                      'timestamp': UTC_NOW},
        }


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


def mock_host_manager_db_calls(mock_obj, disabled=None):
    services = [
        dict(id=1, host='host1', topic='volume', disabled=False,
             availability_zone='zone1', updated_at=timeutils.utcnow()),
        dict(id=2, host='host2', topic='volume', disabled=False,
             availability_zone='zone1', updated_at=timeutils.utcnow()),
        dict(id=3, host='host3', topic='volume', disabled=False,
             availability_zone='zone2', updated_at=timeutils.utcnow()),
        dict(id=4, host='host4', topic='volume', disabled=False,
             availability_zone='zone3', updated_at=timeutils.utcnow()),
        dict(id=5, host='host5', topic='volume', disabled=False,
             availability_zone='zone3', updated_at=timeutils.utcnow()),
    ]
    if disabled is None:
        mock_obj.return_value = services
    else:
        mock_obj.return_value = [service for service in services
                                 if service['disabled'] == disabled]
