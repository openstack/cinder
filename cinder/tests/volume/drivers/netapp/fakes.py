# Copyright (c) - 2014, Rushil Chugh.  All rights reserved.
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


ISCSI_FAKE_IQN = 'iqn.1993-08.org.debian:01:10'

ISCSI_FAKE_ADDRESS = '10.63.165.216'

ISCSI_FAKE_PORT = '2232'

ISCSI_FAKE_VOLUME = {'id': 'fake_id', 'provider_auth': 'None stack password'}

ISCSI_FAKE_LUN_ID = 1

ISCSI_FAKE_DICT = {'target_discovered': False,
                   'target_portal': '10.63.165.216:2232',
                   'target_iqn': ISCSI_FAKE_IQN,
                   'target_lun': ISCSI_FAKE_LUN_ID,
                   'volume_id': ISCSI_FAKE_VOLUME['id'],
                   'auth_method': 'None', 'auth_username': 'stack',
                   'auth_password': 'password'}
