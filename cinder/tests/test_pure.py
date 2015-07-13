# Copyright (c) 2014 Pure Storage, Inc.
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

import sys

import mock
from oslo_concurrency import processutils
from oslo_utils import units

from cinder import exception
from cinder import test


def fake_retry(exceptions, interval=1, retries=3, backoff_rate=2):
    def _decorator(f):
        return f
    return _decorator

patch_retry = mock.patch('cinder.utils.retry', fake_retry)
patch_retry.start()
sys.modules['purestorage'] = mock.Mock()
from cinder.volume.drivers import pure

# Only mock utils.retry for cinder.volume.drivers.pure import
patch_retry.stop()

DRIVER_PATH = "cinder.volume.drivers.pure"
DRIVER_OBJ = DRIVER_PATH + ".PureISCSIDriver"
ARRAY_OBJ = DRIVER_PATH + ".FlashArray"

TARGET = "pure-target"
API_TOKEN = "12345678-abcd-1234-abcd-1234567890ab"
VOLUME_BACKEND_NAME = "Pure_iSCSI"
PORT_NAMES = ["ct0.eth2", "ct0.eth3", "ct1.eth2", "ct1.eth3"]
ISCSI_IPS = ["10.0.0." + str(i + 1) for i in range(len(PORT_NAMES))]
HOSTNAME = "computenode1"
PURE_HOST_NAME = pure._generate_purity_host_name(HOSTNAME)
PURE_HOST = {"name": PURE_HOST_NAME,
             "hgroup": None,
             "iqn": [],
             "wwn": [],
             }
REST_VERSION = "1.2"
VOLUME_ID = "abcdabcd-1234-abcd-1234-abcdeffedcba"
VOLUME = {"name": "volume-" + VOLUME_ID,
          "id": VOLUME_ID,
          "display_name": "fake_volume",
          "size": 2,
          "host": "irrelevant",
          "volume_type": None,
          "volume_type_id": None,
          "consistencygroup_id": None
          }
VOLUME_WITH_CGROUP = VOLUME.copy()
VOLUME_WITH_CGROUP['consistencygroup_id'] = \
    "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
SRC_VOL_ID = "dc7a294d-5964-4379-a15f-ce5554734efc"
SRC_VOL = {"name": "volume-" + SRC_VOL_ID,
           "id": SRC_VOL_ID,
           "display_name": 'fake_src',
           "size": 2,
           "host": "irrelevant",
           "volume_type": None,
           "volume_type_id": None,
           "consistencygroup_id": None
           }
SNAPSHOT_ID = "04fe2f9a-d0c4-4564-a30d-693cc3657b47"
SNAPSHOT = {"name": "snapshot-" + SNAPSHOT_ID,
            "id": SNAPSHOT_ID,
            "volume_id": SRC_VOL_ID,
            "volume_name": "volume-" + SRC_VOL_ID,
            "volume_size": 2,
            "display_name": "fake_snapshot",
            "cgsnapshot_id": None
            }
SNAPSHOT_WITH_CGROUP = SNAPSHOT.copy()
SNAPSHOT_WITH_CGROUP['cgsnapshot_id'] = \
    "4a2f7e3a-312a-40c5-96a8-536b8a0fe075"
INITIATOR_IQN = "iqn.1993-08.org.debian:01:222"
CONNECTOR = {"initiator": INITIATOR_IQN, "host": HOSTNAME}
TARGET_IQN = "iqn.2010-06.com.purestorage:flasharray.12345abc"
TARGET_PORT = "3260"
ISCSI_PORTS = [{"name": name,
                "iqn": TARGET_IQN,
                "portal": ip + ":" + TARGET_PORT,
                "wwn": None,
                } for name, ip in zip(PORT_NAMES, ISCSI_IPS)]
NON_ISCSI_PORT = {"name": "ct0.fc1",
                  "iqn": None,
                  "portal": None,
                  "wwn": "5001500150015081",
                  }
PORTS_WITH = ISCSI_PORTS + [NON_ISCSI_PORT]
PORTS_WITHOUT = [NON_ISCSI_PORT]
VOLUME_CONNECTIONS = [{"host": "h1", "name": VOLUME["name"] + "-cinder"},
                      {"host": "h2", "name": VOLUME["name"] + "-cinder"},
                      ]
TOTAL_CAPACITY = 50.0
USED_SPACE = 32.1
PROVISIONED_CAPACITY = 70.0
DEFAULT_OVER_SUBSCRIPTION = 20
SPACE_INFO = {"capacity": TOTAL_CAPACITY * units.Gi,
              "total": USED_SPACE * units.Gi
              }
SPACE_INFO_EMPTY = {"capacity": TOTAL_CAPACITY * units.Gi,
                    "total": 0
                    }

CONNECTION_INFO = {"driver_volume_type": "iscsi",
                   "data": {"target_iqn": TARGET_IQN,
                            "target_portal": ISCSI_IPS[0] + ":" + TARGET_PORT,
                            "target_lun": 1,
                            "target_discovered": True,
                            "access_mode": "rw",
                            },
                   }


class FakePureStorageHTTPError(Exception):
    def __init__(self, target=None, rest_version=None, code=None,
                 headers=None, text=None):
        self.target = target
        self.rest_version = rest_version
        self.code = code
        self.headers = headers
        self.text = text


class PureISCSIDriverTestCase(test.TestCase):

    def setUp(self):
        super(PureISCSIDriverTestCase, self).setUp()
        self.mock_config = mock.Mock()
        self.mock_config.san_ip = TARGET
        self.mock_config.pure_api_token = API_TOKEN
        self.mock_config.volume_backend_name = VOLUME_BACKEND_NAME
        self.mock_config.use_chap_auth = False
        self.driver = pure.PureISCSIDriver(configuration=self.mock_config)
        self.array = mock.Mock()
        self.driver._array = self.array
        self.purestorage_module = pure.purestorage
        self.purestorage_module.PureHTTPError = FakePureStorageHTTPError

    @mock.patch(DRIVER_OBJ + "._choose_target_iscsi_port")
    def test_do_setup(self, mock_choose_target_iscsi_port):
        mock_choose_target_iscsi_port.return_value = ISCSI_PORTS[0]
        self.purestorage_module.FlashArray.return_value = self.array
        self.array.get_rest_version.return_value = \
            self.driver.SUPPORTED_REST_API_VERSIONS[0]
        self.driver.do_setup(None)
        self.purestorage_module.FlashArray.assert_called_with(
            TARGET,
            api_token=API_TOKEN
        )
        self.assertEqual(self.array, self.driver._array)
        self.assertEqual(
            self.driver.SUPPORTED_REST_API_VERSIONS,
            self.purestorage_module.FlashArray.supported_rest_versions
        )
        mock_choose_target_iscsi_port.assert_called_with()
        self.assertEqual(ISCSI_PORTS[0], self.driver._iscsi_port)
        self.assert_error_propagates(
            [
                self.purestorage_module.FlashArray,
                mock_choose_target_iscsi_port
            ],
            self.driver.do_setup, None
        )

    def assert_error_propagates(self, mocks, func, *args, **kwargs):
        """Assert that errors from mocks propagate to func.

        Fail if exceptions raised by mocks are not seen when calling
        func(*args, **kwargs). Ensure that we are really seeing exceptions
        from the mocks by failing if just running func(*args, **kargs) raises
        an exception itself.
        """
        func(*args, **kwargs)
        for mock_func in mocks:
            mock_func.side_effect = exception.PureDriverException(
                reason="reason")
            self.assertRaises(exception.PureDriverException,
                              func, *args, **kwargs)
            mock_func.side_effect = None

    def test_generate_purity_host_name(self):
        generate = pure._generate_purity_host_name
        result = generate("really-long-string-thats-a-bit-too-long")
        self.assertTrue(result.startswith("really-long-string-that-"))
        self.assertTrue(result.endswith("-cinder"))
        self.assertEqual(len(result), 63)
        self.assertTrue(pure.GENERATED_NAME.match(result))
        result = generate("!@#$%^-invalid&*")
        self.assertTrue(result.startswith("invalid---"))
        self.assertTrue(result.endswith("-cinder"))
        self.assertEqual(len(result), 49)
        self.assertTrue(pure.GENERATED_NAME.match(result))

    def test_create_volume(self):
        self.driver.create_volume(VOLUME)
        self.array.create_volume.assert_called_with(
            VOLUME["name"] + "-cinder", 2 * units.Gi)
        self.assert_error_propagates([self.array.create_volume],
                                     self.driver.create_volume, VOLUME)

    @mock.patch(DRIVER_OBJ + "._add_volume_to_consistency_group",
                autospec=True)
    def test_create_volume_with_cgroup(self, mock_add_to_cgroup):
        vol_name = VOLUME_WITH_CGROUP["name"] + "-cinder"

        self.driver.create_volume(VOLUME_WITH_CGROUP)

        mock_add_to_cgroup\
            .assert_called_with(self.driver,
                                VOLUME_WITH_CGROUP['consistencygroup_id'],
                                vol_name)

    def test_create_volume_from_snapshot(self):
        vol_name = VOLUME["name"] + "-cinder"
        snap_name = SNAPSHOT["volume_name"] + "-cinder." + SNAPSHOT["name"]

        # Branch where extend unneeded
        self.driver.create_volume_from_snapshot(VOLUME, SNAPSHOT)
        self.array.copy_volume.assert_called_with(snap_name, vol_name)
        self.assertFalse(self.array.extend_volume.called)
        self.assert_error_propagates(
            [self.array.copy_volume],
            self.driver.create_volume_from_snapshot, VOLUME, SNAPSHOT)
        self.assertFalse(self.array.extend_volume.called)

        # Branch where extend needed
        SNAPSHOT["volume_size"] = 1  # resize so smaller than VOLUME
        self.driver.create_volume_from_snapshot(VOLUME, SNAPSHOT)
        expected = [mock.call.copy_volume(snap_name, vol_name),
                    mock.call.extend_volume(vol_name, 2 * units.Gi)]
        self.array.assert_has_calls(expected)
        self.assert_error_propagates(
            [self.array.copy_volume, self.array.extend_volume],
            self.driver.create_volume_from_snapshot, VOLUME, SNAPSHOT)
        SNAPSHOT["volume_size"] = 2  # reset size

    @mock.patch(DRIVER_OBJ + "._add_volume_to_consistency_group",
                autospec=True)
    @mock.patch(DRIVER_OBJ + "._extend_if_needed", autospec=True)
    @mock.patch(DRIVER_PATH + "._get_pgroup_vol_snap_name", autospec=True)
    def test_create_volume_from_cgsnapshot(self, mock_get_snap_name,
                                           mock_extend_if_needed,
                                           mock_add_to_cgroup):
        vol_name = VOLUME_WITH_CGROUP["name"] + "-cinder"
        snap_name = "consisgroup-4a2f7e3a-312a-40c5-96a8-536b8a0f" \
                    "e074-cinder.4a2f7e3a-312a-40c5-96a8-536b8a0fe075."\
                    + vol_name
        mock_get_snap_name.return_value = snap_name

        self.driver.create_volume_from_snapshot(VOLUME_WITH_CGROUP,
                                                SNAPSHOT_WITH_CGROUP)

        self.array.copy_volume.assert_called_with(snap_name, vol_name)
        self.assertTrue(mock_get_snap_name.called)
        self.assertTrue(mock_extend_if_needed.called)

        self.driver.create_volume_from_snapshot(VOLUME_WITH_CGROUP,
                                                SNAPSHOT_WITH_CGROUP)
        mock_add_to_cgroup\
            .assert_called_with(self.driver,
                                VOLUME_WITH_CGROUP['consistencygroup_id'],
                                vol_name)

    def test_create_cloned_volume(self):
        vol_name = VOLUME["name"] + "-cinder"
        src_name = SRC_VOL["name"] + "-cinder"
        # Branch where extend unneeded
        self.driver.create_cloned_volume(VOLUME, SRC_VOL)
        self.array.copy_volume.assert_called_with(src_name, vol_name)
        self.assertFalse(self.array.extend_volume.called)
        self.assert_error_propagates(
            [self.array.copy_volume],
            self.driver.create_cloned_volume, VOLUME, SRC_VOL)
        self.assertFalse(self.array.extend_volume.called)
        # Branch where extend needed
        SRC_VOL["size"] = 1  # resize so smaller than VOLUME
        self.driver.create_cloned_volume(VOLUME, SRC_VOL)
        expected = [mock.call.copy_volume(src_name, vol_name),
                    mock.call.extend_volume(vol_name, 2 * units.Gi)]
        self.array.assert_has_calls(expected)
        self.assert_error_propagates(
            [self.array.copy_volume, self.array.extend_volume],
            self.driver.create_cloned_volume, VOLUME, SRC_VOL)
        SRC_VOL["size"] = 2  # reset size

    @mock.patch(DRIVER_OBJ + "._add_volume_to_consistency_group",
                autospec=True)
    def test_create_cloned_volume_with_cgroup(self, mock_add_to_cgroup):
        vol_name = VOLUME_WITH_CGROUP["name"] + "-cinder"

        self.driver.create_cloned_volume(VOLUME_WITH_CGROUP, SRC_VOL)

        mock_add_to_cgroup\
            .assert_called_with(self.driver,
                                VOLUME_WITH_CGROUP['consistencygroup_id'],
                                vol_name)

    def test_delete_volume_already_deleted(self):
        self.array.list_volume_private_connections.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=400,
                text="Volume does not exist"
            )
        self.driver.delete_volume(VOLUME)
        self.assertFalse(self.array.destroy_volume.called)

        # Testing case where array.destroy_volume returns an exception
        # because volume has already been deleted
        self.array.list_volume_private_connections.side_effect = None
        self.array.list_volume_private_connections.return_value = {}
        self.array.destroy_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=400,
                text="Volume does not exist"
            )
        self.driver.delete_volume(VOLUME)
        self.assertTrue(self.array.destroy_volume.called)

    def test_delete_volume(self):
        vol_name = VOLUME["name"] + "-cinder"
        self.array.list_volume_private_connections.return_value = {}
        self.driver.delete_volume(VOLUME)
        expected = [mock.call.destroy_volume(vol_name)]
        self.array.assert_has_calls(expected)
        self.array.destroy_volume.side_effect = \
            self.purestorage_module.PureHTTPError(code=400, text="reason")
        self.driver.delete_snapshot(SNAPSHOT)
        self.array.destroy_volume.side_effect = None
        self.assert_error_propagates([self.array.destroy_volume],
                                     self.driver.delete_volume, VOLUME)

    def test_delete_connected_volume(self):
        vol_name = VOLUME["name"] + "-cinder"
        host_name_a = "ha"
        host_name_b = "hb"
        self.array.list_volume_private_connections.return_value = [{
            "host": host_name_a,
            "lun": 7,
            "name": vol_name,
            "size": 3221225472
        }, {
            "host": host_name_b,
            "lun": 2,
            "name": vol_name,
            "size": 3221225472
        }]

        self.driver.delete_volume(VOLUME)
        expected = [mock.call.list_volume_private_connections(vol_name),
                    mock.call.disconnect_host(host_name_a, vol_name),
                    mock.call.disconnect_host(host_name_b, vol_name),
                    mock.call.destroy_volume(vol_name)]
        self.array.assert_has_calls(expected)

    def test_create_snapshot(self):
        vol_name = SRC_VOL["name"] + "-cinder"
        self.driver.create_snapshot(SNAPSHOT)
        self.array.create_snapshot.assert_called_with(
            vol_name,
            suffix=SNAPSHOT["name"]
        )
        self.assert_error_propagates([self.array.create_snapshot],
                                     self.driver.create_snapshot, SNAPSHOT)

    def test_delete_snapshot(self):
        snap_name = SNAPSHOT["volume_name"] + "-cinder." + SNAPSHOT["name"]
        self.driver.delete_snapshot(SNAPSHOT)
        expected = [mock.call.destroy_volume(snap_name)]
        self.array.assert_has_calls(expected)
        self.array.destroy_volume.side_effect = \
            self.purestorage_module.PureHTTPError(code=400, text="reason")
        self.driver.delete_snapshot(SNAPSHOT)
        self.array.destroy_volume.side_effect = None
        self.assert_error_propagates([self.array.destroy_volume],
                                     self.driver.delete_snapshot, SNAPSHOT)

    @mock.patch(DRIVER_OBJ + "._connect")
    @mock.patch(DRIVER_OBJ + "._get_target_iscsi_port")
    def test_initialize_connection(self, mock_get_iscsi_port, mock_connection):
        mock_get_iscsi_port.return_value = ISCSI_PORTS[0]
        mock_connection.return_value = {"vol": VOLUME["name"] + "-cinder",
                                        "lun": 1,
                                        }
        result = CONNECTION_INFO
        real_result = self.driver.initialize_connection(VOLUME, CONNECTOR)
        self.assertDictMatch(result, real_result)
        mock_get_iscsi_port.assert_called_with()
        mock_connection.assert_called_with(VOLUME, CONNECTOR, None)
        self.assert_error_propagates([mock_get_iscsi_port, mock_connection],
                                     self.driver.initialize_connection,
                                     VOLUME, CONNECTOR)

    @mock.patch(DRIVER_OBJ + "._connect")
    @mock.patch(DRIVER_OBJ + "._get_target_iscsi_port")
    def test_initialize_connection_with_auth(self, mock_get_iscsi_port,
                                             mock_connection):
        auth_type = "CHAP"
        chap_username = CONNECTOR["host"]
        chap_password = "password"
        mock_get_iscsi_port.return_value = ISCSI_PORTS[0]
        initiator_update = [{"key": pure.CHAP_SECRET_KEY,
                            "value": chap_password}]
        mock_connection.return_value = {
            "vol": VOLUME["name"] + "-cinder",
            "lun": 1,
            "auth_username": chap_username,
            "auth_password": chap_password,
        }
        result = CONNECTION_INFO.copy()
        result["data"]["auth_method"] = auth_type
        result["data"]["auth_username"] = chap_username
        result["data"]["auth_password"] = chap_password

        self.mock_config.use_chap_auth = True

        # Branch where no credentials were generated
        real_result = self.driver.initialize_connection(VOLUME,
                                                        CONNECTOR)
        mock_connection.assert_called_with(VOLUME, CONNECTOR, None)
        self.assertDictMatch(result, real_result)

        # Branch where new credentials were generated
        mock_connection.return_value["initiator_update"] = initiator_update
        result["initiator_update"] = initiator_update
        real_result = self.driver.initialize_connection(VOLUME,
                                                        CONNECTOR)
        mock_connection.assert_called_with(VOLUME, CONNECTOR, None)
        self.assertDictMatch(result, real_result)

        self.assert_error_propagates([mock_get_iscsi_port, mock_connection],
                                     self.driver.initialize_connection,
                                     VOLUME, CONNECTOR)

    @mock.patch(DRIVER_OBJ + "._choose_target_iscsi_port")
    @mock.patch(DRIVER_OBJ + "._run_iscsiadm_bare")
    def test_get_target_iscsi_port(self, mock_iscsiadm, mock_choose_port):
        self.driver._iscsi_port = ISCSI_PORTS[1]
        self.assertEqual(self.driver._get_target_iscsi_port(), ISCSI_PORTS[1])
        mock_iscsiadm.assert_called_with(["-m", "discovery",
                                          "-t", "sendtargets",
                                          "-p", ISCSI_PORTS[1]["portal"]])
        self.assertFalse(mock_choose_port.called)
        mock_iscsiadm.side_effect = [processutils.ProcessExecutionError, None]
        mock_choose_port.return_value = ISCSI_PORTS[2]
        self.assertEqual(self.driver._get_target_iscsi_port(), ISCSI_PORTS[2])
        mock_choose_port.assert_called_with()
        mock_iscsiadm.side_effect = processutils.ProcessExecutionError
        self.assert_error_propagates([mock_choose_port],
                                     self.driver._get_target_iscsi_port)

    @mock.patch(DRIVER_OBJ + "._run_iscsiadm_bare")
    def test_choose_target_iscsi_port(self, mock_iscsiadm):
        self.array.list_ports.return_value = PORTS_WITHOUT
        self.assertRaises(exception.PureDriverException,
                          self.driver._choose_target_iscsi_port)
        self.array.list_ports.return_value = PORTS_WITH
        self.assertEqual(ISCSI_PORTS[0],
                         self.driver._choose_target_iscsi_port())
        self.assert_error_propagates([mock_iscsiadm, self.array.list_ports],
                                     self.driver._choose_target_iscsi_port)

    @mock.patch(DRIVER_PATH + "._generate_chap_secret", autospec=True)
    @mock.patch(DRIVER_OBJ + "._get_host", autospec=True)
    @mock.patch(DRIVER_PATH + "._generate_purity_host_name", autospec=True)
    def test_connect(self, mock_generate, mock_host, mock_gen_secret):
        vol_name = VOLUME["name"] + "-cinder"
        result = {"vol": vol_name, "lun": 1}

        # Branch where host already exists
        mock_host.return_value = PURE_HOST
        self.array.connect_host.return_value = {"vol": vol_name, "lun": 1}
        real_result = self.driver._connect(VOLUME, CONNECTOR, None)
        self.assertEqual(result, real_result)
        mock_host.assert_called_with(self.driver, CONNECTOR)
        self.assertFalse(mock_generate.called)
        self.assertFalse(self.array.create_host.called)
        self.array.connect_host.assert_called_with(PURE_HOST_NAME, vol_name)

        # Branch where new host is created
        mock_host.return_value = None
        mock_generate.return_value = PURE_HOST_NAME
        real_result = self.driver._connect(VOLUME, CONNECTOR, None)
        mock_host.assert_called_with(self.driver, CONNECTOR)
        mock_generate.assert_called_with(HOSTNAME)
        self.array.create_host.assert_called_with(PURE_HOST_NAME,
                                                  iqnlist=[INITIATOR_IQN])
        self.assertEqual(result, real_result)

        mock_generate.reset_mock()
        self.array.reset_mock()
        self.assert_error_propagates(
            [mock_host, mock_generate, self.array.connect_host,
             self.array.create_host],
            self.driver._connect, VOLUME, CONNECTOR, None)

        self.mock_config.use_chap_auth = True
        chap_user = CONNECTOR["host"]
        chap_password = "sOmEseCr3t"

        # Branch where chap is used and credentials already exist
        initiator_data = [{"key": pure.CHAP_SECRET_KEY,
                           "value": chap_password}]
        self.driver._connect(VOLUME, CONNECTOR, initiator_data)
        result["auth_username"] = chap_user
        result["auth_password"] = chap_password
        self.assertDictMatch(result, real_result)
        self.array.set_host.assert_called_with(PURE_HOST_NAME,
                                               host_user=chap_user,
                                               host_password=chap_password)

        # Branch where chap is used and credentials are generated
        mock_gen_secret.return_value = chap_password
        self.driver._connect(VOLUME, CONNECTOR, None)
        result["auth_username"] = chap_user
        result["auth_password"] = chap_password
        result["initiator_update"] = {
            "set_values": {
                pure.CHAP_SECRET_KEY: chap_password
            }
        }
        self.assertDictMatch(result, real_result)
        self.array.set_host.assert_called_with(PURE_HOST_NAME,
                                               host_user=chap_user,
                                               host_password=chap_password)

    @mock.patch(DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected(self, mock_host):
        mock_host.return_value = PURE_HOST
        expected = {"host": PURE_HOST_NAME, "lun": 1}
        self.array.list_volume_private_connections.return_value = \
            [expected, {"host": "extra", "lun": 2}]
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=400,
                text="Connection already exists"
            )
        actual = self.driver._connect(VOLUME, CONNECTOR, None)
        self.assertEqual(expected, actual)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(self.array.list_volume_private_connections)

    @mock.patch(DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_empty(self, mock_host):
        mock_host.return_value = PURE_HOST
        self.array.list_volume_private_connections.return_value = {}
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=400,
                text="Connection already exists"
            )
        self.assertRaises(exception.PureDriverException, self.driver._connect,
                          VOLUME, CONNECTOR, None)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(self.array.list_volume_private_connections)

    @mock.patch(DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_exception(self, mock_host):
        mock_host.return_value = PURE_HOST
        self.array.list_volume_private_connections.side_effect = \
            self.purestorage_module.PureHTTPError(code=400, text="")
        self.array.connect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=400,
                text="Connection already exists"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver._connect, VOLUME, CONNECTOR, None)
        self.assertTrue(self.array.connect_host.called)
        self.assertTrue(self.array.list_volume_private_connections)

    def test_get_host(self):
        good_host = PURE_HOST.copy()
        good_host.update(iqn=["another-wrong-iqn", INITIATOR_IQN])
        bad_host = {"name": "bad-host", "iqn": ["wrong-iqn"]}
        self.array.list_hosts.return_value = [bad_host]
        real_result = self.driver._get_host(CONNECTOR)
        self.assertIs(real_result, None)
        self.array.list_hosts.return_value.append(good_host)
        real_result = self.driver._get_host(CONNECTOR)
        self.assertEqual(real_result, good_host)
        self.assert_error_propagates([self.array.list_hosts],
                                     self.driver._get_host, CONNECTOR)

    @mock.patch(DRIVER_OBJ + "._get_host", autospec=True)
    def test_terminate_connection(self, mock_host):
        vol_name = VOLUME["name"] + "-cinder"
        mock_host.return_value = {"name": "some-host"}
        # Branch with manually created host
        self.driver.terminate_connection(VOLUME, CONNECTOR)
        self.array.disconnect_host.assert_called_with("some-host", vol_name)
        self.assertFalse(self.array.list_host_connections.called)
        self.assertFalse(self.array.delete_host.called)
        # Branch with host added to host group
        self.array.reset_mock()
        self.array.list_host_connections.return_value = []
        mock_host.return_value = PURE_HOST.copy()
        mock_host.return_value.update(hgroup="some-group")
        self.driver.terminate_connection(VOLUME, CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.assertTrue(self.array.list_host_connections.called)
        self.assertTrue(self.array.delete_host.called)
        # Branch with host still having connected volumes
        self.array.reset_mock()
        self.array.list_host_connections.return_value = [
            {"lun": 2, "name": PURE_HOST_NAME, "vol": "some-vol"}]
        mock_host.return_value = PURE_HOST
        self.driver.terminate_connection(VOLUME, CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.array.list_host_connections.assert_called_with(PURE_HOST_NAME,
                                                            private=True)
        self.assertFalse(self.array.delete_host.called)
        # Branch where host gets deleted
        self.array.reset_mock()
        self.array.list_host_connections.return_value = []
        self.driver.terminate_connection(VOLUME, CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.array.list_host_connections.assert_called_with(PURE_HOST_NAME,
                                                            private=True)
        self.array.delete_host.assert_called_with(PURE_HOST_NAME)
        # Branch where connection is missing and the host is still deleted
        self.array.reset_mock()
        self.array.disconnect_host.side_effect = \
            self.purestorage_module.PureHTTPError(code=400, text="reason")
        self.driver.terminate_connection(VOLUME, CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.array.list_host_connections.assert_called_with(PURE_HOST_NAME,
                                                            private=True)
        self.array.delete_host.assert_called_with(PURE_HOST_NAME)
        # Branch where an unexpected exception occurs
        self.array.reset_mock()
        self.array.disconnect_host.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=500,
                text="Some other error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.terminate_connection, VOLUME, CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.assertFalse(self.array.list_host_connections.called)
        self.assertFalse(self.array.delete_host.called)

    @mock.patch(DRIVER_OBJ + "._get_host", autospec=True)
    def test_terminate_connection_host_deleted(self, mock_host):
        vol_name = VOLUME["name"] + "-cinder"
        mock_host.return_value = PURE_HOST.copy()
        self.array.reset_mock()
        self.array.list_host_connections.return_value = []
        self.array.delete_host.side_effect = \
            self.purestorage_module.PureHTTPError(code=400,
                                                  text='Host does not exist.')
        self.driver.terminate_connection(VOLUME, CONNECTOR)
        self.array.disconnect_host.assert_called_with(PURE_HOST_NAME, vol_name)
        self.array.list_host_connections.assert_called_with(PURE_HOST_NAME,
                                                            private=True)
        self.array.delete_host.assert_called_once_with(PURE_HOST_NAME)

    @mock.patch(DRIVER_OBJ + "._get_provisioned_space", autospec=True)
    def test_get_volume_stats(self, mock_space):
        mock_space.return_value = PROVISIONED_CAPACITY * units.Gi
        self.assertEqual(self.driver.get_volume_stats(), {})
        self.array.get.return_value = SPACE_INFO
        result = {"volume_backend_name": VOLUME_BACKEND_NAME,
                  "vendor_name": "Pure Storage",
                  "driver_version": self.driver.VERSION,
                  "storage_protocol": "iSCSI",
                  "total_capacity_gb": TOTAL_CAPACITY,
                  "free_capacity_gb": TOTAL_CAPACITY - USED_SPACE,
                  "reserved_percentage": 0,
                  "consistencygroup_support": True,
                  "thin_provisioning_support": True,
                  "provisioned_capacity": PROVISIONED_CAPACITY,
                  "max_over_subscription_ratio": (PROVISIONED_CAPACITY /
                                                  USED_SPACE)
                  }
        real_result = self.driver.get_volume_stats(refresh=True)
        self.assertDictMatch(result, real_result)
        self.assertDictMatch(result, self.driver._stats)

    @mock.patch(DRIVER_OBJ + "._get_provisioned_space", autospec=True)
    def test_get_volume_stats_empty_array(self, mock_space):
        mock_space.return_value = PROVISIONED_CAPACITY * units.Gi
        self.assertEqual(self.driver.get_volume_stats(), {})
        self.array.get.return_value = SPACE_INFO_EMPTY
        result = {"volume_backend_name": VOLUME_BACKEND_NAME,
                  "vendor_name": "Pure Storage",
                  "driver_version": self.driver.VERSION,
                  "storage_protocol": "iSCSI",
                  "total_capacity_gb": TOTAL_CAPACITY,
                  "free_capacity_gb": TOTAL_CAPACITY,
                  "reserved_percentage": 0,
                  "consistencygroup_support": True,
                  "thin_provisioning_support": True,
                  "provisioned_capacity": PROVISIONED_CAPACITY,
                  "max_over_subscription_ratio": DEFAULT_OVER_SUBSCRIPTION
                  }
        real_result = self.driver.get_volume_stats(refresh=True)
        self.assertDictMatch(result, real_result)
        self.assertDictMatch(result, self.driver._stats)

    @mock.patch(DRIVER_OBJ + "._get_provisioned_space", autospec=True)
    def test_get_volume_stats_nothing_provisioned(self, mock_space):
        mock_space.return_value = 0
        self.assertEqual(self.driver.get_volume_stats(), {})
        self.array.get.return_value = SPACE_INFO
        result = {"volume_backend_name": VOLUME_BACKEND_NAME,
                  "vendor_name": "Pure Storage",
                  "driver_version": self.driver.VERSION,
                  "storage_protocol": "iSCSI",
                  "total_capacity_gb": TOTAL_CAPACITY,
                  "free_capacity_gb": TOTAL_CAPACITY - USED_SPACE,
                  "reserved_percentage": 0,
                  "consistencygroup_support": True,
                  "thin_provisioning_support": True,
                  "provisioned_capacity": 0,
                  "max_over_subscription_ratio": DEFAULT_OVER_SUBSCRIPTION
                  }
        real_result = self.driver.get_volume_stats(refresh=True)
        self.assertDictMatch(result, real_result)
        self.assertDictMatch(result, self.driver._stats)

    def test_extend_volume(self):
        vol_name = VOLUME["name"] + "-cinder"
        self.driver.extend_volume(VOLUME, 3)
        self.array.extend_volume.assert_called_with(vol_name, 3 * units.Gi)
        self.assert_error_propagates([self.array.extend_volume],
                                     self.driver.extend_volume, VOLUME, 3)

    def test_get_pgroup_name_from_id(self):
        id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        expected_name = "consisgroup-%s-cinder" % id
        actual_name = pure._get_pgroup_name_from_id(id)
        self.assertEqual(expected_name, actual_name)

    def test_get_pgroup_snap_suffix(self):
        cgsnap = mock.Mock()
        cgsnap.id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        expected_suffix = "cgsnapshot-%s-cinder" % cgsnap.id
        actual_suffix = pure._get_pgroup_snap_suffix(cgsnap)
        self.assertEqual(expected_suffix, actual_suffix)

    def test_get_pgroup_snap_name(self):
        cg_id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        cgsnap_id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe075"

        mock_cgsnap = mock.Mock()
        mock_cgsnap.consistencygroup_id = cg_id
        mock_cgsnap.id = cgsnap_id
        expected_name = "consisgroup-%(cg)s-cinder.cgsnapshot-%(snap)s-cinder"\
                        % {"cg": cg_id, "snap": cgsnap_id}

        actual_name = pure._get_pgroup_snap_name(mock_cgsnap)

        self.assertEqual(expected_name, actual_name)

    def test_get_pgroup_vol_snap_name(self):
        cg_id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        cgsnap_id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe075"
        volume_name = "volume-4a2f7e3a-312a-40c5-96a8-536b8a0fe075"

        mock_snap = mock.Mock()
        mock_snap.cgsnapshot = mock.Mock()
        mock_snap.cgsnapshot.consistencygroup_id = cg_id
        mock_snap.cgsnapshot.id = cgsnap_id
        mock_snap.volume_name = volume_name

        expected_name = "consisgroup-%(cg)s-cinder.cgsnapshot-%(snap)s-cinder"\
                        ".%(vol)s-cinder" % {"cg": cg_id,
                                             "snap": cgsnap_id,
                                             "vol": volume_name}

        actual_name = pure._get_pgroup_vol_snap_name(mock_snap)

        self.assertEqual(expected_name, actual_name)

    def test_create_consistencygroup(self):
        mock_cgroup = mock.Mock()
        mock_cgroup.id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"

        model_update = self.driver.create_consistencygroup(None, mock_cgroup)

        expected_name = pure._get_pgroup_name_from_id(mock_cgroup.id)
        self.array.create_pgroup.assert_called_with(expected_name)
        self.assertEqual({'status': 'available'}, model_update)

        self.assert_error_propagates(
            [self.array.create_pgroup],
            self.driver.create_consistencygroup, None, mock_cgroup)

    @mock.patch(DRIVER_OBJ + ".create_volume_from_snapshot")
    @mock.patch(DRIVER_OBJ + ".create_consistencygroup")
    def test_create_consistencygroup_from_src(self, mock_create_cg,
                                              mock_create_vol):
        mock_context = mock.Mock()
        mock_group = mock.Mock()
        mock_cgsnapshot = mock.Mock()
        mock_snapshots = [mock.Mock() for i in range(5)]
        mock_volumes = [mock.Mock() for i in range(5)]
        self.driver.create_consistencygroup_from_src(
            mock_context,
            mock_group,
            mock_volumes,
            cgsnapshot=mock_cgsnapshot,
            snapshots=mock_snapshots
        )
        mock_create_cg.assert_called_with(mock_context, mock_group)
        expected_calls = [mock.call(vol, snap)
                          for vol, snap in zip(mock_volumes, mock_snapshots)]
        mock_create_vol.assert_has_calls(expected_calls,
                                         any_order=True)

        self.assert_error_propagates(
            [mock_create_vol, mock_create_cg],
            self.driver.create_consistencygroup_from_src,
            mock_context,
            mock_group,
            mock_volumes,
            cgsnapshot=mock_cgsnapshot,
            snapshots=mock_snapshots
        )

    def test_create_consistencygroup_from_src_no_snap(self):
        # Expect an error when no cgsnapshot or snapshots are provided
        self.assertRaises(exception.InvalidInput,
                          self.driver.create_consistencygroup_from_src,
                          mock.Mock(),  # context
                          mock.Mock(),  # group
                          [mock.Mock()])  # volumes

    @mock.patch(DRIVER_OBJ + ".delete_volume", autospec=True)
    def test_delete_consistencygroup(self, mock_delete_volume):
        mock_cgroup = mock.MagicMock()
        mock_cgroup.id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        mock_cgroup['status'] = "deleted"
        mock_context = mock.Mock()
        self.driver.db = mock.Mock()
        mock_volume = mock.MagicMock()
        expected_volumes = [mock_volume]
        self.driver.db.volume_get_all_by_group.return_value = expected_volumes

        model_update, volumes = \
            self.driver.delete_consistencygroup(mock_context, mock_cgroup)

        expected_name = pure._get_pgroup_name_from_id(mock_cgroup.id)
        self.array.destroy_pgroup.assert_called_with(expected_name)
        self.assertEqual(expected_volumes, volumes)
        self.assertEqual(mock_cgroup['status'], model_update['status'])
        mock_delete_volume.assert_called_with(self.driver, mock_volume)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=400,
                text="Protection group has been destroyed."
            )
        self.driver.delete_consistencygroup(mock_context, mock_cgroup)
        self.array.destroy_pgroup.assert_called_with(expected_name)
        mock_delete_volume.assert_called_with(self.driver, mock_volume)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=400,
                text="Protection group does not exist"
            )
        self.driver.delete_consistencygroup(mock_context, mock_cgroup)
        self.array.destroy_pgroup.assert_called_with(expected_name)
        mock_delete_volume.assert_called_with(self.driver, mock_volume)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=400,
                text="Some other error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.delete_consistencygroup,
                          mock_context,
                          mock_volume)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=500,
                text="Another different error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.delete_consistencygroup,
                          mock_context,
                          mock_volume)

        self.array.destroy_pgroup.side_effect = None
        self.assert_error_propagates(
            [self.array.destroy_pgroup],
            self.driver.delete_consistencygroup, mock_context, mock_cgroup)

    def _create_mock_cg(self):
        mock_group = mock.MagicMock()
        mock_group.id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        mock_group.status = "Available"
        mock_group.cg_name = "consisgroup-" + mock_group.id + "-cinder"
        return mock_group

    def test_update_consistencygroup(self):
        mock_group = self._create_mock_cg()
        add_vols = [
            {'name': 'vol1'},
            {'name': 'vol2'},
            {'name': 'vol3'},
        ]
        expected_addvollist = [vol['name'] + '-cinder' for vol in add_vols]
        remove_vols = [
            {'name': 'vol4'},
            {'name': 'vol5'}
        ]
        expected_remvollist = [vol['name'] + '-cinder' for vol in remove_vols]
        self.driver.update_consistencygroup(mock.Mock(), mock_group,
                                            add_vols, remove_vols)
        self.array.set_pgroup.assert_called_with(
            mock_group.cg_name,
            addvollist=expected_addvollist,
            remvollist=expected_remvollist
        )

    def test_update_consistencygroup_no_add_vols(self):
        mock_group = self._create_mock_cg()
        expected_addvollist = []
        remove_vols = [
            {'name': 'vol4'},
            {'name': 'vol5'}
        ]
        expected_remvollist = [vol['name'] + '-cinder' for vol in remove_vols]
        self.driver.update_consistencygroup(mock.Mock(), mock_group,
                                            None, remove_vols)
        self.array.set_pgroup.assert_called_with(
            mock_group.cg_name,
            addvollist=expected_addvollist,
            remvollist=expected_remvollist
        )

    def test_update_consistencygroup_no_remove_vols(self):
        mock_group = self._create_mock_cg()
        add_vols = [
            {'name': 'vol1'},
            {'name': 'vol2'},
            {'name': 'vol3'},
        ]
        expected_addvollist = [vol['name'] + '-cinder' for vol in add_vols]
        expected_remvollist = []
        self.driver.update_consistencygroup(mock.Mock(), mock_group,
                                            add_vols, None)
        self.array.set_pgroup.assert_called_with(
            mock_group.cg_name,
            addvollist=expected_addvollist,
            remvollist=expected_remvollist
        )

    def test_update_consistencygroup_no_vols(self):
        mock_group = self._create_mock_cg()
        self.driver.update_consistencygroup(mock.Mock(), mock_group,
                                            None, None)
        self.array.set_pgroup.assert_called_with(
            mock_group.cg_name,
            addvollist=[],
            remvollist=[]
        )

    def test_create_cgsnapshot(self):
        mock_cgsnap = mock.Mock()
        mock_cgsnap.id = "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        mock_cgsnap.consistencygroup_id = \
            "4a2f7e3a-312a-40c5-96a8-536b8a0fe075"
        mock_context = mock.Mock()
        self.driver.db = mock.Mock()
        mock_snap = mock.MagicMock()
        expected_snaps = [mock_snap]
        self.driver.db.snapshot_get_all_for_cgsnapshot.return_value = \
            expected_snaps

        model_update, snapshots = \
            self.driver.create_cgsnapshot(mock_context, mock_cgsnap)

        expected_pgroup_name = \
            pure._get_pgroup_name_from_id(mock_cgsnap.consistencygroup_id)
        expected_snap_suffix = pure._get_pgroup_snap_suffix(mock_cgsnap)
        self.array.create_pgroup_snapshot\
            .assert_called_with(expected_pgroup_name,
                                suffix=expected_snap_suffix)
        self.assertEqual({'status': 'available'}, model_update)
        self.assertEqual(expected_snaps, snapshots)
        self.assertEqual('available', mock_snap.status)

        self.assert_error_propagates(
            [self.array.create_pgroup_snapshot],
            self.driver.create_cgsnapshot, mock_context, mock_cgsnap)

    @mock.patch(DRIVER_PATH + "._get_pgroup_snap_name", autospec=True)
    def test_delete_cgsnapshot(self, mock_get_snap_name):
        snap_name = "consisgroup-4a2f7e3a-312a-40c5-96a8-536b8a0f" \
                    "e074-cinder.4a2f7e3a-312a-40c5-96a8-536b8a0fe075"
        mock_get_snap_name.return_value = snap_name
        mock_cgsnap = mock.Mock()
        mock_cgsnap.status = 'deleted'
        mock_context = mock.Mock()
        mock_snap = mock.MagicMock()
        expected_snaps = [mock_snap]
        self.driver.db = mock.Mock()
        self.driver.db.snapshot_get_all_for_cgsnapshot.return_value = \
            expected_snaps

        model_update, snapshots = \
            self.driver.delete_cgsnapshot(mock_context, mock_cgsnap)

        self.array.destroy_pgroup.assert_called_with(snap_name)
        self.assertEqual({'status': mock_cgsnap.status}, model_update)
        self.assertEqual(expected_snaps, snapshots)
        self.assertEqual('deleted', mock_snap.status)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=400,
                text="Protection group snapshot has been destroyed."
            )
        self.driver.delete_cgsnapshot(mock_context, mock_cgsnap)
        self.array.destroy_pgroup.assert_called_with(snap_name)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=400,
                text="Protection group snapshot does not exist"
            )
        self.driver.delete_cgsnapshot(mock_context, mock_cgsnap)
        self.array.destroy_pgroup.assert_called_with(snap_name)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=400,
                text="Some other error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.delete_cgsnapshot,
                          mock_context,
                          mock_cgsnap)

        self.array.destroy_pgroup.side_effect = \
            self.purestorage_module.PureHTTPError(
                code=500,
                text="Another different error"
            )
        self.assertRaises(self.purestorage_module.PureHTTPError,
                          self.driver.delete_cgsnapshot,
                          mock_context,
                          mock_cgsnap)

        self.array.destroy_pgroup.side_effect = None

        self.assert_error_propagates(
            [self.array.destroy_pgroup],
            self.driver.delete_cgsnapshot, mock_context, mock_cgsnap)

    def test_manage_existing(self):
        ref_name = 'vol1'
        volume_ref = {'name': ref_name}
        self.array.list_volume_private_connections.return_value = []
        vol_name = VOLUME['name'] + '-cinder'
        self.driver.manage_existing(VOLUME, volume_ref)
        self.array.list_volume_private_connections.assert_called_with(ref_name)
        self.array.rename_volume.assert_called_with(ref_name, vol_name)

    def test_manage_existing_error_propagates(self):
        self.array.list_volume_private_connections.return_value = []
        self.assert_error_propagates(
            [self.array.list_volume_private_connections,
             self.array.rename_volume],
            self.driver.manage_existing,
            VOLUME, {'name': 'vol1'}
        )

    def test_manage_existing_bad_ref(self):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          VOLUME, {'bad_key': 'bad_value'})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          VOLUME, {'name': ''})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          VOLUME, {'name': None})

        self.array.get_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                text="Volume does not exist.",
                code=400
            )
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          VOLUME, {'name': 'non-existing-volume'})

    def test_manage_existing_with_connected_hosts(self):
        ref_name = 'vol1'
        self.array.list_volume_private_connections.return_value = \
            ["host1", "host2"]

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          VOLUME, {'name': ref_name})

        self.array.list_volume_private_connections.assert_called_with(ref_name)
        self.assertFalse(self.array.rename_volume.called)

    def test_manage_existing_get_size(self):
        ref_name = 'vol1'
        volume_ref = {'name': ref_name}
        expected_size = 5
        self.array.get_volume.return_value = {"size": 5368709120}

        size = self.driver.manage_existing_get_size(VOLUME, volume_ref)

        self.assertEqual(expected_size, size)
        self.array.get_volume.assert_called_with(ref_name)

    def test_manage_existing_get_size_error_propagates(self):
        self.array.get_volume.return_value = mock.MagicMock()
        self.assert_error_propagates([self.array.get_volume],
                                     self.driver.manage_existing_get_size,
                                     VOLUME, {'name': 'vol1'})

    def test_manage_existing_get_size_bad_ref(self):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          VOLUME, {'bad_key': 'bad_value'})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          VOLUME, {'name': ''})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          VOLUME, {'name': None})

    def test_unmanage(self):
        vol_name = VOLUME['name'] + "-cinder"
        unmanaged_vol_name = vol_name + "-unmanaged"

        self.driver.unmanage(VOLUME)

        self.array.rename_volume.assert_called_with(vol_name,
                                                    unmanaged_vol_name)

    def test_unmanage_error_propagates(self):
        self.assert_error_propagates([self.array.rename_volume],
                                     self.driver.unmanage,
                                     VOLUME)

    def test_unmanage_with_deleted_volume(self):
        vol_name = VOLUME['name'] + "-cinder"
        unmanaged_vol_name = vol_name + "-unmanaged"
        self.array.rename_volume.side_effect = \
            self.purestorage_module.PureHTTPError(
                text="Volume does not exist.",
                code=400
            )

        self.driver.unmanage(VOLUME)

        self.array.rename_volume.assert_called_with(vol_name,
                                                    unmanaged_vol_name)
