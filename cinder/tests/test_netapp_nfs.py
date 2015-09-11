# Copyright (c) 2012 NetApp, Inc.
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
"""Unit tests for the NetApp-specific NFS driver module."""

import itertools
import os
import shutil
import unittest

from lxml import etree
import mock
import mox as mox_lib
from oslo_log import log as logging
import six

from cinder import exception
from cinder.i18n import _LW
from cinder.image import image_utils
from cinder import test
from cinder import utils as cinder_utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.netapp import common
from cinder.volume.drivers.netapp.dataontap.client import api
from cinder.volume.drivers.netapp.dataontap.client import client_7mode
from cinder.volume.drivers.netapp.dataontap.client import client_base
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp.dataontap import nfs_7mode \
    as netapp_nfs_7mode
from cinder.volume.drivers.netapp.dataontap import nfs_base
from cinder.volume.drivers.netapp.dataontap import nfs_cmode \
    as netapp_nfs_cmode
from cinder.volume.drivers.netapp.dataontap import ssc_cmode
from cinder.volume.drivers.netapp import utils


from oslo_config import cfg
CONF = cfg.CONF

LOG = logging.getLogger(__name__)


CONNECTION_INFO = {'hostname': 'fake_host',
                   'transport_type': 'https',
                   'port': 443,
                   'username': 'admin',
                   'password': 'passw0rd'}
SEVEN_MODE_CONNECTION_INFO = dict(
    itertools.chain(CONNECTION_INFO.items(),
                    {'vfiler': 'test_vfiler'}.items()))
FAKE_VSERVER = 'fake_vserver'


def create_configuration():
    configuration = mox_lib.MockObject(conf.Configuration)
    configuration.append_config_values(mox_lib.IgnoreArg())
    configuration.nfs_mount_point_base = '/mnt/test'
    configuration.nfs_mount_options = None
    configuration.nas_mount_options = None
    configuration.netapp_server_hostname = CONNECTION_INFO['hostname']
    configuration.netapp_transport_type = CONNECTION_INFO['transport_type']
    configuration.netapp_server_port = CONNECTION_INFO['port']
    configuration.netapp_login = CONNECTION_INFO['username']
    configuration.netapp_password = CONNECTION_INFO['password']
    configuration.netapp_vfiler = SEVEN_MODE_CONNECTION_INFO['vfiler']
    return configuration


class FakeVolume(object):
    def __init__(self, host='', size=0):
        self.size = size
        self.id = hash(self)
        self.name = None
        self.host = host

    def __getitem__(self, key):
        return self.__dict__[key]

    def __setitem__(self, key, val):
        self.__dict__[key] = val


class FakeSnapshot(object):
    def __init__(self, volume_size=0):
        self.volume_name = None
        self.name = None
        self.volume_id = None
        self.volume_size = volume_size
        self.user_id = None
        self.status = None

    def __getitem__(self, key):
        return self.__dict__[key]


class FakeResponse(object):
    def __init__(self, status):
        """Initialize FakeResponse.

        :param status: Either 'failed' or 'passed'
        """
        self.Status = status

        if status == 'failed':
            self.Reason = 'Sample error'


class NetAppCmodeNfsDriverTestCase(test.TestCase):
    """Test direct NetApp C Mode driver."""

    TEST_NFS_HOST = 'nfs-host1'
    TEST_NFS_SHARE_PATH = '/export'
    TEST_NFS_EXPORT1 = '%s:%s' % (TEST_NFS_HOST, TEST_NFS_SHARE_PATH)
    TEST_NFS_EXPORT2 = 'nfs-host2:/export'
    TEST_MNT_POINT = '/mnt/nfs'

    def setUp(self):
        super(NetAppCmodeNfsDriverTestCase, self).setUp()
        self._custom_setup()

    def _custom_setup(self):
        self.mock_object(utils, 'OpenStackInfo')
        kwargs = {}
        kwargs['netapp_mode'] = 'proxy'
        kwargs['configuration'] = create_configuration()
        self._driver = netapp_nfs_cmode.NetAppCmodeNfsDriver(**kwargs)
        self._driver.zapi_client = mock.Mock()

        config = self._driver.configuration
        config.netapp_vserver = FAKE_VSERVER

    def test_create_snapshot(self):
        """Test snapshot can be created and deleted."""
        mox = self.mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_clone_volume')
        drv._clone_volume(mox_lib.IgnoreArg(),
                          mox_lib.IgnoreArg(),
                          mox_lib.IgnoreArg())
        mox.ReplayAll()

        drv.create_snapshot(FakeSnapshot())

        mox.VerifyAll()

    def test_create_volume_from_snapshot(self):
        """Tests volume creation from snapshot."""
        drv = self._driver
        mox = self.mox
        location = '127.0.0.1:/nfs'
        host = 'hostname@backend#' + location
        volume = FakeVolume(host, 1)
        snapshot = FakeSnapshot(1)

        expected_result = {'provider_location': location}
        mox.StubOutWithMock(drv, '_clone_volume')
        mox.StubOutWithMock(drv, '_get_volume_location')
        mox.StubOutWithMock(drv, 'local_path')
        mox.StubOutWithMock(drv, '_discover_file_till_timeout')
        mox.StubOutWithMock(drv, '_set_rw_permissions')
        drv._clone_volume(mox_lib.IgnoreArg(),
                          mox_lib.IgnoreArg(),
                          mox_lib.IgnoreArg())
        drv._get_volume_location(mox_lib.IgnoreArg()).AndReturn(location)
        drv.local_path(mox_lib.IgnoreArg()).AndReturn('/mnt')
        drv._discover_file_till_timeout(mox_lib.IgnoreArg()).AndReturn(True)
        drv._set_rw_permissions(mox_lib.IgnoreArg())

        mox.ReplayAll()

        loc = drv.create_volume_from_snapshot(volume, snapshot)

        self.assertEqual(loc, expected_result)

        mox.VerifyAll()

    def _prepare_delete_snapshot_mock(self, snapshot_exists):
        drv = self._driver
        mox = self.mox

        mox.StubOutWithMock(drv, '_get_provider_location')
        mox.StubOutWithMock(drv, '_volume_not_present')
        mox.StubOutWithMock(drv, '_post_prov_deprov_in_ssc')

        if snapshot_exists:
            mox.StubOutWithMock(drv, '_execute')
            mox.StubOutWithMock(drv, '_get_volume_path')
        drv._get_provider_location(mox_lib.IgnoreArg())
        drv._get_provider_location(mox_lib.IgnoreArg())
        drv._volume_not_present(mox_lib.IgnoreArg(), mox_lib.IgnoreArg())\
            .AndReturn(not snapshot_exists)

        if snapshot_exists:
            drv._get_volume_path(mox_lib.IgnoreArg(), mox_lib.IgnoreArg())
            drv._execute('rm', None, run_as_root=True)

        drv._post_prov_deprov_in_ssc(mox_lib.IgnoreArg())

        mox.ReplayAll()

        return mox

    def test_delete_existing_snapshot(self):
        drv = self._driver
        mox = self._prepare_delete_snapshot_mock(True)

        drv.delete_snapshot(FakeSnapshot())

        mox.VerifyAll()

    def test_delete_missing_snapshot(self):
        drv = self._driver
        mox = self._prepare_delete_snapshot_mock(False)

        drv.delete_snapshot(FakeSnapshot())

        mox.VerifyAll()

    @mock.patch.object(nfs_base.NetAppNfsDriver, 'do_setup')
    @mock.patch.object(client_cmode.Client, '__init__', return_value=None)
    def test_do_setup(self, mock_client_init, mock_super_do_setup):
        context = mock.Mock()
        self._driver.do_setup(context)
        mock_client_init.assert_called_once_with(vserver=FAKE_VSERVER,
                                                 **CONNECTION_INFO)
        mock_super_do_setup.assert_called_once_with(context)

    @mock.patch.object(nfs_base.NetAppNfsDriver, 'check_for_setup_error')
    @mock.patch.object(ssc_cmode, 'check_ssc_api_permissions')
    def test_check_for_setup_error(self, mock_ssc_api_permission_check,
                                   mock_super_check_for_setup_error):
        self._driver.zapi_client = mock.Mock()
        self._driver.check_for_setup_error()
        mock_ssc_api_permission_check.assert_called_once_with(
            self._driver.zapi_client)
        mock_super_check_for_setup_error.assert_called_once_with()

    def _prepare_clone_mock(self, status):
        drv = self._driver
        mox = self.mox

        volume = FakeVolume()
        setattr(volume, 'provider_location', '127.0.0.1:/nfs')

        drv.zapi_client = mox.CreateMockAnything()
        mox.StubOutWithMock(drv, '_get_host_ip')
        mox.StubOutWithMock(drv, '_get_export_path')
        mox.StubOutWithMock(drv, '_post_prov_deprov_in_ssc')

        drv.zapi_client.get_if_info_by_ip('127.0.0.1').AndReturn(
            self._prepare_info_by_ip_response())
        drv.zapi_client.get_vol_by_junc_vserver('openstack', '/nfs').AndReturn(
            'nfsvol')
        drv.zapi_client.clone_file('nfsvol', 'volume_name', 'clone_name',
                                   'openstack')
        drv._get_host_ip(mox_lib.IgnoreArg()).AndReturn('127.0.0.1')
        drv._get_export_path(mox_lib.IgnoreArg()).AndReturn('/nfs')
        drv._post_prov_deprov_in_ssc(mox_lib.IgnoreArg())
        return mox

    def _prepare_info_by_ip_response(self):
        res = """<attributes-list>
        <net-interface-info>
        <address>127.0.0.1</address>
        <administrative-status>up</administrative-status>
        <current-node>fas3170rre-cmode-01</current-node>
        <current-port>e1b-1165</current-port>
        <data-protocols>
          <data-protocol>nfs</data-protocol>
        </data-protocols>
        <dns-domain-name>none</dns-domain-name>
        <failover-group/>
        <failover-policy>disabled</failover-policy>
        <firewall-policy>data</firewall-policy>
        <home-node>fas3170rre-cmode-01</home-node>
        <home-port>e1b-1165</home-port>
        <interface-name>nfs_data1</interface-name>
        <is-auto-revert>false</is-auto-revert>
        <is-home>true</is-home>
        <netmask>255.255.255.0</netmask>
        <netmask-length>24</netmask-length>
        <operational-status>up</operational-status>
        <role>data</role>
        <routing-group-name>c10.63.165.0/24</routing-group-name>
        <use-failover-group>disabled</use-failover-group>
        <vserver>openstack</vserver>
      </net-interface-info></attributes-list>"""
        response_el = etree.XML(res)
        return api.NaElement(response_el).get_children()

    def test_clone_volume(self):
        drv = self._driver
        mox = self._prepare_clone_mock('pass')

        mox.ReplayAll()

        volume_name = 'volume_name'
        clone_name = 'clone_name'
        volume_id = volume_name + six.text_type(hash(volume_name))
        share = 'ip:/share'

        drv._clone_volume(volume_name, clone_name, volume_id, share)

        mox.VerifyAll()

    def test_register_img_in_cache_noshare(self):
        volume = {'id': '1', 'name': 'testvol'}
        volume['provider_location'] = '10.61.170.1:/share/path'
        drv = self._driver
        mox = self.mox
        mox.StubOutWithMock(drv, '_do_clone_rel_img_cache')

        drv._do_clone_rel_img_cache('testvol', 'img-cache-12345',
                                    '10.61.170.1:/share/path',
                                    'img-cache-12345')

        mox.ReplayAll()
        drv._register_image_in_cache(volume, '12345')
        mox.VerifyAll()

    def test_register_img_in_cache_with_share(self):
        volume = {'id': '1', 'name': 'testvol'}
        volume['provider_location'] = '10.61.170.1:/share/path'
        drv = self._driver
        mox = self.mox
        mox.StubOutWithMock(drv, '_do_clone_rel_img_cache')

        drv._do_clone_rel_img_cache('testvol', 'img-cache-12345',
                                    '10.61.170.1:/share/path',
                                    'img-cache-12345')

        mox.ReplayAll()
        drv._register_image_in_cache(volume, '12345')
        mox.VerifyAll()

    def test_find_image_in_cache_no_shares(self):
        drv = self._driver
        drv._mounted_shares = []
        result = drv._find_image_in_cache('image_id')
        if not result:
            pass
        else:
            self.fail('Return result is unexpected')

    def test_find_image_in_cache_shares(self):
        drv = self._driver
        mox = self.mox
        drv._mounted_shares = ['testshare']
        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        mox.StubOutWithMock(os.path, 'exists')

        drv._get_mount_point_for_share('testshare').AndReturn('/mnt')
        os.path.exists('/mnt/img-cache-id').AndReturn(True)
        mox.ReplayAll()
        result = drv._find_image_in_cache('id')
        (share, file_name) = result[0]
        mox.VerifyAll()
        drv._mounted_shares.remove('testshare')

        if (share == 'testshare' and file_name == 'img-cache-id'):
            pass
        else:
            LOG.warning(_LW("Share %(share)s and file name %(file_name)s")
                        % {'share': share, 'file_name': file_name})
            self.fail('Return result is unexpected')

    def test_find_old_cache_files_notexists(self):
        drv = self._driver
        mox = self.mox
        cmd = ['find', '/mnt', '-maxdepth', '1', '-name',
               'img-cache*', '-amin', '+720']
        setattr(drv.configuration, 'expiry_thres_minutes', 720)
        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        mox.StubOutWithMock(drv, '_execute')

        drv._get_mount_point_for_share(mox_lib.IgnoreArg()).AndReturn('/mnt')
        drv._execute(*cmd, run_as_root=True).AndReturn((None, ''))
        mox.ReplayAll()
        res = drv._find_old_cache_files('share')
        mox.VerifyAll()
        if len(res) == 0:
            pass
        else:
            self.fail('No files expected but got return values.')

    def test_find_old_cache_files_exists(self):
        drv = self._driver
        mox = self.mox
        cmd = ['find', '/mnt', '-maxdepth', '1', '-name',
               'img-cache*', '-amin', '+720']
        setattr(drv.configuration, 'expiry_thres_minutes', '720')
        files = '/mnt/img-id1\n/mnt/img-id2\n'
        r_files = ['img-id1', 'img-id2']
        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, '_shortlist_del_eligible_files')

        drv._get_mount_point_for_share('share').AndReturn('/mnt')
        drv._execute(*cmd, run_as_root=True).AndReturn((files, None))
        drv._shortlist_del_eligible_files(
            mox_lib.IgnoreArg(), r_files).AndReturn(r_files)
        mox.ReplayAll()
        res = drv._find_old_cache_files('share')
        mox.VerifyAll()
        if len(res) == len(r_files):
            for f in res:
                r_files.remove(f)
        else:
            self.fail('Returned files not same as expected.')

    def test_delete_files_till_bytes_free_success(self):
        drv = self._driver
        mox = self.mox
        files = [('img-cache-1', 230), ('img-cache-2', 380)]
        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        mox.StubOutWithMock(drv, '_delete_file')

        drv._get_mount_point_for_share(mox_lib.IgnoreArg()).AndReturn('/mnt')
        drv._delete_file('/mnt/img-cache-2').AndReturn(True)
        drv._delete_file('/mnt/img-cache-1').AndReturn(True)
        mox.ReplayAll()
        drv._delete_files_till_bytes_free(files, 'share', bytes_to_free=1024)
        mox.VerifyAll()

    def test_clean_image_cache_exec(self):
        drv = self._driver
        mox = self.mox
        drv.configuration.thres_avl_size_perc_start = 20
        drv.configuration.thres_avl_size_perc_stop = 50
        drv._mounted_shares = ['testshare']

        mox.StubOutWithMock(drv, '_find_old_cache_files')
        mox.StubOutWithMock(drv, '_delete_files_till_bytes_free')
        mox.StubOutWithMock(drv, '_get_capacity_info')

        drv._get_capacity_info('testshare').AndReturn((100, 19))
        drv._find_old_cache_files('testshare').AndReturn(['f1', 'f2'])
        drv._delete_files_till_bytes_free(
            ['f1', 'f2'], 'testshare', bytes_to_free=31)
        mox.ReplayAll()
        drv._clean_image_cache()
        mox.VerifyAll()
        drv._mounted_shares.remove('testshare')
        if not drv.cleaning:
            pass
        else:
            self.fail('Clean image cache failed.')

    def test_clean_image_cache_noexec(self):
        drv = self._driver
        mox = self.mox
        drv.configuration.thres_avl_size_perc_start = 20
        drv.configuration.thres_avl_size_perc_stop = 50
        drv._mounted_shares = ['testshare']

        mox.StubOutWithMock(drv, '_get_capacity_info')

        drv._get_capacity_info('testshare').AndReturn((100, 30, 70))
        mox.ReplayAll()
        drv._clean_image_cache()
        mox.VerifyAll()
        drv._mounted_shares.remove('testshare')
        if not drv.cleaning:
            pass
        else:
            self.fail('Clean image cache failed.')

    def test_clone_image_fromcache(self):
        drv = self._driver
        mox = self.mox
        volume = {'name': 'vol', 'size': '20'}
        mox.StubOutWithMock(drv, '_find_image_in_cache')
        mox.StubOutWithMock(drv, '_do_clone_rel_img_cache')
        mox.StubOutWithMock(drv, '_post_clone_image')
        mox.StubOutWithMock(drv, '_is_share_vol_compatible')

        drv._find_image_in_cache(mox_lib.IgnoreArg()).AndReturn(
            [('share', 'file_name')])
        drv._is_share_vol_compatible(mox_lib.IgnoreArg(),
                                     mox_lib.IgnoreArg()).AndReturn(True)
        drv._do_clone_rel_img_cache('file_name', 'vol', 'share', 'file_name')
        drv._post_clone_image(volume)

        mox.ReplayAll()
        drv.clone_image('',
                        volume,
                        ('image_location', None),
                        {'id': 'image_id'}, '')
        mox.VerifyAll()

    def get_img_info(self, format):
        class img_info(object):
            def __init__(self, fmt):
                self.file_format = fmt

        return img_info(format)

    def test_clone_image_cloneableshare_nospace(self):
        drv = self._driver
        mox = self.mox
        volume = {'name': 'vol', 'size': '20'}
        mox.StubOutWithMock(drv, '_find_image_in_cache')
        mox.StubOutWithMock(drv, '_is_cloneable_share')
        mox.StubOutWithMock(drv, '_is_share_vol_compatible')

        drv._find_image_in_cache(mox_lib.IgnoreArg()).AndReturn([])
        drv._is_cloneable_share(
            mox_lib.IgnoreArg()).AndReturn('127.0.0.1:/share')
        drv._is_share_vol_compatible(mox_lib.IgnoreArg(),
                                     mox_lib.IgnoreArg()).AndReturn(False)

        mox.ReplayAll()
        (prop, cloned) = drv.clone_image(
            '',
            volume,
            ('nfs://127.0.0.1:/share/img-id', None),
            {'id': 'image_id'},
            '')
        mox.VerifyAll()
        if not cloned and not prop['provider_location']:
            pass
        else:
            self.fail('Expected not cloned, got cloned.')

    def test_clone_image_cloneableshare_raw(self):
        drv = self._driver
        mox = self.mox
        volume = {'name': 'vol', 'size': '20'}
        mox.StubOutWithMock(drv, '_find_image_in_cache')
        mox.StubOutWithMock(drv, '_is_cloneable_share')
        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        mox.StubOutWithMock(drv, '_clone_volume')
        mox.StubOutWithMock(drv, '_discover_file_till_timeout')
        mox.StubOutWithMock(drv, '_set_rw_permissions')
        mox.StubOutWithMock(drv, '_resize_image_file')
        mox.StubOutWithMock(drv, '_is_share_vol_compatible')

        drv._find_image_in_cache(mox_lib.IgnoreArg()).AndReturn([])
        drv._is_cloneable_share(
            mox_lib.IgnoreArg()).AndReturn('127.0.0.1:/share')
        drv._is_share_vol_compatible(mox_lib.IgnoreArg(),
                                     mox_lib.IgnoreArg()).AndReturn(True)
        drv._get_mount_point_for_share(mox_lib.IgnoreArg()).AndReturn('/mnt')
        image_utils.qemu_img_info('/mnt/img-id', run_as_root=True).\
            AndReturn(self.get_img_info('raw'))
        drv._clone_volume(
            'img-id', 'vol', share='127.0.0.1:/share', volume_id=None)
        drv._get_mount_point_for_share(mox_lib.IgnoreArg()).AndReturn('/mnt')
        drv._discover_file_till_timeout(mox_lib.IgnoreArg()).AndReturn(True)
        drv._set_rw_permissions('/mnt/vol')
        drv._resize_image_file({'name': 'vol'}, mox_lib.IgnoreArg())

        mox.ReplayAll()
        drv.clone_image(
            '',
            volume,
            ('nfs://127.0.0.1:/share/img-id', None),
            {'id': 'image_id'},
            '')
        mox.VerifyAll()

    def test_clone_image_cloneableshare_notraw(self):
        drv = self._driver
        mox = self.mox
        volume = {'name': 'vol', 'size': '20'}
        mox.StubOutWithMock(drv, '_find_image_in_cache')
        mox.StubOutWithMock(drv, '_is_cloneable_share')
        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        mox.StubOutWithMock(drv, '_clone_volume')
        mox.StubOutWithMock(drv, '_discover_file_till_timeout')
        mox.StubOutWithMock(drv, '_set_rw_permissions')
        mox.StubOutWithMock(drv, '_resize_image_file')
        mox.StubOutWithMock(image_utils, 'convert_image')
        mox.StubOutWithMock(drv, '_register_image_in_cache')
        mox.StubOutWithMock(drv, '_is_share_vol_compatible')

        drv._find_image_in_cache(mox_lib.IgnoreArg()).AndReturn([])
        drv._is_cloneable_share('nfs://127.0.0.1/share/img-id').AndReturn(
            '127.0.0.1:/share')
        drv._is_share_vol_compatible(mox_lib.IgnoreArg(),
                                     mox_lib.IgnoreArg()).AndReturn(True)
        drv._get_mount_point_for_share('127.0.0.1:/share').AndReturn('/mnt')
        image_utils.qemu_img_info('/mnt/img-id', run_as_root=True).\
            AndReturn(self.get_img_info('notraw'))
        image_utils.convert_image(mox_lib.IgnoreArg(),
                                  mox_lib.IgnoreArg(),
                                  'raw', run_as_root=True)
        image_utils.qemu_img_info('/mnt/vol', run_as_root=True).\
            AndReturn(self.get_img_info('raw'))
        drv._register_image_in_cache(mox_lib.IgnoreArg(), mox_lib.IgnoreArg())
        drv._get_mount_point_for_share('127.0.0.1:/share').AndReturn('/mnt')
        drv._discover_file_till_timeout(mox_lib.IgnoreArg()).AndReturn(True)
        drv._set_rw_permissions('/mnt/vol')
        drv._resize_image_file({'name': 'vol'}, mox_lib.IgnoreArg())

        mox.ReplayAll()
        drv.clone_image(
            '',
            volume,
            ('nfs://127.0.0.1/share/img-id', None),
            {'id': 'image_id'},
            '')
        mox.VerifyAll()

    def test_clone_image_file_not_discovered(self):
        drv = self._driver
        mox = self.mox
        volume = {'name': 'vol', 'size': '20'}
        mox.StubOutWithMock(drv, '_find_image_in_cache')
        mox.StubOutWithMock(drv, '_is_cloneable_share')
        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        mox.StubOutWithMock(drv, '_clone_volume')
        mox.StubOutWithMock(drv, '_discover_file_till_timeout')
        mox.StubOutWithMock(image_utils, 'convert_image')
        mox.StubOutWithMock(drv, '_register_image_in_cache')
        mox.StubOutWithMock(drv, '_is_share_vol_compatible')
        mox.StubOutWithMock(drv, 'local_path')
        mox.StubOutWithMock(os.path, 'exists')
        mox.StubOutWithMock(drv, '_delete_file')

        drv._find_image_in_cache(mox_lib.IgnoreArg()).AndReturn([])
        drv._is_cloneable_share('nfs://127.0.0.1/share/img-id').AndReturn(
            '127.0.0.1:/share')
        drv._is_share_vol_compatible(mox_lib.IgnoreArg(),
                                     mox_lib.IgnoreArg()).AndReturn(True)
        drv._get_mount_point_for_share('127.0.0.1:/share').AndReturn('/mnt')
        image_utils.qemu_img_info('/mnt/img-id', run_as_root=True).\
            AndReturn(self.get_img_info('notraw'))
        image_utils.convert_image(mox_lib.IgnoreArg(),
                                  mox_lib.IgnoreArg(),
                                  'raw', run_as_root=True)
        image_utils.qemu_img_info('/mnt/vol', run_as_root=True).\
            AndReturn(self.get_img_info('raw'))
        drv._register_image_in_cache(mox_lib.IgnoreArg(),
                                     mox_lib.IgnoreArg())
        drv.local_path(mox_lib.IgnoreArg()).AndReturn('/mnt/vol')
        drv._discover_file_till_timeout(mox_lib.IgnoreArg()).AndReturn(False)
        drv.local_path(mox_lib.IgnoreArg()).AndReturn('/mnt/vol')
        os.path.exists('/mnt/vol').AndReturn(True)
        drv._delete_file('/mnt/vol')

        mox.ReplayAll()
        vol_dict, result = drv.clone_image(
            '',
            volume,
            ('nfs://127.0.0.1/share/img-id', None),
            {'id': 'image_id'},
            '')
        mox.VerifyAll()
        self.assertFalse(result)
        self.assertFalse(vol_dict['bootable'])
        self.assertIsNone(vol_dict['provider_location'])

    def test_clone_image_resizefails(self):
        drv = self._driver
        mox = self.mox
        volume = {'name': 'vol', 'size': '20'}
        mox.StubOutWithMock(drv, '_find_image_in_cache')
        mox.StubOutWithMock(drv, '_is_cloneable_share')
        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        mox.StubOutWithMock(drv, '_clone_volume')
        mox.StubOutWithMock(drv, '_discover_file_till_timeout')
        mox.StubOutWithMock(drv, '_set_rw_permissions')
        mox.StubOutWithMock(drv, '_resize_image_file')
        mox.StubOutWithMock(image_utils, 'convert_image')
        mox.StubOutWithMock(drv, '_register_image_in_cache')
        mox.StubOutWithMock(drv, '_is_share_vol_compatible')
        mox.StubOutWithMock(drv, 'local_path')
        mox.StubOutWithMock(os.path, 'exists')
        mox.StubOutWithMock(drv, '_delete_file')

        drv._find_image_in_cache(mox_lib.IgnoreArg()).AndReturn([])
        drv._is_cloneable_share('nfs://127.0.0.1/share/img-id').AndReturn(
            '127.0.0.1:/share')
        drv._is_share_vol_compatible(mox_lib.IgnoreArg(),
                                     mox_lib.IgnoreArg()).AndReturn(True)
        drv._get_mount_point_for_share('127.0.0.1:/share').AndReturn('/mnt')
        image_utils.qemu_img_info('/mnt/img-id', run_as_root=True).\
            AndReturn(self.get_img_info('notraw'))
        image_utils.convert_image(mox_lib.IgnoreArg(),
                                  mox_lib.IgnoreArg(), 'raw',
                                  run_as_root=True)
        image_utils.qemu_img_info('/mnt/vol', run_as_root=True).\
            AndReturn(self.get_img_info('raw'))
        drv._register_image_in_cache(mox_lib.IgnoreArg(),
                                     mox_lib.IgnoreArg())
        drv.local_path(mox_lib.IgnoreArg()).AndReturn('/mnt/vol')
        drv._discover_file_till_timeout(mox_lib.IgnoreArg()).AndReturn(True)
        drv._set_rw_permissions('/mnt/vol')
        drv._resize_image_file(
            mox_lib.IgnoreArg(),
            mox_lib.IgnoreArg()).AndRaise(exception.InvalidResults())
        drv.local_path(mox_lib.IgnoreArg()).AndReturn('/mnt/vol')
        os.path.exists('/mnt/vol').AndReturn(True)
        drv._delete_file('/mnt/vol')

        mox.ReplayAll()
        vol_dict, result = drv.clone_image(
            '',
            volume,
            ('nfs://127.0.0.1/share/img-id', None),
            {'id': 'image_id'},
            '')
        mox.VerifyAll()
        self.assertFalse(result)
        self.assertFalse(vol_dict['bootable'])
        self.assertIsNone(vol_dict['provider_location'])

    def test_is_cloneable_share_badformats(self):
        drv = self._driver
        strgs = ['10.61.666.22:/share/img',
                 'nfs://10.61.666.22:/share/img',
                 'nfs://10.61.666.22//share/img',
                 'nfs://com.netapp.com:/share/img',
                 'nfs://com.netapp.com//share/img',
                 'com.netapp.com://share/im\g',
                 'http://com.netapp.com://share/img',
                 'nfs://com.netapp.com:/share/img',
                 'nfs://com.netapp.com:8080//share/img'
                 'nfs://com.netapp.com//img',
                 'nfs://[ae::sr::ty::po]/img']
        for strg in strgs:
            res = drv._is_cloneable_share(strg)
            if res:
                msg = 'Invalid format matched for url %s.' % strg
                self.fail(msg)

    def test_is_cloneable_share_goodformat1(self):
        drv = self._driver
        mox = self.mox
        strg = 'nfs://10.61.222.333/share/img'
        mox.StubOutWithMock(drv, '_check_share_in_use')
        drv._check_share_in_use(mox_lib.IgnoreArg(),
                                mox_lib.IgnoreArg()).AndReturn('share')
        mox.ReplayAll()
        drv._is_cloneable_share(strg)
        mox.VerifyAll()

    def test_is_cloneable_share_goodformat2(self):
        drv = self._driver
        mox = self.mox
        strg = 'nfs://10.61.222.333:8080/share/img'
        mox.StubOutWithMock(drv, '_check_share_in_use')
        drv._check_share_in_use(mox_lib.IgnoreArg(),
                                mox_lib.IgnoreArg()).AndReturn('share')
        mox.ReplayAll()
        drv._is_cloneable_share(strg)
        mox.VerifyAll()

    def test_is_cloneable_share_goodformat3(self):
        drv = self._driver
        mox = self.mox
        strg = 'nfs://com.netapp:8080/share/img'
        mox.StubOutWithMock(drv, '_check_share_in_use')
        drv._check_share_in_use(mox_lib.IgnoreArg(),
                                mox_lib.IgnoreArg()).AndReturn('share')
        mox.ReplayAll()
        drv._is_cloneable_share(strg)
        mox.VerifyAll()

    def test_is_cloneable_share_goodformat4(self):
        drv = self._driver
        mox = self.mox
        strg = 'nfs://netapp.com/share/img'
        mox.StubOutWithMock(drv, '_check_share_in_use')
        drv._check_share_in_use(mox_lib.IgnoreArg(),
                                mox_lib.IgnoreArg()).AndReturn('share')
        mox.ReplayAll()
        drv._is_cloneable_share(strg)
        mox.VerifyAll()

    def test_is_cloneable_share_goodformat5(self):
        drv = self._driver
        mox = self.mox
        strg = 'nfs://netapp.com/img'
        mox.StubOutWithMock(drv, '_check_share_in_use')
        drv._check_share_in_use(mox_lib.IgnoreArg(),
                                mox_lib.IgnoreArg()).AndReturn('share')
        mox.ReplayAll()
        drv._is_cloneable_share(strg)
        mox.VerifyAll()

    def test_check_share_in_use_no_conn(self):
        drv = self._driver
        share = drv._check_share_in_use(None, '/dir')
        if share:
            self.fail('Unexpected share detected.')

    def test_check_share_in_use_invalid_conn(self):
        drv = self._driver
        share = drv._check_share_in_use(':8989', '/dir')
        if share:
            self.fail('Unexpected share detected.')

    def test_check_share_in_use_incorrect_host(self):
        drv = self._driver
        mox = self.mox
        mox.StubOutWithMock(utils, 'resolve_hostname')
        utils.resolve_hostname(mox_lib.IgnoreArg()).AndRaise(Exception())
        mox.ReplayAll()
        share = drv._check_share_in_use('incorrect:8989', '/dir')
        mox.VerifyAll()
        if share:
            self.fail('Unexpected share detected.')

    def test_check_share_in_use_success(self):
        drv = self._driver
        mox = self.mox
        drv._mounted_shares = ['127.0.0.1:/dir/share']
        mox.StubOutWithMock(utils, 'resolve_hostname')
        mox.StubOutWithMock(drv, '_share_match_for_ip')
        utils.resolve_hostname(mox_lib.IgnoreArg()).AndReturn('10.22.33.44')
        drv._share_match_for_ip(
            '10.22.33.44', ['127.0.0.1:/dir/share']).AndReturn('share')
        mox.ReplayAll()
        share = drv._check_share_in_use('127.0.0.1:8989', '/dir/share')
        mox.VerifyAll()
        if not share:
            self.fail('Expected share not detected')

    def test_construct_image_url_loc(self):
        drv = self._driver
        img_loc = (None,
                   # Valid metdata
                   [{'metadata':
                     {'share_location': 'nfs://host/path',
                      'mountpoint': '/opt/stack/data/glance',
                      'id': 'abc-123',
                      'type': 'nfs'},
                     'url': 'file:///opt/stack/data/glance/image-id-0'},
                    # missing metadata
                    {'metadata': {},
                     'url': 'file:///opt/stack/data/glance/image-id-1'},
                    # missing location_type
                    {'metadata': {'location_type': None},
                     'url': 'file:///opt/stack/data/glance/image-id-2'},
                    # non-nfs location_type
                    {'metadata': {'location_type': 'not-NFS'},
                     'url': 'file:///opt/stack/data/glance/image-id-3'},
                    # missing share_location
                    {'metadata': {'location_type': 'nfs',
                                  'share_location': None},
                     'url': 'file:///opt/stack/data/glance/image-id-4'},
                    # missing mountpoint
                    {'metadata': {'location_type': 'nfs',
                                  'share_location': 'nfs://host/path',
                                  # Pre-kilo we documented "mount_point"
                                  'mount_point': '/opt/stack/data/glance'},
                     'url': 'file:///opt/stack/data/glance/image-id-5'},
                    # Valid metadata
                    {'metadata':
                     {'share_location': 'nfs://host/path',
                      'mountpoint': '/opt/stack/data/glance',
                      'id': 'abc-123',
                      'type': 'nfs'},
                     'url': 'file:///opt/stack/data/glance/image-id-6'}])

        locations = drv._construct_image_nfs_url(img_loc)

        self.assertIn("nfs://host/path/image-id-0", locations)
        self.assertIn("nfs://host/path/image-id-6", locations)
        self.assertEqual(2, len(locations))

    def test_construct_image_url_direct(self):
        drv = self._driver
        img_loc = ("nfs://host/path/image-id", None)

        locations = drv._construct_image_nfs_url(img_loc)

        self.assertIn("nfs://host/path/image-id", locations)

    def test_get_pool(self):
        pool = self._driver.get_pool({'provider_location': 'fake-share'})
        self.assertEqual(pool, 'fake-share')

    def _set_config(self, configuration):
        configuration.netapp_storage_family = 'ontap_cluster'
        configuration.netapp_storage_protocol = 'nfs'
        configuration.netapp_login = 'admin'
        configuration.netapp_password = 'pass'
        configuration.netapp_server_hostname = '127.0.0.1'
        configuration.netapp_transport_type = 'http'
        configuration.netapp_server_port = None
        configuration.netapp_vserver = 'openstack'
        configuration.nfs_shares_config = '/nfs'
        return configuration

    @mock.patch.object(utils, 'get_volume_extra_specs')
    def test_check_volume_type_mismatch(self, get_specs):
        if not hasattr(self._driver, 'vserver'):
            return unittest.skip("Test only applies to cmode driver")
        get_specs.return_value = {'thin_volume': 'true'}
        self._driver._is_share_vol_type_match = mock.Mock(return_value=False)
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self._driver._check_volume_type, 'vol',
                          'share', 'file')
        get_specs.assert_called_once_with('vol')
        self._driver._is_share_vol_type_match.assert_called_once_with(
            'vol', 'share', 'file')

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.Mock(return_value=(1, 20)))
    @mock.patch.object(nfs_base.NetAppNfsDriver, 'do_setup', mock.Mock())
    def test_do_setup_all_default(self):
        configuration = self._set_config(create_configuration())
        driver = common.NetAppDriver(configuration=configuration)
        driver.do_setup(context='')
        na_server = driver.zapi_client.get_connection()
        self.assertEqual('80', na_server.get_port())
        self.assertEqual('http', na_server.get_transport_type())

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.Mock(return_value=(1, 20)))
    @mock.patch.object(nfs_base.NetAppNfsDriver, 'do_setup', mock.Mock())
    def test_do_setup_http_default_port(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_transport_type = 'http'
        driver = common.NetAppDriver(configuration=configuration)
        driver.do_setup(context='')
        na_server = driver.zapi_client.get_connection()
        self.assertEqual('80', na_server.get_port())
        self.assertEqual('http', na_server.get_transport_type())

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.Mock(return_value=(1, 20)))
    @mock.patch.object(nfs_base.NetAppNfsDriver, 'do_setup', mock.Mock())
    def test_do_setup_https_default_port(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_transport_type = 'https'
        driver = common.NetAppDriver(configuration=configuration)
        driver.do_setup(context='')
        na_server = driver.zapi_client.get_connection()
        self.assertEqual('443', na_server.get_port())
        self.assertEqual('https', na_server.get_transport_type())

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.Mock(return_value=(1, 20)))
    @mock.patch.object(nfs_base.NetAppNfsDriver, 'do_setup', mock.Mock())
    def test_do_setup_http_non_default_port(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_server_port = 81
        driver = common.NetAppDriver(configuration=configuration)
        driver.do_setup(context='')
        na_server = driver.zapi_client.get_connection()
        self.assertEqual('81', na_server.get_port())
        self.assertEqual('http', na_server.get_transport_type())

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.Mock(return_value=(1, 20)))
    @mock.patch.object(nfs_base.NetAppNfsDriver, 'do_setup', mock.Mock())
    def test_do_setup_https_non_default_port(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_transport_type = 'https'
        configuration.netapp_server_port = 446
        driver = common.NetAppDriver(configuration=configuration)
        driver.do_setup(context='')
        na_server = driver.zapi_client.get_connection()
        self.assertEqual('446', na_server.get_port())
        self.assertEqual('https', na_server.get_transport_type())

    @mock.patch.object(utils, 'get_volume_extra_specs')
    def test_check_volume_type_qos(self, get_specs):
        get_specs.return_value = {'netapp:qos_policy_group': 'qos'}
        self._driver._get_vserver_and_exp_vol = mock.Mock(
            return_value=('vs', 'vol'))
        self._driver.zapi_client.file_assign_qos = mock.Mock(
            side_effect=api.NaApiError)
        self._driver._is_share_vol_type_match = mock.Mock(return_value=True)
        self.assertRaises(exception.NetAppDriverException,
                          self._driver._check_volume_type, 'vol',
                          'share', 'file')
        get_specs.assert_called_once_with('vol')
        self.assertEqual(1,
                         self._driver.zapi_client.file_assign_qos.call_count)
        self.assertEqual(1, self._driver._get_vserver_and_exp_vol.call_count)
        self._driver._is_share_vol_type_match.assert_called_once_with(
            'vol', 'share')

    @mock.patch.object(utils, 'resolve_hostname', return_value='10.12.142.11')
    def test_convert_vol_ref_share_name_to_share_ip(self, mock_hostname):
        drv = self._driver
        share = "%s/%s" % (self.TEST_NFS_EXPORT1, 'test_file_name')
        modified_share = '10.12.142.11:/export/test_file_name'

        modified_vol_ref = drv._convert_vol_ref_share_name_to_share_ip(share)

        self.assertEqual(modified_share, modified_vol_ref)

    @mock.patch.object(utils, 'resolve_hostname', return_value='10.12.142.11')
    @mock.patch.object(os.path, 'isfile', return_value=True)
    def test_get_share_mount_and_vol_from_vol_ref(self, mock_isfile,
                                                  mock_hostname):
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1]
        vol_path = "%s/%s" % (self.TEST_NFS_EXPORT1, 'test_file_name')
        vol_ref = {'source-name': vol_path}
        drv._ensure_shares_mounted = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)

        (share, mount, file_path) = \
            drv._get_share_mount_and_vol_from_vol_ref(vol_ref)

        self.assertEqual(self.TEST_NFS_EXPORT1, share)
        self.assertEqual(self.TEST_MNT_POINT, mount)
        self.assertEqual('test_file_name', file_path)

    @mock.patch.object(utils, 'resolve_hostname', return_value='10.12.142.11')
    def test_get_share_mount_and_vol_from_vol_ref_with_bad_ref(self,
                                                               mock_hostname):
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1]
        vol_ref = {'source-id': '1234546'}

        drv._ensure_shares_mounted = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)

        self.assertRaises(exception.ManageExistingInvalidReference,
                          drv._get_share_mount_and_vol_from_vol_ref, vol_ref)

    @mock.patch.object(utils, 'resolve_hostname', return_value='10.12.142.11')
    def test_get_share_mount_and_vol_from_vol_ref_where_not_found(self,
                                                                  mock_host):
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1]
        vol_path = "%s/%s" % (self.TEST_NFS_EXPORT2, 'test_file_name')
        vol_ref = {'source-name': vol_path}

        drv._ensure_shares_mounted = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)

        self.assertRaises(exception.ManageExistingInvalidReference,
                          drv._get_share_mount_and_vol_from_vol_ref, vol_ref)

    @mock.patch.object(utils, 'resolve_hostname', return_value='10.12.142.11')
    def test_get_share_mount_and_vol_from_vol_ref_where_is_dir(self,
                                                               mock_host):
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1]
        vol_ref = {'source-name': self.TEST_NFS_EXPORT2}

        drv._ensure_shares_mounted = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)

        self.assertRaises(exception.ManageExistingInvalidReference,
                          drv._get_share_mount_and_vol_from_vol_ref, vol_ref)

    @mock.patch.object(cinder_utils, 'get_file_size', return_value=1073741824)
    def test_manage_existing_get_size(self, get_file_size):
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1]
        test_file = 'test_file_name'
        volume = FakeVolume()
        volume['name'] = 'file-new-managed-123'
        volume['id'] = 'volume-new-managed-123'
        vol_path = "%s/%s" % (self.TEST_NFS_EXPORT1, test_file)
        vol_ref = {'source-name': vol_path}

        drv._ensure_shares_mounted = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)
        drv._get_share_mount_and_vol_from_vol_ref = mock.Mock(
            return_value=(self.TEST_NFS_EXPORT1, self.TEST_MNT_POINT,
                          test_file))

        vol_size = drv.manage_existing_get_size(volume, vol_ref)
        self.assertEqual(1, vol_size)

    @mock.patch.object(cinder_utils, 'get_file_size', return_value=1074253824)
    def test_manage_existing_get_size_round_up(self, get_file_size):
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1]
        test_file = 'test_file_name'
        volume = FakeVolume()
        volume['name'] = 'file-new-managed-123'
        volume['id'] = 'volume-new-managed-123'
        vol_path = "%s/%s" % (self.TEST_NFS_EXPORT1, test_file)
        vol_ref = {'source-name': vol_path}

        drv._ensure_shares_mounted = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)
        drv._get_share_mount_and_vol_from_vol_ref = mock.Mock(
            return_value=(self.TEST_NFS_EXPORT1, self.TEST_MNT_POINT,
                          test_file))

        vol_size = drv.manage_existing_get_size(volume, vol_ref)
        self.assertEqual(2, vol_size)

    @mock.patch.object(cinder_utils, 'get_file_size', return_value='badfloat')
    def test_manage_existing_get_size_error(self, get_size):
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1]
        test_file = 'test_file_name'
        volume = FakeVolume()
        volume['name'] = 'file-new-managed-123'
        volume['id'] = 'volume-new-managed-123'
        vol_path = "%s/%s" % (self.TEST_NFS_EXPORT1, test_file)
        vol_ref = {'source-name': vol_path}

        drv._ensure_shares_mounted = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)
        drv._get_share_mount_and_vol_from_vol_ref = mock.Mock(
            return_value=(self.TEST_NFS_EXPORT1, self.TEST_MNT_POINT,
                          test_file))

        self.assertRaises(exception.VolumeBackendAPIException,
                          drv.manage_existing_get_size, volume, vol_ref)

    @mock.patch.object(cinder_utils, 'get_file_size', return_value=1074253824)
    def test_manage_existing(self, get_file_size):
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1]
        test_file = 'test_file_name'
        volume = FakeVolume()
        volume['name'] = 'file-new-managed-123'
        volume['id'] = 'volume-new-managed-123'
        vol_path = "%s/%s" % (self.TEST_NFS_EXPORT1, test_file)
        vol_ref = {'source-name': vol_path}
        drv._check_volume_type = mock.Mock()
        self.stubs.Set(drv, '_execute', mock.Mock())
        drv._ensure_shares_mounted = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)
        drv._get_share_mount_and_vol_from_vol_ref = mock.Mock(
            return_value=(self.TEST_NFS_EXPORT1, self.TEST_MNT_POINT,
                          test_file))
        shutil.move = mock.Mock()

        location = drv.manage_existing(volume, vol_ref)
        self.assertEqual(self.TEST_NFS_EXPORT1, location['provider_location'])
        drv._check_volume_type.assert_called_once_with(
            volume, self.TEST_NFS_EXPORT1, test_file)

    @mock.patch.object(cinder_utils, 'get_file_size', return_value=1074253824)
    def test_manage_existing_move_fails(self, get_file_size):
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1]
        test_file = 'test_file_name'
        volume = FakeVolume()
        volume['name'] = 'volume-new-managed-123'
        volume['id'] = 'volume-new-managed-123'
        vol_path = "%s/%s" % (self.TEST_NFS_EXPORT1, test_file)
        vol_ref = {'source-name': vol_path}
        drv._check_volume_type = mock.Mock()
        drv._ensure_shares_mounted = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)
        drv._get_share_mount_and_vol_from_vol_ref = mock.Mock(
            return_value=(self.TEST_NFS_EXPORT1, self.TEST_MNT_POINT,
                          test_file))
        drv._execute = mock.Mock(side_effect=OSError)
        self.assertRaises(exception.VolumeBackendAPIException,
                          drv.manage_existing, volume, vol_ref)
        drv._check_volume_type.assert_called_once_with(
            volume, self.TEST_NFS_EXPORT1, test_file)

    @mock.patch.object(nfs_base, 'LOG')
    def test_unmanage(self, mock_log):
        drv = self._driver
        volume = FakeVolume()
        volume['id'] = '123'
        volume['provider_location'] = '/share'
        drv.unmanage(volume)
        self.assertEqual(1, mock_log.info.call_count)


class NetAppCmodeNfsDriverOnlyTestCase(test.TestCase):
    """Test direct NetApp C Mode driver only and not inherit."""

    def setUp(self):
        super(NetAppCmodeNfsDriverOnlyTestCase, self).setUp()
        self._custom_setup()

    def _custom_setup(self):
        self.mock_object(utils, 'OpenStackInfo')
        kwargs = {}
        kwargs['netapp_mode'] = 'proxy'
        kwargs['configuration'] = create_configuration()
        self._driver = netapp_nfs_cmode.NetAppCmodeNfsDriver(**kwargs)
        self._driver.ssc_enabled = True
        self._driver.configuration.netapp_copyoffload_tool_path = 'cof_path'
        self._driver.zapi_client = mock.Mock()

    @mock.patch.object(utils, 'get_volume_extra_specs')
    @mock.patch.object(utils, 'LOG', mock.Mock())
    def test_create_volume(self, mock_volume_extra_specs):
        drv = self._driver
        drv.ssc_enabled = False
        extra_specs = {}
        mock_volume_extra_specs.return_value = extra_specs
        fake_share = 'localhost:myshare'
        host = 'hostname@backend#' + fake_share
        with mock.patch.object(drv, '_ensure_shares_mounted'):
            with mock.patch.object(drv, '_do_create_volume'):
                volume_info = self._driver.create_volume(FakeVolume(host, 1))
                self.assertEqual(volume_info.get('provider_location'),
                                 fake_share)
                self.assertEqual(0, utils.LOG.warning.call_count)

    @mock.patch.object(utils, 'LOG', mock.Mock())
    def test_create_volume_obsolete_extra_spec(self):
        drv = self._driver
        drv.ssc_enabled = False
        extra_specs = {'netapp:raid_type': 'raid4'}
        mock_volume_extra_specs = mock.Mock()
        self.mock_object(utils,
                         'get_volume_extra_specs',
                         mock_volume_extra_specs)
        mock_volume_extra_specs.return_value = extra_specs
        fake_share = 'localhost:myshare'
        host = 'hostname@backend#' + fake_share
        with mock.patch.object(drv, '_ensure_shares_mounted'):
            with mock.patch.object(drv, '_do_create_volume'):
                self._driver.create_volume(FakeVolume(host, 1))
                warn_msg = 'Extra spec netapp:raid_type is obsolete.  ' \
                           'Use netapp_raid_type instead.'
                utils.LOG.warning.assert_called_once_with(warn_msg)

    @mock.patch.object(utils, 'LOG', mock.Mock())
    def test_create_volume_deprecated_extra_spec(self):
        drv = self._driver
        drv.ssc_enabled = False
        extra_specs = {'netapp_thick_provisioned': 'true'}
        fake_share = 'localhost:myshare'
        host = 'hostname@backend#' + fake_share
        mock_volume_extra_specs = mock.Mock()
        self.mock_object(utils,
                         'get_volume_extra_specs',
                         mock_volume_extra_specs)
        mock_volume_extra_specs.return_value = extra_specs
        with mock.patch.object(drv, '_ensure_shares_mounted'):
            with mock.patch.object(drv, '_do_create_volume'):
                self._driver.create_volume(FakeVolume(host, 1))
                warn_msg = 'Extra spec netapp_thick_provisioned is ' \
                           'deprecated.  Use netapp_thin_provisioned instead.'
                utils.LOG.warning.assert_called_once_with(warn_msg)

    def test_create_volume_no_pool_specified(self):
        drv = self._driver
        drv.ssc_enabled = False
        host = 'hostname@backend'  # missing pool
        with mock.patch.object(drv, '_ensure_shares_mounted'):
            self.assertRaises(exception.InvalidHost,
                              self._driver.create_volume, FakeVolume(host, 1))

    @mock.patch.object(utils, 'get_volume_extra_specs')
    def test_create_volume_with_qos_policy(self, mock_volume_extra_specs):
        drv = self._driver
        drv.ssc_enabled = False
        extra_specs = {'netapp:qos_policy_group': 'qos_policy_1'}
        fake_share = 'localhost:myshare'
        host = 'hostname@backend#' + fake_share
        fake_volume = FakeVolume(host, 1)
        fake_qos_policy = 'qos_policy_1'
        mock_volume_extra_specs.return_value = extra_specs

        with mock.patch.object(drv, '_ensure_shares_mounted'):
            with mock.patch.object(drv, '_do_create_volume'):
                with mock.patch.object(drv,
                                       '_set_qos_policy_group_on_volume'
                                       ) as mock_set_qos:
                    volume_info = self._driver.create_volume(fake_volume)
                    self.assertEqual(volume_info.get('provider_location'),
                                     'localhost:myshare')
                    mock_set_qos.assert_called_once_with(fake_volume,
                                                         fake_share,
                                                         fake_qos_policy)

    def test_copy_img_to_vol_copyoffload_success(self):
        drv = self._driver
        context = object()
        volume = {'id': 'vol_id', 'name': 'name'}
        image_service = object()
        image_id = 'image_id'
        drv.zapi_client.get_ontapi_version = mock.Mock(return_value=(1, 20))
        drv._try_copyoffload = mock.Mock()
        drv._get_provider_location = mock.Mock(return_value='share')
        drv._get_vol_for_share = mock.Mock(return_value='vol')
        drv._update_stale_vols = mock.Mock()

        drv.copy_image_to_volume(context, volume, image_service, image_id)
        drv._try_copyoffload.assert_called_once_with(context, volume,
                                                     image_service,
                                                     image_id)
        drv._update_stale_vols.assert_called_once_with('vol')

    def test_copy_img_to_vol_copyoffload_failure(self):
        drv = self._driver
        context = object()
        volume = {'id': 'vol_id', 'name': 'name'}
        image_service = object()
        image_id = 'image_id'
        drv.zapi_client.get_ontapi_version = mock.Mock(return_value=(1, 20))
        drv._try_copyoffload = mock.Mock(side_effect=Exception())
        nfs_base.NetAppNfsDriver.copy_image_to_volume = mock.Mock()
        drv._get_provider_location = mock.Mock(return_value='share')
        drv._get_vol_for_share = mock.Mock(return_value='vol')
        drv._update_stale_vols = mock.Mock()

        drv.copy_image_to_volume(context, volume, image_service, image_id)
        drv._try_copyoffload.assert_called_once_with(context, volume,
                                                     image_service,
                                                     image_id)
        nfs_base.NetAppNfsDriver.copy_image_to_volume.\
            assert_called_once_with(context, volume, image_service, image_id)
        drv._update_stale_vols.assert_called_once_with('vol')

    def test_copy_img_to_vol_copyoffload_nonexistent_binary_path(self):
        drv = self._driver
        context = object()
        volume = {'id': 'vol_id', 'name': 'name'}
        image_service = mock.Mock()
        image_service.get_location.return_value = (mock.Mock(), mock.Mock())
        image_service.show.return_value = {'size': 0}
        image_id = 'image_id'
        drv._client = mock.Mock()
        drv._client.get_api_version = mock.Mock(return_value=(1, 20))
        drv._find_image_in_cache = mock.Mock(return_value=[])
        drv._construct_image_nfs_url = mock.Mock(return_value=["nfs://1"])
        drv._check_get_nfs_path_segs = mock.Mock(return_value=("test:test",
                                                               "dr"))
        drv._get_ip_verify_on_cluster = mock.Mock(return_value="192.1268.1.1")
        drv._get_mount_point_for_share = mock.Mock(return_value='mnt_point')
        drv._get_host_ip = mock.Mock()
        drv._get_provider_location = mock.Mock()
        drv._get_export_path = mock.Mock(return_value="dr")
        drv._check_share_can_hold_size = mock.Mock()
        # Raise error as if the copyoffload file can not be found
        drv._clone_file_dst_exists = mock.Mock(side_effect=OSError())

        # Verify the original error is propagated
        self.assertRaises(OSError, drv._try_copyoffload,
                          context, volume, image_service, image_id)

    def test_copyoffload_frm_cache_success(self):
        drv = self._driver
        context = object()
        volume = {'id': 'vol_id', 'name': 'name'}
        image_service = object()
        image_id = 'image_id'
        drv._find_image_in_cache = mock.Mock(return_value=[('share', 'img')])
        drv._copy_from_cache = mock.Mock(return_value=True)

        drv._try_copyoffload(context, volume, image_service, image_id)
        drv._copy_from_cache.assert_called_once_with(volume,
                                                     image_id,
                                                     [('share', 'img')])

    def test_copyoffload_frm_img_service_success(self):
        drv = self._driver
        context = object()
        volume = {'id': 'vol_id', 'name': 'name'}
        image_service = object()
        image_id = 'image_id'
        drv._client = mock.Mock()
        drv._client.get_api_version = mock.Mock(return_value=(1, 20))
        drv._find_image_in_cache = mock.Mock(return_value=[])
        drv._copy_from_img_service = mock.Mock()

        drv._try_copyoffload(context, volume, image_service, image_id)
        drv._copy_from_img_service.assert_called_once_with(context,
                                                           volume,
                                                           image_service,
                                                           image_id)

    def test_cache_copyoffload_workflow_success(self):
        drv = self._driver
        volume = {'id': 'vol_id', 'name': 'name', 'size': 1}
        image_id = 'image_id'
        cache_result = [('ip1:/openstack', 'img-cache-imgid')]
        drv._get_ip_verify_on_cluster = mock.Mock(return_value='ip1')
        drv._get_host_ip = mock.Mock(return_value='ip2')
        drv._get_export_path = mock.Mock(return_value='/exp_path')
        drv._execute = mock.Mock()
        drv._register_image_in_cache = mock.Mock()
        drv._get_provider_location = mock.Mock(return_value='/share')
        drv._post_clone_image = mock.Mock()

        copied = drv._copy_from_cache(volume, image_id, cache_result)
        self.assertTrue(copied)
        drv._get_ip_verify_on_cluster.assert_any_call('ip1')
        drv._get_export_path.assert_called_with('vol_id')
        drv._execute.assert_called_once_with('cof_path', 'ip1', 'ip1',
                                             '/openstack/img-cache-imgid',
                                             '/exp_path/name',
                                             run_as_root=False,
                                             check_exit_code=0)
        drv._post_clone_image.assert_called_with(volume)
        drv._get_provider_location.assert_called_with('vol_id')

    @mock.patch.object(image_utils, 'qemu_img_info')
    def test_img_service_raw_copyoffload_workflow_success(self,
                                                          mock_qemu_img_info):
        drv = self._driver
        volume = {'id': 'vol_id', 'name': 'name', 'size': 1}
        image_id = 'image_id'
        context = object()
        image_service = mock.Mock()
        image_service.get_location.return_value = ('nfs://ip1/openstack/img',
                                                   None)
        image_service.show.return_value = {'size': 1,
                                           'disk_format': 'raw'}

        drv._check_get_nfs_path_segs =\
            mock.Mock(return_value=('ip1', '/openstack'))
        drv._get_ip_verify_on_cluster = mock.Mock(return_value='ip1')
        drv._get_host_ip = mock.Mock(return_value='ip2')
        drv._get_export_path = mock.Mock(return_value='/exp_path')
        drv._get_provider_location = mock.Mock(return_value='share')
        drv._execute = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(return_value='mnt_point')
        drv._discover_file_till_timeout = mock.Mock(return_value=True)
        img_inf = mock.Mock()
        img_inf.file_format = 'raw'
        mock_qemu_img_info.return_value = img_inf
        drv._check_share_can_hold_size = mock.Mock()
        drv._move_nfs_file = mock.Mock(return_value=True)
        drv._delete_file = mock.Mock()
        drv._clone_file_dst_exists = mock.Mock()
        drv._post_clone_image = mock.Mock()

        drv._copy_from_img_service(context, volume, image_service, image_id)
        drv._get_ip_verify_on_cluster.assert_any_call('ip1')
        drv._get_export_path.assert_called_with('vol_id')
        drv._check_share_can_hold_size.assert_called_with('share', 1)

        assert drv._execute.call_count == 1
        drv._post_clone_image.assert_called_with(volume)

    @mock.patch.object(image_utils, 'convert_image')
    @mock.patch.object(image_utils, 'qemu_img_info')
    @mock.patch('os.path.exists')
    def test_img_service_qcow2_copyoffload_workflow_success(self, mock_exists,
                                                            mock_qemu_img_info,
                                                            mock_cvrt_image):
        drv = self._driver
        volume = {'id': 'vol_id', 'name': 'name', 'size': 1}
        image_id = 'image_id'
        context = object()
        image_service = mock.Mock()
        image_service.get_location.return_value = ('nfs://ip1/openstack/img',
                                                   None)
        image_service.show.return_value = {'size': 1,
                                           'disk_format': 'qcow2'}
        drv._check_get_nfs_path_segs =\
            mock.Mock(return_value=('ip1', '/openstack'))

        drv._get_ip_verify_on_cluster = mock.Mock(return_value='ip1')
        drv._get_host_ip = mock.Mock(return_value='ip2')
        drv._get_export_path = mock.Mock(return_value='/exp_path')
        drv._get_provider_location = mock.Mock(return_value='share')
        drv._execute = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(return_value='mnt_point')
        img_inf = mock.Mock()
        img_inf.file_format = 'raw'
        mock_qemu_img_info.return_value = img_inf
        drv._check_share_can_hold_size = mock.Mock()

        drv._move_nfs_file = mock.Mock(return_value=True)
        drv._delete_file = mock.Mock()
        drv._clone_file_dst_exists = mock.Mock()
        drv._post_clone_image = mock.Mock()

        drv._copy_from_img_service(context, volume, image_service, image_id)
        drv._get_ip_verify_on_cluster.assert_any_call('ip1')
        drv._get_export_path.assert_called_with('vol_id')
        drv._check_share_can_hold_size.assert_called_with('share', 1)
        assert mock_cvrt_image.call_count == 1
        assert drv._execute.call_count == 1
        assert drv._delete_file.call_count == 2
        drv._clone_file_dst_exists.call_count == 1
        drv._post_clone_image.assert_called_with(volume)


class NetApp7modeNfsDriverTestCase(NetAppCmodeNfsDriverTestCase):
    """Test direct NetApp C Mode driver."""

    def _custom_setup(self):
        self.mock_object(utils, 'OpenStackInfo')
        self._driver = netapp_nfs_7mode.NetApp7modeNfsDriver(
            configuration=create_configuration())
        self._driver.zapi_client = mock.Mock()

    def _prepare_delete_snapshot_mock(self, snapshot_exists):
        drv = self._driver
        mox = self.mox

        mox.StubOutWithMock(drv, '_get_provider_location')
        mox.StubOutWithMock(drv, '_volume_not_present')

        if snapshot_exists:
            mox.StubOutWithMock(drv, '_execute')
            mox.StubOutWithMock(drv, '_get_volume_path')

        drv._get_provider_location(mox_lib.IgnoreArg())
        drv._volume_not_present(mox_lib.IgnoreArg(), mox_lib.IgnoreArg())\
            .AndReturn(not snapshot_exists)

        if snapshot_exists:
            drv._get_volume_path(mox_lib.IgnoreArg(), mox_lib.IgnoreArg())
            drv._execute('rm', None, run_as_root=True)

        mox.ReplayAll()

        return mox

    def test_create_volume_no_pool_specified(self):
        drv = self._driver
        drv.ssc_enabled = False
        host = 'hostname@backend'  # missing pool
        with mock.patch.object(drv, '_ensure_shares_mounted'):
            self.assertRaises(exception.InvalidHost,
                              self._driver.create_volume, FakeVolume(host, 1))

    @mock.patch.object(nfs_base.NetAppNfsDriver, 'do_setup')
    @mock.patch.object(client_7mode.Client, '__init__', return_value=None)
    def test_do_setup(self, mock_client_init, mock_super_do_setup):
        context = mock.Mock()
        self._driver.do_setup(context)
        mock_client_init.assert_called_once_with(**SEVEN_MODE_CONNECTION_INFO)
        mock_super_do_setup.assert_called_once_with(context)

    @mock.patch.object(nfs_base.NetAppNfsDriver, 'check_for_setup_error')
    def test_check_for_setup_error(self, mock_super_check_for_setup_error):
        self._driver.zapi_client.get_ontapi_version.return_value = (1, 20)
        self.assertIsNone(self._driver.check_for_setup_error())
        mock_super_check_for_setup_error.assert_called_once_with()

    def test_check_for_setup_error_old_version(self):
        self._driver.zapi_client.get_ontapi_version.return_value = (1, 8)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.check_for_setup_error)

    def test_check_for_setup_error_no_version(self):
        self._driver.zapi_client.get_ontapi_version.return_value = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.check_for_setup_error)

    def _prepare_clone_mock(self, status):
        drv = self._driver
        mox = self.mox

        volume = FakeVolume()
        setattr(volume, 'provider_location', '127.0.0.1:/nfs')

        mox.StubOutWithMock(drv, '_get_export_ip_path')

        drv._get_export_ip_path(
            mox_lib.IgnoreArg(),
            mox_lib.IgnoreArg()).AndReturn(('127.0.0.1', '/nfs'))
        return mox

    def test_clone_volume_clear(self):
        drv = self._driver
        mox = self._prepare_clone_mock('fail')
        drv.zapi_client = mox.CreateMockAnything()
        drv.zapi_client.get_actual_path_for_export('/nfs').AndReturn(
            '/vol/vol1/nfs')
        drv.zapi_client.clone_file(mox_lib.IgnoreArg(), mox_lib.IgnoreArg())

        mox.ReplayAll()

        volume_name = 'volume_name'
        clone_name = 'clone_name'
        volume_id = volume_name + six.text_type(hash(volume_name))
        try:
            drv._clone_volume(volume_name, clone_name, volume_id)
        except Exception as e:
            if isinstance(e, api.NaApiError):
                pass
            else:
                raise

        mox.VerifyAll()

    def test_get_pool(self):
        pool = self._driver.get_pool({'provider_location': 'fake-share'})
        self.assertEqual(pool, 'fake-share')

    @mock.patch.object(utils, 'get_volume_extra_specs')
    def test_check_volume_type_qos(self, get_specs):
        get_specs.return_value = {'netapp:qos_policy_group': 'qos'}
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self._driver._check_volume_type,
                          'vol', 'share', 'file')
        get_specs.assert_called_once_with('vol')

    def _set_config(self, configuration):
        super(NetApp7modeNfsDriverTestCase, self)._set_config(
            configuration)
        configuration.netapp_storage_family = 'ontap_7mode'
        return configuration

    def test_clone_volume(self):
        drv = self._driver
        mox = self._prepare_clone_mock('pass')
        drv.zapi_client = mox.CreateMockAnything()
        drv.zapi_client.get_actual_path_for_export('/nfs').AndReturn(
            '/vol/vol1/nfs')
        drv.zapi_client.clone_file(mox_lib.IgnoreArg(), mox_lib.IgnoreArg())

        mox.ReplayAll()

        volume_name = 'volume_name'
        clone_name = 'clone_name'
        volume_id = volume_name + six.text_type(hash(volume_name))
        share = 'ip:/share'

        drv._clone_volume(volume_name, clone_name, volume_id, share)

        mox.VerifyAll()
