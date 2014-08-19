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

import json
import urllib2

import mock

from cinder import exception
from cinder.openstack.common import processutils
from cinder.openstack.common import units
from cinder import test
from cinder.volume.drivers import pure

DRIVER_PATH = "cinder.volume.drivers.pure"
DRIVER_OBJ = DRIVER_PATH + ".PureISCSIDriver"
ARRAY_OBJ = DRIVER_PATH + ".FlashArray"

TARGET = "pure-target"
API_TOKEN = "12345678-abcd-1234-abcd-1234567890ab"
VOLUME_BACKEND_NAME = "Pure_iSCSI"
PORT_NAMES = ["ct0.eth2", "ct0.eth3", "ct1.eth2", "ct1.eth3"]
ISCSI_IPS = ["10.0.0." + str(i + 1) for i in range(len(PORT_NAMES))]
HOST_NAME = "pure-host"
REST_VERSION = "1.2"
VOLUME_ID = "abcdabcd-1234-abcd-1234-abcdeffedcba"
VOLUME = {"name": "volume-" + VOLUME_ID,
          "id": VOLUME_ID,
          "display_name": "fake_volume",
          "size": 2,
          "host": "irrelevant",
          "volume_type": None,
          "volume_type_id": None,
          }
SRC_VOL_ID = "dc7a294d-5964-4379-a15f-ce5554734efc"
SRC_VOL = {"name": "volume-" + SRC_VOL_ID,
           "id": SRC_VOL_ID,
           "display_name": 'fake_src',
           "size": 2,
           "host": "irrelevant",
           "volume_type": None,
           "volume_type_id": None,
           }
SNAPSHOT_ID = "04fe2f9a-d0c4-4564-a30d-693cc3657b47"
SNAPSHOT = {"name": "snapshot-" + SNAPSHOT_ID,
            "id": SNAPSHOT_ID,
            "volume_id": SRC_VOL_ID,
            "volume_name": "volume-" + SRC_VOL_ID,
            "volume_size": 2,
            "display_name": "fake_snapshot",
            }
INITIATOR_IQN = "iqn.1993-08.org.debian:01:222"
CONNECTOR = {"initiator": INITIATOR_IQN}
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
TOTAL_SPACE = 50.0
FREE_SPACE = 32.1
SPACE_INFO = {"capacity": TOTAL_SPACE * units.Gi,
              "total": (TOTAL_SPACE - FREE_SPACE) * units.Gi,
              }


class PureISCSIDriverTestCase(test.TestCase):

    def setUp(self):
        super(PureISCSIDriverTestCase, self).setUp()
        self.config = mock.Mock()
        self.config.san_ip = TARGET
        self.config.pure_api_token = API_TOKEN
        self.config.volume_backend_name = VOLUME_BACKEND_NAME
        self.driver = pure.PureISCSIDriver(configuration=self.config)
        self.array = mock.create_autospec(pure.FlashArray)
        self.driver._array = self.array

    @mock.patch(ARRAY_OBJ, autospec=True)
    @mock.patch(DRIVER_OBJ + "._choose_target_iscsi_port")
    def test_do_setup(self, mock_choose_target_iscsi_port, mock_array):
        mock_choose_target_iscsi_port.return_value = ISCSI_PORTS[0]
        mock_array.return_value = self.array
        self.driver.do_setup(None)
        mock_array.assert_called_with(TARGET, API_TOKEN)
        self.assertEqual(self.array, self.driver._array)
        mock_choose_target_iscsi_port.assert_called_with()
        self.assertEqual(ISCSI_PORTS[0], self.driver._iscsi_port)
        self.assert_error_propagates(
            [mock_array, mock_choose_target_iscsi_port],
            self.driver.do_setup, None)

    def assert_error_propagates(self, mocks, func, *args, **kwargs):
        """Assert that errors from mocks propogate to func.

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

    def test_create_volume(self):
        self.driver.create_volume(VOLUME)
        self.array.create_volume.assert_called_with(
            VOLUME["name"] + "-cinder", 2 * units.Gi)
        self.assert_error_propagates([self.array.create_volume],
                                     self.driver.create_volume, VOLUME)

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

    def test_delete_volume(self):
        vol_name = VOLUME["name"] + "-cinder"
        self.driver.delete_volume(VOLUME)
        expected = [mock.call.destroy_volume(vol_name)]
        self.array.assert_has_calls(expected)
        self.array.destroy_volume.side_effect = exception.PureAPIException(
            code=400, reason="reason")
        self.driver.delete_snapshot(SNAPSHOT)
        self.array.destroy_volume.side_effect = None
        self.assert_error_propagates([self.array.destroy_volume],
                                     self.driver.delete_volume, VOLUME)

    def test_create_snapshot(self):
        vol_name = SRC_VOL["name"] + "-cinder"
        self.driver.create_snapshot(SNAPSHOT)
        self.array.create_snapshot.assert_called_with(vol_name,
                                                      SNAPSHOT["name"])
        self.assert_error_propagates([self.array.create_snapshot],
                                     self.driver.create_snapshot, SNAPSHOT)

    def test_delete_snapshot(self):
        snap_name = SNAPSHOT["volume_name"] + "-cinder." + SNAPSHOT["name"]
        self.driver.delete_snapshot(SNAPSHOT)
        expected = [mock.call.destroy_volume(snap_name)]
        self.array.assert_has_calls(expected)
        self.array.destroy_volume.side_effect = exception.PureAPIException(
            code=400, reason="reason")
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
        result = {"driver_volume_type": "iscsi",
                  "data": {"target_iqn": TARGET_IQN,
                           "target_portal": ISCSI_IPS[0] + ":" + TARGET_PORT,
                           "target_lun": 1,
                           "target_discovered": True,
                           "access_mode": "rw",
                           },
                  }
        real_result = self.driver.initialize_connection(VOLUME, CONNECTOR)
        self.assertDictMatch(result, real_result)
        mock_get_iscsi_port.assert_called_with()
        mock_connection.assert_called_with(VOLUME, CONNECTOR)
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
        mock_iscsiadm.reset_mock()
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

    @mock.patch(DRIVER_OBJ + "._get_host_name", autospec=True)
    def test_connect(self, mock_host):
        vol_name = VOLUME["name"] + "-cinder"
        result = {"vol": vol_name, "lun": 1}
        mock_host.return_value = HOST_NAME
        self.array.connect_host.return_value = {"vol": vol_name, "lun": 1}
        real_result = self.driver._connect(VOLUME, CONNECTOR)
        self.assertEqual(result, real_result)
        mock_host.assert_called_with(self.driver, CONNECTOR)
        self.array.connect_host.assert_called_with(HOST_NAME, vol_name)
        self.assert_error_propagates([mock_host, self.array.connect_host],
                                     self.driver._connect,
                                     VOLUME, CONNECTOR)

    def test_get_host_name(self):
        good_host = {"name": HOST_NAME,
                     "iqn": ["another-wrong-iqn", INITIATOR_IQN]}
        bad_host = {"name": "bad-host", "iqn": ["wrong-iqn"]}
        self.array.list_hosts.return_value = [bad_host]
        self.assertRaises(exception.PureDriverException,
                          self.driver._get_host_name, CONNECTOR)
        self.array.list_hosts.return_value.append(good_host)
        real_result = self.driver._get_host_name(CONNECTOR)
        self.assertEqual(real_result, good_host["name"])
        self.assert_error_propagates([self.array.list_hosts],
                                     self.driver._get_host_name, CONNECTOR)

    @mock.patch(DRIVER_OBJ + "._get_host_name", autospec=True)
    def test_terminate_connection(self, mock_host):
        vol_name = VOLUME["name"] + "-cinder"
        mock_host.return_value = HOST_NAME
        self.driver.terminate_connection(VOLUME, CONNECTOR)
        self.array.disconnect_host.assert_called_with(HOST_NAME, vol_name)
        self.array.disconnect_host.side_effect = exception.PureAPIException(
            code=400, reason="reason")
        self.driver.terminate_connection(VOLUME, CONNECTOR)
        self.array.disconnect_host.assert_called_with(HOST_NAME, vol_name)
        self.array.disconnect_host.side_effect = None
        self.array.disconnect_host.reset_mock()
        mock_host.side_effect = exception.PureDriverException(reason="reason")
        self.assertFalse(self.array.disconnect_host.called)
        mock_host.side_effect = None
        self.assert_error_propagates(
            [self.array.disconnect_host],
            self.driver.terminate_connection, VOLUME, CONNECTOR)

    def test_get_volume_stats(self):
        self.assertEqual(self.driver.get_volume_stats(), {})
        self.array.get_array.return_value = SPACE_INFO
        result = {"volume_backend_name": VOLUME_BACKEND_NAME,
                  "vendor_name": "Pure Storage",
                  "driver_version": self.driver.VERSION,
                  "storage_protocol": "iSCSI",
                  "total_capacity_gb": TOTAL_SPACE,
                  "free_capacity_gb": FREE_SPACE,
                  "reserved_percentage": 0,
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


class FlashArrayBaseTestCase(test.TestCase):

    def setUp(self):
        super(FlashArrayBaseTestCase, self).setUp()
        array = FakeFlashArray()
        array._target = TARGET
        array._rest_version = REST_VERSION
        array._root_url = "https://{0}/api/{1}/".format(TARGET, REST_VERSION)
        array._api_token = API_TOKEN
        self.array = array

    def assert_error_propagates(self, mocks, func, *args, **kwargs):
        """Assert that errors from mocks propogate to func.

        Fail if exceptions raised by mocks are not seen when calling
        func(*args, **kwargs). Ensure that we are really seeing exceptions
        from the mocks by failing if just running func(*args, **kargs) raises
        an exception itself.
        """
        func(*args, **kwargs)
        for mock_func in mocks:
            mock_func.side_effect = exception.PureAPIException(reason="reason")
            self.assertRaises(exception.PureAPIException,
                              func, *args, **kwargs)
            mock_func.side_effect = None


class FlashArrayInitTestCase(FlashArrayBaseTestCase):

    @mock.patch(ARRAY_OBJ + "._start_session", autospec=True)
    @mock.patch(ARRAY_OBJ + "._choose_rest_version", autospec=True)
    @mock.patch(DRIVER_PATH + ".urllib2.build_opener", autospec=True)
    def test_init(self, mock_build_opener, mock_choose, mock_start):
        opener = mock.Mock()
        mock_build_opener.return_value = opener
        mock_choose.return_value = REST_VERSION
        array = pure.FlashArray(TARGET, API_TOKEN)
        mock_choose.assert_called_with(array)
        mock_start.assert_called_with(array)
        self.assertEqual(array._target, TARGET)
        self.assertEqual(array._api_token, API_TOKEN)
        self.assertEqual(array._rest_version, REST_VERSION)
        self.assertIs(array._opener, opener)
        self.assert_error_propagates([mock_choose, mock_start],
                                     pure.FlashArray, TARGET, API_TOKEN)


class FlashArrayHttpRequestTestCase(FlashArrayBaseTestCase):

    def setUp(self):
        super(FlashArrayHttpRequestTestCase, self).setUp()
        self.method = "POST"
        self.path = "path"
        self.path_template = "https://{0}/api/{1}/{2}"
        self.full_path = self.path_template.format(TARGET, REST_VERSION,
                                                   self.path)
        self.headers = {"Content-Type": "application/json"}
        self.data = {"list": [1, 2, 3]}
        self.data_json = json.dumps(self.data)
        self.response_json = '[{"hello": "world"}, "!"]'
        self.result = json.loads(self.response_json)
        self.error_msg = "error-msg"
        self.response = mock.Mock(spec=["read", "readline", "info"])
        self.response.read.return_value = self.response_json
        self.response.read.side_effect = None
        self.response.info.return_value = self.headers
        self.response.info.side_effect = None

    def make_call(self, method=None, path=None, data=None):
        method = method if method else self.method
        path = path if path else self.full_path
        data = data if data else self.data_json
        return mock.call(FakeRequest(method, path, headers=self.headers), data)

    def test_http_request_success(self):
        self.array._opener.open.return_value = self.response
        real_result = self.array._http_request(
            self.method, self.path, self.data)
        self.assertEqual(self.result, real_result)
        self.assertEqual(self.array._opener.open.call_args_list,
                         [self.make_call()])

    def test_http_request_401_error(self):
        self.array._opener.open.return_value = self.response
        error = urllib2.HTTPError(self.full_path, 401, self.error_msg,
                                  None, self.response)
        self.array._opener.open.side_effect = iter([error] +
                                                   [self.response] * 2)
        real_result = self.array._http_request(
            self.method, self.path, self.data)
        self.assertEqual(self.result, real_result)
        expected = [self.make_call(),
                    self.make_call(
                        "POST", self.path_template.format(
                            TARGET, REST_VERSION, "auth/session"),
                        json.dumps({"api_token": API_TOKEN})),
                    self.make_call()]
        self.assertEqual(self.array._opener.open.call_args_list, expected)
        self.array._opener.open.reset_mock()
        self.array._opener.open.side_effect = iter([error, error])
        self.assertRaises(exception.PureAPIException,
                          self.array._http_request,
                          self.method, self.path, self.data)
        self.array._opener.open.reset_mock()
        self.array._opener.open.side_effect = iter([error, self.response,
                                                    error])
        self.assertRaises(exception.PureAPIException,
                          self.array._http_request,
                          self.method, self.path, self.data)

    @mock.patch(ARRAY_OBJ + "._choose_rest_version", autospec=True)
    def test_http_request_450_error(self, mock_choose):
        mock_choose.return_value = "1.1"
        error = urllib2.HTTPError(self.full_path, 450, self.error_msg,
                                  None, self.response)
        self.array._opener.open.side_effect = iter([error, self.response])
        real_result = self.array._http_request(
            self.method, self.path, self.data)
        self.assertEqual(self.result, real_result)
        expected = [self.make_call(),
                    self.make_call(path=self.path_template.format(
                        TARGET, "1.1", self.path))]
        self.assertEqual(self.array._opener.open.call_args_list, expected)
        mock_choose.assert_called_with(self.array)
        self.array._opener.open.side_effect = error
        self.assertRaises(exception.PureAPIException,
                          self.array._http_request,
                          self.method, self.path, self.data)
        self.array._opener.open.reset_mock()
        mock_choose.reset_mock()
        self.array._opener.open.side_effect = error
        mock_choose.side_effect = exception.PureAPIException(reason="reason")
        self.assertRaises(exception.PureAPIException,
                          self.array._http_request,
                          self.method, self.path, self.data)

    def test_http_request_http_error(self):
        self.array._opener.open.return_value = self.response
        error = urllib2.HTTPError(self.full_path, 500, self.error_msg,
                                  None, self.response)
        self.array._opener.open.side_effect = error
        self.assertRaises(exception.PureAPIException,
                          self.array._http_request,
                          self.method, self.path, self.data)
        self.assertEqual(self.array._opener.open.call_args_list,
                         [self.make_call()])

    def test_http_request_url_error(self):
        self.array._opener.open.return_value = self.response
        error = urllib2.URLError(self.error_msg)
        self.array._opener.open.side_effect = error
        # try/except used to ensure is instance of type but not subtype
        try:
            self.array._http_request(self.method, self.path, self.data)
        except exception.PureDriverException as err:
            self.assertFalse(isinstance(err, exception.PureAPIException))
        else:
            self.assertTrue(False, "expected failure, but passed")
        self.assertEqual(self.array._opener.open.call_args_list,
                         [self.make_call()])

    def test_http_request_other_error(self):
        self.array._opener.open.return_value = self.response
        self.assert_error_propagates([self.array._opener.open],
                                     self.array._http_request,
                                     self.method, self.path, self.data)

    # Test with _http_requests rather than rest calls to ensure
    # root_url change happens properly
    def test_choose_rest_version(self):
        response_string = '{"version": ["0.1", "1.3", "1.1", "1.0"]}'
        self.response.read.return_value = response_string
        self.array._opener.open.return_value = self.response
        result = self.array._choose_rest_version()
        self.assertEqual(result, "1.1")
        self.array._opener.open.assert_called_with(FakeRequest(
            "GET", "https://{0}/api/api_version".format(TARGET),
            headers=self.headers), "null")
        self.array._opener.open.reset_mock()
        self.response.read.return_value = '{"version": ["0.1", "1.3"]}'
        self.assertRaises(exception.PureDriverException,
                          self.array._choose_rest_version)


@mock.patch(ARRAY_OBJ + "._http_request", autospec=True)
class FlashArrayRESTTestCase(FlashArrayBaseTestCase):

    def setUp(self):
        super(FlashArrayRESTTestCase, self).setUp()
        self.kwargs = {"kwarg1": "val1", "kwarg2": "val2"}
        self.result = "expected_return"

    def test_choose_rest_version(self, mock_req):
        mock_req.return_value = {"version": ["0.1", "1.3", "1.1", "1.0"]}
        self.assert_error_propagates([mock_req],
                                     self.array._choose_rest_version)

    def test_start_session(self, mock_req):
        self.array._start_session()
        data = {"api_token": API_TOKEN}
        mock_req.assert_called_with(self.array, "POST", "auth/session",
                                    data, reestablish_session=False)
        self.assert_error_propagates([mock_req], self.array._start_session)

    def test_get_array(self, mock_req):
        mock_req.return_value = self.result
        result = self.array.get_array(**self.kwargs)
        self.assertEqual(result, self.result)
        mock_req.assert_called_with(self.array, "GET", "array", self.kwargs)
        self.assert_error_propagates([mock_req], self.array.get_array,
                                     **self.kwargs)

    def test_create_volume(self, mock_req):
        mock_req.return_value = self.result
        result = self.array.create_volume("vol-name", "5G")
        self.assertEqual(result, self.result)
        mock_req.assert_called_with(self.array, "POST", "volume/vol-name",
                                    {"size": "5G"})
        self.assert_error_propagates([mock_req], self.array.create_volume,
                                     "vol-name", "5G")

    def test_copy_volume(self, mock_req):
        mock_req.return_value = self.result
        result = self.array.copy_volume("src-name", "dest-name")
        self.assertEqual(result, self.result)
        mock_req.assert_called_with(self.array, "POST", "volume/dest-name",
                                    {"source": "src-name"})
        self.assert_error_propagates([mock_req], self.array.copy_volume,
                                     "dest-name", "src-name")

    def test_create_snapshot(self, mock_req):
        mock_req.return_value = [self.result, "second-arg"]
        result = self.array.create_snapshot("vol-name", "suff")
        self.assertEqual(result, self.result)
        mock_req.assert_called_with(
            self.array, "POST", "volume",
            {"source": ["vol-name"], "suffix": "suff", "snap": True})
        self.assert_error_propagates([mock_req], self.array.create_snapshot,
                                     "vol-name", "suff")

    def test_destroy_volume(self, mock_req):
        mock_req.return_value = self.result
        result = self.array.destroy_volume("vol-name")
        self.assertEqual(result, self.result)
        mock_req.assert_called_with(self.array, "DELETE", "volume/vol-name")
        self.assert_error_propagates([mock_req], self.array.destroy_volume,
                                     "vol-name")

    def test_extend_volume(self, mock_req):
        mock_req.return_value = self.result
        result = self.array.extend_volume("vol-name", "5G")
        self.assertEqual(result, self.result)
        mock_req.assert_called_with(self.array, "PUT", "volume/vol-name",
                                    {"size": "5G", "truncate": False})
        self.assert_error_propagates([mock_req], self.array.extend_volume,
                                     "vol-name", "5G")

    def test_list_hosts(self, mock_req):
        mock_req.return_value = self.result
        result = self.array.list_hosts(**self.kwargs)
        self.assertEqual(result, self.result)
        mock_req.assert_called_with(self.array, "GET", "host", self.kwargs)
        self.assert_error_propagates([mock_req], self.array.list_hosts,
                                     **self.kwargs)

    def test_connect_host(self, mock_req):
        mock_req.return_value = self.result
        result = self.array.connect_host("host-name", "vol-name",
                                         **self.kwargs)
        self.assertEqual(result, self.result)
        mock_req.assert_called_with(self.array, "POST",
                                    "host/host-name/volume/vol-name",
                                    self.kwargs)
        self.assert_error_propagates([mock_req], self.array.connect_host,
                                     "host-name", "vol-name", **self.kwargs)

    def test_disconnect_host(self, mock_req):
        mock_req.return_value = self.result
        result = self.array.disconnect_host("host-name", "vol-name")
        self.assertEqual(result, self.result)
        mock_req.assert_called_with(self.array, "DELETE",
                                    "host/host-name/volume/vol-name")
        self.assert_error_propagates([mock_req], self.array.disconnect_host,
                                     "host-name", "vol-name")

    def test_list_ports(self, mock_req):
        mock_req.return_value = self.result
        result = self.array.list_ports(**self.kwargs)
        self.assertEqual(result, self.result)
        mock_req.assert_called_with(self.array, "GET", "port", self.kwargs)
        self.assert_error_propagates([mock_req], self.array.list_ports,
                                     **self.kwargs)


class FakeFlashArray(pure.FlashArray):

    def __init__(self):
        self._opener = mock.Mock()


class FakeRequest(urllib2.Request):

    def __init__(self, method, *args, **kwargs):
        urllib2.Request.__init__(self, *args, **kwargs)
        self.get_method = lambda: method

    def __eq__(self, other):
        if not isinstance(other, urllib2.Request):
            return False
        return (self.get_method() == other.get_method() and
                self.get_full_url() == other.get_full_url() and
                self.header_items() == other.header_items())

    def __ne__(self, other):
        return not (self == other)
