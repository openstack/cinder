# Copyright (c) 2016 Reduxio Systems
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
import copy
import random
import string

import mock
from oslo_utils import units

from cinder import exception
from cinder import test
from cinder.volume.drivers.reduxio import rdx_cli_api
from cinder.volume.drivers.reduxio import rdx_iscsi_driver

DRIVER_PATH = ("cinder.volume.drivers."
               "reduxio.rdx_iscsi_driver.ReduxioISCSIDriver")
API_PATH = "cinder.volume.drivers.reduxio.rdx_cli_api.ReduxioAPI"

TARGET = "mock_target"
TARGET_USER = "rdxadmin"
TARGET_PASSWORD = "mock_password"
VOLUME_BACKEND_NAME = "REDUXIO_VOLUME_TYPE"
CINDER_ID_LENGTH = 36
VOLUME_ID = "abcdabcd-1234-abcd-1234-abcdeffedcba"
VOLUME = {
    "name": "volume-" + VOLUME_ID,
    "id": VOLUME_ID,
    "display_name": "fake_volume",
    "size": 2,
    "host": "irrelevant",
    "volume_type": None,
    "volume_type_id": None,
    "consistencygroup_id": None,
    'metadata': {}
}

VOLUME_RDX_NAME = "abcdabcd1234abcd1234abcdeffedcb"
VOLUME_RDX_DESC = "openstack_" + VOLUME["name"]

SRC_VOL_ID = "4c7a294d-5964-4379-a15f-ce5554734efc"
SRC_VOL_RDX_NAME = "ac7a294d59644379a15fce5554734ef"

SRC_VOL = {
    "name": "volume-" + SRC_VOL_ID,
    "id": SRC_VOL_ID,
    "display_name": 'fake_src',
    "size": 2,
    "host": "irrelevant",
    "volume_type": None,
    "volume_type_id": None,
    "consistencygroup_id": None,
}

SNAPSHOT_ID = "04fe2f9a-d0c4-4564-a30d-693cc3657b47"
SNAPSHOT_RDX_NAME = "a4fe2f9ad0c44564a30d693cc3657b4"

SNAPSHOT = {
    "name": "snapshot-" + SNAPSHOT_ID,
    "id": SNAPSHOT_ID,
    "volume_id": SRC_VOL_ID,
    "volume_name": "volume-" + SRC_VOL_ID,
    "volume_size": 2,
    "display_name": "fake_snapshot",
    "cgsnapshot_id": None,
    "metadata": {}
}

CONNECTOR = {
    "initiator": "iqn.2013-12.com.stub:af4032f00014000e",
}

LS_SETTINGS = {
    "system_configuration": [
        {
            "name": "host_name",
            "value": "reduxio"
        },
        {
            "name": "serial_number",
            "value": "af4032f00014000e"
        },
        {
            "name": "primary_ntp",
            "value": "mickey.il.reduxio"
        },
        {
            "name": "secondary_ntp",
            "value": "minnie.il.reduxio"
        },
        {
            "name": "timezone",
            "value": "Asia/Jerusalem"
        },
        {
            "name": "capacity_threshold",
            "value": "93%"
        },
        {
            "name": "storsense_enabled",
            "value": True
        }
    ],
    "network_configuration": [
        {
            "name": "iscsi_target_iqn",
            "value": "iqn.2013-12.com.reduxio:af4032f00014000e"
        },
        {
            "name": "iscsi_target_tcp_port",
            "value": "3260"
        },
        {
            "name": "mtu",
            "value": "9000"
        }
    ],
    "iscsi_network1": [
        {
            "name": "controller_1_port_1",
            "value": "10.46.93.11"
        },
        {
            "name": "controller_2_port_1",
            "value": "10.46.93.22"
        },
        {
            "name": "subnet_mask",
            "value": "255.0.0.0"
        },
        {
            "name": "default_gateway",
            "value": None
        },
        {
            "name": "vlan_tag",
            "value": None
        }
    ],
    "iscsi_network2": [
        {
            "name": "controller_1_port_2",
            "value": "10.64.93.11"
        },
        {
            "name": "controller_2_port_2",
            "value": "10.64.93.22"
        },
        {
            "name": "subnet_mask",
            "value": "255.0.0.0"
        },
        {
            "name": "default_gateway",
            "value": None
        },
        {
            "name": "vlan_tag",
            "value": None
        }
    ],
    "management_settings": [
        {
            "name": "floating_ip",
            "value": "172.17.46.93"
        },
        {
            "name": "management_ip1",
            "value": "172.17.46.91"
        },
        {
            "name": "management_ip2",
            "value": "172.17.46.92"
        },
        {
            "name": "subnet_mask",
            "value": "255.255.254.0"
        },
        {
            "name": "default_gateway",
            "value": "172.17.47.254"
        },
        {
            "name": "primary_dns",
            "value": "172.17.32.11"
        },
        {
            "name": "secondary_dns",
            "value": "8.8.8.8"
        },
        {
            "name": "domain_name",
            "value": "il.reduxio"
        }
    ],
    "snmp": [
        {
            "Name": "trap_destination",
            "value": None
        },
        {
            "Name": "udp_port",
            "value": "162"
        },
        {
            "Name": "community",
            "value": "public"
        }
    ],
    "email_notification": [
        {
            "Name": "smtp_server",
            "value": None
        },
        {
            "Name": "tcp_port",
            "value": None
        },
        {
            "Name": "smtp_authentication",
            "value": "None"
        },
        {
            "Name": "user_name",
            "value": None
        },
        {
            "Name": "sender_address",
            "value": None
        }
    ],
    "email_recipient_list": [
        {
            "email": None
        }
    ],
    "directories": [
        {
            "name": "history_policies/"
        }
    ]
}

TEST_ASSIGN_LUN_NUM = 7

ISCSI_CONNECTION_INFO_NO_MULTIPATH = {
    "driver_volume_type": "iscsi",
    "data": {
        "target_discovered": False,
        "discard": False,
        "volume_id": VOLUME["id"],
        "target_lun": TEST_ASSIGN_LUN_NUM,
        "target_iqn": "iqn.2013-12.com.reduxio:af4032f00014000e",
        "target_portal": "10.46.93.11:3260",

    }
}

connection_copied = copy.deepcopy(
    ISCSI_CONNECTION_INFO_NO_MULTIPATH["data"]
)
connection_copied.update({
    "target_luns": [TEST_ASSIGN_LUN_NUM] * 4,
    "target_iqns": ["iqn.2013-12.com.reduxio:af4032f00014000e",
                    "iqn.2013-12.com.reduxio:af4032f00014000e",
                    "iqn.2013-12.com.reduxio:af4032f00014000e",
                    "iqn.2013-12.com.reduxio:af4032f00014000e"],
    "target_portals": ["10.46.93.11:3260", "10.46.93.22:3260",
                       "10.64.93.11:3260", "10.64.93.22:3260"]
})

ISCSI_CONNECTION_INFO = {
    "driver_volume_type": "iscsi",
    "data": connection_copied
}


def mock_api(to_mock=False):
    def client_mock_wrapper(func):

        def inner_client_mock(self, *args, **kwargs):
            rdx_cli_api.ReduxioAPI._connect = mock.Mock()
            if to_mock:
                self.driver = rdx_iscsi_driver.ReduxioISCSIDriver(
                    configuration=self.mock_config)
                self.mock_api = mock.Mock(spec=rdx_cli_api.ReduxioAPI)
                self.driver.rdxApi = self.mock_api
            else:
                self.driver = rdx_iscsi_driver.ReduxioISCSIDriver(
                    configuration=self.mock_config)
                self.driver.do_setup(None)
            func(self, *args)

        return inner_client_mock

    return client_mock_wrapper


class ReduxioISCSIDriverTestCase(test.TestCase):
    def setUp(self):
        super(ReduxioISCSIDriverTestCase, self).setUp()
        self.mock_config = mock.Mock()
        self.mock_config.san_ip = TARGET
        self.mock_config.san_login = TARGET_USER
        self.mock_config.san_password = TARGET_PASSWORD
        self.mock_config.volume_backend_name = VOLUME_BACKEND_NAME
        self.driver = None  # type: ReduxioISCSIDriver

    @staticmethod
    def generate_random_uuid():
        return ''.join(
            random.choice(string.ascii_uppercase + string.digits) for _ in
            range(rdx_iscsi_driver.RDX_CLI_MAX_VOL_LENGTH))

    @mock_api(False)
    def test_cinder_id_to_rdx(self):
        random_uuid1 = self.generate_random_uuid()
        random_uuid2 = self.generate_random_uuid()
        result1 = self.driver._cinder_id_to_rdx(random_uuid1)
        result2 = self.driver._cinder_id_to_rdx(random_uuid2)
        self.assertEqual(rdx_iscsi_driver.RDX_CLI_MAX_VOL_LENGTH, len(result1))
        self.assertEqual(rdx_iscsi_driver.RDX_CLI_MAX_VOL_LENGTH, len(result2))
        self.assertNotEqual(result1, result2)

    @mock.patch.object(rdx_cli_api.ReduxioAPI, "_run_cmd")
    @mock_api(False)
    def test_create_volume(self, mock_run_cmd):
        self.driver.create_volume(VOLUME)
        expected_cmd = rdx_cli_api.RdxApiCmd("volumes new",
                                             argument=VOLUME_RDX_NAME,
                                             flags=[
                                                 ["size", VOLUME["size"]],
                                                 ["description",
                                                  VOLUME_RDX_DESC]
                                             ])
        mock_run_cmd.assert_called_with(expected_cmd)

    @mock.patch.object(rdx_cli_api.ReduxioAPI, "_run_cmd")
    @mock_api(False)
    def test_manage_existing(self, mock_run_cmd):
        source_name = 'test-source'
        self.driver.rdxApi.find_volume_by_name = mock.Mock()
        self.driver.rdxApi.find_volume_by_name.return_value = {
            'name': source_name,
            'description': None

        }
        self.driver.manage_existing(VOLUME, {'source-name': source_name})

        expected_cmd = rdx_cli_api.RdxApiCmd("volumes update",
                                             argument=source_name,
                                             flags=[
                                                 ["new-name", VOLUME_RDX_NAME],
                                                 ["description",
                                                  VOLUME_RDX_DESC]
                                             ])
        mock_run_cmd.assert_called_with(expected_cmd)

        self.driver.rdxApi.find_volume_by_name.return_value = {
            'name': source_name,
            'description': "openstack_1234"
        }

        self.assertRaises(
            exception.ManageExistingAlreadyManaged,
            self.driver.manage_existing,
            VOLUME, {'source-name': source_name}
        )

    @mock.patch.object(rdx_cli_api.ReduxioAPI, "_run_cmd")
    @mock_api(False)
    def test_manage_existing_get_size(self, mock_run_cmd):
        source_name = 'test-source'
        self.driver.rdxApi.find_volume_by_name = mock.Mock()

        vol_cli_ret = {
            'name': source_name,
            'description': None,
            "size": units.Gi * 10
        }
        source_vol = {'source-name': source_name}

        self.driver.rdxApi.find_volume_by_name.return_value = vol_cli_ret
        ret = self.driver.manage_existing_get_size(VOLUME, source_vol)
        self.assertEqual(10, ret)

        vol_cli_ret["size"] = units.Gi * 9
        self.driver.rdxApi.find_volume_by_name.return_value = vol_cli_ret
        ret = self.driver.manage_existing_get_size(VOLUME, source_vol)
        self.assertNotEqual(10, ret)

    @mock.patch.object(rdx_cli_api.ReduxioAPI, "_run_cmd")
    @mock_api(False)
    def test_unmanage(self, mock_run_cmd):
        source_name = 'test-source'
        self.driver.rdxApi.find_volume_by_name = mock.Mock()
        self.driver.rdxApi.find_volume_by_name.return_value = {
            'name': source_name,
            'description': "openstack_1234"

        }
        self.driver.unmanage(VOLUME)

        expected_cmd = rdx_cli_api.RdxApiCmd(
            "volumes update",
            argument=VOLUME_RDX_NAME,
            flags=[["description", ""]])
        mock_run_cmd.assert_called_with(expected_cmd)

    @mock.patch.object(rdx_cli_api.ReduxioAPI, "_run_cmd")
    @mock_api(False)
    def test_delete_volume(self, mock_run_cmd):
        self.driver.delete_volume(VOLUME)
        expected_cmd = rdx_cli_api.RdxApiCmd(
            "volumes delete {} -force".format(VOLUME_RDX_NAME))
        mock_run_cmd.assert_called_with(expected_cmd)

    @mock.patch.object(rdx_cli_api.ReduxioAPI, "_run_cmd")
    @mock_api(False)
    def test_create_volume_from_snapshot(self, mock_run_cmd):
        self.driver.create_volume_from_snapshot(VOLUME, SNAPSHOT)

        expected_cmd = rdx_cli_api.RdxApiCmd(
            "volumes clone",
            argument=SRC_VOL_RDX_NAME,
            flags={
                "name": VOLUME_RDX_NAME,
                "bookmark": SNAPSHOT_RDX_NAME,
                "description": VOLUME_RDX_DESC}
        )

        mock_run_cmd.assert_called_with(expected_cmd)

        # Test resize
        bigger_vol = copy.deepcopy(VOLUME)
        bigger_size = SNAPSHOT['volume_size'] + 10
        bigger_vol['size'] = bigger_size

        self.driver.create_volume_from_snapshot(bigger_vol, SNAPSHOT)

        expected_cmd = rdx_cli_api.RdxApiCmd("volumes update",
                                             argument=VOLUME_RDX_NAME,
                                             flags={"size": bigger_size})

        mock_run_cmd.assert_called_with(expected_cmd)

    @mock.patch.object(rdx_cli_api.ReduxioAPI, "_run_cmd")
    @mock_api(False)
    def test_create_cloned_volume(self, mock_run_cmd):
        self.driver.create_cloned_volume(VOLUME, SRC_VOL)

        expected_cmd = rdx_cli_api.RdxApiCmd(
            "volumes clone",
            argument=SRC_VOL_RDX_NAME,
            flags={"name": VOLUME_RDX_NAME, "description": VOLUME_RDX_DESC})

        mock_run_cmd.assert_called_with(expected_cmd)

        # Test clone from date
        backdated_clone = copy.deepcopy(VOLUME)
        clone_date = "02/17/2015-11:39:00"
        backdated_clone["metadata"]["backdate"] = clone_date

        self.driver.create_cloned_volume(backdated_clone, SRC_VOL)
        expected_cmd.add_flag("timestamp", clone_date)
        mock_run_cmd.assert_called_with(expected_cmd)

    @mock.patch.object(rdx_cli_api.ReduxioAPI, "_run_cmd")
    @mock_api(False)
    def test_create_snapshot(self, mock_run_cmd):
        self.driver.create_snapshot(SNAPSHOT)

        expected_cmd = rdx_cli_api.RdxApiCmd(
            "volumes bookmark",
            argument=SRC_VOL_RDX_NAME,
            flags={"name": SNAPSHOT_RDX_NAME, "type": "manual"})

        mock_run_cmd.assert_called_with(expected_cmd)

        backdated_snap = copy.deepcopy(SNAPSHOT)
        clone_date = "02/17/2015-11:39:00"
        backdated_snap["metadata"]["backdate"] = clone_date

        self.driver.create_snapshot(backdated_snap)

        expected_cmd = rdx_cli_api.RdxApiCmd(
            "volumes bookmark",
            argument=SRC_VOL_RDX_NAME,
            flags={
                "name": SNAPSHOT_RDX_NAME,
                "type": "manual",
                "timestamp": clone_date}
        )

        mock_run_cmd.assert_called_with(expected_cmd)

    @mock.patch.object(rdx_cli_api.ReduxioAPI, "_run_cmd")
    @mock_api(False)
    def test_delete_snapshot(self, mock_run_cmd):
        self.driver.delete_snapshot(SNAPSHOT)

        expected_cmd = rdx_cli_api.RdxApiCmd("volumes delete-bookmark",
                                             argument=SRC_VOL_RDX_NAME,
                                             flags={"name": SNAPSHOT_RDX_NAME})

        mock_run_cmd.assert_called_with(expected_cmd)

    @mock.patch.object(rdx_cli_api.ReduxioAPI, "_run_cmd")
    @mock_api(False)
    def test_get_volume_stats(self, mock_run_cmd):
        pass

    @mock.patch.object(rdx_cli_api.ReduxioAPI, "_run_cmd")
    @mock_api(False)
    def test_extend_volume(self, mock_run_cmd):
        new_size = VOLUME["size"] + 1
        self.driver.extend_volume(VOLUME, new_size)

        expected_cmd = rdx_cli_api.RdxApiCmd("volumes update",
                                             argument=VOLUME_RDX_NAME,
                                             flags={"size": new_size})

        mock_run_cmd.assert_called_with(expected_cmd)

    def settings_side_effect(*args):
        if args[0].cmd == "settings ls":
            return LS_SETTINGS
        else:
            return mock.Mock()

    def get_single_assignment_side_effect(*args, **kwargs):
        if "raise_on_non_exists" in kwargs:
            raise_given = kwargs["raise_on_non_exists"]
        else:
            raise_given = True
        if (raise_given is True) or (raise_given is None):
            return {
                "host": kwargs["host"],
                "vol": kwargs["vol"],
                "lun": TEST_ASSIGN_LUN_NUM
            }
        else:
            return None

    @mock.patch.object(rdx_cli_api.ReduxioAPI, "_run_cmd",
                       side_effect=settings_side_effect)
    @mock.patch.object(rdx_cli_api.ReduxioAPI, "get_single_assignment",
                       side_effect=get_single_assignment_side_effect)
    @mock_api(False)
    def test_initialize_connection(self, mock_list_assignmnet, mock_run_cmd):
        generated_host_name = "openstack-123456789012"
        self.driver.rdxApi.list_hosts = mock.Mock()
        self.driver.rdxApi.list_hosts.return_value = []
        self.driver._generate_initiator_name = mock.Mock()
        self.driver._generate_initiator_name.return_value = generated_host_name

        ret_connection_info = self.driver.initialize_connection(VOLUME,
                                                                CONNECTOR)

        create_host_cmd = rdx_cli_api.RdxApiCmd(
            "hosts new",
            argument=generated_host_name,
            flags={"iscsi-name": CONNECTOR["initiator"]}
        )
        assign_cmd = rdx_cli_api.RdxApiCmd(
            "volumes assign",
            argument=VOLUME_RDX_NAME,
            flags={"host": generated_host_name}
        )

        calls = [
            mock.call.driver._run_cmd(create_host_cmd),
            mock.call.driver._run_cmd(assign_cmd)
        ]

        mock_run_cmd.assert_has_calls(calls)
        self.assertDictEqual(
            ret_connection_info,
            ISCSI_CONNECTION_INFO_NO_MULTIPATH
        )

        connector = copy.deepcopy(CONNECTOR)
        connector["multipath"] = True

        ret_connection_info = self.driver.initialize_connection(VOLUME,
                                                                connector)

        create_host_cmd = rdx_cli_api.RdxApiCmd(
            "hosts new",
            argument=generated_host_name,
            flags={"iscsi-name": CONNECTOR["initiator"]})

        assign_cmd = rdx_cli_api.RdxApiCmd(
            "volumes assign",
            argument=VOLUME_RDX_NAME,
            flags={"host": generated_host_name}
        )

        calls = [
            mock.call.driver._run_cmd(create_host_cmd),
            mock.call.driver._run_cmd(assign_cmd)
        ]

        mock_run_cmd.assert_has_calls(calls)
        self.assertDictEqual(ret_connection_info, ISCSI_CONNECTION_INFO)

        self.driver.rdxApi.list_hosts.return_value = [{
            "iscsi_name": CONNECTOR["initiator"],
            "name": generated_host_name
        }]

        ret_connection_info = self.driver.initialize_connection(VOLUME,
                                                                connector)

        mock_run_cmd.assert_has_calls([mock.call.driver._run_cmd(assign_cmd)])

        self.assertDictEqual(ISCSI_CONNECTION_INFO, ret_connection_info)

    @mock.patch.object(rdx_cli_api.ReduxioAPI, "_run_cmd")
    @mock_api(False)
    def test_terminate_connection(self, mock_run_cmd):
        generated_host_name = "openstack-123456789012"
        self.driver.rdxApi.list_hosts = mock.Mock()
        self.driver.rdxApi.list_hosts.return_value = [{
            "iscsi_name": CONNECTOR["initiator"],
            "name": generated_host_name
        }]

        self.driver.terminate_connection(VOLUME, CONNECTOR)

        unassign_cmd = rdx_cli_api.RdxApiCmd(
            "volumes unassign",
            argument=VOLUME_RDX_NAME,
            flags={"host": generated_host_name}
        )

        mock_run_cmd.assert_has_calls(
            [mock.call.driver._run_cmd(unassign_cmd)])
