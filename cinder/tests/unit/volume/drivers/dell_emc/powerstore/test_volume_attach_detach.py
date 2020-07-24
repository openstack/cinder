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


class TestVolumeAttachDetach(powerstore.TestPowerStoreDriver):
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_appliance_id_by_name")
    def setUp(self, mock_appliance):
        super(TestVolumeAttachDetach, self).setUp()
        mock_appliance.return_value = "A1"
        self.iscsi_driver.check_for_setup_error()
        self.fc_driver.check_for_setup_error()
        self.volume = fake_volume.fake_volume_obj(
            {},
            host="host@backend#test-appliance",
            provider_id="fake_id",
            size=8
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
        self.fake_iscsi_targets_response = [
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
        self.fake_fc_wwns_response = [
            {
                "wwn": "58:cc:f0:98:49:21:07:02"
            },
            {
                "wwn": "58:cc:f0:98:49:23:07:02"
            },
        ]
        self.fake_connector = {
            "host": self.volume.host,
            "wwpns": ["58:cc:f0:98:49:21:07:02", "58:cc:f0:98:49:23:07:02"],
            "initiator": "fake_initiator",
        }

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_fc_port")
    def test_get_fc_targets(self, mock_get_ip_pool):
        mock_get_ip_pool.return_value = self.fake_fc_wwns_response
        wwns = self.fc_driver.adapter._get_fc_targets("A1")
        self.assertEqual(2, len(wwns))

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_fc_port")
    def test_get_fc_targets_filtered(self, mock_get_ip_pool):
        mock_get_ip_pool.return_value = self.fake_fc_wwns_response
        self.fc_driver.adapter.allowed_ports = ["58:cc:f0:98:49:23:07:02"]
        wwns = self.fc_driver.adapter._get_fc_targets("A1")
        self.assertEqual(1, len(wwns))
        self.assertFalse(
            utils.fc_wwn_to_string("58:cc:f0:98:49:21:07:02") in wwns
        )

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_fc_port")
    def test_get_fc_targets_filtered_no_matched_ports(self, mock_get_ip_pool):
        mock_get_ip_pool.return_value = self.fake_fc_wwns_response
        self.fc_driver.adapter.allowed_ports = ["fc_wwn_1", "fc_wwn_2"]
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.fc_driver.adapter._get_fc_targets,
                                  "A1")
        self.assertIn("There are no accessible Fibre Channel targets on the "
                      "system.", error.msg)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_ip_pool_address")
    def test_get_iscsi_targets(self, mock_get_ip_pool):
        mock_get_ip_pool.return_value = self.fake_iscsi_targets_response
        iqns, portals = self.iscsi_driver.adapter._get_iscsi_targets("A1")
        self.assertTrue(len(iqns) == len(portals))
        self.assertEqual(2, len(portals))

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_ip_pool_address")
    def test_get_iscsi_targets_filtered(self, mock_get_ip_pool):
        mock_get_ip_pool.return_value = self.fake_iscsi_targets_response
        self.iscsi_driver.adapter.allowed_ports = ["1.2.3.4"]
        iqns, portals = self.iscsi_driver.adapter._get_iscsi_targets("A1")
        self.assertTrue(len(iqns) == len(portals))
        self.assertEqual(1, len(portals))
        self.assertFalse(
            "iqn.2020-07.com.dell:dellemc-powerstore-test-iqn-2" in iqns
        )

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_ip_pool_address")
    def test_get_iscsi_targets_filtered_no_matched_ports(self,
                                                         mock_get_ip_pool):
        mock_get_ip_pool.return_value = self.fake_iscsi_targets_response
        self.iscsi_driver.adapter.allowed_ports = ["1.1.1.1", "2.2.2.2"]
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.iscsi_driver.adapter._get_iscsi_targets,
                                  "A1")
        self.assertIn("There are no accessible iSCSI targets on the system.",
                      error.msg)

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
