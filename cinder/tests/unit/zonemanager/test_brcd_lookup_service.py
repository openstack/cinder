#    (c) Copyright 2013 Brocade Communications Systems Inc.
#    All Rights Reserved.
#
#    Copyright 2014 OpenStack Foundation
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


"""Unit tests for fc san lookup service."""

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.zonemanager import fc_san_lookup_service as san_service

_target_ns_map = {'100000051e55a100': ['20240002ac000a50']}
_initiator_ns_map = {'100000051e55a100': ['10008c7cff523b01']}
_device_map_to_verify = {
    '100000051e55a100': {
        'initiator_port_wwn_list': [
            '10008c7cff523b01'], 'target_port_wwn_list': ['20240002ac000a50']}}
_fabric_wwn = '100000051e55a100'


class TestFCSanLookupService(san_service.FCSanLookupService, test.TestCase):

    def setUp(self):
        super(TestFCSanLookupService, self).setUp()
        self.configuration = self.setup_config()

    # override some of the functions
    def __init__(self, *args, **kwargs):
        test.TestCase.__init__(self, *args, **kwargs)

    def setup_config(self):
        configuration = conf.Configuration(None)
        # fill up config
        configuration.fc_san_lookup_service = (
            'cinder.tests.unit.zonemanager.test_brcd_lookup_service.'
            'FakeBrcdFCSanLookupService')
        return configuration

    def test_get_device_mapping_from_network(self):
        GlobalParams._is_normal_test = True
        initiator_list = ['10008c7cff523b01']
        target_list = ['20240002ac000a50', '20240002ac000a40']
        device_map = self.get_device_mapping_from_network(
            initiator_list, target_list)
        self.assertDictMatch(device_map, _device_map_to_verify)

    def test_get_device_mapping_from_network_for_invalid_config(self):
        GlobalParams._is_normal_test = False
        initiator_list = ['10008c7cff523b01']
        target_list = ['20240002ac000a50', '20240002ac000a40']
        self.assertRaises(exception.FCSanLookupServiceException,
                          self.get_device_mapping_from_network,
                          initiator_list, target_list)


class FakeBrcdFCSanLookupService(object):

    def __init__(self, **kwargs):
        pass

    def get_device_mapping_from_network(self,
                                        initiator_wwn_list,
                                        target_wwn_list):
        if not GlobalParams._is_normal_test:
            raise exception.FCSanLookupServiceException("Error")
        device_map = {}
        initiators = []
        targets = []
        for i in initiator_wwn_list:
            if (i in _initiator_ns_map[_fabric_wwn]):
                initiators.append(i)
        for t in target_wwn_list:
            if (t in _target_ns_map[_fabric_wwn]):
                targets.append(t)
        device_map[_fabric_wwn] = {
            'initiator_port_wwn_list': initiators,
            'target_port_wwn_list': targets}
        return device_map


class GlobalParams(object):
    global _is_normal_test
    _is_normal_test = True
