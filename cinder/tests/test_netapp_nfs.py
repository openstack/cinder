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

from cinder import context
from cinder import exception
from cinder import test

from cinder.volume import configuration as conf
from cinder.volume.drivers.netapp import api
from cinder.volume.drivers.netapp import nfs as netapp_nfs
from lxml import etree
from mox import IgnoreArg
from mox import IsA
from mox import MockObject

import mox


def create_configuration():
    configuration = mox.MockObject(conf.Configuration)
    configuration.append_config_values(mox.IgnoreArg())
    return configuration


class FakeVolume(object):
    def __init__(self, size=0):
        self.size = size
        self.id = hash(self)
        self.name = None

    def __getitem__(self, key):
        return self.__dict__[key]


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
        snapshot = FakeSnapshot(2)

        self.assertRaises(exception.CinderException,
                          drv.create_volume_from_snapshot,
                          volume,
                          snapshot)

        snapshot = FakeSnapshot(1)

        location = '127.0.0.1:/nfs'
        expected_result = {'provider_location': location}
        mox.StubOutWithMock(drv, '_clone_volume')
        mox.StubOutWithMock(drv, '_get_volume_location')
        drv._clone_volume(IgnoreArg(), IgnoreArg(), IgnoreArg())
        drv._get_volume_location(IgnoreArg()).AndReturn(location)

        mox.ReplayAll()

        loc = drv.create_volume_from_snapshot(volume, snapshot)

        self.assertEquals(loc, expected_result)

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

    def test_cloned_volume_size_fail(self):
        volume_clone_fail = FakeVolume(1)
        volume_src = FakeVolume(2)
        try:
            self._driver.create_cloned_volume(volume_clone_fail,
                                              volume_src)
            raise AssertionError()
        except exception.CinderException:
            pass

    def _custom_setup(self):
        kwargs = {}
        kwargs['netapp_mode'] = 'proxy'
        kwargs['configuration'] = create_configuration()
        self._driver = netapp_nfs.NetAppDirectCmodeNfsDriver(
            **kwargs)

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

        mox.StubOutWithMock(drv, 'check_for_setup_error')
        mox.StubOutWithMock(drv, '_get_client')
        mox.StubOutWithMock(drv, '_do_custom_setup')

        drv.check_for_setup_error()
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


class NetappDirect7modeNfsDriverTestCase(NetappDirectCmodeNfsDriverTestCase):
    """Test direct NetApp C Mode driver."""
    def _custom_setup(self):
        self._driver = netapp_nfs.NetAppDirect7modeNfsDriver(
            configuration=create_configuration())

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

        mox.StubOutWithMock(drv, 'check_for_setup_error')
        mox.StubOutWithMock(drv, '_get_client')
        mox.StubOutWithMock(drv, '_do_custom_setup')

        drv.check_for_setup_error()
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

        mox.StubOutWithMock(drv, '_get_export_path')
        mox.StubOutWithMock(drv, '_get_actual_path_for_export')
        mox.StubOutWithMock(drv, '_start_clone')
        mox.StubOutWithMock(drv, '_wait_for_clone_finish')
        if status == 'fail':
            mox.StubOutWithMock(drv, '_clear_clone')

        drv._get_export_path(IgnoreArg()).AndReturn('/nfs')
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
