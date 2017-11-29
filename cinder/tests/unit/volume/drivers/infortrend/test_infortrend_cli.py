# Copyright (c) 2015 Infortrend Technology, Inc.
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

import mock

from cinder import test
from cinder.volume.drivers.infortrend.raidcmd_cli import cli_factory as cli


class InfortrendCLITestData(object):

    """CLI Test Data."""

    # Infortrend entry
    fake_lv_id = ['5DE94FF775D81C30', '1234567890', 'HK3345678']

    fake_partition_id = ['6A41315B0EDC8EB7', '51B4283E4E159173',
                         '987654321', '123456789',
                         '2667FE351FC505AE', '53F3E98141A2E871']

    fake_pair_id = ['55D790F8350B036B', '095A184B0ED2DB10']

    fake_snapshot_id = ['2C7A8D211F3B1E36', '60135EE53C14D5EB',
                        '4884610D11FD3335', '5C44BE0A776A2804']

    fake_snapshot_name = ['9e8b27e9-568c-44ca-bd7c-2c7af96ab248',
                          '35e8ba6e-3372-4e67-8464-2b68758f3aeb',
                          'f69696ea-26fc-4f4c-97335-e3ce33ee563',
                          'cinder-unmanaged-f31d8326-c2d8-4668-']

    fake_data_port_ip = ['172.27.0.1', '172.27.0.2',
                         '172.27.0.3', '172.27.0.4',
                         '172.27.0.5', '172.27.0.6']

    fake_model = ['DS S12F-G2852-6']

    fake_manage_port_ip = ['172.27.0.10']

    fake_system_id = ['DEEC']

    fake_host_ip = ['172.27.0.2']

    fake_target_wwnns = ['100123D02300DEEC', '100123D02310DEEC']

    fake_target_wwpns = ['110123D02300DEEC', '120123D02300DEEC',
                         '110123D02310DEEC', '120123D02310DEEC']

    fake_initiator_wwnns = ['2234567890123456', '2234567890543216']

    fake_initiator_wwpns = ['1234567890123456', '1234567890543216']

    fake_initiator_iqn = ['iqn.1991-05.com.infortrend:pc123',
                          'iqn.1991-05.com.infortrend:pc456']

    fake_lun_map = [0, 1, 2]

    # cinder entry
    test_provider_location = [(
        'system_id^%s@partition_id^%s') % (
            int(fake_system_id[0], 16), fake_partition_id[0]), (
        'system_id^%s@partition_id^%s') % (
            int(fake_system_id[0], 16), fake_partition_id[1])
    ]

    test_volume = {
        'id': '5aa119a8-d25b-45a7-8d1b-88e127885635',
        'size': 1,
        'name': 'Part-1',
        'host': 'infortrend-server1@backend_1#LV-1',
        'name_id': '5aa119a8-d25b-45a7-8d1b-88e127885635',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': None,
        'display_description': 'Part-1',
        'volume_type_id': None,
        'status': 'available',
        'provider_location': test_provider_location[0],
        'volume_attachment': [],
    }

    test_volume_1 = {
        'id': '5aa119a8-d25b-45a7-8d1b-88e127885634',
        'size': 1,
        'name': 'Part-1',
        'host': 'infortrend-server1@backend_1#LV-1',
        'name_id': '5aa119a8-d25b-45a7-8d1b-88e127885635',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': None,
        'display_description': 'Part-1',
        'volume_type_id': None,
        'status': 'in-use',
        'provider_location': test_provider_location[1],
        'volume_attachment': [],
    }

    test_dst_volume = {
        'id': '6bb119a8-d25b-45a7-8d1b-88e127885666',
        'size': 1,
        'name': 'Part-1-Copy',
        'host': 'infortrend-server1@backend_1#LV-1',
        'name_id': '6bb119a8-d25b-45a7-8d1b-88e127885666',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': None,
        '_name_id': '6bb119a8-d25b-45a7-8d1b-88e127885666',
        'display_description': 'Part-1-Copy',
        'volume_type_id': None,
        'provider_location': '',
        'volume_attachment': [],
    }

    test_ref_volume = {
        'source-id': fake_partition_id[0],
        'size': 1,
    }

    test_ref_volume_with_id = {
        'source-id': '6bb119a8-d25b-45a7-8d1b-88e127885666',
        'size': 1,
    }

    test_ref_volume_with_name = {
        'source-name': 'import_into_openstack',
        'size': 1,
    }

    test_snapshot = {
        'id': 'ffa9bc5e-1172-4021-acaf-cdcd78a9584d',
        'volume_id': test_volume['id'],
        'volume_name': test_volume['name'],
        'volume_size': 2,
        'project_id': 'project',
        'display_name': None,
        'display_description': 'SI-1',
        'volume_type_id': None,
        'provider_location': fake_snapshot_id[0],
    }
    test_snapshot_without_provider_location = {
        'id': 'ffa9bc5e-1172-4021-acaf-cdcd78a9584d',
        'volume_id': test_volume['id'],
        'volume_name': test_volume['name'],
        'volume_size': 2,
        'project_id': 'project',
        'display_name': None,
        'display_description': 'SI-1',
        'volume_type_id': None,
    }

    test_iqn = [(
        'iqn.2002-10.com.infortrend:raid.uid%s.%s%s%s') % (
            int(fake_system_id[0], 16), 1, 0, 1), (
        'iqn.2002-10.com.infortrend:raid.uid%s.%s%s%s') % (
            int(fake_system_id[0], 16), 1, 0, 1), (
        'iqn.2002-10.com.infortrend:raid.uid%s.%s%s%s') % (
            int(fake_system_id[0], 16), 2, 0, 1),
    ]

    test_iscsi_properties = {
        'driver_volume_type': 'iscsi',
        'data': {
            'target_discovered': True,
            'target_portal': '%s:3260' % fake_data_port_ip[2],
            'target_iqn': test_iqn[0],
            'target_lun': fake_lun_map[0],
            'volume_id': test_volume['id'],
        },
    }

    test_iscsi_properties_with_mcs = {
        'driver_volume_type': 'iscsi',
        'data': {
            'target_discovered': True,
            'target_portal': '%s:3260' % fake_data_port_ip[4],
            'target_iqn': test_iqn[2],
            'target_lun': fake_lun_map[0],
            'volume_id': test_volume['id'],
        },
    }

    test_iscsi_properties_with_mcs_1 = {
        'driver_volume_type': 'iscsi',
        'data': {
            'target_discovered': True,
            'target_portal': '%s:3260' % fake_data_port_ip[4],
            'target_iqn': test_iqn[2],
            'target_lun': fake_lun_map[1],
            'volume_id': test_volume_1['id'],
        },
    }

    test_iqn_empty_map = [(
        'iqn.2002-10.com.infortrend:raid.uid%s.%s%s%s') % (
            int(fake_system_id[0], 16), 0, 0, 1),
    ]

    test_iscsi_properties_empty_map = {
        'driver_volume_type': 'iscsi',
        'data': {
            'target_discovered': True,
            'target_portal': '%s:3260' % fake_data_port_ip[0],
            'target_iqn': test_iqn_empty_map[0],
            'target_lun': fake_lun_map[0],
            'volume_id': test_volume['id'],
        },
    }

    test_initiator_target_map = {
        fake_initiator_wwpns[0]: fake_target_wwpns[0:2],
        fake_initiator_wwpns[1]: fake_target_wwpns[0:2],
    }

    test_fc_properties = {
        'driver_volume_type': 'fibre_channel',
        'data': {
            'target_discovered': True,
            'target_lun': fake_lun_map[0],
            'target_wwn': fake_target_wwpns[0:2],
            'initiator_target_map': test_initiator_target_map,
        },
    }

    test_initiator_target_map_specific_channel = {
        fake_initiator_wwpns[0]: [fake_target_wwpns[1]],
        fake_initiator_wwpns[1]: [fake_target_wwpns[1]],
    }

    test_fc_properties_with_specific_channel = {
        'driver_volume_type': 'fibre_channel',
        'data': {
            'target_discovered': True,
            'target_lun': fake_lun_map[0],
            'target_wwn': [fake_target_wwpns[1]],
            'initiator_target_map': test_initiator_target_map_specific_channel,
        },
    }

    test_target_wwpns_map_multipath_r_model = [
        fake_target_wwpns[0],
        fake_target_wwpns[2],
        fake_target_wwpns[1],
        fake_target_wwpns[3],
    ]

    test_initiator_target_map_multipath_r_model = {
        fake_initiator_wwpns[0]: test_target_wwpns_map_multipath_r_model[:],
        fake_initiator_wwpns[1]: test_target_wwpns_map_multipath_r_model[:],
    }

    test_fc_properties_multipath_r_model = {
        'driver_volume_type': 'fibre_channel',
        'data': {
            'target_discovered': True,
            'target_lun': fake_lun_map[0],
            'target_wwn': test_target_wwpns_map_multipath_r_model[:],
            'initiator_target_map':
                test_initiator_target_map_multipath_r_model,
        },
    }

    test_initiator_target_map_zoning = {
        fake_initiator_wwpns[0].lower():
            [x.lower() for x in fake_target_wwpns[0:2]],
        fake_initiator_wwpns[1].lower():
            [x.lower() for x in fake_target_wwpns[0:2]],
    }

    test_fc_properties_zoning = {
        'driver_volume_type': 'fibre_channel',
        'data': {
            'target_discovered': True,
            'target_lun': fake_lun_map[0],
            'target_wwn': [x.lower() for x in fake_target_wwpns[0:2]],
            'initiator_target_map': test_initiator_target_map_zoning,
        },
    }

    test_initiator_target_map_zoning_r_model = {
        fake_initiator_wwpns[0].lower():
            [x.lower() for x in fake_target_wwpns[1:3]],
        fake_initiator_wwpns[1].lower():
            [x.lower() for x in fake_target_wwpns[1:3]],
    }

    test_fc_properties_zoning_r_model = {
        'driver_volume_type': 'fibre_channel',
        'data': {
            'target_discovered': True,
            'target_lun': fake_lun_map[0],
            'target_wwn': [x.lower() for x in fake_target_wwpns[1:3]],
            'initiator_target_map': test_initiator_target_map_zoning_r_model,
        },
    }

    test_fc_terminate_conn_info = {
        'driver_volume_type': 'fibre_channel',
        'data': {
            'initiator_target_map': test_initiator_target_map_zoning,
        },
    }

    test_connector_iscsi = {
        'ip': fake_host_ip[0],
        'initiator': fake_initiator_iqn[0],
        'host': 'infortrend-server1@backend_1',
    }

    test_connector_iscsi_1 = {
        'ip': fake_host_ip[0],
        'initiator': fake_initiator_iqn[1],
        'host': 'infortrend-server1@backend_1',
    }

    test_connector_fc = {
        'wwpns': fake_initiator_wwpns,
        'wwnns': fake_initiator_wwnns,
        'host': 'infortrend-server1@backend_1',
    }

    fake_pool = {
        'pool_name': 'LV-2',
        'pool_id': fake_lv_id[1],
        'total_capacity_gb': 1000,
        'free_capacity_gb': 1000,
        'reserved_percentage': 0,
        'QoS_support': False,
        'thin_provisioning_support': False,
    }

    test_pools_full = [{
        'pool_name': 'LV-1',
        'pool_id': fake_lv_id[0],
        'location_info': 'Infortrend:' + fake_system_id[0],
        'total_capacity_gb': round(857982.0 / 1024, 2),
        'free_capacity_gb': round(841978.0 / 1024, 2),
        'reserved_percentage': 0,
        'QoS_support': False,
        'thick_provisioning_support': True,
        'thin_provisioning_support': False,
    }]

    test_volume_states_full = {
        'volume_backend_name': 'infortrend_backend_1',
        'vendor_name': 'Infortrend',
        'driver_version': '99.99',
        'storage_protocol': 'iSCSI',
        'model_type': 'R',
        'status': 'Connected',
        'system_id': fake_system_id[0],
        'pools': test_pools_full,
    }

    test_pools_thin = [{
        'pool_name': 'LV-1',
        'pool_id': fake_lv_id[0],
        'location_info': 'Infortrend:' + fake_system_id[0],
        'total_capacity_gb': round(857982.0 / 1024, 2),
        'free_capacity_gb': round(841978.0 / 1024, 2),
        'reserved_percentage': 0,
        'QoS_support': False,
        'thick_provisioning_support': True,
        'thin_provisioning_support': True,
        'provisioned_capacity_gb':
            round((40000) / 1024, 2),
        'max_over_subscription_ratio': 20.0,
    }]

    test_volume_states_thin = {
        'volume_backend_name': 'infortrend_backend_1',
        'vendor_name': 'Infortrend',
        'driver_version': '99.99',
        'storage_protocol': 'iSCSI',
        'model_type': 'R',
        'status': 'Connected',
        'system_id': fake_system_id[0],
        'pools': test_pools_thin,
    }

    test_host = {
        'host': 'infortrend-server1@backend_1',
        'capabilities': test_volume_states_thin,
    }

    test_migrate_volume_states = {
        'volume_backend_name': 'infortrend_backend_1',
        'vendor_name': 'Infortrend',
        'driver_version': '99.99',
        'storage_protocol': 'iSCSI',
        'pool_name': 'LV-1',
        'pool_id': fake_lv_id[1],
        'location_info': 'Infortrend:' + fake_system_id[0],
        'total_capacity_gb': round(857982.0 / 1024, 2),
        'free_capacity_gb': round(841978.0 / 1024, 2),
        'reserved_percentage': 0,
        'QoS_support': False,
    }

    test_migrate_host = {
        'host': 'infortrend-server1@backend_1#LV-2',
        'capabilities': test_migrate_volume_states,
    }

    test_migrate_volume_states_2 = {
        'volume_backend_name': 'infortrend_backend_1',
        'vendor_name': 'Infortrend',
        'driver_version': '99.99',
        'storage_protocol': 'iSCSI',
        'pool_name': 'LV-1',
        'pool_id': fake_lv_id[1],
        'location_info': 'Infortrend:' + fake_system_id[0],
        'total_capacity_gb': round(857982.0 / 1024, 2),
        'free_capacity_gb': round(841978.0 / 1024, 2),
        'reserved_percentage': 0,
        'QoS_support': False,
    }

    test_migrate_host_2 = {
        'host': 'infortrend-server1@backend_1#LV-1',
        'capabilities': test_migrate_volume_states_2,
    }

    fake_host = {
        'host': 'infortrend-server1@backend_1',
        'capabilities': {},
    }

    fake_volume_id = [test_volume['id'], test_dst_volume['id']]

    fake_lookup_map = {
        '12345678': {
            'initiator_port_wwn_list':
                [x.lower() for x in fake_initiator_wwpns],
            'target_port_wwn_list':
                [x.lower() for x in fake_target_wwpns[0:2]],
        },
    }

    fake_lookup_map_r_model = {
        '12345678': {
            'initiator_port_wwn_list':
                [x.lower() for x in fake_initiator_wwpns[:]],
            'target_port_wwn_list':
                [x.lower() for x in fake_target_wwpns[1:3]],
        },
    }

    test_new_type = {
        'name': 'type0',
        'qos_specs_id': None,
        'deleted': False,
        'extra_specs': {'infortrend:provisioning': 'thin'},
        'id': '28c8f82f-416e-148b-b1ae-2556c032d3c0',
    }

    test_diff = {'extra_specs': {'infortrend:provisioning': ('full', 'thin')}}

    def get_fake_cli_failed(self):
        return """
ift cli command
CLI: No selected device
Return: 0x000c

RAIDCmd:>
"""

    def get_fake_cli_failed_with_network(self):
        return """
ift cli command
CLI: Not exist: There is no such partition: 3345678
Return: 0x000b

RAIDCmd:>
"""

    def get_fake_cli_succeed(self):
        return """
ift cli command
CLI: Successful: 0 mapping(s) shown
Return: 0x0000

RAIDCmd:>
"""

    def get_test_show_empty_list(self):
        return (0, [])

    def get_test_show_snapshot(self, partition_id=None, snapshot_id=None):
        if partition_id and snapshot_id:
            return (0, [{
                'Map': 'No',
                'Partition-ID': partition_id,
                'SI-ID': snapshot_id,
                'Name': '---',
                'Activated-time': 'Thu, Jan 09 01:33:11 2020',
                'Index': '1',
            }])
        else:
            return (0, [{
                'Map': 'No',
                'Partition-ID': self.fake_partition_id[0],
                'SI-ID': self.fake_snapshot_id[0],
                'Name': '---',
                'Activated-time': 'Thu, Jan 09 01:33:11 2020',
                'Index': '1',
            }, {
                'Map': 'No',
                'Partition-ID': self.fake_partition_id[0],
                'SI-ID': self.fake_snapshot_id[1],
                'Name': '---',
                'Activated-time': 'Thu, Jan 09 01:35:50 2020',
                'Index': '2',
            }])

    def get_test_show_snapshot_named(self):
        return (0, [{
            'Map': 'No',
            'Partition-ID': self.fake_partition_id[0],
            'SI-ID': self.fake_snapshot_id[0],
            'Name': self.fake_snapshot_name[0],
            'Activated-time': 'Thu, Jan 09 01:33:11 2020',
            'Index': '1',
        }, {
            'Map': 'No',
            'Partition-ID': self.fake_partition_id[1],
            'SI-ID': self.fake_snapshot_id[1],
            'Name': self.fake_snapshot_name[1],
            'Activated-time': 'Thu, Jan 09 01:35:50 2020',
            'Index': '1',
        }])

    def get_fake_show_snapshot(self):
        msg = r"""
show si
\/\/\/-
\
/
-

\
/
-
\/-\/- Index  SI-ID  Name  Partition-ID  Map  Activated-time
---------------------------------------------------------------------------------
 1      %s     ---   %s            No   Thu, Jan 09 01:33:11 2020
 2      %s     ---   %s            No   Thu, Jan 09 01:35:50 2020

CLI: Successful: 2 snapshot image(s) shown
Return: 0x0000

RAIDCmd:>
"""
        return msg % (self.fake_snapshot_id[0],
                      self.fake_partition_id[0],
                      self.fake_snapshot_id[1],
                      self.fake_partition_id[0])

    def get_test_show_snapshot_detail_filled_block(self):
        return (0, [{
            'Mapped': 'Yes',
            'Created-time': 'Wed, Jun 10 10:57:16 2015',
            'ID': self.fake_snapshot_id[0],
            'Last-modification-time': 'Wed, Jun 10 10:57:16 2015',
            'Description': '---',
            'Total-filled-block': '1',
            'LV-ID': self.fake_lv_id[0],
            'Activation-schedule-time': 'Not Actived',
            'Mapping': 'CH:0/ID:0/LUN:1',
            'Index': '1',
            'Used': '0',
            'Name': '---',
            'Valid-filled-block': '0',
            'Partition-ID': self.fake_partition_id[0],
        }])

    def get_test_show_snapshot_detail(self):
        return (0, [{
            'Mapped': 'Yes',
            'Created-time': 'Wed, Jun 10 10:57:16 2015',
            'ID': self.fake_snapshot_id[0],
            'Last-modification-time': 'Wed, Jun 10 10:57:16 2015',
            'Description': '---',
            'Total-filled-block': '0',
            'LV-ID': self.fake_lv_id[0],
            'Activation-schedule-time': 'Not Actived',
            'Mapping': 'CH:0/ID:0/LUN:1',
            'Index': '1',
            'Used': '0',
            'Name': '---',
            'Valid-filled-block': '0',
            'Partition-ID': self.fake_partition_id[0],
        }])

    def get_test_show_snapshot_get_manage(self):
        """Show 4 si for api `list si`: 1.Mapped 2.Managed 3.Free 4.WrongLV"""

        return (0, [{
            'ID': self.fake_snapshot_id[0],
            'Index': '1',
            'Name': self.fake_snapshot_name[0],
            'Partition-ID': self.fake_partition_id[0],
            'LV-ID': self.fake_lv_id[0],
            'Created-time': 'Fri, Dec 23 07:54:33 2016',
            'Last-modification-time': 'Fri, Dec 23 07:54:33 2016',
            'Activated-time': 'Fri, Dec 23 08:29:41 2016',
            'Activation-schedule-time': 'Not Actived',
            'Used': '0',
            'Valid-filled-block': '0',
            'Total-filled-block': '0',
            'Description': '---',
            'Mapped': 'No',
            'Mapping': '---',
            'Backup-to-Cloud': 'false',
            'Status': 'OK',
            'Progress': '---',
        }, {
            'ID': self.fake_snapshot_id[1],
            'Index': '2',
            'Name': self.fake_snapshot_name[1],
            'Partition-ID': self.fake_partition_id[1],
            'LV-ID': self.fake_lv_id[0],
            'Created-time': 'Fri, Dec 23 07:54:33 2016',
            'Last-modification-time': 'Fri, Dec 23 07:54:33 2016',
            'Activated-time': 'Fri, Dec 23 08:29:41 2016',
            'Activation-schedule-time': 'Not Actived',
            'Used': '0',
            'Valid-filled-block': '0',
            'Total-filled-block': '0',
            'Description': '---',
            'Mapped': 'No',
            'Mapping': '---',
            'Backup-to-Cloud': 'false',
            'Status': 'OK',
            'Progress': '---'
        }, {
            'ID': self.fake_snapshot_id[2],
            'Index': '1',
            'Name': self.fake_snapshot_name[2],
            'Partition-ID': self.fake_partition_id[2],
            'LV-ID': self.fake_lv_id[1],
            'Created-time': 'Fri, Dec 23 07:54:33 2016',
            'Last-modification-time': 'Fri, Dec 23 07:54:33 2016',
            'Activated-time': 'Fri, Dec 23 08:29:41 2016',
            'Activation-schedule-time': 'Not Actived',
            'Used': '0',
            'Valid-filled-block': '0',
            'Total-filled-block': '0',
            'Description': '---',
            'Mapped': 'No',
            'Mapping': '---',
            'Backup-to-Cloud': 'false',
            'Status': 'OK',
            'Progress': '---',
        }, {
            'ID': self.fake_snapshot_id[3],
            'Index': '1',
            'Name': 'test-get-snapshot-list',
            # Part ID from get_test_show_partition_detail()
            'Partition-ID': '123123123123',
            'LV-ID': '987654321',
            'Created-time': 'Fri, Dec 23 07:54:33 2016',
            'Last-modification-time': 'Fri, Dec 23 07:54:33 2016',
            'Activated-time': 'Fri, Dec 23 08:29:41 2016',
            'Activation-schedule-time': 'Not Actived',
            'Used': '0',
            'Valid-filled-block': '0',
            'Total-filled-block': '0',
            'Description': '---',
            'Mapped': 'No',
            'Mapping': '---',
            'Backup-to-Cloud': 'false',
            'Status': 'OK',
            'Progress': '---'
        }])

    def get_fake_show_snapshot_detail(self):
        msg = """
show si -l
 ID: %s
 Index: 1
 Name: ---
 Partition-ID: %s
 LV-ID: %s
 Created-time: Wed, Jun 10 10:57:16 2015
 Last-modification-time: Wed, Jun 10 10:57:16 2015
 Activation-schedule-time: Not Actived
 Used: 0
 Valid-filled-block: 0
 Total-filled-block: 0
 Description: ---
 Mapped: Yes
 Mapping: CH:0/ID:0/LUN:1

CLI: Successful: 1 snapshot image(s) shown
Return: 0x0000

RAIDCmd:>
"""
        return msg % (self.fake_snapshot_id[0],
                      self.fake_partition_id[0],
                      self.fake_lv_id[0])

    def get_test_show_net(self):
        return (0, [{
            'Slot': 'slotA',
            'MAC': '10D02380DEEC',
            'ID': '1',
            'IPv4': self.fake_data_port_ip[0],
            'Mode': 'Disabled',
            'IPv6': '---',
        }, {
            'Slot': 'slotB',
            'MAC': '10D02390DEEC',
            'ID': '1',
            'IPv4': self.fake_data_port_ip[1],
            'Mode': 'Disabled',
            'IPv6': '---',
        }, {
            'Slot': 'slotA',
            'MAC': '10D02340DEEC',
            'ID': '2',
            'IPv4': self.fake_data_port_ip[2],
            'Mode': 'Disabled',
            'IPv6': '---',
        }, {
            'Slot': 'slotB',
            'MAC': '10D02350DEEC',
            'ID': '2',
            'IPv4': self.fake_data_port_ip[3],
            'Mode': 'Disabled',
            'IPv6': '---',
        }, {
            'Slot': 'slotA',
            'MAC': '10D02310DEEC',
            'ID': '4',
            'IPv4': self.fake_data_port_ip[4],
            'Mode': 'Disabled',
            'IPv6': '---',
        }, {
            'Slot': 'slotB',
            'MAC': '10D02320DEEC',
            'ID': '4',
            'IPv4': self.fake_data_port_ip[5],
            'Mode': 'Disabled',
            'IPv6': '---',
        }, {
            'Slot': '---',
            'MAC': '10D023077124',
            'ID': '32',
            'IPv4': '172.27.1.1',
            'Mode': 'Disabled',
            'IPv6': '---',
        }])

    def get_fake_show_net(self):
        msg = """
show net
 ID  MAC           Mode  IPv4            Mode      IPv6  Slot
---------------------------------------------------------------
 1   10D02380DEEC  DHCP  %s              Disabled  ---   slotA
 1   10D02390DEEC  DHCP  %s              Disabled  ---   slotB
 2   10D02340DEEC  DHCP  %s              Disabled  ---   slotA
 2   10D02350DEEC  DHCP  %s              Disabled  ---   slotB
 4   10D02310DEEC  DHCP  %s              Disabled  ---   slotA
 4   10D02320DEEC  DHCP  %s              Disabled  ---   slotB
 32  10D023077124  DHCP  172.27.1.1      Disabled  ---   ---

CLI: Successful: 2 record(s) found
Return: 0x0000

RAIDCmd:>
"""
        return msg % (self.fake_data_port_ip[0], self.fake_data_port_ip[1],
                      self.fake_data_port_ip[2], self.fake_data_port_ip[3],
                      self.fake_data_port_ip[4], self.fake_data_port_ip[5])

    def get_test_show_net_detail(self):
        return (0, [{
            'Slot': 'slotA',
            'IPv4-mode': 'DHCP',
            'ID': '1',
            'IPv6-address': '---',
            'Net-mask': '---',
            'IPv4-address': '---',
            'Route': '---',
            'Gateway': '---',
            'IPv6-mode': 'Disabled',
            'MAC': '00D023877124',
            'Prefix-length': '---',
        }, {
            'Slot': '---',
            'IPv4-mode': 'DHCP',
            'ID': '32',
            'IPv6-address': '---',
            'Net-mask': '255.255.240.0',
            'IPv4-address': '172.27.112.245',
            'Route': '---',
            'Gateway': '172.27.127.254',
            'IPv6-mode': 'Disabled',
            'MAC': '00D023077124',
            'Prefix-length': '---',
        }])

    def get_fake_show_net_detail(self):
        msg = """
show net -l
 ID: 1
 MAC: 00D023877124
 IPv4-mode: DHCP
 IPv4-address: ---
 Net-mask: ---
 Gateway: ---
 IPv6-mode: Disabled
 IPv6-address: ---
 Prefix-length: ---
 Route: ---
 Slot: slotA

 ID: 32
 MAC: 00D023077124
 IPv4-mode: DHCP
 IPv4-address: 172.27.112.245
 Net-mask: 255.255.240.0
 Gateway: 172.27.127.254
 IPv6-mode: Disabled
 IPv6-address: ---
 Prefix-length: ---
 Route: ---
 Slot: ---

CLI: Successful: 3 record(s) found
Return: 0x0000

RAIDCmd:>
"""
        return msg

    def get_test_show_partition(self, volume_id=None, pool_id=None):
        result = [{
            'ID': self.fake_partition_id[0],
            'Used': '20000',
            'Name': self.fake_volume_id[0],
            'Size': '20000',
            'Min-reserve': '20000',
            'LV-ID': self.fake_lv_id[0],
        }, {
            'ID': self.fake_partition_id[1],
            'Used': '20000',
            'Name': self.fake_volume_id[1],
            'Size': '20000',
            'Min-reserve': '20000',
            'LV-ID': self.fake_lv_id[0],
        }]
        if volume_id and pool_id:
            result.append({
                'ID': self.fake_partition_id[2],
                'Used': '20000',
                'Name': volume_id,
                'Size': '20000',
                'Min-reserve': '20000',
                'LV-ID': pool_id,
            })
        return (0, result)

    def get_fake_show_partition(self):
        msg = """
show part
 ID  Name         LV-ID  Size     Used     Min-reserve
---------------------------------------------------
 %s  %s           %s     20000    20000    20000
 %s  %s           %s     20000    20000    20000

CLI: Successful: 3 partition(s) shown
Return: 0x0000

RAIDCmd:>
"""
        return msg % (self.fake_partition_id[0],
                      self.fake_volume_id[0],
                      self.fake_lv_id[0],
                      self.fake_partition_id[1],
                      self.fake_volume_id[1],
                      self.fake_lv_id[0])

    def get_test_show_partition_detail_for_map(
            self, partition_id, mapped='true'):
        result = [{
            'LV-ID': self.fake_lv_id[0],
            'Mapping': 'CH:1/ID:0/LUN:0, CH:1/ID:0/LUN:1',
            'Used': '20000',
            'Size': '20000',
            'ID': partition_id,
            'Progress': '---',
            'Min-reserve': '20000',
            'Last-modification-time': 'Wed, Jan 08 20:23:23 2020',
            'Valid-filled-block': '100',
            'Name': self.fake_volume_id[0],
            'Mapped': mapped,
            'Total-filled-block': '100',
            'Creation-time': 'Wed, Jan 08 20:23:23 2020',
        }]
        return (0, result)

    def get_test_show_partition_detail(self, volume_id=None, pool_id=None):
        result = [{
            'LV-ID': self.fake_lv_id[0],
            'Mapping': 'CH:1/ID:0/LUN:0, CH:1/ID:0/LUN:1, CH:4/ID:0/LUN:0',
            'Used': '20000',
            'Size': '20000',
            'ID': self.fake_partition_id[0],
            'Progress': '---',
            'Min-reserve': '20000',
            'Last-modification-time': 'Wed, Jan 08 20:23:23 2020',
            'Valid-filled-block': '100',
            'Name': self.fake_volume_id[0],
            'Mapped': 'true',
            'Total-filled-block': '100',
            'Creation-time': 'Wed, Jan 08 20:23:23 2020',
        }, {
            'LV-ID': self.fake_lv_id[0],
            'Mapping': '---',
            'Used': '20000',
            'Size': '20000',
            'ID': self.fake_partition_id[1],
            'Progress': '---',
            'Min-reserve': '20000',
            'Last-modification-time': 'Sat, Jan 11 22:18:40 2020',
            'Valid-filled-block': '100',
            'Name': self.fake_volume_id[1],
            'Mapped': 'false',
            'Total-filled-block': '100',
            'Creation-time': 'Sat, Jan 11 22:18:40 2020',
        }]
        if volume_id and pool_id:
            result.extend([{
                'LV-ID': pool_id,
                'Mapping': '---',
                'Used': '20000',
                'Size': '20000',
                'ID': self.fake_partition_id[2],
                'Progress': '---',
                'Min-reserve': '20000',
                'Last-modification-time': 'Sat, Jan 15 22:18:40 2020',
                'Valid-filled-block': '100',
                'Name': volume_id,
                'Mapped': 'false',
                'Total-filled-block': '100',
                'Creation-time': 'Sat, Jan 15 22:18:40 2020',
            }, {
                'LV-ID': '987654321',
                'Mapping': '---',
                'Used': '20000',
                'Size': '20000',
                'ID': '123123123123',
                'Progress': '---',
                'Min-reserve': '20000',
                'Last-modification-time': 'Sat, Jan 12 22:18:40 2020',
                'Valid-filled-block': '100',
                'Name': volume_id,
                'Mapped': 'false',
                'Total-filled-block': '100',
                'Creation-time': 'Sat, Jan 15 22:18:40 2020',
            }, {
                'LV-ID': self.fake_lv_id[0],
                'Mapping': '---',
                'Used': '20000',
                'Size': '20000',
                'ID': '6bb119a8-d25b-45a7-8d1b-88e127885666',
                'Progress': '---',
                'Min-reserve': '20000',
                'Last-modification-time': 'Sat, Jan 16 22:18:40 2020',
                'Valid-filled-block': '100',
                'Name': volume_id,
                'Mapped': 'false',
                'Total-filled-block': '100',
                'Creation-time': 'Sat, Jan 14 22:18:40 2020',
            }])
        return (0, result)

    def get_fake_show_partition_detail(self):
        msg = """
show part -l
 ID: %s
 Name: %s
 LV-ID: %s
 Size: 20000
 Used: 20000
 Min-reserve: 20000
 Creation-time: Wed, Jan 08 20:23:23 2020
 Last-modification-time: Wed, Jan 08 20:23:23 2020
 Valid-filled-block: 100
 Total-filled-block: 100
 Progress: ---
 Mapped: true
 Mapping: CH:1/ID:0/LUN:0, CH:1/ID:0/LUN:1, CH:4/ID:0/LUN:0

 ID: %s
 Name: %s
 LV-ID: %s
 Size: 20000
 Used: 20000
 Min-reserve: 20000
 Creation-time: Sat, Jan 11 22:18:40 2020
 Last-modification-time: Sat, Jan 11 22:18:40 2020
 Valid-filled-block: 100
 Total-filled-block: 100
 Progress: ---
 Mapped: false
 Mapping: ---

CLI: Successful: 3 partition(s) shown
Return: 0x0000

RAIDCmd:>
"""
        return msg % (self.fake_partition_id[0],
                      self.fake_volume_id[0],
                      self.fake_lv_id[0],
                      self.fake_partition_id[1],
                      self.fake_volume_id[1],
                      self.fake_lv_id[0])

    def get_test_show_replica_detail_for_migrate(
            self, src_part_id, dst_part_id, volume_id, status='Completed'):
        result = [{
            'Pair-ID': self.fake_pair_id[0],
            'Name': 'Cinder-Snapshot',
            'Source-Device': 'DEEC',
            'Source': src_part_id,
            'Source-Type': 'LV-Partition',
            'Source-Name': volume_id,
            'Source-LV': '5DE94FF775D81C30',
            'Source-VS': '2C482316298F7A4E',
            'Source-Mapped': 'Yes',
            'Target-Device': 'DEEC',
            'Target': dst_part_id,
            'Target-Type': 'LV-Partition',
            'Target-Name': volume_id,
            'Target-LV': '5DE94FF775D81C30',
            'Target-VS': '033EA1FA4EA193EB',
            'Target-Mapped': 'No',
            'Type': 'Copy',
            'Priority': 'Normal',
            'Timeout': '---',
            'Incremental': '---',
            'Compression': '---',
            'Status': status,
            'Progress': '---',
            'Created-time': '01/11/2020 22:20 PM',
            'Sync-commence-time': '01/11/2020 22:20 PM',
            'Split-time': '01/11/2020 22:20 PM',
            'Completed-time': '01/11/2020 22:21 PM',
            'Description': '---',
        }]
        return (0, result)

    def get_test_show_replica_detail_for_si_sync_pair(self):
        result = [{
            'Pair-ID': self.fake_pair_id[0],
            'Name': 'Cinder-Snapshot',
            'Source-Device': 'DEEC',
            'Source': self.fake_snapshot_id[0],
            'Source-Type': 'LV-Partition',
            'Source-Name': '',
            'Source-LV': '5DE94FF775D81C30',
            'Source-VS': '2C482316298F7A4E',
            'Source-Mapped': 'Yes',
            'Target-Device': 'DEEC',
            'Target': self.fake_partition_id[1],
            'Target-Type': 'LV-Partition',
            'Target-Name': '',
            'Target-LV': '5DE94FF775D81C30',
            'Target-VS': '033EA1FA4EA193EB',
            'Target-Mapped': 'No',
            'Type': 'Copy',
            'Priority': 'Normal',
            'Timeout': '---',
            'Incremental': '---',
            'Compression': '---',
            'Status': 'Copy',
            'Progress': '---',
            'Created-time': '01/11/2020 22:20 PM',
            'Sync-commence-time': '01/11/2020 22:20 PM',
            'Split-time': '01/11/2020 22:20 PM',
            'Completed-time': '01/11/2020 22:21 PM',
            'Description': '---',
        }]
        return (0, result)

    def get_test_show_replica_detail_for_sync_pair(self):
        result = [{
            'Pair-ID': self.fake_pair_id[0],
            'Name': 'Cinder-Snapshot',
            'Source-Device': 'DEEC',
            'Source': self.fake_partition_id[0],
            'Source-Type': 'LV-Partition',
            'Source-Name': self.fake_volume_id[0],
            'Source-LV': '5DE94FF775D81C30',
            'Source-VS': '2C482316298F7A4E',
            'Source-Mapped': 'Yes',
            'Target-Device': 'DEEC',
            'Target': self.fake_partition_id[1],
            'Target-Type': 'LV-Partition',
            'Target-Name': self.fake_volume_id[1],
            'Target-LV': '5DE94FF775D81C30',
            'Target-VS': '033EA1FA4EA193EB',
            'Target-Mapped': 'No',
            'Type': 'Copy',
            'Priority': 'Normal',
            'Timeout': '---',
            'Incremental': '---',
            'Compression': '---',
            'Status': 'Copy',
            'Progress': '---',
            'Created-time': '01/11/2020 22:20 PM',
            'Sync-commence-time': '01/11/2020 22:20 PM',
            'Split-time': '01/11/2020 22:20 PM',
            'Completed-time': '01/11/2020 22:21 PM',
            'Description': '---',
        }]
        return (0, result)

    def get_test_show_replica_detail(self):
        result = [{
            'Pair-ID': '4BF246E26966F015',
            'Name': 'Cinder-Snapshot',
            'Source-Device': 'DEEC',
            'Source': self.fake_partition_id[2],
            'Source-Type': 'LV-Partition',
            'Source-Name': 'Part-2',
            'Source-LV': '5DE94FF775D81C30',
            'Source-VS': '2C482316298F7A4E',
            'Source-Mapped': 'No',
            'Target-Device': 'DEEC',
            'Target': self.fake_partition_id[3],
            'Target-Type': 'LV-Partition',
            'Target-Name': 'Part-1-Copy',
            'Target-LV': '5DE94FF775D81C30',
            'Target-VS': '714B80F0335F6E52',
            'Target-Mapped': 'No',
            'Type': 'Copy',
            'Priority': 'Normal',
            'Timeout': '---',
            'Incremental': '---',
            'Compression': '---',
            'Status': 'Completed',
            'Progress': '---',
            'Created-time': '01/11/2020 22:20 PM',
            'Sync-commence-time': '01/11/2020 22:20 PM',
            'Split-time': '01/11/2020 22:20 PM',
            'Completed-time': '01/11/2020 22:21 PM',
            'Description': '---',
        }, {
            'Pair-ID': self.fake_pair_id[0],
            'Name': 'Cinder-Migrate',
            'Source-Device': 'DEEC',
            'Source': self.fake_partition_id[0],
            'Source-Type': 'LV-Partition',
            'Source-Name': self.fake_volume_id[0],
            'Source-LV': '5DE94FF775D81C30',
            'Source-VS': '2C482316298F7A4E',
            'Source-Mapped': 'Yes',
            'Target-Device': 'DEEC',
            'Target': self.fake_partition_id[1],
            'Target-Type': 'LV-Partition',
            'Target-Name': self.fake_volume_id[1],
            'Target-LV': '5DE94FF775D81C30',
            'Target-VS': '033EA1FA4EA193EB',
            'Target-Mapped': 'No',
            'Type': 'Mirror',
            'Priority': 'Normal',
            'Timeout': '---',
            'Incremental': '---',
            'Compression': '---',
            'Status': 'Mirror',
            'Progress': '---',
            'Created-time': '01/11/2020 22:20 PM',
            'Sync-commence-time': '01/11/2020 22:20 PM',
            'Split-time': '01/11/2020 22:20 PM',
            'Completed-time': '01/11/2020 22:21 PM',
            'Description': '---',
        }, {
            'Pair-ID': self.fake_pair_id[1],
            'Name': 'Cinder-Migrate',
            'Source-Device': 'DEEC',
            'Source': self.fake_partition_id[4],
            'Source-Type': 'LV-Partition',
            'Source-Name': self.fake_volume_id[0],
            'Source-LV': '5DE94FF775D81C30',
            'Source-VS': '2C482316298F7A4E',
            'Source-Mapped': 'No',
            'Target-Device': 'DEEC',
            'Target': self.fake_partition_id[5],
            'Target-Type': 'LV-Partition',
            'Target-Name': self.fake_volume_id[1],
            'Target-LV': '5DE94FF775D81C30',
            'Target-VS': '714B80F0335F6E52',
            'Target-Mapped': 'Yes',
            'Type': 'Mirror',
            'Priority': 'Normal',
            'Timeout': '---',
            'Incremental': '---',
            'Compression': '---',
            'Status': 'Mirror',
            'Progress': '---',
            'Created-time': '01/11/2020 22:20 PM',
            'Sync-commence-time': '01/11/2020 22:20 PM',
            'Split-time': '01/11/2020 22:20 PM',
            'Completed-time': '01/11/2020 22:21 PM',
            'Description': '---',
        }]
        return (0, result)

    def get_fake_show_replica_detail(self):
        msg = """
show replica -l
 Pair-ID: 4BF246E26966F015
 Name: Cinder-Snapshot
 Source-Device: DEEC
 Source: %s
 Source-Type: LV-Partition
 Source-Name: Part-2
 Source-LV: 5DE94FF775D81C30
 Source-VS: 2C482316298F7A4E
 Source-Mapped: No
 Target-Device: DEEC
 Target: %s
 Target-Type: LV-Partition
 Target-Name: Part-1-Copy
 Target-LV: 5DE94FF775D81C30
 Target-VS: 714B80F0335F6E52
 Target-Mapped: No
 Type: Copy
 Priority: Normal
 Timeout: ---
 Incremental: ---
 Compression: ---
 Status: Completed
 Progress: ---
 Created-time: 01/11/2020 22:20 PM
 Sync-commence-time: 01/11/2020 22:20 PM
 Split-time: 01/11/2020 22:20 PM
 Completed-time: 01/11/2020 22:21 PM
 Description: ---

 Pair-ID: %s
 Name: Cinder-Migrate
 Source-Device: DEEC
 Source: %s
 Source-Type: LV-Partition
 Source-Name: %s
 Source-LV: 5DE94FF775D81C30
 Source-VS: 2C482316298F7A4E
 Source-Mapped: Yes
 Target-Device: DEEC
 Target: %s
 Target-Type: LV-Partition
 Target-Name: %s
 Target-LV: 5DE94FF775D81C30
 Target-VS: 033EA1FA4EA193EB
 Target-Mapped: No
 Type: Mirror
 Priority: Normal
 Timeout: ---
 Incremental: ---
 Compression: ---
 Status: Mirror
 Progress: ---
 Created-time: 01/11/2020 22:20 PM
 Sync-commence-time: 01/11/2020 22:20 PM
 Split-time: 01/11/2020 22:20 PM
 Completed-time: 01/11/2020 22:21 PM
 Description: ---

 Pair-ID: %s
 Name: Cinder-Migrate
 Source-Device: DEEC
 Source: %s
 Source-Type: LV-Partition
 Source-Name: %s
 Source-LV: 5DE94FF775D81C30
 Source-VS: 2C482316298F7A4E
 Source-Mapped: No
 Target-Device: DEEC
 Target: %s
 Target-Type: LV-Partition
 Target-Name: %s
 Target-LV: 5DE94FF775D81C30
 Target-VS: 714B80F0335F6E52
 Target-Mapped: Yes
 Type: Mirror
 Priority: Normal
 Timeout: ---
 Incremental: ---
 Compression: ---
 Status: Mirror
 Progress: ---
 Created-time: 01/11/2020 22:20 PM
 Sync-commence-time: 01/11/2020 22:20 PM
 Split-time: 01/11/2020 22:20 PM
 Completed-time: 01/11/2020 22:21 PM
 Description: ---

CLI: Successful: 3 replication job(s) shown
Return: 0x0000

RAIDCmd:>
"""
        return msg % (self.fake_partition_id[2],
                      self.fake_partition_id[3],
                      self.fake_pair_id[0],
                      self.fake_partition_id[0],
                      self.fake_volume_id[0],
                      self.fake_partition_id[1],
                      self.fake_volume_id[1],
                      self.fake_pair_id[1],
                      self.fake_partition_id[4],
                      self.fake_volume_id[0],
                      self.fake_partition_id[5],
                      self.fake_volume_id[1])

    def get_test_show_lv(self):
        return (0, [{
            'Name': 'LV-1',
            'LD-amount': '1',
            'Available': '841978 MB',
            'ID': self.fake_lv_id[0],
            'Progress': '---',
            'Size': '857982 MB',
            'Status': 'On-line',
        }])

    def get_fake_show_lv(self):
        msg = """
show lv
 ID  Name  LD-amount  Size       Available  Progress  Status
--------------------------------------------------------------
 %s  LV-1  1          857982 MB  841978 MB  ---       On-line

CLI: Successful: 1 Logical Volumes(s) shown
Return: 0x0000

RAIDCmd:>
"""
        return msg % self.fake_lv_id[0]

    def get_test_show_lv_detail(self):
        return (0, [{
            'Policy': 'Default',
            'Status': 'On-line',
            'ID': self.fake_lv_id[0],
            'Available': '841978 MB',
            'Expandable-size': '0 MB',
            'Name': 'LV-1',
            'Size': '857982 MB',
            'LD-amount': '1',
            'Progress': '---',
        }])

    def get_fake_show_lv_detail(self):
        msg = """
show lv -l
 ID: %s
 Name: LV-1
 LD-amount: 1
 Size: 857982 MB
 Available: 841978 MB
 Expandable-size: 0 MB
 Policy: Default
 Progress: ---
 Status: On-line

CLI: Successful: 1 Logical Volumes(s) shown
Return: 0x0000

RAIDCmd:>
"""
        return msg % self.fake_lv_id[0]

    def get_test_show_lv_tier_for_migration(self):
        return (0, [{
            'LV-Name': 'LV-1',
            'LV-ID': self.fake_lv_id[1],
            'Tier': '0',
            'Size': '418.93 GB',
            'Used': '10 GB(2.4%)',
            'Data Service': '0 MB(0.0%)',
            'Reserved Ratio': '10.0%',
        }, {
            'LV-Name': 'LV-1',
            'LV-ID': self.fake_lv_id[1],
            'Tier': '3',
            'Size': '931.02 GB',
            'Used': '0 MB(0.0%)',
            'Data Service': '0 MB(0.0%)',
            'Reserved Ratio': '0.0%',
        }])

    def get_test_show_lv_tier(self):
        return (0, [{
            'LV-Name': 'LV-1',
            'LV-ID': self.fake_lv_id[0],
            'Tier': '0',
            'Size': '418.93 GB',
            'Used': '10 GB(2.4%)',
            'Data Service': '0 MB(0.0%)',
            'Reserved Ratio': '10.0%',
        }, {
            'LV-Name': 'LV-1',
            'LV-ID': self.fake_lv_id[0],
            'Tier': '3',
            'Size': '931.02 GB',
            'Used': '0 MB(0.0%)',
            'Data Service': '0 MB(0.0%)',
            'Reserved Ratio': '0.0%',
        }])

    def get_fake_show_lv_tier(self):
        msg = """
show lv tier
 LV-Name  LV-ID  Tier  Size       Used          Data Service   Reserved Ratio
------------------------------------------------------------------------------
 LV-1     %s     0     418.93 GB  10 GB(2.4%%)  0 MB(0.0%%)    10.0%%
 LV-1     %s     3     931.02 GB  0 MB(0.0%%)   0 MB(0.0%%)    0.0%%

CLI: Successful: 2 lv tiering(s) shown
Return: 0x0000

RAIDCmd:>
"""
        return msg % (self.fake_lv_id[0],
                      self.fake_lv_id[0])

    def get_test_show_device(self):
        return (0, [{
            'ID': self.fake_system_id[0],
            'Connected-IP': self.fake_manage_port_ip[0],
            'Name': '---',
            'Index': '0*',
            'JBOD-ID': 'N/A',
            'Capacity': '1.22 TB',
            'Model': self.fake_model[0],
            'Service-ID': '8445676',
        }])

    def get_fake_show_device(self):
        msg = """
show device
 Index  ID     Model  Name  Connected-IP  JBOD-ID  Capacity  Service-ID
------------------------------------------------------------------------
 0*     %s     %s     ---   %s            N/A      1.22 TB   8445676

CLI: Successful: 1 device(s) found
Return: 0x0000

RAIDCmd:>
"""
        return msg % (self.fake_system_id[0],
                      self.fake_model[0],
                      self.fake_manage_port_ip[0])

    def get_test_show_channel_single(self):
        return (0, [{
            'ID': '112',
            'defClock': 'Auto',
            'Type': 'FIBRE',
            'Mode': 'Host',
            'Width': '---',
            'Ch': '0',
            'MCS': 'N/A',
            'curClock': '---',
        }, {
            'ID': '0',
            'defClock': 'Auto',
            'Type': 'NETWORK',
            'Mode': 'Host',
            'Width': 'iSCSI',
            'Ch': '1',
            'MCS': '0',
            'curClock': '---',
        }])

    def get_test_show_channel_with_mcs(self):
        return (0, [{
            'ID': '112',
            'defClock': 'Auto',
            'Type': 'FIBRE',
            'Mode': 'Host',
            'Width': '---',
            'Ch': '0',
            'MCS': 'N/A',
            'curClock': '---',
        }, {
            'ID': '0',
            'defClock': 'Auto',
            'Type': 'NETWORK',
            'Mode': 'Host',
            'Width': 'iSCSI',
            'Ch': '1',
            'MCS': '1',
            'curClock': '---',
        }, {
            'ID': '0',
            'defClock': 'Auto',
            'Type': 'NETWORK',
            'Mode': 'Host',
            'Width': 'iSCSI',
            'Ch': '2',
            'MCS': '1',
            'curClock': '---',
        }, {
            'ID': '---',
            'defClock': '6.0 Gbps',
            'Type': 'SAS',
            'Mode': 'Drive',
            'Width': 'SAS',
            'Ch': '3',
            'MCS': 'N/A',
            'curClock': '6.0 Gbps',
        }, {
            'ID': '0',
            'defClock': 'Auto',
            'Type': 'NETWORK',
            'Mode': 'Host',
            'Width': 'iSCSI',
            'Ch': '4',
            'MCS': '2',
            'curClock': '---',
        }, {
            'ID': '112',
            'defClock': 'Auto',
            'Type': 'FIBRE',
            'Mode': 'Host',
            'Width': '---',
            'Ch': '5',
            'MCS': 'N/A',
            'curClock': '---',
        }])

    def get_test_show_channel_without_mcs(self):
        return (0, [{
            'ID': '112',
            'defClock': 'Auto',
            'Type': 'FIBRE',
            'Mode': 'Host',
            'Width': '---',
            'Ch': '0',
            'curClock': '---',
        }, {
            'ID': '0',
            'defClock': 'Auto',
            'Type': 'NETWORK',
            'Mode': 'Host',
            'Width': 'iSCSI',
            'Ch': '1',
            'curClock': '---',
        }, {
            'ID': '0',
            'defClock': 'Auto',
            'Type': 'NETWORK',
            'Mode': 'Host',
            'Width': 'iSCSI',
            'Ch': '2',
            'curClock': '---',
        }, {
            'ID': '---',
            'defClock': '6.0 Gbps',
            'Type': 'SAS',
            'Mode': 'Drive',
            'Width': 'SAS',
            'Ch': '3',
            'curClock': '6.0 Gbps',
        }, {
            'ID': '0',
            'defClock': 'Auto',
            'Type': 'NETWORK',
            'Mode': 'Host',
            'Width': 'iSCSI',
            'Ch': '4',
            'curClock': '---',
        }, {
            'ID': '112',
            'defClock': 'Auto',
            'Type': 'FIBRE',
            'Mode': 'Host',
            'Width': '---',
            'Ch': '5',
            'curClock': '---',
        }])

    def get_test_show_channel_with_diff_target_id(self):
        return (0, [{
            'ID': '32',
            'defClock': 'Auto',
            'Type': 'FIBRE',
            'Mode': 'Host',
            'Width': '---',
            'Ch': '0',
            'MCS': 'N/A',
            'curClock': '---',
        }, {
            'ID': '0',
            'defClock': 'Auto',
            'Type': 'NETWORK',
            'Mode': 'Host',
            'Width': 'iSCSI',
            'Ch': '1',
            'MCS': '0',
            'curClock': '---',
        }, {
            'ID': '0',
            'defClock': 'Auto',
            'Type': 'NETWORK',
            'Mode': 'Host',
            'Width': 'iSCSI',
            'Ch': '2',
            'MCS': '1',
            'curClock': '---',
        }, {
            'ID': '---',
            'defClock': '6.0 Gbps',
            'Type': 'SAS',
            'Mode': 'Drive',
            'Width': 'SAS',
            'Ch': '3',
            'MCS': 'N/A',
            'curClock': '6.0 Gbps',
        }, {
            'ID': '0',
            'defClock': 'Auto',
            'Type': 'NETWORK',
            'Mode': 'Host',
            'Width': 'iSCSI',
            'Ch': '4',
            'MCS': '2',
            'curClock': '---',
        }, {
            'ID': '48',
            'defClock': 'Auto',
            'Type': 'FIBRE',
            'Mode': 'Host',
            'Width': '---',
            'Ch': '5',
            'MCS': 'N/A',
            'curClock': '---',
        }])

    def get_test_show_channel(self):
        return (0, [{
            'ID': '112',
            'defClock': 'Auto',
            'Type': 'FIBRE',
            'Mode': 'Host',
            'Width': '---',
            'Ch': '0',
            'MCS': 'N/A',
            'curClock': '---',
        }, {
            'ID': '0',
            'defClock': 'Auto',
            'Type': 'NETWORK',
            'Mode': 'Host',
            'Width': 'iSCSI',
            'Ch': '1',
            'MCS': '0',
            'curClock': '---',
        }, {
            'ID': '0',
            'defClock': 'Auto',
            'Type': 'NETWORK',
            'Mode': 'Host',
            'Width': 'iSCSI',
            'Ch': '2',
            'MCS': '1',
            'curClock': '---',
        }, {
            'ID': '---',
            'defClock': '6.0 Gbps',
            'Type': 'SAS',
            'Mode': 'Drive',
            'Width': 'SAS',
            'Ch': '3',
            'MCS': 'N/A',
            'curClock': '6.0 Gbps',
        }, {
            'ID': '0',
            'defClock': 'Auto',
            'Type': 'NETWORK',
            'Mode': 'Host',
            'Width': 'iSCSI',
            'Ch': '4',
            'MCS': '2',
            'curClock': '---',
        }, {
            'ID': '112',
            'defClock': 'Auto',
            'Type': 'FIBRE',
            'Mode': 'Host',
            'Width': '---',
            'Ch': '5',
            'MCS': 'N/A',
            'curClock': '---',
        }])

    def get_fake_show_channel(self):
        msg = """
show ch
 Ch  Mode   Type     defClock  curClock  Width  ID   MCS
---------------------------------------------------------
 0   Host   FIBRE    Auto      ---       ---    112  N/A
 1   Host   NETWORK  Auto      ---       iSCSI  0    0
 2   Host   NETWORK  Auto      ---       iSCSI  0    1
 3   Drive  SAS      6.0 Gbps  6.0 Gbps  SAS    ---  N/A
 4   Host   NETWORK  Auto      ---       iSCSI  0    2
 5   Host   FIBRE    Auto      ---       ---    112  N/A

CLI: Successful: : 6 channel(s) shown
Return: 0x0000

RAIDCmd:>
"""
        return msg

    def get_test_show_channel_r_model_diff_target_id(self):
        return (0, [{
            'Mode': 'Host',
            'AID': '32',
            'defClock': 'Auto',
            'MCS': 'N/A',
            'Ch': '0',
            'BID': '33',
            'curClock': '---',
            'Width': '---',
            'Type': 'FIBRE',
        }, {
            'Mode': 'Host',
            'AID': '0',
            'defClock': 'Auto',
            'MCS': '0',
            'Ch': '1',
            'BID': '1',
            'curClock': '---',
            'Width': 'iSCSI',
            'Type': 'NETWORK',
        }, {
            'Mode': 'Host',
            'AID': '0',
            'defClock': 'Auto',
            'MCS': '1',
            'Ch': '2',
            'BID': '1',
            'curClock': '---',
            'Width': 'iSCSI',
            'Type': 'NETWORK',
        }, {
            'Mode': 'Drive',
            'AID': '---',
            'defClock': '6.0 Gbps',
            'MCS': 'N/A',
            'Ch': '3',
            'BID': '---',
            'curClock': '6.0 Gbps',
            'Width': 'SAS',
            'Type': 'SAS',
        }, {
            'Mode': 'Host',
            'AID': '0',
            'defClock': 'Auto',
            'MCS': '2',
            'Ch': '4',
            'BID': '1',
            'curClock': '---',
            'Width': 'iSCSI',
            'Type': 'NETWORK',
        }, {
            'Mode': 'Host',
            'AID': '48',
            'defClock': 'Auto',
            'MCS': 'N/A',
            'Ch': '5',
            'BID': '49',
            'curClock': '---',
            'Width': '---',
            'Type': 'FIBRE',
        }])

    def get_test_show_channel_r_model(self):
        return (0, [{
            'Mode': 'Host',
            'AID': '112',
            'defClock': 'Auto',
            'MCS': 'N/A',
            'Ch': '0',
            'BID': '113',
            'curClock': '---',
            'Width': '---',
            'Type': 'FIBRE',
        }, {
            'Mode': 'Host',
            'AID': '0',
            'defClock': 'Auto',
            'MCS': '0',
            'Ch': '1',
            'BID': '1',
            'curClock': '---',
            'Width': 'iSCSI',
            'Type': 'NETWORK',
        }, {
            'Mode': 'Host',
            'AID': '0',
            'defClock': 'Auto',
            'MCS': '1',
            'Ch': '2',
            'BID': '1',
            'curClock': '---',
            'Width': 'iSCSI',
            'Type': 'NETWORK',
        }, {
            'Mode': 'Drive',
            'AID': '---',
            'defClock': '6.0 Gbps',
            'MCS': 'N/A',
            'Ch': '3',
            'BID': '---',
            'curClock': '6.0 Gbps',
            'Width': 'SAS',
            'Type': 'SAS',
        }, {
            'Mode': 'Host',
            'AID': '0',
            'defClock': 'Auto',
            'MCS': '2',
            'Ch': '4',
            'BID': '1',
            'curClock': '---',
            'Width': 'iSCSI',
            'Type': 'NETWORK',
        }, {
            'Mode': 'Host',
            'AID': '112',
            'defClock': 'Auto',
            'MCS': 'N/A',
            'Ch': '5',
            'BID': '113',
            'curClock': '---',
            'Width': '---',
            'Type': 'FIBRE',
        }])

    def get_fake_show_channel_r_model(self):
        msg = """
show ch
 Ch    Mode   Type     defClock  curClock  Width  AID  BID  MCS
----------------------------------------------------------------
 0     Host   FIBRE    Auto      ---       ---    112  113  N/A
 1     Host   NETWORK  Auto      ---       iSCSI  0    1    0
 2     Host   NETWORK  Auto      ---       iSCSI  0    1    1
 3     Drive  SAS      6.0 Gbps  6.0 Gbps  SAS    ---  ---  N/A
 4     Host   NETWORK  Auto      ---       iSCSI  0    1    2
 5     Host   FIBRE    Auto      ---       ---    112  113  N/A

CLI: Successful: : 9 channel(s) shown
Return: 0x0000

RAIDCmd:>
"""
        return msg

    def get_show_map_with_lun_map_on_zoning(self):
        return (0, [{
            'Ch': '0',
            'LUN': '0',
            'Media': 'PART',
            'Host-ID': self.fake_initiator_wwpns[0],
            'Target': '112',
            'Name': 'Part-1',
            'ID': self.fake_partition_id[0],
        }])

    def get_test_show_map(self, partition_id=None, channel_id=None):
        if partition_id and channel_id:
            return (0, [{
                'Ch': channel_id,
                'LUN': '0',
                'Media': 'PART',
                'Host-ID': '---',
                'Target': '0',
                'Name': 'Part-1',
                'ID': partition_id,
            }, {
                'Ch': channel_id,
                'LUN': '1',
                'Media': 'PART',
                'Host-ID': '---',
                'Target': '0',
                'Name': 'Part-1',
                'ID': partition_id,
            }])
        else:
            return (0, [{
                'Ch': '1',
                'LUN': '0',
                'Media': 'PART',
                'Host-ID': self.fake_initiator_iqn[0],
                'Target': '0',
                'Name': 'Part-1',
                'ID': self.fake_partition_id[0],
            }, {
                'Ch': '1',
                'LUN': '1',
                'Media': 'PART',
                'Host-ID': self.fake_initiator_iqn[0],
                'Target': '0',
                'Name': 'Part-1',
                'ID': self.fake_partition_id[0],
            }, {
                'Ch': '4',
                'LUN': '0',
                'Media': 'PART',
                'Host-ID': self.fake_initiator_iqn[0],
                'Target': '0',
                'Name': 'Part-1',
                'ID': self.fake_partition_id[0],
            }])

    def get_test_show_map_fc(self):
        return (0, [{
            'Ch': '0',
            'LUN': '0',
            'Media': 'PART',
            'Host-ID': self.fake_initiator_wwpns[0],
            'Target': '112',
            'Name': 'Part-1',
            'ID': self.fake_partition_id[0],
        }, {
            'Ch': '0',
            'LUN': '0',
            'Media': 'PART',
            'Host-ID': self.fake_initiator_wwpns[1],
            'Target': '112',
            'Name': 'Part-1',
            'ID': self.fake_partition_id[0],
        }, {
            'Ch': '5',
            'LUN': '0',
            'Media': 'PART',
            'Host-ID': self.fake_initiator_wwpns[0],
            'Target': '112',
            'Name': 'Part-1',
            'ID': self.fake_partition_id[0],
        }, {
            'Ch': '5',
            'LUN': '0',
            'Media': 'PART',
            'Host-ID': self.fake_initiator_wwpns[1],
            'Target': '112',
            'Name': 'Part-1',
            'ID': self.fake_partition_id[0],
        }])

    def get_test_show_map_multimap(self):
        return (0, [{
            'Ch': '1',
            'LUN': '0',
            'Media': 'PART',
            'Host-ID': '---',
            'Target': '0',
            'Name': 'Part-1',
            'ID': self.fake_partition_id[0],
        }, {
            'Ch': '1',
            'LUN': '1',
            'Media': 'PART',
            'Host-ID': '---',
            'Target': '0',
            'Name': 'Part-1',
            'ID': self.fake_partition_id[0],
        }, {
            'Ch': '4',
            'LUN': '0',
            'Media': 'PART',
            'Host-ID': '210000E08B0AADE1',
            'Target': '0',
            'Name': 'Part-1',
            'ID': self.fake_partition_id[0],
        }, {
            'Ch': '4',
            'LUN': '0',
            'Media': 'PART',
            'Host-ID': '210000E08B0AADE2',
            'Target': '0',
            'Name': 'Part-1',
            'ID': self.fake_partition_id[0],
        }])

    def get_fake_show_map(self):
        msg = """
show map
 Ch  Target  LUN  Media  Name    ID  Host-ID
-----------------------------------------------------------
 1   0       0    PART   Part-1  %s  %s
 1   0       1    PART   Part-1  %s  %s
 4   0       0    PART   Part-1  %s  %s

CLI: Successful: 3 mapping(s) shown
Return: 0x0000

RAIDCmd:>
"""
        return msg % (self.fake_partition_id[0],
                      self.fake_initiator_iqn[0],
                      self.fake_partition_id[0],
                      self.fake_initiator_iqn[0],
                      self.fake_partition_id[0],
                      self.fake_initiator_iqn[0])

    def get_test_show_license_full(self):
        return (0, {
            'Local Volume Copy': {
                'Support': False,
                'Amount': '8/256',
            },
            'Synchronous Remote Mirror': {
                'Support': False,
                'Amount': '8/256',
            },
            'Snapshot': {
                'Support': False,
                'Amount': '1024/16384',
            },
            'Self-Encryption Drives': {
                'Support': False,
                'Amount': '---',
            },
            'Compression': {
                'Support': False,
                'Amount': '---',
            },
            'Local volume Mirror': {
                'Support': False,
                'Amount': '8/256',
            },
            'Storage Tiering': {
                'Support': False,
                'Amount': '---',
            },
            'Asynchronous Remote Mirror': {
                'Support': False,
                'Amount': '8/256',
            },
            'Scale-out': {
                'Support': False,
                'Amount': 'Not Support',
            },
            'Thin Provisioning': {
                'Support': False,
                'Amount': '---',
            },
            'Max JBOD': {
                'Support': False,
                'Amount': '15',
            },
            'EonPath': {
                'Support': False,
                'Amount': '---',
            }
        })

    def get_test_show_license_thin(self):
        return (0, {
            'Local Volume Copy': {
                'Support': False,
                'Amount': '8/256',
            },
            'Synchronous Remote Mirror': {
                'Support': False,
                'Amount': '8/256',
            },
            'Snapshot': {
                'Support': False,
                'Amount': '1024/16384',
            },
            'Self-Encryption Drives': {
                'Support': False,
                'Amount': '---',
            },
            'Compression': {
                'Support': False,
                'Amount': '---',
            },
            'Local volume Mirror': {
                'Support': False,
                'Amount': '8/256',
            },
            'Storage Tiering': {
                'Support': False,
                'Amount': '---',
            },
            'Asynchronous Remote Mirror': {
                'Support': False,
                'Amount': '8/256',
            },
            'Scale-out': {
                'Support': False,
                'Amount': 'Not Support',
            },
            'Thin Provisioning': {
                'Support': True,
                'Amount': '---',
            },
            'Max JBOD': {
                'Support': False,
                'Amount': '15',
            },
            'EonPath': {
                'Support': False,
                'Amount': '---',
            }
        })

    def get_fake_show_license(self):
        msg = """
show license
 License                     Amount(Partition/Subsystem)  Expired
------------------------------------------------------------------
 EonPath                     ---                          Expired
 Scale-out                   Not Support                  ---
 Snapshot                    1024/16384                   Expired
 Local Volume Copy           8/256                        Expired
 Local volume Mirror         8/256                        Expired
 Synchronous Remote Mirror   8/256                        Expired
 Asynchronous Remote Mirror  8/256                        Expired
 Compression                 ---                          Expired
 Thin Provisioning           ---                          Expired
 Storage Tiering             ---                          Expired
 Max JBOD                    15                           Expired
 Self-Encryption Drives      ---                          Expired

CLI: Successful
Return: 0x0000

RAIDCmd:>
"""
        return msg

    def get_test_show_wwn_with_g_model(self):
        return (0, [{
            'ID': 'ID:112',
            'WWPN': self.fake_target_wwpns[0],
            'CH': '0',
            'WWNN': self.fake_target_wwnns[0],
        }, {
            'ID': 'ID:112',
            'WWPN': self.fake_target_wwpns[1],
            'CH': '5',
            'WWNN': self.fake_target_wwnns[0],
        }])

    def get_test_show_wwn_with_diff_target_id(self):
        return (0, [{
            'ID': 'AID:32',
            'WWPN': self.fake_target_wwpns[0],
            'CH': '0',
            'WWNN': self.fake_target_wwnns[0],
        }, {
            'ID': 'BID:33',
            'WWPN': self.fake_target_wwpns[2],
            'CH': '0',
            'WWNN': self.fake_target_wwnns[1],
        }, {
            'ID': 'AID:48',
            'WWPN': self.fake_target_wwpns[1],
            'CH': '5',
            'WWNN': self.fake_target_wwnns[0],
        }, {
            'ID': 'BID:49',
            'WWPN': self.fake_target_wwpns[3],
            'CH': '5',
            'WWNN': self.fake_target_wwnns[1],
        }])

    def get_test_show_wwn(self):
        return (0, [{
            'ID': 'AID:112',
            'WWPN': self.fake_target_wwpns[0],
            'CH': '0',
            'WWNN': self.fake_target_wwnns[0],
        }, {
            'ID': 'BID:113',
            'WWPN': self.fake_target_wwpns[2],
            'CH': '0',
            'WWNN': self.fake_target_wwnns[1],
        }, {
            'ID': 'AID:112',
            'WWPN': self.fake_target_wwpns[1],
            'CH': '5',
            'WWNN': self.fake_target_wwnns[0],
        }, {
            'ID': 'BID:113',
            'WWPN': self.fake_target_wwpns[3],
            'CH': '5',
            'WWNN': self.fake_target_wwnns[1],
        }])

    def get_fake_show_wwn(self):
        msg = """
show wwn
WWN entries in controller for host channels:
 CH  ID       WWNN  WWPN
-------------------------------------------------
 0   AID:112  %s    %s
 0   BID:113  %s    %s
 5   AID:112  %s    %s
 5   BID:113  %s    %s

CLI: Successful
Return: 0x0000

RAIDCmd:>
"""
        return msg % (self.fake_target_wwnns[0], self.fake_target_wwpns[0],
                      self.fake_target_wwnns[1], self.fake_target_wwpns[2],
                      self.fake_target_wwnns[0], self.fake_target_wwpns[1],
                      self.fake_target_wwnns[1], self.fake_target_wwpns[3])

    def get_test_show_iqn(self):
        return (0, [{
            'Name': self.fake_initiator_iqn[0][-16:],
            'IQN': self.fake_initiator_iqn[0],
            'User': '---',
            'Password': '---',
            'Target': '---',
            'Target-Password': '---',
            'IP': '0.0.0.0',
            'Mask': '0.0.0.0',
        }])

    def get_fake_show_iqn(self):
        msg = """
show iqn
Detected host IQN:
 IQN
----------------------------------------
 %s


List of initiator IQN(s):
--------------------------
 Name: %s
 IQN: %s
 User: ---
 Password: ---
 Target: ---
 Target-Password: ---
 IP: 0.0.0.0
 Mask: 0.0.0.0

CLI: Successful: 1 initiator iqn(s) shown
Return: 0x0000

RAIDCmd:>
"""
        return msg % (self.fake_initiator_iqn[0],
                      self.fake_initiator_iqn[0][-16:],
                      self.fake_initiator_iqn[0])

    def get_test_show_host(self):
        return (0, [{
            'Fibre connection option': 'Point to point only',
            'Max queued count': '1024',
            'Max LUN per ID': '64',
            'CHAP': 'Disabled',
            'Jumbo frame': 'Disabled',
            'Max concurrent LUN connection': '4',
            'LUN connection reserved tags': '4',
            'Peripheral device type': 'No Device Present (Type=0x7f)',
            'Peripheral device qualifier': 'Connected',
            'Removable media support': 'Disabled',
            'LUN applicability': 'First Undefined LUN',
            'Supported CHS Cylinder': 'Variable',
            'Supported CHS Head': 'Variable',
            'Supported CHS Sector': 'Variable',
        }])

    def get_fake_show_host(self):
        msg = """
show host
 Fibre connection option: Point to point only
 Max queued count: 1024
 Max LUN per ID: 64
 CHAP: Disabled
 Jumbo frame: Disabled
 Max concurrent LUN connection: 4
 LUN connection reserved tags: 4
 Peripheral device type: No Device Present (Type=0x7f)
 Peripheral device qualifier: Connected
 Removable media support: Disabled
 LUN applicability: First Undefined LUN
 Supported CHS Cylinder: Variable
 Supported CHS Head: Variable
 Supported CHS Sector: Variable

CLI: Successful
Return: 0x0000

RAIDCmd:>
"""
        return msg

    def get_fake_discovery(self, target_iqns, target_portals):
        template = '%s,1 %s'

        if len(target_iqns) == 1:
            result = template % (target_portals[0], target_iqns[0])
            return (0, result)

        result = []
        for i in range(len(target_iqns)):
            result.append(template % (
                target_portals[i], target_iqns[i]))
        return (0, '\n'.join(result))

    class Fake_cinder_object(object):
        id = None

        def __init__(self, test_volume):
            self.id = test_volume

    class Fake_cinder_snapshot(Fake_cinder_object):
        provider_location = None

        def __init__(self, id, provider_location):
            self.id = id
            self.provider_location = provider_location

    fake_cinder_volumes = [Fake_cinder_object(test_dst_volume['id'])]
    fake_cinder_snapshots = [Fake_cinder_object(fake_snapshot_name[1])]


class InfortrendCLITestCase(test.TestCase):

    CommandList = ['CreateLD', 'CreateLV',
                   'CreatePartition', 'DeletePartition',
                   'CreateMap', 'DeleteMap',
                   'CreateSnapshot', 'DeleteSnapshot',
                   'CreateReplica', 'DeleteReplica',
                   'CreateIQN', 'DeleteIQN',
                   'ShowLD', 'ShowLV',
                   'ShowPartition', 'ShowSnapshot',
                   'ShowDevice', 'ShowChannel',
                   'ShowDisk', 'ShowMap',
                   'ShowNet', 'ShowLicense',
                   'ShowWWN', 'ShowReplica',
                   'ShowIQN', 'ShowHost', 'ConnectRaid',
                   'SetPartition', 'SetLV']

    def __init__(self, *args, **kwargs):
        super(InfortrendCLITestCase, self).__init__(*args, **kwargs)
        self.cli_data = InfortrendCLITestData()

    def _cli_set(self, cli, fake_result):
        cli_conf = {
            'path': '',
            'password': '',
            'ip': '',
            'cli_retry_time': 1,
            'raidcmd_timeout': 60,
            'cli_cache': False,
            'pid': 12345,
            'fd': 10,
        }
        cli = cli(cli_conf)

        cli._execute = mock.Mock(return_value=fake_result)

        return cli

    def _cli_multi_set(self, cli, fake_result_list):
        cli_conf = {
            'path': '',
            'password': '',
            'ip': '',
            'cli_retry_time': 5,
            'raidcmd_timeout': 60,
            'cli_cache': False,
            'pid': 12345,
            'fd': 10,
        }
        cli = cli(cli_conf)

        cli._execute = mock.Mock(side_effect=fake_result_list)

        return cli

    def _test_command_succeed(self, command):

        fake_cli_succeed = self.cli_data.get_fake_cli_succeed()
        test_command = self._cli_set(command, fake_cli_succeed)

        rc, out = test_command.execute()
        self.assertEqual(0, rc)

    def _test_command_failed(self, command):

        fake_cli_failed = self.cli_data.get_fake_cli_failed()
        test_command = self._cli_set(command, fake_cli_failed)

        rc, out = test_command.execute()
        self.assertEqual(int('0x000c', 16), rc)

    def _test_command_failed_retry_succeed(self, log_error, command):

        log_error.reset_mock()

        LOG_ERROR_STR = (
            'Retry %(retry)s times: %(method)s Failed %(rc)s: %(reason)s'
        )

        fake_result_list = [
            self.cli_data.get_fake_cli_failed(),
            self.cli_data.get_fake_cli_failed_with_network(),
            self.cli_data.get_fake_cli_succeed(),
        ]
        test_command = self._cli_multi_set(command, fake_result_list)

        rc, out = test_command.execute()
        self.assertEqual(11, rc)

        expect_log_error = [
            mock.call(LOG_ERROR_STR, {
                'retry': 1,
                'method': test_command.__class__.__name__,
                'rc': int('0x000c', 16),
                'reason': 'No selected device',
            }),
            mock.call(LOG_ERROR_STR, {
                'retry': 2,
                'method': test_command.__class__.__name__,
                'rc': int('0x000b', 16),
                'reason': 'Not exist: There is no such partition: 3345678',
            })
        ]
        log_error.assert_has_calls(expect_log_error)

    def _test_command_failed_retry_timeout(self, log_error, command):

        log_error.reset_mock()

        LOG_ERROR_STR = (
            'Retry %(retry)s times: %(method)s Failed %(rc)s: %(reason)s'
        )

        fake_result_list = [
            self.cli_data.get_fake_cli_failed(),
            self.cli_data.get_fake_cli_failed(),
            self.cli_data.get_fake_cli_failed(),
            self.cli_data.get_fake_cli_failed(),
            self.cli_data.get_fake_cli_failed(),
        ]
        test_command = self._cli_multi_set(command, fake_result_list)

        rc, out = test_command.execute()
        self.assertEqual(int('0x000c', 16), rc)
        self.assertEqual('No selected device', out)

        expect_log_error = [
            mock.call(LOG_ERROR_STR, {
                'retry': 1,
                'method': test_command.__class__.__name__,
                'rc': int('0x000c', 16),
                'reason': 'No selected device',
            }),
            mock.call(LOG_ERROR_STR, {
                'retry': 2,
                'method': test_command.__class__.__name__,
                'rc': int('0x000c', 16),
                'reason': 'No selected device',
            }),
            mock.call(LOG_ERROR_STR, {
                'retry': 3,
                'method': test_command.__class__.__name__,
                'rc': int('0x000c', 16),
                'reason': 'No selected device',
            }),
            mock.call(LOG_ERROR_STR, {
                'retry': 4,
                'method': test_command.__class__.__name__,
                'rc': int('0x000c', 16),
                'reason': 'No selected device',
            }),
            mock.call(LOG_ERROR_STR, {
                'retry': 5,
                'method': test_command.__class__.__name__,
                'rc': int('0x000c', 16),
                'reason': 'No selected device',
            })
        ]
        log_error.assert_has_calls(expect_log_error)

    def _test_show_command(self, fake_data, test_data, command, *params):

        test_command = self._cli_set(command, fake_data)

        rc, out = test_command.execute(*params)

        self.assertEqual(test_data[0], rc)

        if isinstance(out, list):
            for i in range(len(test_data[1])):
                self.assertDictEqual(test_data[1][i], out[i])
        else:
            self.assertDictEqual(test_data[1], out)

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_cli_all_command_execute(self):

        for command in self.CommandList:
            self._test_command_succeed(getattr(cli, command))
            self._test_command_failed(getattr(cli, command))

    @mock.patch.object(cli.LOG, 'error')
    def test_cli_all_command_execute_retry_succeed(self, log_error):

        for command in self.CommandList:
            self._test_command_failed_retry_succeed(
                log_error, getattr(cli, command))

    @mock.patch.object(cli.LOG, 'error')
    def test_cli_all_command_execute_retry_timeout(self, log_error):

        for command in self.CommandList:
            self._test_command_failed_retry_timeout(
                log_error, getattr(cli, command))

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_snapshot(self):
        self._test_show_command(
            self.cli_data.get_fake_show_snapshot(),
            self.cli_data.get_test_show_snapshot(),
            cli.ShowSnapshot)

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_snapshot_detail(self):
        self._test_show_command(
            self.cli_data.get_fake_show_snapshot_detail(),
            self.cli_data.get_test_show_snapshot_detail(),
            cli.ShowSnapshot, '-l')

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_net(self):
        self._test_show_command(
            self.cli_data.get_fake_show_net(),
            self.cli_data.get_test_show_net(),
            cli.ShowNet)

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_detail_net(self):
        self._test_show_command(
            self.cli_data.get_fake_show_net_detail(),
            self.cli_data.get_test_show_net_detail(),
            cli.ShowNet, '-l')

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_partition(self):
        self._test_show_command(
            self.cli_data.get_fake_show_partition(),
            self.cli_data.get_test_show_partition(),
            cli.ShowPartition)

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_partition_detail(self):
        self._test_show_command(
            self.cli_data.get_fake_show_partition_detail(),
            self.cli_data.get_test_show_partition_detail(),
            cli.ShowPartition, '-l')

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_lv(self):
        self._test_show_command(
            self.cli_data.get_fake_show_lv(),
            self.cli_data.get_test_show_lv(),
            cli.ShowLV)

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_lv_detail(self):
        self._test_show_command(
            self.cli_data.get_fake_show_lv_detail(),
            self.cli_data.get_test_show_lv_detail(),
            cli.ShowLV, '-l')

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_lv_tier(self):
        self._test_show_command(
            self.cli_data.get_fake_show_lv_tier(),
            self.cli_data.get_test_show_lv_tier(),
            cli.ShowLV, 'tier')

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_device(self):
        self._test_show_command(
            self.cli_data.get_fake_show_device(),
            self.cli_data.get_test_show_device(),
            cli.ShowDevice)

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_channel(self):
        self._test_show_command(
            self.cli_data.get_fake_show_channel(),
            self.cli_data.get_test_show_channel(),
            cli.ShowChannel)

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_channel_with_r_model(self):
        self._test_show_command(
            self.cli_data.get_fake_show_channel_r_model(),
            self.cli_data.get_test_show_channel_r_model(),
            cli.ShowChannel)

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_map(self):
        self._test_show_command(
            self.cli_data.get_fake_show_map(),
            self.cli_data.get_test_show_map(),
            cli.ShowMap)

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_license(self):
        self._test_show_command(
            self.cli_data.get_fake_show_license(),
            self.cli_data.get_test_show_license_full(),
            cli.ShowLicense)

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_replica_detail(self):
        self._test_show_command(
            self.cli_data.get_fake_show_replica_detail(),
            self.cli_data.get_test_show_replica_detail(),
            cli.ShowReplica, '-l')

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_wwn(self):
        self._test_show_command(
            self.cli_data.get_fake_show_wwn(),
            self.cli_data.get_test_show_wwn(),
            cli.ShowWWN)

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_iqn(self):
        self._test_show_command(
            self.cli_data.get_fake_show_iqn(),
            self.cli_data.get_test_show_iqn(),
            cli.ShowIQN)

    @mock.patch.object(cli.LOG, 'debug', mock.Mock())
    def test_show_host(self):
        self._test_show_command(
            self.cli_data.get_fake_show_host(),
            self.cli_data.get_test_show_host(),
            cli.ShowHost)
