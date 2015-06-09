# Copyright 2014 Violin Memory, Inc.
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
Fake VMEM REST client for testing drivers.
"""

import sys

import mock

vmemclient = mock.Mock()
vmemclient.__version__ = "unknown"

sys.modules['vmemclient'] = vmemclient

mock_client_conf = [
    'basic',
    'basic.login',
    'basic.get_node_values',
    'basic.save_config',
    'lun',
    'lun.export_lun',
    'lun.unexport_lun',
    'snapshot',
    'snapshot.export_lun_snapshot',
    'snapshot.unexport_lun_snapshot',
    'iscsi',
    'iscsi.bind_ip_to_target',
    'iscsi.create_iscsi_target',
    'iscsi.delete_iscsi_target',
    'igroup',
]
