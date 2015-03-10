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
Tests for Violin Memory 6000 Series All-Flash Array Common Driver
"""

import mock

from cinder import exception
from cinder import test
from cinder.tests import fake_vmem_client as vmemclient
from cinder.volume import configuration as conf
from cinder.volume.drivers.violin import v6000_common

VOLUME_ID = "abcdabcd-1234-abcd-1234-abcdeffedcba"
VOLUME = {
    "name": "volume-" + VOLUME_ID,
    "id": VOLUME_ID,
    "display_name": "fake_volume",
    "size": 2,
    "host": "irrelevant",
    "volume_type": None,
    "volume_type_id": None,
}
SNAPSHOT_ID = "abcdabcd-1234-abcd-1234-abcdeffedcbb"
SNAPSHOT = {
    "name": "snapshot-" + SNAPSHOT_ID,
    "id": SNAPSHOT_ID,
    "volume_id": VOLUME_ID,
    "volume_name": "volume-" + VOLUME_ID,
    "volume_size": 2,
    "display_name": "fake_snapshot",
    "volume": VOLUME,
}
SRC_VOL_ID = "abcdabcd-1234-abcd-1234-abcdeffedcbc"
SRC_VOL = {
    "name": "volume-" + SRC_VOL_ID,
    "id": SRC_VOL_ID,
    "display_name": "fake_src_vol",
    "size": 2,
    "host": "irrelevant",
    "volume_type": None,
    "volume_type_id": None,
}
INITIATOR_IQN = "iqn.1111-22.org.debian:11:222"
CONNECTOR = {
    "initiator": INITIATOR_IQN,
    "host": "irrelevant"
}


class V6000CommonTestCase(test.TestCase):
    """Test cases for VMEM V6000 driver common class."""
    def setUp(self):
        super(V6000CommonTestCase, self).setUp()
        self.conf = self.setup_configuration()
        self.driver = v6000_common.V6000Common(self.conf)
        self.driver.container = 'myContainer'
        self.driver.device_id = 'ata-VIOLIN_MEMORY_ARRAY_23109R00000022'
        self.stats = {}

    def tearDown(self):
        super(V6000CommonTestCase, self).tearDown()

    def setup_configuration(self):
        config = mock.Mock(spec=conf.Configuration)
        config.volume_backend_name = 'v6000_common'
        config.san_ip = '1.1.1.1'
        config.san_login = 'admin'
        config.san_password = ''
        config.san_thin_provision = False
        config.san_is_local = False
        config.gateway_mga = '2.2.2.2'
        config.gateway_mgb = '3.3.3.3'
        config.use_igroups = False
        config.request_timeout = 300
        config.container = 'myContainer'
        return config

    @mock.patch('vmemclient.open')
    def setup_mock_client(self, _m_client, m_conf=None):
        """Create a fake backend communication factory.

        The vmemclient creates a VShare connection object (for V6000
        devices) and returns it for use on a call to vmemclient.open().
        """
        # configure the vshare object mock with defaults
        _m_vshare = mock.Mock(name='VShare',
                              version='1.1.1',
                              spec=vmemclient.mock_client_conf)

        # if m_conf, clobber the defaults with it
        if m_conf:
            _m_vshare.configure_mock(**m_conf)

        # set calls to vmemclient.open() to return this mocked vshare object
        _m_client.return_value = _m_vshare

        return _m_client

    def setup_mock_vshare(self, m_conf=None):
        """Create a fake VShare communication object."""
        _m_vshare = mock.Mock(name='VShare',
                              version='1.1.1',
                              spec=vmemclient.mock_client_conf)

        if m_conf:
            _m_vshare.configure_mock(**m_conf)

        return _m_vshare

    def test_check_for_setup_error(self):
        """No setup errors are found."""
        bn1 = ("/vshare/state/local/container/%s/threshold/usedspace"
               "/threshold_hard_val" % self.driver.container)
        bn2 = ("/vshare/state/local/container/%s/threshold/provision"
               "/threshold_hard_val" % self.driver.container)
        bn_thresholds = {bn1: 0, bn2: 100}

        conf = {
            'basic.get_node_values.return_value': bn_thresholds,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._is_supported_vmos_version = mock.Mock(return_value=True)

        result = self.driver.check_for_setup_error()

        self.driver._is_supported_vmos_version.assert_called_with(
            self.driver.vip.version)
        self.driver.vip.basic.get_node_values.assert_called_with(
            [bn1, bn2])
        self.assertEqual(None, result)

    def test_check_for_setup_error_no_container(self):
        """No container was configured."""
        self.driver.vip = self.setup_mock_vshare()
        self.driver.container = ''
        self.assertRaises(exception.ViolinInvalidBackendConfig,
                          self.driver.check_for_setup_error)

    def test_check_for_setup_error_invalid_usedspace_threshold(self):
        """The array's usedspace threshold was altered (not supported)."""
        bn1 = ("/vshare/state/local/container/%s/threshold/usedspace"
               "/threshold_hard_val" % self.driver.container)
        bn2 = ("/vshare/state/local/container/%s/threshold/provision"
               "/threshold_hard_val" % self.driver.container)
        bn_thresholds = {bn1: 99, bn2: 100}

        conf = {
            'basic.get_node_values.return_value': bn_thresholds,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._is_supported_vmos_version = mock.Mock(return_value=True)

        self.assertRaises(exception.ViolinInvalidBackendConfig,
                          self.driver.check_for_setup_error)

    def test_check_for_setup_error_invalid_provisionedspace_threshold(self):
        """The array's provisioned threshold was altered (not supported)."""
        bn1 = ("/vshare/state/local/container/%s/threshold/usedspace"
               "/threshold_hard_val" % self.driver.container)
        bn2 = ("/vshare/state/local/container/%s/threshold/provision"
               "/threshold_hard_val" % self.driver.container)
        bn_thresholds = {bn1: 0, bn2: 99}

        conf = {
            'basic.get_node_values.return_value': bn_thresholds,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._is_supported_vmos_version = mock.Mock(return_value=True)

        self.assertRaises(exception.ViolinInvalidBackendConfig,
                          self.driver.check_for_setup_error)

    def test_create_lun(self):
        """Lun is successfully created."""
        response = {'code': 0, 'message': 'LUN create: success!'}

        conf = {
            'lun.create_lun.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        result = self.driver._create_lun(VOLUME)

        self.driver._send_cmd.assert_called_with(
            self.driver.vip.lun.create_lun, 'LUN create: success!',
            self.driver.container, VOLUME['id'], VOLUME['size'], 1, "0",
            "0", "w", 1, 512, False, False, None)
        self.assertTrue(result is None)

    def test_create_lun_lun_already_exists(self):
        """Array returns error that the lun already exists."""
        response = {'code': 14005,
                    'message': 'LUN with name ... already exists'}

        conf = {
            'lun.create_lun.return_value': response,
        }
        self.driver.vip = self.setup_mock_client(m_conf=conf)
        self.driver._send_cmd = mock.Mock(
            side_effect=exception.ViolinBackendErrExists(
                response['message']))

        self.assertTrue(self.driver._create_lun(VOLUME) is None)

    def test_create_lun_create_fails_with_exception(self):
        """Array returns a out of space error."""
        response = {'code': 512, 'message': 'Not enough space available'}
        failure = exception.ViolinBackendErr

        conf = {
            'lun.create_lun.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._send_cmd = mock.Mock(
            side_effect=failure(response['message']))

        self.assertRaises(failure, self.driver._create_lun, VOLUME)

    def test_delete_lun(self):
        """Lun is deleted successfully."""
        response = {'code': 0, 'message': 'lun deletion started'}
        success_msgs = ['lun deletion started', '']

        conf = {
            'lun.delete_lun.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        result = self.driver._delete_lun(VOLUME)

        self.driver._send_cmd.assert_called_with(
            self.driver.vip.lun.bulk_delete_luns,
            success_msgs, self.driver.container, VOLUME['id'])

        self.assertTrue(result is None)

    def test_delete_lun_empty_response_message(self):
        """Array bug where delete action returns no message."""
        response = {'code': 0, 'message': ''}

        conf = {
            'lun.delete_lun.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        self.assertTrue(self.driver._delete_lun(VOLUME) is None)

    def test_delete_lun_lun_already_deleted(self):
        """Array fails to delete a lun that doesn't exist."""
        response = {'code': 14005, 'message': 'LUN ... does not exist.'}

        conf = {
            'lun.delete_lun.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._send_cmd = mock.Mock(
            side_effect=exception.ViolinBackendErrNotFound(
                response['message']))

        self.assertTrue(self.driver._delete_lun(VOLUME) is None)

    def test_delete_lun_delete_fails_with_exception(self):
        """Array returns a generic error."""
        response = {'code': 14000, 'message': 'Generic error'}
        failure = exception.ViolinBackendErr
        conf = {
            'lun.delete_lun.return_value': response
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._send_cmd = mock.Mock(
            side_effect=failure(response['message']))

        self.assertRaises(failure, self.driver._delete_lun, VOLUME)

    def test_extend_lun(self):
        """Volume extend completes successfully."""
        new_volume_size = 10
        response = {'code': 0, 'message': 'Success '}

        conf = {
            'lun.resize_lun.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        result = self.driver._extend_lun(VOLUME, new_volume_size)
        self.driver._send_cmd.assert_called_with(
            self.driver.vip.lun.resize_lun,
            'Success', self.driver.container,
            VOLUME['id'], new_volume_size)
        self.assertTrue(result is None)

    def test_extend_lun_new_size_is_too_small(self):
        """Volume extend fails when new size would shrink the volume."""
        new_volume_size = 0
        response = {'code': 14036, 'message': 'Failure'}

        conf = {
            'lun.resize_lun.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._send_cmd = mock.Mock(
            side_effect=exception.ViolinBackendErr(message='fail'))

        self.assertRaises(exception.ViolinBackendErr,
                          self.driver._extend_lun, VOLUME, new_volume_size)

    def test_create_lun_snapshot(self):
        """Snapshot creation completes successfully."""
        response = {'code': 0, 'message': 'success'}
        success_msg = 'Snapshot create: success!'

        conf = {
            'snapshot.create_lun_snapshot.return_value': response
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        result = self.driver._create_lun_snapshot(SNAPSHOT)

        self.driver._send_cmd.assert_called_with(
            self.driver.vip.snapshot.create_lun_snapshot, success_msg,
            self.driver.container, SNAPSHOT['volume_id'], SNAPSHOT['id'])
        self.assertTrue(result is None)

    def test_delete_lun_snapshot(self):
        """Snapshot deletion completes successfully."""
        response = {'code': 0, 'message': 'success'}
        success_msg = 'Snapshot delete: success!'

        conf = {
            'snapshot.delete_lun_snapshot.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        result = self.driver._delete_lun_snapshot(SNAPSHOT)

        self.driver._send_cmd.assert_called_with(
            self.driver.vip.snapshot.delete_lun_snapshot, success_msg,
            self.driver.container, SNAPSHOT['volume_id'], SNAPSHOT['id'])
        self.assertTrue(result is None)

    def test_get_lun_id(self):
        bn = "/vshare/config/export/container/%s/lun/%s/target/**" \
            % (self.conf.container, VOLUME['id'])
        response = {("/vshare/config/export/container/%s/lun"
                     "/%s/target/hba-a1/initiator/openstack/lun_id"
                     % (self.conf.container, VOLUME['id'])): 1}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)

        result = self.driver._get_lun_id(VOLUME['id'])

        self.driver.vip.basic.get_node_values.assert_called_with(bn)
        self.assertEqual(1, result)

    def test_get_lun_id_with_no_lun_config(self):
        response = {}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)

        self.assertRaises(exception.ViolinBackendErrNotFound,
                          self.driver._get_lun_id, VOLUME['id'])

    def test_get_snapshot_id(self):
        bn = ("/vshare/config/export/snapshot/container/%s/lun/%s/snap/%s"
              "/target/**") % (self.conf.container, VOLUME['id'],
                               SNAPSHOT['id'])
        response = {("/vshare/config/export/snapshot/container/%s/lun"
                     "/%s/snap/%s/target/hba-a1/initiator/openstack/lun_id"
                     % (self.conf.container, VOLUME['id'],
                        SNAPSHOT['id'])): 1}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)

        result = self.driver._get_snapshot_id(VOLUME['id'], SNAPSHOT['id'])

        self.driver.vip.basic.get_node_values.assert_called_with(bn)
        self.assertEqual(1, result)

    def test_get_snapshot_id_with_no_lun_config(self):
        response = {}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)

        self.assertRaises(exception.ViolinBackendErrNotFound,
                          self.driver._get_snapshot_id,
                          SNAPSHOT['volume_id'], SNAPSHOT['id'])

    def test_send_cmd(self):
        """Command callback completes successfully."""
        success_msg = 'success'
        request_args = ['arg1', 'arg2', 'arg3']
        response = {'code': 0, 'message': 'success'}

        request_func = mock.Mock(return_value=response)
        self.driver._fatal_error_code = mock.Mock(return_value=None)

        result = self.driver._send_cmd(request_func, success_msg, request_args)

        self.driver._fatal_error_code.assert_called_with(response)
        self.assertEqual(response, result)

    def test_send_cmd_request_timed_out(self):
        """The callback retry timeout hits immediately."""
        success_msg = 'success'
        request_args = ['arg1', 'arg2', 'arg3']
        self.conf.request_timeout = 0

        request_func = mock.Mock()

        self.assertRaises(exception.ViolinRequestRetryTimeout,
                          self.driver._send_cmd,
                          request_func, success_msg, request_args)

    def test_send_cmd_response_has_no_message(self):
        """The callback returns no message on the first call."""
        success_msg = 'success'
        request_args = ['arg1', 'arg2', 'arg3']
        response1 = {'code': 0, 'message': None}
        response2 = {'code': 0, 'message': 'success'}

        request_func = mock.Mock(side_effect=[response1, response2])
        self.driver._fatal_error_code = mock.Mock(return_value=None)

        self.assertEqual(response2, self.driver._send_cmd
                         (request_func, success_msg, request_args))

    def test_send_cmd_response_has_fatal_error(self):
        """The callback response contains a fatal error code."""
        success_msg = 'success'
        request_args = ['arg1', 'arg2', 'arg3']
        response = {'code': 14000, 'message': 'try again later.'}
        failure = exception.ViolinBackendErr

        request_func = mock.Mock(return_value=response)
        self.driver._fatal_error_code = mock.Mock(
            side_effect=failure(message='fail'))
        self.assertRaises(failure, self.driver._send_cmd,
                          request_func, success_msg, request_args)

    def test_get_igroup(self):
        """The igroup is verified and already exists."""
        bn = '/vshare/config/igroup/%s' % CONNECTOR['host']
        response = {bn: CONNECTOR['host']}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)

        result = self.driver._get_igroup(VOLUME, CONNECTOR)

        self.driver.vip.basic.get_node_values.assert_called_with(bn)
        self.assertEqual(CONNECTOR['host'], result)

    def test_get_igroup_with_new_name(self):
        """The igroup is verified but must be created on the backend."""
        response = {}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.vip = self.setup_mock_vshare(m_conf=conf)

        self.assertEqual(CONNECTOR['host'],
                         self.driver._get_igroup(VOLUME, CONNECTOR))

    def test_wait_for_export_config(self):
        """Queries to cluster nodes verify export config."""
        bn = "/vshare/config/export/container/myContainer/lun/%s" \
            % VOLUME['id']
        response = {'/vshare/config/export/container/myContainer/lun/vol-01':
                    VOLUME['id']}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.mga = self.setup_mock_vshare(m_conf=conf)
        self.driver.mgb = self.setup_mock_vshare(m_conf=conf)

        result = self.driver._wait_for_export_config(VOLUME['id'], state=True)

        self.driver.mga.basic.get_node_values.assert_called_with(bn)
        self.driver.mgb.basic.get_node_values.assert_called_with(bn)
        self.assertTrue(result)

    def test_wait_for_export_config_with_no_config(self):
        """Queries to cluster nodes verify *no* export config."""
        response = {}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.mga = self.setup_mock_vshare(m_conf=conf)
        self.driver.mgb = self.setup_mock_vshare(m_conf=conf)

        self.assertTrue(self.driver._wait_for_export_config(
            VOLUME['id'], state=False))

    def test_is_supported_vmos_version(self):
        """Currently supported VMOS version."""
        version = 'V6.3.1'
        self.assertTrue(self.driver._is_supported_vmos_version(version))

    def test_is_supported_vmos_version_supported_future_version(self):
        """Potential future supported VMOS version."""
        version = 'V6.3.7'
        self.assertTrue(self.driver._is_supported_vmos_version(version))

    def test_is_supported_vmos_version_unsupported_past_version(self):
        """Currently unsupported VMOS version."""
        version = 'G5.5.2'
        self.assertFalse(self.driver._is_supported_vmos_version(version))

    def test_is_supported_vmos_version_unsupported_future_version(self):
        """Future incompatible VMOS version."""
        version = 'V7.0.0'
        self.assertFalse(self.driver._is_supported_vmos_version(version))

    def test_fatal_error_code(self):
        """Return an exception for a valid fatal error code."""
        response = {'code': 14000, 'message': 'fail city'}
        self.assertRaises(exception.ViolinBackendErr,
                          self.driver._fatal_error_code,
                          response)

    def test_fatal_error_code_non_fatal_error(self):
        """Returns no exception for a non-fatal error code."""
        response = {'code': 1024, 'message': 'try again!'}
        self.assertEqual(None, self.driver._fatal_error_code(response))
