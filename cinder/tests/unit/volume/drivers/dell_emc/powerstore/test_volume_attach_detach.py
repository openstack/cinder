# Copyright (c) 2020 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from unittest import mock

from cinder import exception
from cinder.objects import fields
from cinder.objects import volume_attachment
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerstore
from cinder.volume.drivers.dell_emc.powerstore import utils

FAKE_HOST = {
    "name": "fake_host",
    "id": "fake_id"
}


class TestVolumeAttachDetach(powerstore.TestPowerStoreDriver):

    QOS_SPECS = {
        'qos_specs': {
            'name': 'powerstore_qos',
            'id': 'd8c88f5a-4c6f-4f89-97c5-da1ef059006e',
            'created_at': 'fake_date',
            'consumer': 'back-end',
            'specs': {
                'max_bw': '104857600',
                'max_iops': '500',
                'bandwidth_limit_type': 'Absolute',
                'burst_percentage': '50'
            }
        }
    }

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    def setUp(self, mock_chap):
        super(TestVolumeAttachDetach, self).setUp()
        mock_chap.return_value = {"mode": "Single"}
        self.iscsi_driver.check_for_setup_error()
        self.fc_driver.check_for_setup_error()
        with mock.patch.object(self.nvme_driver.adapter.client,
                               "get_array_version",
                               return_value=(
                                   "3.0.0.0"
                               )):
            self.nvme_driver.check_for_setup_error()
        self.volume = fake_volume.fake_volume_obj(
            self.context,
            host="host@backend",
            provider_id="fake_id",
            size=8,
            volume_type_id="fake_volume_type_id"
        )
        self.volume.volume_attachment = (
            volume_attachment.VolumeAttachmentList()
        )
        self.volume.volume_attachment.objects = [
            volume_attachment.VolumeAttachment(
                attach_status=fields.VolumeAttachStatus.ATTACHED,
                attached_host=self.volume.host
            ),
            volume_attachment.VolumeAttachment(
                attach_status=fields.VolumeAttachStatus.ATTACHED,
                attached_host=self.volume.host
            )
        ]
        fake_iscsi_targets_response = [
            {
                "address": "1.2.3.4",
                "ip_port": {
                    "target_iqn":
                        "iqn.2020-07.com.dell:dellemc-powerstore-test-iqn-1"
                },
            },
            {
                "address": "5.6.7.8",
                "ip_port": {
                    "target_iqn":
                        "iqn.2020-07.com.dell:dellemc-powerstore-test-iqn-1"
                },
            },
        ]
        fake_fc_wwns_response = [
            {
                "wwn": "58:cc:f0:98:49:21:07:02"
            },
            {
                "wwn": "58:cc:f0:98:49:23:07:02"
            },
        ]
        fake_nvme_portals_response = [
            {
                "address": "11.22.33.44"
            },
            {
                "address": "55.66.77.88"
            }
        ]
        fake_nvme_nqn_response = [
            {
                "nvm_subsystem_nqn":
                    "nqn.2020-07.com.dell:powerstore:00:test-nqn"
            }
        ]
        self.fake_connector = {
            "host": self.volume.host,
            "wwpns": ["58:cc:f0:98:49:21:07:02", "58:cc:f0:98:49:23:07:02"],
            "initiator": "fake_initiator",
        }
        self.iscsi_targets_mock = self.mock_object(
            self.iscsi_driver.adapter.client,
            "get_ip_pool_address",
            return_value=fake_iscsi_targets_response
        )
        self.fc_wwns_mock = self.mock_object(
            self.fc_driver.adapter.client,
            "get_fc_port",
            return_value=fake_fc_wwns_response
        )
        self.nvme_portal_mock = self.mock_object(
            self.nvme_driver.adapter.client,
            "get_ip_pool_address",
            return_value=fake_nvme_portals_response
        )
        self.nvme_nqn_mock = self.mock_object(
            self.nvme_driver.adapter.client,
            "get_subsystem_nqn",
            return_value=fake_nvme_nqn_response
        )

    def test_initialize_connection_chap_enabled(self):
        self.iscsi_driver.adapter.use_chap_auth = True
        with mock.patch.object(self.iscsi_driver.adapter,
                               "_create_host_and_attach",
                               return_value=(
                                   utils.get_chap_credentials(),
                                   1
                               )):
            connection_properties = self.iscsi_driver.initialize_connection(
                self.volume,
                self.fake_connector
            )
            self.assertIn("auth_username", connection_properties["data"])
            self.assertIn("auth_password", connection_properties["data"])

    def test_initialize_connection_chap_disabled(self):
        self.iscsi_driver.adapter.use_chap_auth = False
        with mock.patch.object(self.iscsi_driver.adapter,
                               "_create_host_and_attach",
                               return_value=(
                                   utils.get_chap_credentials(),
                                   1
                               )):
            connection_properties = self.iscsi_driver.initialize_connection(
                self.volume,
                self.fake_connector
            )
            self.assertNotIn("auth_username", connection_properties["data"])
            self.assertNotIn("auth_password", connection_properties["data"])

    def test_get_fc_targets(self):
        wwns = self.fc_driver.adapter._get_fc_targets()
        self.assertEqual(2, len(wwns))

    def test_get_fc_targets_filtered(self):
        self.fc_driver.adapter.allowed_ports = ["58:cc:f0:98:49:23:07:02"]
        wwns = self.fc_driver.adapter._get_fc_targets()
        self.assertEqual(1, len(wwns))
        self.assertNotIn(
            utils.fc_wwn_to_string("58:cc:f0:98:49:21:07:02"), wwns
        )

    def test_get_fc_targets_filtered_no_matched_ports(self):
        self.fc_driver.adapter.allowed_ports = ["fc_wwn_1", "fc_wwn_2"]
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.fc_driver.adapter._get_fc_targets)
        self.assertIn("There are no accessible Fibre Channel targets on the "
                      "system.", error.msg)

    def test_get_iscsi_targets(self):
        iqns, portals = self.iscsi_driver.adapter._get_iscsi_targets()
        self.assertTrue(len(iqns) == len(portals))
        self.assertEqual(2, len(portals))

    def test_get_iscsi_targets_filtered(self):
        self.iscsi_driver.adapter.allowed_ports = ["1.2.3.4"]
        iqns, portals = self.iscsi_driver.adapter._get_iscsi_targets()
        self.assertTrue(len(iqns) == len(portals))
        self.assertEqual(1, len(portals))
        self.assertNotIn(
            "iqn.2020-07.com.dell:dellemc-powerstore-test-iqn-2", iqns
        )

    def test_get_iscsi_targets_filtered_no_matched_ports(self):
        self.iscsi_driver.adapter.allowed_ports = ["1.1.1.1", "2.2.2.2"]
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.iscsi_driver.adapter._get_iscsi_targets)
        self.assertIn("There are no accessible iSCSI targets on the system.",
                      error.msg)

    def test_get_nvme_targets(self):
        portals, nqn = self.nvme_driver.adapter._get_nvme_targets()
        self.assertEqual(2, len(portals))

    def test_get_connection_properties(self):
        volume_identifier = '123'
        portals, nqn = self.nvme_driver.adapter._get_nvme_targets()
        result = {
            'driver_volume_type': 'nvmeof',
            'data': {
                'portals': [('11.22.33.44', 4420, 'tcp'),
                            ('55.66.77.88', 4420, 'tcp')],
                'target_nqn': [{
                    'nvm_subsystem_nqn':
                        'nqn.2020-07.com.dell:powerstore:00:test-nqn'
                }],
                'volume_nguid': '123',
                'discard': True
            }
        }
        self.assertEqual(result,
                         self.nvme_driver.adapter.
                         _get_connection_properties(volume_identifier))

    def test_get_connection_properties_no_volume_identifier(self):
        portals, nqn = self.nvme_driver.adapter._get_nvme_targets()
        result = {
            'driver_volume_type': 'nvmeof',
            'data': {
                'portals': [('11.22.33.44', 4420, 'tcp'),
                            ('55.66.77.88', 4420, 'tcp')],
                'target_nqn': [{
                    'nvm_subsystem_nqn':
                        'nqn.2020-07.com.dell:powerstore:00:test-nqn'
                }],
                'volume_nguid': None,
                'discard': True
            }
        }
        self.assertEqual(result, self.nvme_driver.adapter.
                         _get_connection_properties(None))

    def test_get_connection_properties_no_nqn(self):
        volume_identifier = '123'
        with mock.patch.object(self.nvme_driver.adapter,
                               "_get_nvme_targets",
                               return_value=(['11.22.33.44', '55.66.77.88'],
                                             [])):
            result = {
                'driver_volume_type': 'nvmeof',
                'data': {
                    'portals': [('11.22.33.44', 4420, 'tcp'),
                                ('55.66.77.88', 4420, 'tcp')],
                    'target_nqn': [],
                    'volume_nguid': '123',
                    'discard': True
                }
            }
            self.assertEqual(result, self.nvme_driver.adapter.
                             _get_connection_properties(volume_identifier))

    def test_get_connection_properties_no_portals(self):
        volume_identifier = '123'
        with mock.patch.object(self.nvme_driver.adapter,
                               "_get_nvme_targets",
                               return_value=(
                                   [],
                                   [{
                                       'nvm_subsystem_nqn':
                                           'nqn.2020-07.com.dell:powerstore:0'
                                           '0:test-nqn'
                                   }]
                               )):
            result = {
                'driver_volume_type': 'nvmeof',
                'data': {
                    'portals': [],
                    'target_nqn': [{
                        'nvm_subsystem_nqn':
                        'nqn.2020-07.com.dell:powerstore:00:test-nqn'
                    }],
                    'volume_nguid': '123',
                    'discard': True
                }
            }
            self.assertEqual(result, self.nvme_driver.adapter.
                             _get_connection_properties(volume_identifier))

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter._detach_volume_from_hosts")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter._filter_hosts_by_initiators")
    def test_detach_multiattached_volume(self, mock_filter_hosts, mock_detach):
        self.iscsi_driver.terminate_connection(self.volume,
                                               self.fake_connector)
        mock_filter_hosts.assert_not_called()
        mock_detach.assert_not_called()
        self.volume.volume_attachment.objects.pop()
        self.iscsi_driver.terminate_connection(self.volume,
                                               self.fake_connector)
        mock_filter_hosts.assert_called_once()
        mock_detach.assert_called_once()

    @mock.patch('cinder.volume.volume_types.'
                'get_volume_type_qos_specs',
                return_value=QOS_SPECS)
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.attach_volume_to_host")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_lun")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_array_version",
                return_value='4.0')
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_qos_policy_id_by_name",
                return_value=None)
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.create_qos_io_rule")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.create_qos_policy")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.update_volume_with_qos_policy")
    def test_volume_qos_policy_create(self,
                                      mock_volume_types,
                                      mock_attach_volume,
                                      mock_get_volume_lun,
                                      mock_get_array_version,
                                      mock_get_qos_policy,
                                      mock_qos_io_rule,
                                      mock_qos_policy,
                                      mock_volume_qos_update):

        self.iscsi_driver.adapter.use_chap_auth = False
        self.mock_object(self.iscsi_driver.adapter,
                         "_create_host_if_not_exist",
                         return_value=(
                             FAKE_HOST,
                             utils.get_chap_credentials(),
                         ))
        self.iscsi_driver.initialize_connection(
            self.volume,
            self.fake_connector
        )
        mock_get_volume_lun.return_value = "fake_volume_identifier"
        mock_qos_io_rule.return_value = "9beb10ff-a00c-4d88-a7d9-692be2b3073f"
        mock_qos_policy.return_value = "d69f7131-4617-4bae-89f8-a540a6bda94b"
        mock_volume_types.assert_called_once()
        mock_get_array_version.assert_called_once()
        mock_get_qos_policy.assert_called_once()
        mock_attach_volume.assert_called_once()
        mock_qos_policy.assert_called_once()
        mock_volume_qos_update.assert_called_once()

    @mock.patch('cinder.volume.volume_types.'
                'get_volume_type_qos_specs',
                return_value=QOS_SPECS)
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.attach_volume_to_host")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_lun")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_array_version",
                return_value='4.0')
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_qos_policy_id_by_name")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.update_qos_io_rule")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.update_volume_with_qos_policy")
    def test_volume_qos_io_rule_update(self,
                                       mock_volume_types,
                                       mock_attach_volume,
                                       mock_get_volume_lun,
                                       mock_get_array_version,
                                       mock_get_qos_policy,
                                       mock_update_qos_io_rule,
                                       mock_volume_qos_update):
        self.iscsi_driver.adapter.use_chap_auth = False
        self.mock_object(self.iscsi_driver.adapter,
                         "_create_host_if_not_exist",
                         return_value=(
                             FAKE_HOST,
                             utils.get_chap_credentials(),
                         ))
        self.iscsi_driver.initialize_connection(
            self.volume,
            self.fake_connector
        )
        mock_get_volume_lun.return_value = "fake_volume_identifier"
        mock_get_qos_policy.return_value = ("d69f7131-"
                                            "4617-4bae-89f8-a540a6bda94b")
        mock_volume_types.assert_called_once()
        mock_attach_volume.assert_called_once()
        mock_get_array_version.assert_called_once()
        mock_update_qos_io_rule.assert_called_once()
        mock_volume_qos_update.assert_called_once()

    @mock.patch('cinder.volume.volume_types.'
                'get_volume_type_qos_specs',
                return_value=QOS_SPECS)
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.utils."
                "is_multiattached_to_host", return_value=False)
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.detach_volume_from_host")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_array_version",
                return_value='4.0')
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.update_volume_with_qos_policy")
    def test_volume_qos_policy_update(self,
                                      mock_volume_types,
                                      mock_multi_attached_host,
                                      mock_detach_volume,
                                      mock_get_array_version,
                                      mock_volume_qos_update):
        self.mock_object(self.iscsi_driver.adapter,
                         "_filter_hosts_by_initiators",
                         return_value=FAKE_HOST)
        self.iscsi_driver.terminate_connection(self.volume,
                                               self.fake_connector)
        mock_volume_types.assert_called_once()
        mock_multi_attached_host.assert_called_once()
        mock_detach_volume.assert_called_once()
        mock_get_array_version.assert_called_once()
        mock_volume_qos_update.assert_called_once()
