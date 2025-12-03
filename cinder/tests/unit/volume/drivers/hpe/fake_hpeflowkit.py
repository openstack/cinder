# (c) Copyright 2025 Hewlett Packard Enterprise Development LP
#    All Rights Reserved.
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

import sys
from unittest import mock

from oslo_config import cfg

opts = [
    cfg.StrOpt('hpe3par_api_url'),
    cfg.StrOpt('hpe3par_username'),
    cfg.StrOpt('hpe3par_password'),
    cfg.StrOpt('hpe3par_cpg'),
    cfg.StrOpt('hpe3par_cpg_snap'),
    cfg.BoolOpt('hpe3par_debug', default=False),
    cfg.ListOpt('hpe3par_iscsi_ips', default=[]),
    cfg.BoolOpt('hpe3par_iscsi_chap_enabled', default=False),
]


# Create a proper mock module with CinderClient class
class MockCinderClient:
    def __init__(self, *args, **kwargs):
        self.session_mgr = mock.Mock()
        self._replication_enabled = False
        self._replication_targets = []
        self._client_conf = {
            'hpe3par_api_url': 'https://1.1.1.1/api/v1',
            'hpe3par_iscsi_ips': [],
            'hpe3par_iscsi_chap_enabled': False
        }

    @staticmethod
    def get_driver_options():
        return []

    def do_setup(self, *args, **kwargs):
        pass

    def check_flags(self, *args, **kwargs):
        pass

    def get_volume_stats(self, *args, **kwargs):
        return {}

    def create_volume(self, *args, **kwargs):
        return mock.Mock()

    def delete_volume(self, *args, **kwargs):
        return mock.Mock()

    def extend_volume(self, *args, **kwargs):
        return mock.Mock()

    def create_volume_from_snapshot(self, *args, **kwargs):
        return mock.Mock()

    def create_snapshot(self, *args, **kwargs):
        return mock.Mock()

    def delete_snapshot(self, *args, **kwargs):
        return mock.Mock()

    def revert_to_snapshot(self, *args, **kwargs):
        return mock.Mock()

    def get_cpg(self, *args, **kwargs):
        return mock.Mock()

    def create_group(self, *args, **kwargs):
        return mock.Mock()

    def update_group(self, *args, **kwargs):
        return mock.Mock()

    def delete_group(self, *args, **kwargs):
        return mock.Mock()

    def create_group_from_src(self, *args, **kwargs):
        return mock.Mock()

    def create_group_snapshot(self, *args, **kwargs):
        return mock.Mock()

    def delete_group_snapshot(self, *args, **kwargs):
        return mock.Mock()

    def create_cloned_volume(self, *args, **kwargs):
        return mock.Mock()

    def manage_existing(self, *args, **kwargs):
        return mock.Mock()

    def manage_existing_get_size(self, *args, **kwargs):
        return mock.Mock()

    def unmanage(self, *args, **kwargs):
        return mock.Mock()

    def manage_existing_snapshot(self, *args, **kwargs):
        return mock.Mock()

    def manage_existing_snapshot_get_size(self, *args, **kwargs):
        return mock.Mock()

    def unmanage_snapshot(self, *args, **kwargs):
        return mock.Mock()

    def get_manageable_volumes(self, *args, **kwargs):
        return mock.Mock()

    def get_manageable_snapshots(self, *args, **kwargs):
        return mock.Mock()

    def client_logout(self):
        pass

    # FC-specific methods
    def _create_host_fc(self, *args, **kwargs):
        return mock.Mock(), mock.Mock()

    def _build_initiator_target_map(self, *args, **kwargs):
        return mock.Mock(), mock.Mock(), mock.Mock()

    def find_existing_vlun(self, *args, **kwargs):
        return mock.Mock()

    def find_existing_vluns(self, *args, **kwargs):
        return []

    def create_vlun(self, *args, **kwargs):
        return mock.Mock()

    def _get_user_target(self, *args, **kwargs):
        return mock.Mock()

    def _safe_hostname(self, *args, **kwargs):
        return 'test-host'

    def terminate_connection(self, *args, **kwargs):
        pass

    def get_active_fc_target_ports(self, *args, **kwargs):
        return []

    def _create_replication_client(self, *args, **kwargs):
        return mock.Mock()

    def _destroy_replication_client(self, *args, **kwargs):
        pass

    def merge_dicts(self, *args, **kwargs):
        return {}

    # iSCSI-specific methods
    def _create_host_iscsi(self, *args, **kwargs):
        return mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock()

    def get_active_iscsi_target_ports(self, *args, **kwargs):
        return []

    def get_matched_array_ips_iscsi(self, *args, **kwargs):
        return {}, {}

    def build_portPos(self, *args, **kwargs):
        return mock.Mock()

    def build_nsp(self, *args, **kwargs):
        return mock.Mock()

    def _get_least_used_nsp_for_host(self, *args, **kwargs):
        return mock.Mock()

    def _get_ip_using_nsp(self, *args, **kwargs):
        return mock.Mock()

    def _clear_chap_3par(self, *args, **kwargs):
        pass

    def _get_3par_vol_name(self, *args, **kwargs):
        return 'test-volume'

    # Other common methods
    def failover_host(self, *args, **kwargs):
        return mock.Mock(), [], []

    def failover_replication(self, *args, **kwargs):
        return mock.Mock(), []

    def retype(self, *args, **kwargs):
        return mock.Mock()

    def migrate_volume(self, *args, **kwargs):
        return mock.Mock()

    def update_migrated_volume(self, *args, **kwargs):
        return mock.Mock()


hpeflowkit = mock.Mock()
hpeflowkit.hpe3par_opts = opts
hpeflowkit.CinderClient = MockCinderClient

sys.modules['hpeflowkit'] = hpeflowkit
