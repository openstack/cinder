# Copyright 2015 Violin Memory, Inc.
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
Tests for Violin Memory 7000 Series All-Flash Array Common Driver
"""
import math
import mock

from oslo_utils import units

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_vmem_client as vmemclient
from cinder.volume import configuration as conf
from cinder.volume.drivers.violin import v7000_common
from cinder.volume import volume_types


VOLUME_ID = "abcdabcd-1234-abcd-1234-abcdeffedcba"
VOLUME = {"name": "volume-" + VOLUME_ID,
          "id": VOLUME_ID,
          "display_name": "fake_volume",
          "size": 2,
          "host": "irrelevant",
          "volume_type": None,
          "volume_type_id": None,
          }
SNAPSHOT_ID = "abcdabcd-1234-abcd-1234-abcdeffedcbb"
SNAPSHOT = {"name": "snapshot-" + SNAPSHOT_ID,
            "id": SNAPSHOT_ID,
            "volume_id": VOLUME_ID,
            "volume_name": "volume-" + VOLUME_ID,
            "volume_size": 2,
            "display_name": "fake_snapshot",
            }
SRC_VOL_ID = "abcdabcd-1234-abcd-1234-abcdeffedcbc"
SRC_VOL = {"name": "volume-" + SRC_VOL_ID,
           "id": SRC_VOL_ID,
           "display_name": "fake_src_vol",
           "size": 2,
           "host": "irrelevant",
           "volume_type": None,
           "volume_type_id": None,
           }
INITIATOR_IQN = "iqn.1111-22.org.debian:11:222"
CONNECTOR = {"initiator": INITIATOR_IQN}


class V7000CommonTestCase(test.TestCase):
    """Test case for Violin drivers."""
    def setUp(self):
        super(V7000CommonTestCase, self).setUp()
        self.conf = self.setup_configuration()
        self.driver = v7000_common.V7000Common(self.conf)
        self.driver.container = 'myContainer'
        self.driver.device_id = 'ata-VIOLIN_MEMORY_ARRAY_23109R00000022'
        self.stats = {}

    def tearDown(self):
        super(V7000CommonTestCase, self).tearDown()

    def setup_configuration(self):
        config = mock.Mock(spec=conf.Configuration)
        config.volume_backend_name = 'v7000_common'
        config.san_ip = '1.1.1.1'
        config.san_login = 'admin'
        config.san_password = ''
        config.san_thin_provision = False
        config.san_is_local = False
        config.gateway_mga = '2.2.2.2'
        config.gateway_mgb = '3.3.3.3'
        config.use_igroups = False
        config.violin_request_timeout = 300
        config.container = 'myContainer'
        return config

    @mock.patch('vmemclient.open')
    def setup_mock_client(self, _m_client, m_conf=None):
        """Create a fake backend communication factory.

        The xg-tools creates a Concerto connection object (for V7000
        devices) and returns it for use on a call to vmemclient.open().
        """
        # configure the concerto object mock with defaults
        _m_concerto = mock.Mock(name='Concerto',
                                version='1.1.1',
                                spec=vmemclient.mock_client_conf)

        # if m_conf, clobber the defaults with it
        if m_conf:
            _m_concerto.configure_mock(**m_conf)

        # set calls to vmemclient.open() to return this mocked concerto object
        _m_client.return_value = _m_concerto

        return _m_client

    def setup_mock_concerto(self, m_conf=None):
        """Create a fake Concerto communication object."""
        _m_concerto = mock.Mock(name='Concerto',
                                version='1.1.1',
                                spec=vmemclient.mock_client_conf)

        if m_conf:
            _m_concerto.configure_mock(**m_conf)

        return _m_concerto

    def test_check_for_setup_error(self):
        """No setup errors are found."""
        self.driver.vmem_mg = self.setup_mock_concerto()
        self.driver._is_supported_vmos_version = mock.Mock(return_value=True)

        result = self.driver.check_for_setup_error()

        self.driver._is_supported_vmos_version.assert_called_with(
            self.driver.vmem_mg.version)
        self.assertIsNone(result)

    def test_create_lun(self):
        """Lun is successfully created."""
        response = {'success': True, 'msg': 'Create resource successfully.'}
        size_in_mb = VOLUME['size'] * units.Ki

        conf = {
            'lun.create_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        result = self.driver._create_lun(VOLUME)

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.lun.create_lun,
            'Create resource successfully.',
            VOLUME['id'], size_in_mb, False, False, size_in_mb,
            storage_pool=None)
        self.assertIsNone(result)

    def test_create_dedup_lun(self):
        """Lun is successfully created."""
        vol = VOLUME.copy()
        vol['size'] = 100
        vol['volume_type_id'] = '1'

        response = {'success': True, 'msg': 'Create resource successfully.'}
        size_in_mb = vol['size'] * units.Ki
        full_size_mb = size_in_mb

        conf = {
            'lun.create_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        # simulate extra specs of {'thin': 'true', 'dedupe': 'true'}
        self.driver._get_volume_type_extra_spec = mock.Mock(
            return_value="True")

        self.driver._get_violin_extra_spec = mock.Mock(
            return_value=None)

        result = self.driver._create_lun(vol)

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.lun.create_lun,
            'Create resource successfully.',
            VOLUME['id'], size_in_mb / 10, True, True, full_size_mb,
            storage_pool=None)
        self.assertIsNone(result)

    def test_fail_extend_dedup_lun(self):
        """Volume extend fails when new size would shrink the volume."""
        failure = exception.VolumeDriverException
        vol = VOLUME.copy()
        vol['volume_type_id'] = '1'

        size_in_mb = vol['size'] * units.Ki

        self.driver.vmem_mg = self.setup_mock_concerto()

        # simulate extra specs of {'thin': 'true', 'dedupe': 'true'}
        self.driver._get_volume_type_extra_spec = mock.Mock(
            return_value="True")

        self.assertRaises(failure, self.driver._extend_lun,
                          vol, size_in_mb)

    def test_create_non_dedup_lun(self):
        """Lun is successfully created."""
        vol = VOLUME.copy()
        vol['size'] = 100
        vol['volume_type_id'] = '1'

        response = {'success': True, 'msg': 'Create resource successfully.'}
        size_in_mb = vol['size'] * units.Ki
        full_size_mb = size_in_mb

        conf = {
            'lun.create_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        # simulate extra specs of {'thin': 'false', 'dedupe': 'false'}
        self.driver._get_volume_type_extra_spec = mock.Mock(
            return_value="False")

        self.driver._get_violin_extra_spec = mock.Mock(
            return_value=None)

        result = self.driver._create_lun(vol)

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.lun.create_lun,
            'Create resource successfully.',
            VOLUME['id'], size_in_mb, False, False, full_size_mb,
            storage_pool=None)
        self.assertIsNone(result)

    def test_create_lun_fails(self):
        """Array returns error that the lun already exists."""
        response = {'success': False,
                    'msg': 'Duplicate Virtual Device name. Error: 0x90010022'}

        conf = {
            'lun.create_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        self.assertIsNone(self.driver._create_lun(VOLUME))

    def test_create_lun_on_a_storage_pool(self):
        """Lun is successfully created."""
        vol = VOLUME.copy()
        vol['size'] = 100
        vol['volume_type_id'] = '1'
        response = {'success': True, 'msg': 'Create resource successfully.'}
        size_in_mb = vol['size'] * units.Ki
        full_size_mb = size_in_mb

        conf = {
            'lun.create_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)
        self.driver._get_volume_type_extra_spec = mock.Mock(
            return_value="False")

        # simulates extra specs: {'storage_pool', 'StoragePool'}
        self.driver._get_violin_extra_spec = mock.Mock(
            return_value="StoragePool")

        result = self.driver._create_lun(vol)

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.lun.create_lun,
            'Create resource successfully.',
            VOLUME['id'], size_in_mb, False, False, full_size_mb,
            storage_pool="StoragePool")
        self.assertIsNone(result)

    def test_delete_lun(self):
        """Lun is deleted successfully."""
        response = {'success': True, 'msg': 'Delete resource successfully'}
        success_msgs = ['Delete resource successfully', '']

        conf = {
            'lun.delete_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)
        self.driver._delete_lun_snapshot_bookkeeping = mock.Mock()

        result = self.driver._delete_lun(VOLUME)

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.lun.delete_lun,
            success_msgs, VOLUME['id'], True)
        self.driver._delete_lun_snapshot_bookkeeping.assert_called_with(
            VOLUME['id'])

        self.assertIsNone(result)

    # TODO(rlucio) More delete lun failure cases to be added after
    # collecting the possible responses from Concerto

    def test_extend_lun(self):
        """Volume extend completes successfully."""
        new_volume_size = 10
        change_in_size_mb = (new_volume_size - VOLUME['size']) * units.Ki

        response = {'success': True, 'message': 'Expand resource successfully'}

        conf = {
            'lun.extend_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        result = self.driver._extend_lun(VOLUME, new_volume_size)

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.lun.extend_lun,
            response['message'], VOLUME['id'], change_in_size_mb)
        self.assertIsNone(result)

    def test_extend_lun_new_size_is_too_small(self):
        """Volume extend fails when new size would shrink the volume."""
        new_volume_size = 0
        change_in_size_mb = (new_volume_size - VOLUME['size']) * units.Ki

        response = {'success': False, 'msg': 'Invalid size. Error: 0x0902000c'}
        failure = exception.ViolinBackendErr

        conf = {
            'lun.resize_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(side_effect=failure(message='fail'))

        self.assertRaises(failure, self.driver._extend_lun,
                          VOLUME, change_in_size_mb)

    def test_create_volume_from_snapshot(self):
        """Create a new cinder volume from a given snapshot of a lun."""
        object_id = '12345'
        vdev_id = 11111
        response = {'success': True,
                    'object_id': object_id,
                    'msg': 'Copy TimeMark successfully.'}
        lun_info = {'virtualDeviceID': vdev_id}
        compressed_snap_id = 'abcdabcd1234abcd1234abcdeffedcbb'

        conf = {
            'lun.copy_snapshot_to_new_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._compress_snapshot_id = mock.Mock(
            return_value=compressed_snap_id)
        self.driver.vmem_mg.lun.get_lun_info = mock.Mock(return_value=lun_info)
        self.driver._wait_for_lun_or_snap_copy = mock.Mock()

        result = self.driver._create_volume_from_snapshot(SNAPSHOT, VOLUME)

        self.driver.vmem_mg.lun.copy_snapshot_to_new_lun.assert_called_with(
            source_lun=SNAPSHOT['volume_id'],
            source_snapshot_comment=compressed_snap_id,
            destination=VOLUME['id'], storage_pool=None)
        self.driver.vmem_mg.lun.get_lun_info.assert_called_with(
            object_id=object_id)
        self.driver._wait_for_lun_or_snap_copy.assert_called_with(
            SNAPSHOT['volume_id'], dest_vdev_id=vdev_id)

        self.assertIsNone(result)

    def test_create_volume_from_snapshot_on_a_storage_pool(self):
        """Create a new cinder volume from a given snapshot of a lun."""
        dest_vol = VOLUME.copy()
        dest_vol['size'] = 100
        dest_vol['volume_type_id'] = '1'
        object_id = '12345'
        vdev_id = 11111
        response = {'success': True,
                    'object_id': object_id,
                    'msg': 'Copy TimeMark successfully.'}
        lun_info = {'virtualDeviceID': vdev_id}
        compressed_snap_id = 'abcdabcd1234abcd1234abcdeffedcbb'

        conf = {
            'lun.copy_snapshot_to_new_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._compress_snapshot_id = mock.Mock(
            return_value=compressed_snap_id)
        self.driver.vmem_mg.lun.get_lun_info = mock.Mock(return_value=lun_info)
        self.driver._wait_for_lun_or_snap_copy = mock.Mock()

        # simulates extra specs: {'storage_pool', 'StoragePool'}
        self.driver._get_violin_extra_spec = mock.Mock(
            return_value="StoragePool")

        result = self.driver._create_volume_from_snapshot(SNAPSHOT, dest_vol)

        self.assertIsNone(result)

    def test_create_volume_from_snapshot_fails(self):
        """Array returns error that the lun already exists."""
        response = {'success': False,
                    'msg': 'Duplicate Virtual Device name. Error: 0x90010022'}
        compressed_snap_id = 'abcdabcd1234abcd1234abcdeffedcbb'
        failure = exception.ViolinBackendErrExists

        conf = {
            'lun.copy_snapshot_to_new_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)
        self.driver._compress_snapshot_id = mock.Mock(
            return_value=compressed_snap_id)

        self.driver._send_cmd = mock.Mock(side_effect=failure(message='fail'))

        self.assertRaises(failure, self.driver._create_volume_from_snapshot,
                          SNAPSHOT, VOLUME)

    def test_create_lun_from_lun(self):
        """lun full clone to new volume completes successfully."""
        object_id = '12345'
        response = {'success': True,
                    'object_id': object_id,
                    'msg': 'Copy Snapshot resource successfully'}

        conf = {
            'lun.copy_lun_to_new_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._ensure_snapshot_resource_area = mock.Mock()
        self.driver._wait_for_lun_or_snap_copy = mock.Mock()

        result = self.driver._create_lun_from_lun(SRC_VOL, VOLUME)

        self.driver._ensure_snapshot_resource_area.assert_called_with(
            SRC_VOL['id'])
        self.driver.vmem_mg.lun.copy_lun_to_new_lun.assert_called_with(
            source=SRC_VOL['id'], destination=VOLUME['id'], storage_pool=None)
        self.driver._wait_for_lun_or_snap_copy.assert_called_with(
            SRC_VOL['id'], dest_obj_id=object_id)

        self.assertIsNone(result)

    def test_create_lun_from_lun_on_a_storage_pool(self):

        """lun full clone to new volume completes successfully."""
        dest_vol = VOLUME.copy()
        dest_vol['size'] = 100
        dest_vol['volume_type_id'] = '1'
        object_id = '12345'
        response = {'success': True,
                    'object_id': object_id,
                    'msg': 'Copy Snapshot resource successfully'}

        conf = {
            'lun.copy_lun_to_new_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._ensure_snapshot_resource_area = mock.Mock()
        self.driver._wait_for_lun_or_snap_copy = mock.Mock()

        # simulates extra specs: {'storage_pool', 'StoragePool'}
        self.driver._get_violin_extra_spec = mock.Mock(
            return_value="StoragePool")

        result = self.driver._create_lun_from_lun(SRC_VOL, dest_vol)

        self.driver._ensure_snapshot_resource_area.assert_called_with(
            SRC_VOL['id'])
        self.driver.vmem_mg.lun.copy_lun_to_new_lun.assert_called_with(
            source=SRC_VOL['id'], destination=dest_vol['id'],
            storage_pool="StoragePool")
        self.driver._wait_for_lun_or_snap_copy.assert_called_with(
            SRC_VOL['id'], dest_obj_id=object_id)

        self.assertIsNone(result)

    def test_create_lun_from_lun_fails(self):
        """lun full clone to new volume completes successfully."""
        failure = exception.ViolinBackendErr
        response = {'success': False,
                    'msg': 'Snapshot Resource is not created '
                    'for this virtual device. Error: 0x0901008c'}

        conf = {
            'lun.copy_lun_to_new_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._ensure_snapshot_resource_area = mock.Mock()
        self.driver._send_cmd = mock.Mock(side_effect=failure(message='fail'))

        self.assertRaises(failure, self.driver._create_lun_from_lun,
                          SRC_VOL, VOLUME)

    def test_send_cmd(self):
        """Command callback completes successfully."""
        success_msg = 'success'
        request_args = ['arg1', 'arg2', 'arg3']
        response = {'success': True, 'msg': 'Operation successful'}

        request_func = mock.Mock(return_value=response)

        result = self.driver._send_cmd(request_func, success_msg, request_args)

        self.assertEqual(response, result)

    def test_send_cmd_request_timed_out(self):
        """The callback retry timeout hits immediately."""
        failure = exception.ViolinRequestRetryTimeout
        success_msg = 'success'
        request_args = ['arg1', 'arg2', 'arg3']
        self.conf.violin_request_timeout = 0

        request_func = mock.Mock()

        self.assertRaises(failure, self.driver._send_cmd,
                          request_func, success_msg, request_args)

    def test_send_cmd_response_has_no_message(self):
        """The callback returns no message on the first call."""
        success_msg = 'success'
        request_args = ['arg1', 'arg2', 'arg3']
        response1 = {'success': True, 'msg': None}
        response2 = {'success': True, 'msg': 'success'}

        request_func = mock.Mock(side_effect=[response1, response2])

        self.assertEqual(response2, self.driver._send_cmd
                         (request_func, success_msg, request_args))

    def test_check_error_code(self):
        """Return an exception for a valid error code."""
        failure = exception.ViolinBackendErr
        response = {'success': False, 'msg': 'Error: 0x90000000'}
        self.assertRaises(failure, self.driver._check_error_code,
                          response)

    def test_check_error_code_non_fatal_error(self):
        """Returns no exception for a non-fatal error code."""
        response = {'success': False, 'msg': 'Error: 0x9001003c'}
        self.assertIsNone(self.driver._check_error_code(response))

    def test_compress_snapshot_id(self):
        test_snap_id = "12345678-abcd-1234-cdef-0123456789ab"
        expected = "12345678abcd1234cdef0123456789ab"

        self.assertTrue(len(expected) == 32)
        result = self.driver._compress_snapshot_id(test_snap_id)
        self.assertTrue(result == expected)

    def test_ensure_snapshot_resource_area(self):
        result_dict = {'success': True, 'res': 'Successful'}

        self.driver.vmem_mg = self.setup_mock_concerto()
        snap = self.driver.vmem_mg.snapshot
        snap.lun_has_a_snapshot_resource = mock.Mock(return_value=False)
        snap.create_snapshot_resource = mock.Mock(return_value=result_dict)

        with mock.patch('cinder.db.sqlalchemy.api.volume_get',
                        return_value=VOLUME):
            result = self.driver._ensure_snapshot_resource_area(VOLUME_ID)

        self.assertIsNone(result)
        snap.lun_has_a_snapshot_resource.assert_called_with(lun=VOLUME_ID)
        snap.create_snapshot_resource.assert_called_with(
            lun=VOLUME_ID,
            size=int(math.ceil(0.2 * (VOLUME['size'] * 1024))),
            enable_notification=False,
            policy=v7000_common.CONCERTO_DEFAULT_SRA_POLICY,
            enable_expansion=
            v7000_common.CONCERTO_DEFAULT_SRA_ENABLE_EXPANSION,
            expansion_threshold=
            v7000_common.CONCERTO_DEFAULT_SRA_EXPANSION_THRESHOLD,
            expansion_increment=
            v7000_common.CONCERTO_DEFAULT_SRA_EXPANSION_INCREMENT,
            expansion_max_size=
            v7000_common.CONCERTO_DEFAULT_SRA_EXPANSION_MAX_SIZE,
            enable_shrink=v7000_common.CONCERTO_DEFAULT_SRA_ENABLE_SHRINK,
            storage_pool=None)

    def test_ensure_snapshot_resource_area_with_storage_pool(self):

        dest_vol = VOLUME.copy()
        dest_vol['size'] = 2
        dest_vol['volume_type_id'] = '1'

        result_dict = {'success': True, 'res': 'Successful'}

        self.driver.vmem_mg = self.setup_mock_concerto()
        snap = self.driver.vmem_mg.snapshot
        snap.lun_has_a_snapshot_resource = mock.Mock(return_value=False)
        snap.create_snapshot_resource = mock.Mock(return_value=result_dict)

        # simulates extra specs: {'storage_pool', 'StoragePool'}
        self.driver._get_violin_extra_spec = mock.Mock(
            return_value="StoragePool")

        with mock.patch('cinder.db.sqlalchemy.api.volume_get',
                        return_value=dest_vol):
            result = self.driver._ensure_snapshot_resource_area(VOLUME_ID)

        self.assertIsNone(result)
        snap.lun_has_a_snapshot_resource.assert_called_with(lun=VOLUME_ID)
        snap.create_snapshot_resource.assert_called_with(
            lun=VOLUME_ID,
            size=int(math.ceil(0.2 * (VOLUME['size'] * 1024))),
            enable_notification=False,
            policy=v7000_common.CONCERTO_DEFAULT_SRA_POLICY,
            enable_expansion=
            v7000_common.CONCERTO_DEFAULT_SRA_ENABLE_EXPANSION,
            expansion_threshold=
            v7000_common.CONCERTO_DEFAULT_SRA_EXPANSION_THRESHOLD,
            expansion_increment=
            v7000_common.CONCERTO_DEFAULT_SRA_EXPANSION_INCREMENT,
            expansion_max_size=
            v7000_common.CONCERTO_DEFAULT_SRA_EXPANSION_MAX_SIZE,
            enable_shrink=v7000_common.CONCERTO_DEFAULT_SRA_ENABLE_SHRINK,
            storage_pool="StoragePool")

    def test_ensure_snapshot_resource_policy(self):
        result_dict = {'success': True, 'res': 'Successful'}

        self.driver.vmem_mg = self.setup_mock_concerto()

        snap = self.driver.vmem_mg.snapshot
        snap.lun_has_a_snapshot_policy = mock.Mock(return_value=False)
        snap.create_snapshot_policy = mock.Mock(return_value=result_dict)

        result = self.driver._ensure_snapshot_policy(VOLUME_ID)
        self.assertIsNone(result)
        snap.lun_has_a_snapshot_policy.assert_called_with(lun=VOLUME_ID)

        snap.create_snapshot_policy.assert_called_with(
            lun=VOLUME_ID,
            max_snapshots=v7000_common.CONCERTO_DEFAULT_POLICY_MAX_SNAPSHOTS,
            enable_replication=False,
            enable_snapshot_schedule=False,
            enable_cdp=False,
            retention_mode=v7000_common.CONCERTO_DEFAULT_POLICY_RETENTION_MODE)

    def test_delete_lun_snapshot_bookkeeping(self):
        result_dict = {'success': True, 'res': 'Successful'}

        self.driver.vmem_mg = self.setup_mock_concerto()
        snap = self.driver.vmem_mg.snapshot
        snap.get_snapshots = mock.Mock(
            return_value=[],
            side_effect=vmemclient.core.error.NoMatchingObjectIdError)
        snap.delete_snapshot_policy = mock.Mock(return_value=result_dict)
        snap.delete_snapshot_resource = mock.Mock()

        result = self.driver._delete_lun_snapshot_bookkeeping(
            volume_id=VOLUME_ID)

        self.assertIsNone(result)

        snap.get_snapshots.assert_called_with(VOLUME_ID)
        snap.delete_snapshot_policy.assert_called_with(lun=VOLUME_ID)
        snap.delete_snapshot_resource.assert_called_with(lun=VOLUME_ID)

    def test_create_lun_snapshot(self):
        response = {'success': True, 'msg': 'Create TimeMark successfully'}

        self.driver.vmem_mg = self.setup_mock_concerto()
        self.driver._ensure_snapshot_resource_area = (
            mock.Mock(return_value=True))
        self.driver._ensure_snapshot_policy = mock.Mock(return_value=True)
        self.driver._send_cmd = mock.Mock(return_value=response)

        with mock.patch('cinder.db.sqlalchemy.api.volume_get',
                        return_value=VOLUME):
            result = self.driver._create_lun_snapshot(SNAPSHOT)

        self.assertIsNone(result)

        self.driver._ensure_snapshot_resource_area.assert_called_with(
            VOLUME_ID)
        self.driver._ensure_snapshot_policy.assert_called_with(VOLUME_ID)
        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.snapshot.create_lun_snapshot,
            'Create TimeMark successfully',
            lun=VOLUME_ID,
            comment=self.driver._compress_snapshot_id(SNAPSHOT_ID),
            priority=v7000_common.CONCERTO_DEFAULT_PRIORITY,
            enable_notification=False)

    def test_delete_lun_snapshot(self):
        response = {'success': True, 'msg': 'Delete TimeMark successfully'}
        compressed_snap_id = 'abcdabcd1234abcd1234abcdeffedcbb'

        self.driver.vmem_mg = self.setup_mock_concerto()
        self.driver._send_cmd = mock.Mock(return_value=response)
        self.driver._compress_snapshot_id = mock.Mock(
            return_value=compressed_snap_id)

        self.assertIsNone(self.driver._delete_lun_snapshot(SNAPSHOT))

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.snapshot.delete_lun_snapshot,
            'Delete TimeMark successfully',
            lun=VOLUME_ID,
            comment=compressed_snap_id)

    def test_wait_for_lun_or_snap_copy_completes_for_snap(self):
        """waiting for a snapshot to copy succeeds."""
        vdev_id = 11111
        response = (vdev_id, None, 100)

        conf = {
            'snapshot.get_snapshot_copy_status.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)

        result = self.driver._wait_for_lun_or_snap_copy(
            SRC_VOL['id'], dest_vdev_id=vdev_id)

        (self.driver.vmem_mg.snapshot.get_snapshot_copy_status.
         assert_called_with(SRC_VOL['id']))
        self.assertTrue(result)

    def test_wait_for_lun_or_snap_copy_completes_for_lun(self):
        """waiting for a lun to copy succeeds."""
        object_id = '12345'
        response = (object_id, None, 100)

        conf = {
            'lun.get_lun_copy_status.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)

        result = self.driver._wait_for_lun_or_snap_copy(
            SRC_VOL['id'], dest_obj_id=object_id)

        self.driver.vmem_mg.lun.get_lun_copy_status.assert_called_with(
            SRC_VOL['id'])
        self.assertTrue(result)

    @mock.patch.object(context, 'get_admin_context')
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_get_volume_type_extra_spec(self,
                                        m_get_volume_type,
                                        m_get_admin_context):
        """Volume_type extra specs are found successfully."""
        vol = VOLUME.copy()
        vol['volume_type_id'] = 1
        volume_type = {'extra_specs': {'override:test_key': 'test_value'}}

        m_get_admin_context.return_value = None
        m_get_volume_type.return_value = volume_type

        result = self.driver._get_volume_type_extra_spec(vol, 'test_key')

        m_get_admin_context.assert_called_with()
        m_get_volume_type.assert_called_with(None, vol['volume_type_id'])
        self.assertEqual('test_value', result)

    @mock.patch.object(context, 'get_admin_context')
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_get_violin_extra_spec(self,
                                   m_get_volume_type,
                                   m_get_admin_context):
        """Volume_type extra specs are found successfully."""
        vol = VOLUME.copy()
        vol['volume_type_id'] = 1
        volume_type = {'extra_specs': {'violin:test_key': 'test_value'}}

        m_get_admin_context.return_value = None
        m_get_volume_type.return_value = volume_type

        result = self.driver._get_volume_type_extra_spec(vol, 'test_key')

        m_get_admin_context.assert_called_with()
        m_get_volume_type.assert_called_with(None, vol['volume_type_id'])
        self.assertEqual('test_value', result)
