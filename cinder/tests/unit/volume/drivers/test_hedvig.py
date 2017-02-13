# Copyright (c) 2017 Hedvig Inc.
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
#

import mock

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume import configuration as conf
from cinder.volume.drivers.hedvig import hedvig_cinder as hdvg
from cinder.volume import qos_specs
from cinder.volume import volume_types


def _fake_volume_type(*args, **kwargs):
    ctxt = context.get_admin_context()
    type_ref = volume_types.create(ctxt, "qos_extra_specs", {})
    qos_ref = qos_specs.create(ctxt, 'qos-specs', {})
    qos_specs.associate_qos_with_type(ctxt, qos_ref['id'],
                                      type_ref['id'])
    qos_type = volume_types.get_volume_type(ctxt, type_ref['id'])
    return qos_type


def _fake_volume(*args, **kwargs):
    qos_type = _fake_volume_type()
    return fake_volume.fake_volume_obj(context,
                                       name='hedvig',
                                       volume_type_id=qos_type['id'],
                                       volume_type=qos_type,
                                       volume_name='hedvig',
                                       display_name='hedvig',
                                       display_description='test volume',
                                       size=2)


class HedvigDriverTest(test.TestCase):

    def setUp(self):
        super(HedvigDriverTest, self).setUp()
        self.context = context.get_admin_context()
        self._create_fake_config()
        self.assertIsNone(self.driver.do_setup(self.ctxt))

    def _create_fake_config(self):
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.san_ip = '1.0.0.1'
        self.configuration.san_login = 'dummy_user'
        self.configuration.san_password = 'dummy_password'
        self.configuration.san_clustername = 'dummy_cluster'
        self.configuration.san_is_local = False
        self.ctxt = context.get_admin_context()
        self.vol = fake_volume.fake_volume_obj(self.context)
        self.vol.volume_type = fake_volume.fake_volume_type_obj(self.context)
        self.snap = fake_snapshot.fake_snapshot_obj(self.context)
        self.snap.volume = self.vol
        self.driver = hdvg.HedvigISCSIDriver(configuration=self.configuration)

    @mock.patch('cinder.volume.drivers.hedvig.rest_client.RestClient'
                '.create_vdisk')
    def test_create_volume(self, *args, **keywargs):
        result = self.driver.create_volume(self.vol)
        self.assertIsNone(result)

    def test_create_volume_negative(self, *args, **keywargs):
        self.driver.hrs = exception.VolumeDriverException()
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_volume, self.vol)

    @mock.patch('cinder.volume.drivers.hedvig.rest_client.RestClient'
                '.delete_vdisk')
    def test_create_delete_volume(self, *args, **keywargs):
        result = self.driver.delete_volume(self.vol)
        self.assertIsNone(result)

    def test_create_delete_volume_negative(self, *args, **keywargs):
        self.driver.hrs = exception.VolumeDriverException()
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.delete_volume, self.vol)

    @mock.patch('cinder.volume.drivers.hedvig.rest_client.RestClient'
                '.resize_vdisk')
    def test_extend_volume(self, *args, **keywargs):
        self.assertIsNone(self.driver.extend_volume(self.vol, 10))

    def test_extend_volume_negative(self, *args, **keywargs):
        self.driver.hrs = exception.VolumeDriverException()
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.extend_volume, self.vol, 10)

    @mock.patch('cinder.volume.drivers.hedvig.rest_client.RestClient'
                '.resize_vdisk')
    def test_extend_volume_shrinking(self, *args, **keywargs):
        volume = _fake_volume()
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.extend_volume, volume, 1)

    @mock.patch('cinder.volume.drivers.hedvig.rest_client.RestClient'
                '.clone_vdisk')
    def test_create_cloned_volume(self, *args, **keywargs):
        result = self.driver.create_cloned_volume(self.vol, self.vol)
        self.assertIsNone(result)

    def test_create_cloned_volume_negative(self, *args, **keywargs):
        self.driver.hrs = exception.VolumeDriverException()
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_cloned_volume, self.vol, self.vol)

    @mock.patch('cinder.volume.drivers.hedvig.rest_client.RestClient'
                '.create_snapshot')
    def test_create_snapshot(self, *args, **keywargs):
        result = self.driver.create_snapshot(self.snap)
        self.assertIsNone(result)

    def test_create_snapshot_negative(self, *args, **keywargs):
        self.driver.hrs = exception.VolumeDriverException()
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_snapshot, self.snap)

    @mock.patch('cinder.volume.drivers.hedvig.rest_client.RestClient'
                '.delete_snapshot')
    def test_delete_snapshot(self, *args, **keywargs):
        result = self.driver.delete_snapshot(self.snap)
        self.assertIsNone(result)

    def test_delete_snapshot_negative(self, *args, **keywargs):
        self.driver.hrs = exception.VolumeDriverException()
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.delete_snapshot, self.snap)

    @mock.patch('cinder.volume.drivers.hedvig.rest_client.RestClient'
                '.clone_hedvig_snapshot')
    def test_create_volume_from_snapshot(self, *args, **keywargs):
        result = self.driver.create_volume_from_snapshot(self.vol, self.snap)
        self.assertIsNone(result)

    def test_create_volume_from_snapshot_negative(self, *args, **keywargs):
        self.driver.hrs = exception.VolumeDriverException()
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_volume_from_snapshot,
                          self.vol, self.snap)

    def test_do_setup(self):
        self.driver.do_setup(self.context)

    def test_do_setup_san_ip_negative(self):
        self.configuration.san_ip = None
        # check the driver for setup errors
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.do_setup, self.context)
        self.configuration.san_ip = "1.0.0.1"

    def test_do_setup_san_cluster_negative(self):
        self.configuration.san_clustername = None
        # check the driver for setup errors
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.do_setup, self.context)
        self.configuration.san_clustername = "dummy_cluster"

    def test_do_setup_san_login_negative(self):
        self.configuration.san_login = None
        # check the driver for setup errors
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.do_setup, self.context)
        self.configuration.san_login = "dummy_user"

    def test_do_setup_san_password_negative(self):
        self.configuration.san_password = None
        # check the driver for setup errors
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.do_setup, self.context)
        self.configuration.san_password = "dummy_password"

    @mock.patch('cinder.volume.drivers.hedvig.rest_client.RestClient'
                '.list_targets')
    def test_hedvig_lookup_tgt(self, *args, **keywargs):
        host = "hostname"
        result = self.driver.hedvig_lookup_tgt(host)
        self.assertIsNone(result)

    def test_hedvig_lookup_tgt_negative(self, *args, **keywargs):
        host = "hostname"
        self.driver.hrs = exception.VolumeDriverException()
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.hedvig_lookup_tgt, host)

    def test_hedvig_get_lun_negative(self, *args, **keywargs):
        host = "hostname"
        volname = "volume"
        self.driver.hrs = exception.VolumeDriverException()
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.hedvig_get_lun, host, volname)

    @mock.patch('cinder.volume.drivers.hedvig.rest_client.RestClient'
                '.get_iqn')
    def test_hedvig_get_iqn(self, *args, **keywargs):
        host = "hostname"
        result = self.driver.hedvig_get_iqn(host)
        self.assertIsNotNone(result)

    def test_hedvig_get_iqn_negative(self, *args, **keywargs):
        host = "hostname"
        self.driver.hrs = exception.VolumeDriverException()
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.hedvig_get_iqn, host)

    @mock.patch('cinder.volume.drivers.hedvig.rest_client.RestClient'
                '.list_targets')
    def test_terminate_connection_no_connector(self, *args, **keywargs):
        self.assertIsNone(self.driver.
                          terminate_connection(_fake_volume(), None))
