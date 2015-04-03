# Copyright (c) - 2014, Clinton Knight.  All rights reserved.
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


VOLUME = 'f10d1a84-9b7b-427e-8fec-63c48b509a56'
LUN = 'ee6b4cc7-477b-4016-aa0c-7127b4e3af86'
SIZE = '1024'
METADATA = {'OsType': 'linux', 'SpaceReserved': 'true'}

UUID1 = '12345678-1234-5678-1234-567812345678'
LUN1 = '/vol/vol0/lun1'
VSERVER1_NAME = 'openstack-vserver'

FC_VOLUME = {'name': 'fake_volume'}

FC_INITIATORS = ['21000024ff406cc3', '21000024ff406cc2']
FC_FORMATTED_INITIATORS = ['21:00:00:24:ff:40:6c:c3',
                           '21:00:00:24:ff:40:6c:c2']

FC_TARGET_WWPNS = ['500a098280feeba5', '500a098290feeba5',
                   '500a098190feeba5', '500a098180feeba5']

FC_FORMATTED_TARGET_WWPNS = ['50:0a:09:82:80:fe:eb:a5',
                             '50:0a:09:82:90:fe:eb:a5',
                             '50:0a:09:81:90:fe:eb:a5',
                             '50:0a:09:81:80:fe:eb:a5']

FC_CONNECTOR = {'ip': '1.1.1.1',
                'host': 'fake_host',
                'wwnns': ['20000024ff406cc3', '20000024ff406cc2'],
                'wwpns': ['21000024ff406cc3', '21000024ff406cc2']}

FC_I_T_MAP = {'21000024ff406cc3': ['500a098280feeba5', '500a098290feeba5'],
              '21000024ff406cc2': ['500a098190feeba5', '500a098180feeba5']}

FC_I_T_MAP_COMPLETE = {'21000024ff406cc3': FC_TARGET_WWPNS,
                       '21000024ff406cc2': FC_TARGET_WWPNS}

FC_FABRIC_MAP = {'fabricB':
                 {'target_port_wwn_list':
                  ['500a098190feeba5', '500a098180feeba5'],
                  'initiator_port_wwn_list': ['21000024ff406cc2']},
                 'fabricA':
                 {'target_port_wwn_list':
                  ['500a098290feeba5', '500a098280feeba5'],
                  'initiator_port_wwn_list': ['21000024ff406cc3']}}

FC_TARGET_INFO = {'driver_volume_type': 'fibre_channel',
                  'data': {'target_lun': 1,
                           'initiator_target_map': FC_I_T_MAP,
                           'access_mode': 'rw',
                           'target_wwn': FC_TARGET_WWPNS,
                           'target_discovered': True}}

FC_TARGET_INFO_EMPTY = {'driver_volume_type': 'fibre_channel', 'data': {}}

FC_TARGET_INFO_UNMAP = {'driver_volume_type': 'fibre_channel',
                        'data': {'target_wwn': FC_TARGET_WWPNS,
                                 'initiator_target_map': FC_I_T_MAP}}

IGROUP1_NAME = 'openstack-igroup1'

IGROUP1 = {
    'initiator-group-os-type': 'linux',
    'initiator-group-type': 'fcp',
    'initiator-group-name': IGROUP1_NAME,
}

ISCSI_VOLUME = {
    'name': 'fake_volume', 'id': 'fake_id',
    'provider_auth': 'fake provider auth',
}

ISCSI_LUN = {'name': ISCSI_VOLUME, 'lun_id': 42}

ISCSI_SERVICE_IQN = 'fake_iscsi_service_iqn'

ISCSI_CONNECTION_PROPERTIES = {
    'data': {
        'auth_method': 'fake',
        'auth_password': 'auth',
        'auth_username': 'provider',
        'target_discovered': False,
        'target_iqn': ISCSI_SERVICE_IQN,
        'target_lun': 42,
        'target_portal': '1.2.3.4:3260',
        'volume_id': 'fake_id',
    },
    'driver_volume_type': 'iscsi',
}

ISCSI_CONNECTOR = {
    'ip': '1.1.1.1',
    'host': 'fake_host',
    'initiator': 'fake_initiator_iqn',
}

ISCSI_TARGET_DETAILS_LIST = [
    {'address': '5.6.7.8', 'port': '3260'},
    {'address': '1.2.3.4', 'port': '3260'},
    {'address': '99.98.97.96', 'port': '3260'},
]
