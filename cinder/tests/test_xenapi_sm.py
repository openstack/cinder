# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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


import contextlib

import mock
import mox
import six

from cinder.db import api as db_api
from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.xenapi import lib
from cinder.volume.drivers.xenapi import sm as driver
from cinder.volume.drivers.xenapi import tools


class MockContext(object):
    def __init__(ctxt, auth_token):
        ctxt.auth_token = auth_token


@contextlib.contextmanager
def simple_context(value):
    yield value


def get_configured_driver(server='ignore_server', path='ignore_path'):
    configuration = mox.MockObject(conf.Configuration)
    configuration.xenapi_nfs_server = server
    configuration.xenapi_nfs_serverpath = path
    configuration.append_config_values(mox.IgnoreArg())
    configuration.volume_dd_blocksize = '1M'
    return driver.XenAPINFSDriver(configuration=configuration)


class DriverTestCase(test.TestCase):

    def assert_flag(self, flagname):
        self.assertTrue(hasattr(driver.CONF, flagname))

    def test_config_options(self):
        self.assert_flag('xenapi_connection_url')
        self.assert_flag('xenapi_connection_username')
        self.assert_flag('xenapi_connection_password')
        self.assert_flag('xenapi_nfs_server')
        self.assert_flag('xenapi_nfs_serverpath')
        self.assert_flag('xenapi_sr_base_path')

    def test_do_setup(self):
        mock = mox.Mox()
        mock.StubOutWithMock(driver, 'xenapi_lib')
        mock.StubOutWithMock(driver, 'xenapi_opts')

        configuration = mox.MockObject(conf.Configuration)
        configuration.xenapi_connection_url = 'url'
        configuration.xenapi_connection_username = 'user'
        configuration.xenapi_connection_password = 'pass'
        configuration.append_config_values(mox.IgnoreArg())

        session_factory = object()
        nfsops = object()

        driver.xenapi_lib.SessionFactory('url', 'user', 'pass').AndReturn(
            session_factory)

        driver.xenapi_lib.NFSBasedVolumeOperations(
            session_factory).AndReturn(nfsops)

        drv = driver.XenAPINFSDriver(configuration=configuration)

        mock.ReplayAll()
        drv.do_setup('context')
        mock.VerifyAll()

        self.assertEqual(nfsops, drv.nfs_ops)

    def test_create_volume(self):
        mock = mox.Mox()

        ops = mock.CreateMock(lib.NFSBasedVolumeOperations)
        drv = get_configured_driver('server', 'path')
        drv.nfs_ops = ops

        volume_details = dict(
            sr_uuid='sr_uuid',
            vdi_uuid='vdi_uuid'
        )
        ops.create_volume(
            'server', 'path', 1, 'name', 'desc').AndReturn(volume_details)

        mock.ReplayAll()
        result = drv.create_volume(dict(
            size=1, display_name='name', display_description='desc'))
        mock.VerifyAll()

        self.assertEqual(dict(provider_location='sr_uuid/vdi_uuid'), result)

    def test_delete_volume(self):
        mock = mox.Mox()

        ops = mock.CreateMock(lib.NFSBasedVolumeOperations)
        drv = get_configured_driver('server', 'path')
        drv.nfs_ops = ops

        ops.delete_volume('server', 'path', 'sr_uuid', 'vdi_uuid')

        mock.ReplayAll()
        result = drv.delete_volume(dict(
            provider_location='sr_uuid/vdi_uuid'))
        mock.VerifyAll()

    def test_create_export_does_not_raise_exception(self):
        configuration = conf.Configuration([])
        drv = driver.XenAPINFSDriver(configuration=configuration)
        drv.create_export('context', 'volume')

    def test_remove_export_does_not_raise_exception(self):
        configuration = conf.Configuration([])
        drv = driver.XenAPINFSDriver(configuration=configuration)
        drv.remove_export('context', 'volume')

    def test_initialize_connection(self):
        mock = mox.Mox()

        drv = get_configured_driver('server', 'path')

        mock.ReplayAll()
        result = drv.initialize_connection(
            dict(
                display_name='name',
                display_description='desc',
                provider_location='sr_uuid/vdi_uuid'),
            'connector'
        )
        mock.VerifyAll()

        self.assertEqual(
            dict(
                driver_volume_type='xensm',
                data=dict(
                    name_label='name',
                    name_description='desc',
                    sr_uuid='sr_uuid',
                    vdi_uuid='vdi_uuid',
                    sr_type='nfs',
                    server='server',
                    serverpath='path',
                    introduce_sr_keys=['sr_type', 'server', 'serverpath']
                )
            ),
            result
        )

    def test_initialize_connection_null_values(self):
        mock = mox.Mox()

        drv = get_configured_driver('server', 'path')

        mock.ReplayAll()
        result = drv.initialize_connection(
            dict(
                display_name=None,
                display_description=None,
                provider_location='sr_uuid/vdi_uuid'),
            'connector'
        )
        mock.VerifyAll()

        self.assertEqual(
            dict(
                driver_volume_type='xensm',
                data=dict(
                    name_label='',
                    name_description='',
                    sr_uuid='sr_uuid',
                    vdi_uuid='vdi_uuid',
                    sr_type='nfs',
                    server='server',
                    serverpath='path',
                    introduce_sr_keys=['sr_type', 'server', 'serverpath']
                )
            ),
            result
        )

    def _setup_mock_driver(self, server, serverpath, sr_base_path="_srbp"):
        mock = mox.Mox()

        drv = get_configured_driver(server, serverpath)
        ops = mock.CreateMock(lib.NFSBasedVolumeOperations)
        db = mock.CreateMock(db_api)
        drv.nfs_ops = ops
        drv.db = db

        mock.StubOutWithMock(driver, 'CONF')
        driver.CONF.xenapi_nfs_server = server
        driver.CONF.xenapi_nfs_serverpath = serverpath
        driver.CONF.xenapi_sr_base_path = sr_base_path

        return mock, drv

    def test_create_snapshot(self):
        mock, drv = self._setup_mock_driver('server', 'serverpath')

        snapshot = dict(
            volume_id="volume-id",
            display_name="snapshot-name",
            display_description="snapshot-desc",
            volume=dict(provider_location="sr-uuid/vdi-uuid"))

        drv.nfs_ops.copy_volume(
            "server", "serverpath", "sr-uuid", "vdi-uuid",
            "snapshot-name", "snapshot-desc"
        ).AndReturn(dict(sr_uuid="copied-sr", vdi_uuid="copied-vdi"))

        mock.ReplayAll()
        result = drv.create_snapshot(snapshot)
        mock.VerifyAll()
        self.assertEqual(
            dict(provider_location="copied-sr/copied-vdi"),
            result)

    def test_create_volume_from_snapshot(self):
        mock, drv = self._setup_mock_driver('server', 'serverpath')

        snapshot = dict(
            provider_location='src-sr-uuid/src-vdi-uuid')
        volume = dict(
            display_name='tgt-name', name_description='tgt-desc')

        drv.nfs_ops.copy_volume(
            "server", "serverpath", "src-sr-uuid", "src-vdi-uuid",
            "tgt-name", "tgt-desc"
        ).AndReturn(dict(sr_uuid="copied-sr", vdi_uuid="copied-vdi"))

        mock.ReplayAll()
        result = drv.create_volume_from_snapshot(volume, snapshot)
        mock.VerifyAll()

        self.assertEqual(
            dict(provider_location='copied-sr/copied-vdi'), result)

    def test_delete_snapshot(self):
        mock, drv = self._setup_mock_driver('server', 'serverpath')

        snapshot = dict(
            provider_location='src-sr-uuid/src-vdi-uuid')

        drv.nfs_ops.delete_volume(
            "server", "serverpath", "src-sr-uuid", "src-vdi-uuid")

        mock.ReplayAll()
        drv.delete_snapshot(snapshot)
        mock.VerifyAll()

    def test_copy_volume_to_image_xenserver_case(self):
        mock, drv = self._setup_mock_driver(
            'server', 'serverpath', '/var/run/sr-mount')

        mock.StubOutWithMock(drv, '_use_glance_plugin_to_upload_volume')
        mock.StubOutWithMock(driver.image_utils, 'is_xenserver_format')
        context = MockContext('token')

        driver.image_utils.is_xenserver_format('image_meta').AndReturn(True)

        drv._use_glance_plugin_to_upload_volume(
            context, 'volume', 'image_service', 'image_meta').AndReturn(
                'result')
        mock.ReplayAll()

        result = drv.copy_volume_to_image(
            context, "volume", "image_service", "image_meta")
        self.assertEqual('result', result)

        mock.VerifyAll()

    def test_copy_volume_to_image_non_xenserver_case(self):
        mock, drv = self._setup_mock_driver(
            'server', 'serverpath', '/var/run/sr-mount')

        mock.StubOutWithMock(drv, '_use_image_utils_to_upload_volume')
        mock.StubOutWithMock(driver.image_utils, 'is_xenserver_format')
        context = MockContext('token')

        driver.image_utils.is_xenserver_format('image_meta').AndReturn(False)

        drv._use_image_utils_to_upload_volume(
            context, 'volume', 'image_service', 'image_meta').AndReturn(
                'result')
        mock.ReplayAll()

        result = drv.copy_volume_to_image(
            context, "volume", "image_service", "image_meta")
        self.assertEqual('result', result)

        mock.VerifyAll()

    def test_use_image_utils_to_upload_volume(self):
        mock, drv = self._setup_mock_driver(
            'server', 'serverpath', '/var/run/sr-mount')

        volume = dict(provider_location='sr-uuid/vdi-uuid')
        context = MockContext('token')

        mock.StubOutWithMock(driver.image_utils, 'upload_volume')

        drv.nfs_ops.volume_attached_here(
            'server', 'serverpath', 'sr-uuid', 'vdi-uuid', True).AndReturn(
                simple_context('device'))

        driver.image_utils.upload_volume(
            context, 'image_service', 'image_meta', 'device')

        mock.ReplayAll()
        drv._use_image_utils_to_upload_volume(
            context, volume, "image_service", "image_meta")
        mock.VerifyAll()

    def test_use_glance_plugin_to_upload_volume(self):
        mock, drv = self._setup_mock_driver(
            'server', 'serverpath', '/var/run/sr-mount')

        volume = dict(provider_location='sr-uuid/vdi-uuid')
        context = MockContext('token')

        mock.StubOutWithMock(driver.glance, 'get_api_servers')

        driver.glance.get_api_servers().AndReturn((x for x in ['glancesrv']))

        drv.nfs_ops.use_glance_plugin_to_upload_volume(
            'server', 'serverpath', 'sr-uuid', 'vdi-uuid', 'glancesrv',
            'image-id', 'token', '/var/run/sr-mount')

        mock.ReplayAll()
        drv._use_glance_plugin_to_upload_volume(
            context, volume, "image_service", {"id": "image-id"})
        mock.VerifyAll()

    def test_copy_image_to_volume_xenserver_case(self):
        mock, drv = self._setup_mock_driver(
            'server', 'serverpath', '/var/run/sr-mount')

        mock.StubOutWithMock(drv, '_use_glance_plugin_to_copy_image_to_volume')
        mock.StubOutWithMock(driver.image_utils, 'is_xenserver_image')
        context = MockContext('token')

        driver.image_utils.is_xenserver_image(
            context, 'image_service', 'image_id').AndReturn(True)
        drv._use_glance_plugin_to_copy_image_to_volume(
            context, 'volume', 'image_service', 'image_id').AndReturn('result')
        mock.ReplayAll()
        result = drv.copy_image_to_volume(
            context, "volume", "image_service", "image_id")
        self.assertEqual('result', result)
        mock.VerifyAll()

    def test_copy_image_to_volume_non_xenserver_case(self):
        mock, drv = self._setup_mock_driver(
            'server', 'serverpath', '/var/run/sr-mount')

        mock.StubOutWithMock(drv, '_use_image_utils_to_pipe_bytes_to_volume')
        mock.StubOutWithMock(driver.image_utils, 'is_xenserver_image')
        context = MockContext('token')

        driver.image_utils.is_xenserver_image(
            context, 'image_service', 'image_id').AndReturn(False)
        drv._use_image_utils_to_pipe_bytes_to_volume(
            context, 'volume', 'image_service', 'image_id').AndReturn(True)
        mock.ReplayAll()
        drv.copy_image_to_volume(
            context, "volume", "image_service", "image_id")
        mock.VerifyAll()

    def test_use_image_utils_to_pipe_bytes_to_volume(self):
        mock, drv = self._setup_mock_driver(
            'server', 'serverpath', '/var/run/sr-mount')

        volume = dict(provider_location='sr-uuid/vdi-uuid', size=1)
        context = MockContext('token')

        mock.StubOutWithMock(driver.image_utils, 'fetch_to_raw')

        drv.nfs_ops.volume_attached_here(
            'server', 'serverpath', 'sr-uuid', 'vdi-uuid', False).AndReturn(
                simple_context('device'))

        driver.image_utils.fetch_to_raw(
            context, 'image_service', 'image_id', 'device', mox.IgnoreArg(),
            size=1)

        mock.ReplayAll()
        drv._use_image_utils_to_pipe_bytes_to_volume(
            context, volume, "image_service", "image_id")
        mock.VerifyAll()

    def test_use_glance_plugin_to_copy_image_to_volume_success(self):
        mock, drv = self._setup_mock_driver(
            'server', 'serverpath', '/var/run/sr-mount')

        volume = dict(
            provider_location='sr-uuid/vdi-uuid',
            size=2)

        mock.StubOutWithMock(driver.glance, 'get_api_servers')

        driver.glance.get_api_servers().AndReturn((x for x in ['glancesrv']))

        drv.nfs_ops.use_glance_plugin_to_overwrite_volume(
            'server', 'serverpath', 'sr-uuid', 'vdi-uuid', 'glancesrv',
            'image_id', 'token', '/var/run/sr-mount').AndReturn(True)

        drv.nfs_ops.resize_volume(
            'server', 'serverpath', 'sr-uuid', 'vdi-uuid', 2)

        mock.ReplayAll()
        drv._use_glance_plugin_to_copy_image_to_volume(
            MockContext('token'), volume, "ignore", "image_id")
        mock.VerifyAll()

    def test_use_glance_plugin_to_copy_image_to_volume_fail(self):
        mock, drv = self._setup_mock_driver(
            'server', 'serverpath', '/var/run/sr-mount')

        volume = dict(
            provider_location='sr-uuid/vdi-uuid',
            size=2)

        mock.StubOutWithMock(driver.glance, 'get_api_servers')

        driver.glance.get_api_servers().AndReturn((x for x in ['glancesrv']))

        drv.nfs_ops.use_glance_plugin_to_overwrite_volume(
            'server', 'serverpath', 'sr-uuid', 'vdi-uuid', 'glancesrv',
            'image_id', 'token', '/var/run/sr-mount').AndReturn(False)

        mock.ReplayAll()

        self.assertRaises(
            exception.ImageCopyFailure,
            lambda: drv._use_glance_plugin_to_copy_image_to_volume(
                MockContext('token'), volume, "ignore", "image_id"))

        mock.VerifyAll()

    def test_get_volume_stats_reports_required_keys(self):
        drv = get_configured_driver()

        stats = drv.get_volume_stats()

        required_metrics = [
            'volume_backend_name', 'vendor_name', 'driver_version',
            'storage_protocol', 'total_capacity_gb', 'free_capacity_gb',
            'reserved_percentage'
        ]

        for metric in required_metrics:
            self.assertIn(metric, stats)

    def test_get_volume_stats_reports_unknown_cap(self):
        drv = get_configured_driver()

        stats = drv.get_volume_stats()

        self.assertEqual('unknown', stats['free_capacity_gb'])

    def test_reported_driver_type(self):
        drv = get_configured_driver()

        stats = drv.get_volume_stats()

        self.assertEqual('xensm', stats['storage_protocol'])


class ToolsTest(test.TestCase):
    @mock.patch('cinder.volume.drivers.xenapi.tools._stripped_first_line_of')
    def test_get_this_vm_uuid(self, mock_read_first_line):
        mock_read_first_line.return_value = 'someuuid'
        self.assertEqual('someuuid', tools.get_this_vm_uuid())
        mock_read_first_line.assert_called_once_with('/sys/hypervisor/uuid')

    def test_stripped_first_line_of(self):
        mock_context_manager = mock.Mock()
        mock_context_manager.__enter__ = mock.Mock(
            return_value=six.StringIO('  blah  \n second line \n'))
        mock_context_manager.__exit__ = mock.Mock(return_value=False)
        mock_open = mock.Mock(return_value=mock_context_manager)

        with mock.patch('__builtin__.open', mock_open):
            self.assertEqual(
                'blah', tools._stripped_first_line_of('/somefile'))

        mock_open.assert_called_once_with('/somefile', 'rb')
