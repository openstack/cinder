# Copyright 2020 Datera
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
from unittest import mock
import uuid

from cinder import context
from cinder import exception
from cinder.tests.unit import test
from cinder import version
from cinder.volume import configuration as conf
from cinder.volume import volume_types

sys.modules['dfs_sdk'] = mock.MagicMock()

from cinder.volume.drivers.datera import datera_iscsi as datera  # noqa

datera.datc.DEFAULT_SI_SLEEP = 0
datera.datc.DEFAULT_SNAP_SLEEP = 0
OS_PREFIX = datera.datc.OS_PREFIX
UNMANAGE_PREFIX = datera.datc.UNMANAGE_PREFIX
DateraAPIException = datera.datc.DateraAPIException


class DateraVolumeTestCasev22(test.TestCase):

    def setUp(self):
        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.san_ip = '127.0.0.1'
        self.cfg.datera_api_port = '7717'
        self.cfg.san_is_local = True
        self.cfg.datera_num_replicas = 1
        self.cfg.datera_503_timeout = 0.01
        self.cfg.datera_503_interval = 0.001
        self.cfg.datera_debug = False
        self.cfg.san_login = 'user'
        self.cfg.san_password = 'pass'
        self.cfg.datera_tenant_id = '/root/test-tenant'
        self.cfg.driver_client_cert = None
        self.cfg.driver_client_cert_key = None
        self.cfg.datera_disable_profiler = False
        self.cfg.datera_ldap_server = ""
        self.cfg.datera_volume_type_defaults = {}
        self.cfg.datera_disable_template_override = False
        self.cfg.datera_disable_extended_metadata = False
        self.cfg.datera_enable_image_cache = False
        self.cfg.datera_image_cache_volume_type_id = ""
        self.cfg.filter_function = lambda: None
        self.cfg.goodness_function = lambda: None
        self.cfg.use_chap_auth = False
        self.cfg.chap_username = ""
        self.cfg.chap_password = ""

        super(DateraVolumeTestCasev22, self).setUp()
        mock_exec = mock.Mock()
        mock_exec.return_value = ('', '')

        self.driver = datera.DateraDriver(execute=mock_exec,
                                          configuration=self.cfg)
        self.driver.api = mock.MagicMock()
        self.driver.apiv = "2.2"

        self.driver.set_initialized()
        # No-op config getter
        self.driver.configuration.get = lambda *args, **kwargs: {}
        # self.addCleanup(self.api_patcher.stop)
        self.driver.datera_version = "3.3.3"

    def test_volume_create_success(self):
        testvol = _stub_volume()
        self.assertIsNone(self.driver.create_volume(testvol))

    def test_volume_create_fails(self):
        testvol = _stub_volume()
        self.driver.api.app_instances.create.side_effect = DateraAPIException
        self.assertRaises(DateraAPIException,
                          self.driver.create_volume,
                          testvol)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_with_extra_specs(self, mock_get_type):
        mock_get_type.return_value = {
            'name': u'The Best',
            'qos_specs_id': None,
            'deleted': False,
            'created_at': '2015-08-14 04:18:11',
            'updated_at': None,
            'extra_specs': {
                u'volume_backend_name': u'datera',
                u'qos:max_iops_read': u'2000',
                u'qos:max_iops_write': u'4000',
                u'qos:max_iops_total': u'4000'
            },
            'is_public': True,
            'deleted_at': None,
            'id': u'dffb4a83-b8fb-4c19-9f8c-713bb75db3b1',
            'description': None
        }

        mock_volume = _stub_volume(
            volume_type_id='dffb4a83-b8fb-4c19-9f8c-713bb75db3b1'
        )

        self.assertIsNone(self.driver.create_volume(mock_volume))
        self.assertTrue(mock_get_type.called)

    def test_create_cloned_volume_success(self):
        testvol = _stub_volume()
        ref = _stub_volume(id=str(uuid.uuid4()))
        self.assertIsNone(self.driver.create_cloned_volume(testvol, ref))

    def test_create_cloned_volume_success_larger(self):
        newsize = 2
        testvol = _stub_volume(size=newsize)
        ref = _stub_volume(id=str(uuid.uuid4()))
        mock_extend = mock.MagicMock()
        self.driver._extend_volume_2_2 = mock_extend
        self.driver._extend_volume_2_1 = mock_extend
        self.driver.create_cloned_volume(testvol, ref)
        mock_extend.assert_called_once_with(testvol, newsize)

    def test_create_cloned_volume_fails(self):
        testvol = _stub_volume()
        ref = _stub_volume(id=str(uuid.uuid4()))
        self.driver.api.app_instances.create.side_effect = DateraAPIException
        self.assertRaises(DateraAPIException,
                          self.driver.create_cloned_volume,
                          testvol,
                          ref)

    def test_delete_volume_success(self):
        testvol = _stub_volume()
        self.driver.api.app_instances.delete.return_value = {}
        self.assertIsNone(self.driver.delete_volume(testvol))

    def test_delete_volume_not_found(self):
        testvol = _stub_volume()
        self.driver.api.app_instances.list.side_effect = exception.NotFound
        self.assertIsNone(self.driver.delete_volume(testvol))

    def test_delete_volume_fails(self):
        testvol = _stub_volume()
        self.driver.api.app_instances.list.side_effect = DateraAPIException
        self.assertRaises(DateraAPIException,
                          self.driver.delete_volume, testvol)

    def test_ensure_export_success(self):
        testvol = _stub_volume()
        ctxt = context.get_admin_context()
        self.assertIsNone(self.driver.ensure_export(ctxt, testvol, None))

    def test_ensure_export_fails(self):
        # This can't fail because it's a no-op
        testvol = _stub_volume()
        ctxt = context.get_admin_context()
        self.assertIsNone(self.driver.ensure_export(ctxt, testvol, None))

    def test_create_export_target_does_not_exist_success(self):
        testvol = _stub_volume()
        aimock = mock.MagicMock()
        simock = mock.MagicMock()
        simock.reload.return_value = simock
        aimock.storage_instances.list.return_value = [simock]
        simock.op_state = "available"
        self.driver.cvol_to_ai = mock.Mock()
        self.driver.cvol_to_ai.return_value = aimock
        self.assertIsNone(self.driver.create_export(None, testvol, None))

    def test_create_export_fails(self):
        testvol = _stub_volume()
        aimock = mock.MagicMock()
        simock = mock.MagicMock()
        simock.reload.return_value = simock
        aimock.storage_instances.list.side_effect = DateraAPIException
        simock.op_state = "available"
        self.driver.cvol_to_ai = mock.Mock()
        self.driver.cvol_to_ai.return_value = aimock
        self.assertRaises(DateraAPIException,
                          self.driver.create_export,
                          None,
                          testvol,
                          None)

    def test_initialize_connection_success(self):
        testvol = _stub_volume()
        aimock = mock.MagicMock()
        simock = mock.MagicMock()
        simock.access = {"ips": ["test-ip"], "iqn": "test-iqn"}
        simock.reload.return_value = simock
        aimock.storage_instances.list.return_value = [simock]
        self.driver.cvol_to_ai = mock.Mock()
        self.driver.cvol_to_ai.return_value = aimock
        self.assertEqual(self.driver.initialize_connection(testvol, {}),
                         {'data': {'discard': False,
                                   'target_discovered': False,
                                   'target_iqn': 'test-iqn',
                                   'target_lun': 0,
                                   'target_portal': 'test-ip:3260',
                                   'volume_id': testvol['id']},
                          'driver_volume_type': 'iscsi'})

    def test_initialize_connection_fails(self):
        testvol = _stub_volume()
        aimock = mock.MagicMock()
        simock = mock.MagicMock()
        simock.access = {"ips": ["test-ip"], "iqn": "test-iqn"}
        simock.reload.return_value = simock
        aimock.storage_instances.list.side_effect = DateraAPIException
        self.driver.cvol_to_ai = mock.Mock()
        self.driver.cvol_to_ai.return_value = aimock
        self.assertRaises(DateraAPIException,
                          self.driver.initialize_connection,
                          testvol,
                          {})

    def test_detach_volume_success(self):
        testvol = _stub_volume()
        self.driver.cvol_to_ai = mock.MagicMock()
        aimock = mock.MagicMock()
        aimock.set.return_value = {}
        self.driver.cvol_to_ai.return_value = aimock
        ctxt = context.get_admin_context()
        self.assertIsNone(self.driver.detach_volume(ctxt, testvol))

    def test_detach_volume_fails(self):
        testvol = _stub_volume()
        self.driver.cvol_to_ai = mock.MagicMock()
        aimock = mock.MagicMock()
        aimock.set.side_effect = DateraAPIException
        self.driver.cvol_to_ai.return_value = aimock
        ctxt = context.get_admin_context()
        self.assertRaises(DateraAPIException,
                          self.driver.detach_volume,
                          ctxt, testvol)

    def test_detach_volume_not_found(self):
        testvol = _stub_volume()
        self.driver.cvol_to_ai = mock.MagicMock()
        aimock = mock.MagicMock()
        aimock.set.side_effect = exception.NotFound
        self.driver.cvol_to_ai.return_value = aimock
        ctxt = context.get_admin_context()
        self.assertIsNone(self.driver.detach_volume(ctxt, testvol))

    def test_create_snapshot_success(self):
        testsnap = _stub_snapshot(volume_id=str(uuid.uuid4()))
        volmock = mock.MagicMock()
        snapmock = mock.MagicMock()
        snapmock.reload.return_value = snapmock
        snapmock.uuid = testsnap['id']
        snapmock.op_state = "available"
        volmock.snapshots.create.return_value = snapmock
        self.driver.cvol_to_dvol = mock.MagicMock()
        self.driver.cvol_to_dvol.return_value = volmock
        self.assertIsNone(self.driver.create_snapshot(testsnap))

    def test_create_snapshot_fails(self):
        testsnap = _stub_snapshot(volume_id=str(uuid.uuid4()))
        self.driver.api.app_instances.list.side_effect = DateraAPIException
        self.assertRaises(DateraAPIException,
                          self.driver.create_snapshot,
                          testsnap)

    def test_delete_snapshot_success(self):
        testsnap = _stub_snapshot(volume_id=str(uuid.uuid4()))
        self.assertIsNone(self.driver.delete_snapshot(testsnap))

    def test_delete_snapshot_not_found(self):
        testsnap = _stub_snapshot(volume_id=str(uuid.uuid4()))
        self.driver.cvol_to_dvol = mock.MagicMock()
        aimock = mock.MagicMock()
        aimock.snapshots.list.side_effect = exception.NotFound
        self.driver.cvol_to_dvol.return_value = aimock
        self.assertIsNone(self.driver.delete_snapshot(testsnap))

    def test_delete_snapshot_fails(self):
        testsnap = _stub_snapshot(volume_id=str(uuid.uuid4()))
        self.driver.cvol_to_dvol = mock.MagicMock()
        aimock = mock.MagicMock()
        aimock.snapshots.list.side_effect = DateraAPIException
        self.driver.cvol_to_dvol.return_value = aimock
        self.assertRaises(DateraAPIException,
                          self.driver.delete_snapshot,
                          testsnap)

    def test_create_volume_from_snapshot_success(self):
        testsnap = _stub_snapshot(volume_id=str(uuid.uuid4()))
        testvol = _stub_volume()
        volmock = mock.MagicMock()
        snapmock = mock.MagicMock()
        snapmock.reload.return_value = snapmock
        snapmock.uuid = testsnap['id']
        snapmock.op_state = "available"
        self.driver.cvol_to_dvol = mock.MagicMock()
        self.driver.cvol_to_dvol.return_value = volmock
        volmock.snapshots.list.return_value = [snapmock]
        self.assertIsNone(self.driver.create_volume_from_snapshot(
            testvol, testsnap))

    def test_create_volume_from_snapshot_fails(self):
        testsnap = _stub_snapshot(volume_id=str(uuid.uuid4()))
        testvol = _stub_volume()
        self.driver.cvol_to_dvol = mock.MagicMock()
        aimock = mock.MagicMock()
        aimock.snapshots.list.side_effect = DateraAPIException
        self.driver.cvol_to_dvol.return_value = aimock
        self.assertRaises(DateraAPIException,
                          self.driver.create_volume_from_snapshot,
                          testvol,
                          testsnap)

    def test_extend_volume_success(self):
        newsize = 2
        testvol = _stub_volume()
        mockvol = mock.MagicMock()
        mockvol.size = newsize
        self.driver.cvol_to_dvol = mock.MagicMock()
        self.driver.cvol_to_dvol.return_value = mockvol
        self.driver._offline_flip_2_2 = mock.MagicMock()
        self.driver._offline_flip_2_1 = mock.MagicMock()
        self.assertIsNone(self.driver.extend_volume(testvol, newsize))

    def test_extend_volume_fails(self):
        newsize = 2
        testvol = _stub_volume()
        mockvol = mock.MagicMock()
        mockvol.size = newsize
        mockvol.set.side_effect = DateraAPIException
        self.driver.cvol_to_dvol = mock.MagicMock()
        self.driver.cvol_to_dvol.return_value = mockvol
        self.driver._offline_flip_2_2 = mock.MagicMock()
        self.driver._offline_flip_2_1 = mock.MagicMock()
        self.assertRaises(DateraAPIException,
                          self.driver.extend_volume,
                          testvol,
                          newsize)

    def test_manage_existing(self):
        existing_ref = {'source-name': "A:B:C:D"}
        testvol = _stub_volume()
        self.driver.cvol_to_ai = mock.MagicMock()
        self.assertIsNone(self.driver.manage_existing(testvol, existing_ref))

    def test_manage_existing_wrong_ref(self):
        existing_ref = {'source-name': "ABCD"}
        testvol = _stub_volume()
        self.driver.cvol_to_ai = mock.MagicMock()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          testvol,
                          existing_ref)

    def test_manage_existing_get_size(self):
        existing_ref = {'source-name': "A:B:C:D"}
        testvol = _stub_volume()
        volmock = mock.MagicMock()
        volmock.size = testvol['size']
        self.driver.cvol_to_dvol = mock.MagicMock()
        self.driver.cvol_to_dvol.return_value = volmock
        self.assertEqual(self.driver.manage_existing_get_size(
            testvol, existing_ref), testvol['size'])

    def test_manage_existing_get_size_wrong_ref(self):
        existing_ref = {'source-name': "ABCD"}
        testvol = _stub_volume()
        self.driver.cvol_to_ai = mock.MagicMock()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          testvol,
                          existing_ref)

    def test_get_manageable_volumes(self):
        testvol = _stub_volume()
        v1 = {'reference': {'source-name': 'some-ai:storage-1:volume-1'},
              'size': 1,
              'safe_to_manage': True,
              'reason_not_safe': '',
              'cinder_id': None,
              'extra_info': {'snapshots': '[]'}}
        v2 = {'reference': {'source-name': 'some-other-ai:storage-1:volume-1'},
              'size': 2,
              'safe_to_manage': True,
              'reason_not_safe': '',
              'cinder_id': None,
              'extra_info': {'snapshots': '[]'}}

        mock1 = mock.MagicMock()
        mock1.__getitem__.side_effect = ['some-ai']
        mock1.name = 'some-ai'
        mocksi1 = mock.MagicMock()
        mocksi1.name = "storage-1"
        mocksi1.__getitem__.side_effect = [[mock.MagicMock()]]
        mock1.storage_instances.list.return_value = [mocksi1]
        mockvol1 = mock.MagicMock()
        mockvol1.name = "volume-1"
        mockvol1.size = v1['size']
        mocksi1.volumes.list.return_value = [mockvol1]

        mock2 = mock.MagicMock()
        mock2.__getitem__.side_effect = ['some-other-ai']
        mock2.name = 'some-other-ai'
        mocksi2 = mock.MagicMock()
        mocksi2.name = "storage-1"
        mocksi2.__getitem__.side_effect = [[mock.MagicMock()]]
        mock2.storage_instances.list.return_value = [mocksi2]
        mockvol2 = mock.MagicMock()
        mockvol2.name = "volume-1"
        mockvol2.size = v2['size']
        mocksi2.volumes.list.return_value = [mockvol2]

        listmock = mock.MagicMock()
        listmock.return_value = [mock1, mock2]
        self.driver.api.app_instances.list = listmock

        marker = mock.MagicMock()
        limit = mock.MagicMock()
        offset = mock.MagicMock()
        sort_keys = mock.MagicMock()
        sort_dirs = mock.MagicMock()
        if (version.version_string() >= '15.0.0'):
            with mock.patch(
                    'cinder.volume.volume_utils.paginate_entries_list') \
                    as mpage:
                self.driver.get_manageable_volumes(
                    [testvol], marker, limit, offset, sort_keys, sort_dirs)
                mpage.assert_called_once_with(
                    [v1, v2], marker, limit, offset, sort_keys, sort_dirs)
        else:
            with mock.patch(
                    'cinder.volume.utils.paginate_entries_list') as mpage:
                self.driver.get_manageable_volumes(
                    [testvol], marker, limit, offset, sort_keys, sort_dirs)
                mpage.assert_called_once_with(
                    [v1, v2], marker, limit, offset, sort_keys, sort_dirs)

    def test_unmanage(self):
        testvol = _stub_volume()
        self.assertIsNone(self.driver.unmanage(testvol))


class DateraVolumeTestCasev21(DateraVolumeTestCasev22):

    def setUp(self):
        super(DateraVolumeTestCasev21, self).setUp()
        self.driver.api = mock.MagicMock()
        self.driver.apiv = '2.1'


def _stub_volume(*args, **kwargs):
    uuid = 'c20aba21-6ef6-446b-b374-45733b4883ba'
    name = 'volume-00000001'
    size = 1
    volume = {}
    volume['id'] = kwargs.get('id', uuid)
    volume['project_id'] = "test-project"
    volume['display_name'] = kwargs.get('display_name', name)
    volume['size'] = kwargs.get('size', size)
    volume['provider_location'] = kwargs.get('provider_location', None)
    volume['volume_type_id'] = kwargs.get('volume_type_id', None)
    return volume


def _stub_snapshot(*args, **kwargs):
    uuid = '0bb34f0c-fea4-48e0-bf96-591120ac7e3c'
    name = 'snapshot-00000001'
    volume_size = 1
    snap = {}
    snap['id'] = kwargs.get('id', uuid)
    snap['project_id'] = "test-project"
    snap['display_name'] = kwargs.get('display_name', name)
    snap['volume_id'] = kwargs.get('volume_id', None)
    snap['volume_size'] = kwargs.get('volume_size', volume_size)
    return snap
