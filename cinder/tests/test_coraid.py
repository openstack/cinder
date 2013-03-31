# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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

import mox

from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import coraid
from cinder.volume.drivers.coraid import CoraidDriver
from cinder.volume.drivers.coraid import CoraidESMException
from cinder.volume.drivers.coraid import CoraidRESTClient

import cookielib
import urllib2

LOG = logging.getLogger(__name__)


fake_esm_ipaddress = "192.168.0.1"
fake_esm_username = "darmok"
fake_esm_group = "tanagra"
fake_esm_password = "12345678"

fake_volume_name = "volume-12345678-1234-1234-1234-1234567890ab"
fake_volume_size = "10"
fake_repository_name = "A-B:C:D"
fake_pool_name = "FakePool"
fake_aoetarget = 4081
fake_shelf = 16
fake_lun = 241

fake_str_aoetarget = str(fake_aoetarget)
fake_lun_addr = {"shelf": fake_shelf, "lun": fake_lun}

fake_volume = {"name": fake_volume_name,
               "size": fake_volume_size,
               "volume_type": {"id": 1}}

fake_volume_info = {"pool": fake_pool_name,
                    "repo": fake_repository_name,
                    "vsxidx": fake_aoetarget,
                    "index": fake_lun,
                    "shelf": fake_shelf}

fake_lun_info = {"shelf": fake_shelf, "lun": fake_lun}

fake_snapshot_name = "snapshot-12345678-8888-8888-1234-1234567890ab"
fake_snapshot_id = "12345678-8888-8888-1234-1234567890ab"
fake_volume_id = "12345678-1234-1234-1234-1234567890ab"
fake_snapshot = {"id": fake_snapshot_id,
                 "volume_id": fake_volume_id}

fake_configure_data = [{"addr": "cms", "data": "FAKE"}]

fake_esm_fetch = [[
    {"command": "super_fake_command_of_death"},
    {"reply": [
        {"lv":
            {"containingPool": fake_pool_name,
             "lunIndex": fake_aoetarget,
             "name": fake_volume_name,
             "lvStatus":
                {"exportedLun":
                    {"lun": fake_lun,
                     "shelf": fake_shelf}}
             },
         "repoName": fake_repository_name}]}]]

fake_esm_success = {"category": "provider",
                    "tracking": False,
                    "configState": "completedSuccessfully",
                    "heldPending": False,
                    "metaCROp": "noAction",
                    "message": None}

fake_group_fullpath = "admin group:%s" % (fake_esm_group)
fake_group_id = 4
fake_login_reply = {"values": [
                    {"fullPath": fake_group_fullpath,
                     "groupId": fake_group_id}],
                    "message": "",
                    "state": "adminSucceed",
                    "metaCROp": "noAction"}

fake_group_fail_fullpath = "fail group:%s" % (fake_esm_group)
fake_group_fail_id = 5
fake_login_reply_group_fail = {"values": [
                               {"fullPath": fake_group_fail_fullpath,
                                "groupId": fake_group_fail_id}],
                               "message": "",
                               "state": "adminSucceed",
                               "metaCROp": "noAction"}


class TestCoraidDriver(test.TestCase):
    def setUp(self):
        super(TestCoraidDriver, self).setUp()
        self.esm_mock = self.mox.CreateMockAnything()
        self.stubs.Set(coraid, 'CoraidRESTClient',
                       lambda *_, **__: self.esm_mock)
        configuration = mox.MockObject(conf.Configuration)
        configuration.append_config_values(mox.IgnoreArg())
        configuration.coraid_esm_address = fake_esm_ipaddress
        configuration.coraid_user = fake_esm_username
        configuration.coraid_group = fake_esm_group
        configuration.coraid_password = fake_esm_password

        self.drv = CoraidDriver(configuration=configuration)
        self.drv.do_setup({})

    def test_create_volume(self):
        setattr(self.esm_mock, 'create_lun', lambda *_: True)
        self.stubs.Set(CoraidDriver, '_get_repository',
                       lambda *_: fake_repository_name)
        self.drv.create_volume(fake_volume)

    def test_delete_volume(self):
        setattr(self.esm_mock, 'delete_lun',
                lambda *_: True)
        self.drv.delete_volume(fake_volume)

    def test_initialize_connection(self):
        setattr(self.esm_mock, '_get_lun_address',
                lambda *_: fake_lun_addr)
        self.drv.initialize_connection(fake_volume, '')

    def test_create_snapshot(self):
        setattr(self.esm_mock, 'create_snapshot',
                lambda *_: True)
        self.drv.create_snapshot(fake_snapshot)

    def test_delete_snapshot(self):
        setattr(self.esm_mock, 'delete_snapshot',
                lambda *_: True)
        self.drv.delete_snapshot(fake_snapshot)

    def test_create_volume_from_snapshot(self):
        setattr(self.esm_mock, 'create_volume_from_snapshot',
                lambda *_: True)
        self.stubs.Set(CoraidDriver, '_get_repository',
                       lambda *_: fake_repository_name)
        self.drv.create_volume_from_snapshot(fake_volume, fake_snapshot)


class TestCoraidRESTClient(test.TestCase):
    def setUp(self):
        super(TestCoraidRESTClient, self).setUp()
        self.stubs.Set(cookielib, 'CookieJar', lambda *_: True)
        self.stubs.Set(urllib2, 'build_opener', lambda *_: True)
        self.stubs.Set(urllib2, 'HTTPCookieProcessor', lambda *_: True)
        self.stubs.Set(CoraidRESTClient, '_login', lambda *_: True)
        self.rest_mock = self.mox.CreateMockAnything()
        self.stubs.Set(coraid, 'CoraidRESTClient',
                       lambda *_, **__: self.rest_mock)
        self.drv = CoraidRESTClient(fake_esm_ipaddress,
                                    fake_esm_username,
                                    fake_esm_group,
                                    fake_esm_password)

    def test__get_group_id(self):
        setattr(self.rest_mock, '_get_group_id',
                lambda *_: True)
        self.assertEquals(self.drv._get_group_id(fake_esm_group,
                                                 fake_login_reply),
                          fake_group_id)

    def test__set_group(self):
        setattr(self.rest_mock, '_set_group',
                lambda *_: fake_group_id)
        self.stubs.Set(CoraidRESTClient, '_admin_esm_cmd',
                       lambda *_: fake_login_reply)
        self.drv._set_group(fake_login_reply)

    def test__set_group_fails_no_group(self):
        setattr(self.rest_mock, '_set_group',
                lambda *_: False)
        self.stubs.Set(CoraidRESTClient, '_admin_esm_cmd',
                       lambda *_: fake_login_reply_group_fail)
        self.assertRaises(CoraidESMException,
                          self.drv._set_group,
                          fake_login_reply_group_fail)

    def test__configure(self):
        setattr(self.rest_mock, '_configure',
                lambda *_: True)
        self.stubs.Set(CoraidRESTClient, '_esm_cmd',
                       lambda *_: fake_esm_success)
        self.drv._configure(fake_configure_data)

    def test__get_volume_info(self):
        setattr(self.rest_mock, '_get_volume_info',
                lambda *_: fake_volume_info)
        self.stubs.Set(CoraidRESTClient, '_esm_cmd',
                       lambda *_: fake_esm_fetch)
        self.drv._get_volume_info(fake_volume_name)

    def test__get_lun_address(self):
        setattr(self.rest_mock, '_get_lun_address',
                lambda *_: fake_lun_info)
        self.stubs.Set(CoraidRESTClient, '_get_volume_info',
                       lambda *_: fake_volume_info)
        self.drv._get_lun_address(fake_volume_name)

    def test_create_lun(self):
        setattr(self.rest_mock, 'create_lun',
                lambda *_: True)
        self.stubs.Set(CoraidRESTClient, '_configure',
                       lambda *_: fake_esm_success)
        self.rest_mock.create_lun(fake_volume_name, '10',
                                  fake_repository_name)
        self.drv.create_lun(fake_volume_name, '10',
                            fake_repository_name)

    def test_delete_lun(self):
        setattr(self.rest_mock, 'delete_lun',
                lambda *_: True)
        self.stubs.Set(CoraidRESTClient, '_get_volume_info',
                       lambda *_: fake_volume_info)
        self.stubs.Set(CoraidRESTClient, '_configure',
                       lambda *_: fake_esm_success)
        self.rest_mock.delete_lun(fake_volume_name)
        self.drv.delete_lun(fake_volume_name)

    def test_create_snapshot(self):
        setattr(self.rest_mock, 'create_snapshot',
                lambda *_: True)
        self.stubs.Set(CoraidRESTClient, '_get_volume_info',
                       lambda *_: fake_volume_info)
        self.stubs.Set(CoraidRESTClient, '_configure',
                       lambda *_: fake_esm_success)
        self.drv.create_snapshot(fake_volume_name,
                                 fake_volume_name)

    def test_delete_snapshot(self):
        setattr(self.rest_mock, 'delete_snapshot',
                lambda *_: True)
        self.stubs.Set(CoraidRESTClient, '_get_volume_info',
                       lambda *_: fake_volume_info)
        self.stubs.Set(CoraidRESTClient, '_configure',
                       lambda *_: fake_esm_success)
        self.drv.delete_snapshot(fake_volume_name)

    def test_create_volume_from_snapshot(self):
        setattr(self.rest_mock, 'create_volume_from_snapshot',
                lambda *_: True)
        self.stubs.Set(CoraidRESTClient, '_get_volume_info',
                       lambda *_: fake_volume_info)
        self.stubs.Set(CoraidRESTClient, '_configure',
                       lambda *_: fake_esm_success)
        self.drv.create_volume_from_snapshot(fake_volume_name,
                                             fake_volume_name,
                                             fake_repository_name)
