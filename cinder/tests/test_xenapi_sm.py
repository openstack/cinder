# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from cinder.db import api as db_api
from cinder import exception
from cinder.volume.drivers.xenapi import lib
from cinder.volume.drivers.xenapi import sm as driver
import mox
import unittest


class MockContext(object):
    def __init__(ctxt, auth_token):
        ctxt.auth_token = auth_token


class DriverTestCase(unittest.TestCase):

    def assert_flag(self, flagname):
        self.assertTrue(hasattr(driver.FLAGS, flagname))

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
        mock.StubOutWithMock(driver, 'FLAGS')

        driver.FLAGS.xenapi_connection_url = 'url'
        driver.FLAGS.xenapi_connection_username = 'user'
        driver.FLAGS.xenapi_connection_password = 'pass'

        session_factory = object()
        nfsops = object()

        driver.xenapi_lib.SessionFactory('url', 'user', 'pass').AndReturn(
            session_factory)

        driver.xenapi_lib.NFSBasedVolumeOperations(
            session_factory).AndReturn(nfsops)

        drv = driver.XenAPINFSDriver()

        mock.ReplayAll()
        drv.do_setup('context')
        mock.VerifyAll()

        self.assertEquals(nfsops, drv.nfs_ops)

    def test_create_volume(self):
        mock = mox.Mox()

        mock.StubOutWithMock(driver, 'FLAGS')
        driver.FLAGS.xenapi_nfs_server = 'server'
        driver.FLAGS.xenapi_nfs_serverpath = 'path'

        ops = mock.CreateMock(lib.NFSBasedVolumeOperations)
        drv = driver.XenAPINFSDriver()
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

        self.assertEquals(dict(provider_location='sr_uuid/vdi_uuid'), result)

    def test_delete_volume(self):
        mock = mox.Mox()

        mock.StubOutWithMock(driver, 'FLAGS')
        driver.FLAGS.xenapi_nfs_server = 'server'
        driver.FLAGS.xenapi_nfs_serverpath = 'path'

        ops = mock.CreateMock(lib.NFSBasedVolumeOperations)
        drv = driver.XenAPINFSDriver()
        drv.nfs_ops = ops

        ops.delete_volume('server', 'path', 'sr_uuid', 'vdi_uuid')

        mock.ReplayAll()
        result = drv.delete_volume(dict(
            provider_location='sr_uuid/vdi_uuid'))
        mock.VerifyAll()

    def test_create_export_does_not_raise_exception(self):
        drv = driver.XenAPINFSDriver()
        drv.create_export('context', 'volume')

    def test_remove_export_does_not_raise_exception(self):
        drv = driver.XenAPINFSDriver()
        drv.remove_export('context', 'volume')

    def test_initialize_connection(self):
        mock = mox.Mox()

        mock.StubOutWithMock(driver, 'FLAGS')
        driver.FLAGS.xenapi_nfs_server = 'server'
        driver.FLAGS.xenapi_nfs_serverpath = 'path'

        drv = driver.XenAPINFSDriver()

        mock.ReplayAll()
        result = drv.initialize_connection(
            dict(
                display_name='name',
                display_description='desc',
                provider_location='sr_uuid/vdi_uuid'),
            'connector'
        )
        mock.VerifyAll()

        self.assertEquals(
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

        mock.StubOutWithMock(driver, 'FLAGS')
        driver.FLAGS.xenapi_nfs_server = 'server'
        driver.FLAGS.xenapi_nfs_serverpath = 'path'

        drv = driver.XenAPINFSDriver()

        mock.ReplayAll()
        result = drv.initialize_connection(
            dict(
                display_name=None,
                display_description=None,
                provider_location='sr_uuid/vdi_uuid'),
            'connector'
        )
        mock.VerifyAll()

        self.assertEquals(
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

        drv = driver.XenAPINFSDriver()
        ops = mock.CreateMock(lib.NFSBasedVolumeOperations)
        db = mock.CreateMock(db_api)
        drv.nfs_ops = ops
        drv.db = db

        mock.StubOutWithMock(driver, 'FLAGS')
        driver.FLAGS.xenapi_nfs_server = server
        driver.FLAGS.xenapi_nfs_serverpath = serverpath
        driver.FLAGS.xenapi_sr_base_path = sr_base_path

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
        self.assertEquals(
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

        self.assertEquals(
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

    def test_copy_image_to_volume_success(self):
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
        drv.copy_image_to_volume(
            MockContext('token'), volume, "ignore", "image_id")
        mock.VerifyAll()

    def test_copy_image_to_volume_fail(self):
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
            lambda: drv.copy_image_to_volume(
                MockContext('token'), volume, "ignore", "image_id"))

        mock.VerifyAll()
