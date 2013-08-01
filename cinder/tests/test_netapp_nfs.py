# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from lxml import etree
import mox
from mox import IgnoreArg
from mox import IsA
import os
import socket

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import log as logging
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.netapp import api
from cinder.volume.drivers.netapp import nfs as netapp_nfs


from oslo.config import cfg
CONF = cfg.CONF

LOG = logging.getLogger(__name__)


def create_configuration():
    configuration = mox.MockObject(conf.Configuration)
    configuration.append_config_values(mox.IgnoreArg())
    configuration.nfs_mount_point_base = '/mnt/test'
    configuration.nfs_mount_options = None
    return configuration


class FakeVolume(object):
    def __init__(self, size=0):
        self.size = size
        self.id = hash(self)
        self.name = None

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


class FakeResponce(object):
    def __init__(self, status):
        """
        :param status: Either 'failed' or 'passed'
        """
        self.Status = status

        if status == 'failed':
            self.Reason = 'Sample error'


class NetappDirectCmodeNfsDriverTestCase(test.TestCase):
    """Test direct NetApp C Mode driver."""
    def setUp(self):
        super(NetappDirectCmodeNfsDriverTestCase, self).setUp()
        self._custom_setup()

    def test_create_snapshot(self):
        """Test snapshot can be created and deleted."""
        mox = self.mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_clone_volume')
        drv._clone_volume(IgnoreArg(), IgnoreArg(), IgnoreArg())
        mox.ReplayAll()

        drv.create_snapshot(FakeSnapshot())

        mox.VerifyAll()

    def test_create_volume_from_snapshot(self):
        """Tests volume creation from snapshot."""
        drv = self._driver
        mox = self.mox
        volume = FakeVolume(1)
        snapshot = FakeSnapshot(1)

        location = '127.0.0.1:/nfs'
        expected_result = {'provider_location': location}
        mox.StubOutWithMock(drv, '_clone_volume')
        mox.StubOutWithMock(drv, '_get_volume_location')
        mox.StubOutWithMock(drv, 'local_path')
        mox.StubOutWithMock(drv, '_discover_file_till_timeout')
        mox.StubOutWithMock(drv, '_set_rw_permissions_for_all')
        drv._clone_volume(IgnoreArg(), IgnoreArg(), IgnoreArg())
        drv._get_volume_location(IgnoreArg()).AndReturn(location)
        drv.local_path(IgnoreArg()).AndReturn('/mnt')
        drv._discover_file_till_timeout(IgnoreArg()).AndReturn(True)
        drv._set_rw_permissions_for_all(IgnoreArg())

        mox.ReplayAll()

        loc = drv.create_volume_from_snapshot(volume, snapshot)

        self.assertEqual(loc, expected_result)

        mox.VerifyAll()

    def _prepare_delete_snapshot_mock(self, snapshot_exists):
        drv = self._driver
        mox = self.mox

        mox.StubOutWithMock(drv, '_get_provider_location')
        mox.StubOutWithMock(drv, '_volume_not_present')

        if snapshot_exists:
            mox.StubOutWithMock(drv, '_execute')
            mox.StubOutWithMock(drv, '_get_volume_path')

        drv._get_provider_location(IgnoreArg())
        drv._volume_not_present(IgnoreArg(), IgnoreArg())\
            .AndReturn(not snapshot_exists)

        if snapshot_exists:
            drv._get_volume_path(IgnoreArg(), IgnoreArg())
            drv._execute('rm', None, run_as_root=True)

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

    def _custom_setup(self):
        kwargs = {}
        kwargs['netapp_mode'] = 'proxy'
        kwargs['configuration'] = create_configuration()
        self._driver = netapp_nfs.NetAppDirectCmodeNfsDriver(**kwargs)

    def test_check_for_setup_error(self):
        mox = self.mox
        drv = self._driver
        required_flags = [
            'netapp_transport_type',
            'netapp_login',
            'netapp_password',
            'netapp_server_hostname',
            'netapp_server_port']

        # set required flags
        for flag in required_flags:
            setattr(drv.configuration, flag, None)
        # check exception raises when flags are not set
        self.assertRaises(exception.CinderException,
                          drv.check_for_setup_error)

        # set required flags
        for flag in required_flags:
            setattr(drv.configuration, flag, 'val')

        mox.ReplayAll()

        drv.check_for_setup_error()

        mox.VerifyAll()

        # restore initial FLAGS
        for flag in required_flags:
            delattr(drv.configuration, flag)

    def test_do_setup(self):
        mox = self.mox
        drv = self._driver

        mox.StubOutWithMock(netapp_nfs.NetAppNFSDriver, 'do_setup')
        mox.StubOutWithMock(drv, '_get_client')
        mox.StubOutWithMock(drv, '_do_custom_setup')

        netapp_nfs.NetAppNFSDriver.do_setup(IgnoreArg())
        drv._get_client()
        drv._do_custom_setup(IgnoreArg())

        mox.ReplayAll()

        drv.do_setup(IsA(context.RequestContext))

        mox.VerifyAll()

    def _prepare_clone_mock(self, status):
        drv = self._driver
        mox = self.mox

        volume = FakeVolume()
        setattr(volume, 'provider_location', '127.0.0.1:/nfs')

        mox.StubOutWithMock(drv, '_get_host_ip')
        mox.StubOutWithMock(drv, '_get_export_path')
        mox.StubOutWithMock(drv, '_get_if_info_by_ip')
        mox.StubOutWithMock(drv, '_get_vol_by_junc_vserver')
        mox.StubOutWithMock(drv, '_clone_file')

        drv._get_host_ip(IgnoreArg()).AndReturn('127.0.0.1')
        drv._get_export_path(IgnoreArg()).AndReturn('/nfs')
        drv._get_if_info_by_ip('127.0.0.1').AndReturn(
            self._prepare_info_by_ip_response())
        drv._get_vol_by_junc_vserver('openstack', '/nfs').AndReturn('nfsvol')
        drv._clone_file('nfsvol', 'volume_name', 'clone_name',
                        'openstack')
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
        volume_id = volume_name + str(hash(volume_name))

        drv._clone_volume(volume_name, clone_name, volume_id)

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
            LOG.warn(_("Share %(share)s and file name %(file_name)s")
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

        drv._get_mount_point_for_share(IgnoreArg()).AndReturn('/mnt')
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
            IgnoreArg(), r_files).AndReturn(r_files)
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

        drv._get_mount_point_for_share(IgnoreArg()).AndReturn('/mnt')
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

        drv._get_capacity_info('testshare').AndReturn((100, 19, 81))
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

        drv._find_image_in_cache(IgnoreArg()).AndReturn(
            [('share', 'file_name')])
        drv._is_share_vol_compatible(IgnoreArg(), IgnoreArg()).AndReturn(True)
        drv._do_clone_rel_img_cache('file_name', 'vol', 'share', 'file_name')
        drv._post_clone_image(volume)

        mox.ReplayAll()
        drv. clone_image(volume, ('image_location', None), 'image_id')
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

        drv._find_image_in_cache(IgnoreArg()).AndReturn([])
        drv._is_cloneable_share(IgnoreArg()).AndReturn('127.0.0.1:/share')
        drv._is_share_vol_compatible(IgnoreArg(), IgnoreArg()).AndReturn(False)

        mox.ReplayAll()
        (prop, cloned) = drv. clone_image(
            volume, ('nfs://127.0.0.1:/share/img-id', None), 'image_id')
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
        mox.StubOutWithMock(drv, '_set_rw_permissions_for_all')
        mox.StubOutWithMock(drv, '_resize_image_file')
        mox.StubOutWithMock(drv, '_is_share_vol_compatible')

        drv._find_image_in_cache(IgnoreArg()).AndReturn([])
        drv._is_cloneable_share(IgnoreArg()).AndReturn('127.0.0.1:/share')
        drv._is_share_vol_compatible(IgnoreArg(), IgnoreArg()).AndReturn(True)
        drv._get_mount_point_for_share(IgnoreArg()).AndReturn('/mnt')
        image_utils.qemu_img_info('/mnt/img-id').AndReturn(
            self.get_img_info('raw'))
        drv._clone_volume(
            'img-id', 'vol', share='127.0.0.1:/share', volume_id=None)
        drv._get_mount_point_for_share(IgnoreArg()).AndReturn('/mnt')
        drv._discover_file_till_timeout(IgnoreArg()).AndReturn(True)
        drv._set_rw_permissions_for_all('/mnt/vol')
        drv._resize_image_file({'name': 'vol'}, IgnoreArg())

        mox.ReplayAll()
        drv. clone_image(
            volume, ('nfs://127.0.0.1:/share/img-id', None), 'image_id')
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
        mox.StubOutWithMock(drv, '_set_rw_permissions_for_all')
        mox.StubOutWithMock(drv, '_resize_image_file')
        mox.StubOutWithMock(image_utils, 'convert_image')
        mox.StubOutWithMock(drv, '_register_image_in_cache')
        mox.StubOutWithMock(drv, '_is_share_vol_compatible')

        drv._find_image_in_cache(IgnoreArg()).AndReturn([])
        drv._is_cloneable_share('nfs://127.0.0.1/share/img-id').AndReturn(
            '127.0.0.1:/share')
        drv._is_share_vol_compatible(IgnoreArg(), IgnoreArg()).AndReturn(True)
        drv._get_mount_point_for_share('127.0.0.1:/share').AndReturn('/mnt')
        image_utils.qemu_img_info('/mnt/img-id').AndReturn(
            self.get_img_info('notraw'))
        image_utils.convert_image(IgnoreArg(), IgnoreArg(), 'raw')
        image_utils.qemu_img_info('/mnt/vol').AndReturn(
            self.get_img_info('raw'))
        drv._register_image_in_cache(IgnoreArg(), IgnoreArg())
        drv._get_mount_point_for_share('127.0.0.1:/share').AndReturn('/mnt')
        drv._discover_file_till_timeout(IgnoreArg()).AndReturn(True)
        drv._set_rw_permissions_for_all('/mnt/vol')
        drv._resize_image_file({'name': 'vol'}, IgnoreArg())

        mox.ReplayAll()
        drv. clone_image(
            volume, ('nfs://127.0.0.1/share/img-id', None), 'image_id')
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

        drv._find_image_in_cache(IgnoreArg()).AndReturn([])
        drv._is_cloneable_share('nfs://127.0.0.1/share/img-id').AndReturn(
            '127.0.0.1:/share')
        drv._is_share_vol_compatible(IgnoreArg(), IgnoreArg()).AndReturn(True)
        drv._get_mount_point_for_share('127.0.0.1:/share').AndReturn('/mnt')
        image_utils.qemu_img_info('/mnt/img-id').AndReturn(
            self.get_img_info('notraw'))
        image_utils.convert_image(IgnoreArg(), IgnoreArg(), 'raw')
        image_utils.qemu_img_info('/mnt/vol').AndReturn(
            self.get_img_info('raw'))
        drv._register_image_in_cache(IgnoreArg(), IgnoreArg())
        drv.local_path(IgnoreArg()).AndReturn('/mnt/vol')
        drv._discover_file_till_timeout(IgnoreArg()).AndReturn(False)
        drv.local_path(IgnoreArg()).AndReturn('/mnt/vol')
        os.path.exists('/mnt/vol').AndReturn(True)
        drv._delete_file('/mnt/vol')

        mox.ReplayAll()
        vol_dict, result = drv. clone_image(
            volume, ('nfs://127.0.0.1/share/img-id', None), 'image_id')
        mox.VerifyAll()
        self.assertFalse(result)
        self.assertFalse(vol_dict['bootable'])
        self.assertEqual(vol_dict['provider_location'], None)

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
        mox.StubOutWithMock(drv, '_set_rw_permissions_for_all')
        mox.StubOutWithMock(drv, '_resize_image_file')
        mox.StubOutWithMock(image_utils, 'convert_image')
        mox.StubOutWithMock(drv, '_register_image_in_cache')
        mox.StubOutWithMock(drv, '_is_share_vol_compatible')
        mox.StubOutWithMock(drv, 'local_path')
        mox.StubOutWithMock(os.path, 'exists')
        mox.StubOutWithMock(drv, '_delete_file')

        drv._find_image_in_cache(IgnoreArg()).AndReturn([])
        drv._is_cloneable_share('nfs://127.0.0.1/share/img-id').AndReturn(
            '127.0.0.1:/share')
        drv._is_share_vol_compatible(IgnoreArg(), IgnoreArg()).AndReturn(True)
        drv._get_mount_point_for_share('127.0.0.1:/share').AndReturn('/mnt')
        image_utils.qemu_img_info('/mnt/img-id').AndReturn(
            self.get_img_info('notraw'))
        image_utils.convert_image(IgnoreArg(), IgnoreArg(), 'raw')
        image_utils.qemu_img_info('/mnt/vol').AndReturn(
            self.get_img_info('raw'))
        drv._register_image_in_cache(IgnoreArg(), IgnoreArg())
        drv.local_path(IgnoreArg()).AndReturn('/mnt/vol')
        drv._discover_file_till_timeout(IgnoreArg()).AndReturn(True)
        drv._set_rw_permissions_for_all('/mnt/vol')
        drv._resize_image_file(
            IgnoreArg(), IgnoreArg()).AndRaise(exception.InvalidResults())
        drv.local_path(IgnoreArg()).AndReturn('/mnt/vol')
        os.path.exists('/mnt/vol').AndReturn(True)
        drv._delete_file('/mnt/vol')

        mox.ReplayAll()
        vol_dict, result = drv. clone_image(
            volume, ('nfs://127.0.0.1/share/img-id', None), 'image_id')
        mox.VerifyAll()
        self.assertFalse(result)
        self.assertFalse(vol_dict['bootable'])
        self.assertEqual(vol_dict['provider_location'], None)

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
        drv._check_share_in_use(IgnoreArg(), IgnoreArg()).AndReturn('share')
        mox.ReplayAll()
        drv._is_cloneable_share(strg)
        mox.VerifyAll()

    def test_is_cloneable_share_goodformat2(self):
        drv = self._driver
        mox = self.mox
        strg = 'nfs://10.61.222.333:8080/share/img'
        mox.StubOutWithMock(drv, '_check_share_in_use')
        drv._check_share_in_use(IgnoreArg(), IgnoreArg()).AndReturn('share')
        mox.ReplayAll()
        drv._is_cloneable_share(strg)
        mox.VerifyAll()

    def test_is_cloneable_share_goodformat3(self):
        drv = self._driver
        mox = self.mox
        strg = 'nfs://com.netapp:8080/share/img'
        mox.StubOutWithMock(drv, '_check_share_in_use')
        drv._check_share_in_use(IgnoreArg(), IgnoreArg()).AndReturn('share')
        mox.ReplayAll()
        drv._is_cloneable_share(strg)
        mox.VerifyAll()

    def test_is_cloneable_share_goodformat4(self):
        drv = self._driver
        mox = self.mox
        strg = 'nfs://netapp.com/share/img'
        mox.StubOutWithMock(drv, '_check_share_in_use')
        drv._check_share_in_use(IgnoreArg(), IgnoreArg()).AndReturn('share')
        mox.ReplayAll()
        drv._is_cloneable_share(strg)
        mox.VerifyAll()

    def test_is_cloneable_share_goodformat5(self):
        drv = self._driver
        mox = self.mox
        strg = 'nfs://netapp.com/img'
        mox.StubOutWithMock(drv, '_check_share_in_use')
        drv._check_share_in_use(IgnoreArg(), IgnoreArg()).AndReturn('share')
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
        mox.StubOutWithMock(socket, 'gethostbyname')
        socket.gethostbyname(IgnoreArg()).AndRaise(Exception())
        mox.ReplayAll()
        share = drv._check_share_in_use('incorrect:8989', '/dir')
        mox.VerifyAll()
        if share:
            self.fail('Unexpected share detected.')

    def test_check_share_in_use_success(self):
        drv = self._driver
        mox = self.mox
        drv._mounted_shares = ['127.0.0.1:/dir/share']
        mox.StubOutWithMock(socket, 'gethostbyname')
        mox.StubOutWithMock(drv, '_share_match_for_ip')
        socket.gethostbyname(IgnoreArg()).AndReturn('10.22.33.44')
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
                   [{'metadata':
                     {'share_location': 'nfs://host/path',
                      'mount_point': '/opt/stack/data/glance',
                      'type': 'nfs'},
                     'url': 'file:///opt/stack/data/glance/image-id'}])
        location = drv._construct_image_nfs_url(img_loc)
        if location != "nfs://host/path/image-id":
            self.fail("Unexpected direct url.")

    def test_construct_image_url_direct(self):
        drv = self._driver
        img_loc = ("nfs://host/path/image-id", None)
        location = drv._construct_image_nfs_url(img_loc)
        if location != "nfs://host/path/image-id":
            self.fail("Unexpected direct url.")


class NetappDirect7modeNfsDriverTestCase(NetappDirectCmodeNfsDriverTestCase):
    """Test direct NetApp C Mode driver."""
    def _custom_setup(self):
        self._driver = netapp_nfs.NetAppDirect7modeNfsDriver(
            configuration=create_configuration())

    def test_check_for_setup_error_version(self):
        drv = self._driver
        drv._client = api.NaServer("127.0.0.1")

        # check exception raises when version not found
        self.assertRaises(exception.VolumeBackendAPIException,
                          drv.check_for_setup_error)

        drv._client.set_api_version(1, 8)

        # check exception raises when not supported version
        self.assertRaises(exception.VolumeBackendAPIException,
                          drv.check_for_setup_error)

    def test_check_for_setup_error(self):
        mox = self.mox
        drv = self._driver
        drv._client = api.NaServer("127.0.0.1")
        drv._client.set_api_version(1, 9)
        required_flags = [
            'netapp_transport_type',
            'netapp_login',
            'netapp_password',
            'netapp_server_hostname',
            'netapp_server_port']

        # set required flags
        for flag in required_flags:
            setattr(drv.configuration, flag, None)
        # check exception raises when flags are not set
        self.assertRaises(exception.CinderException,
                          drv.check_for_setup_error)

        # set required flags
        for flag in required_flags:
            setattr(drv.configuration, flag, 'val')

        mox.ReplayAll()

        drv.check_for_setup_error()

        mox.VerifyAll()

        # restore initial FLAGS
        for flag in required_flags:
            delattr(drv.configuration, flag)

    def test_do_setup(self):
        mox = self.mox
        drv = self._driver
        mox.StubOutWithMock(netapp_nfs.NetAppNFSDriver, 'do_setup')
        mox.StubOutWithMock(drv, '_get_client')
        mox.StubOutWithMock(drv, '_do_custom_setup')
        netapp_nfs.NetAppNFSDriver.do_setup(IgnoreArg())
        drv._get_client()
        drv._do_custom_setup(IgnoreArg())

        mox.ReplayAll()

        drv.do_setup(IsA(context.RequestContext))

        mox.VerifyAll()

    def _prepare_clone_mock(self, status):
        drv = self._driver
        mox = self.mox

        volume = FakeVolume()
        setattr(volume, 'provider_location', '127.0.0.1:/nfs')

        mox.StubOutWithMock(drv, '_get_export_ip_path')
        mox.StubOutWithMock(drv, '_get_actual_path_for_export')
        mox.StubOutWithMock(drv, '_start_clone')
        mox.StubOutWithMock(drv, '_wait_for_clone_finish')
        if status == 'fail':
            mox.StubOutWithMock(drv, '_clear_clone')

        drv._get_export_ip_path(
            IgnoreArg(), IgnoreArg()).AndReturn(('127.0.0.1', '/nfs'))
        drv._get_actual_path_for_export(IgnoreArg()).AndReturn('/vol/vol1/nfs')
        drv._start_clone(IgnoreArg(), IgnoreArg()).AndReturn(('1', '2'))
        if status == 'fail':
            drv._wait_for_clone_finish('1', '2').AndRaise(
                api.NaApiError('error', 'error'))
            drv._clear_clone('1')
        else:
            drv._wait_for_clone_finish('1', '2')
        return mox

    def test_clone_volume_clear(self):
        drv = self._driver
        mox = self._prepare_clone_mock('fail')

        mox.ReplayAll()

        volume_name = 'volume_name'
        clone_name = 'clone_name'
        volume_id = volume_name + str(hash(volume_name))
        try:
            drv._clone_volume(volume_name, clone_name, volume_id)
        except Exception as e:
            if isinstance(e, api.NaApiError):
                pass
            else:
                raise

        mox.VerifyAll()
