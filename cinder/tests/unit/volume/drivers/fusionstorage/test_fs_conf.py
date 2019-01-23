# Copyright (c) 2018 Huawei Technologies Co., Ltd.
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
import ddt

import mock
import shutil
import tempfile

from six.moves import configparser

from cinder import test
from cinder.volume.drivers.fusionstorage import fs_conf


@ddt.ddt
class FusionStorageConfTestCase(test.TestCase):
    def setUp(self):
        super(FusionStorageConfTestCase, self).setUp()
        self.tmp_dir = tempfile.mkdtemp()
        self.conf = mock.Mock()
        self._create_fake_conf_file()
        self.fusionstorage_conf = fs_conf.FusionStorageConf(
            self.conf, "cinder@fs")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)
        super(FusionStorageConfTestCase, self).tearDown()

    def _create_fake_conf_file(self):
        self.conf.cinder_fusionstorage_conf_file = (
            self.tmp_dir + '/cinder.conf')

        config = configparser.ConfigParser()
        config.add_section('storage')
        config.set('storage', 'RestURL', 'https://fake_rest_site')
        config.set('storage', 'UserName', 'fake_user')
        config.set('storage', 'Password', 'fake_passwd')
        config.set('storage', 'StoragePool', 'fake_pool')
        config.add_section('manager_ip')
        config.set('manager_ip', 'fake_host', 'fake_ip')
        config.write(open(self.conf.cinder_fusionstorage_conf_file, 'w'))

    def test_update_config_value(self):
        config = configparser.ConfigParser()
        config.read(self.conf.cinder_fusionstorage_conf_file)
        storage_info = {'RestURL': config.get('storage', 'RestURL'),
                        'UserName': config.get('storage', 'UserName'),
                        'Password': config.get('storage', 'Password'),
                        'StoragePool': config.get('storage', 'StoragePool')}

        self.mock_object(
            self.fusionstorage_conf.configuration, 'safe_get',
            return_value=storage_info)

        self.fusionstorage_conf.update_config_value()

        self.assertEqual('https://fake_rest_site',
                         self.fusionstorage_conf.configuration.san_address)
        self.assertEqual(
            'fake_user', self.fusionstorage_conf.configuration.san_user)
        self.assertEqual(
            'fake_passwd', self.fusionstorage_conf.configuration.san_password)
        self.assertListEqual(
            ['fake_pool'], self.fusionstorage_conf.configuration.pools_name)

    def test__encode_authentication(self):
        config = configparser.ConfigParser()
        config.read(self.conf.cinder_fusionstorage_conf_file)

        storage_info = {'RestURL': config.get('storage', 'RestURL'),
                        'UserName': config.get('storage', 'UserName'),
                        'Password': config.get('storage', 'Password'),
                        'StoragePool': config.get('storage', 'StoragePool')}
        self.fusionstorage_conf._encode_authentication(storage_info)
        name_node = storage_info.get('UserName')
        pwd_node = storage_info.get('Password')
        self.assertEqual('!&&&ZmFrZV91c2Vy', name_node)
        self.assertEqual('!&&&ZmFrZV9wYXNzd2Q=', pwd_node)

    def test__manager_ip(self):
        manager_ips = {'fake_host': 'fake_ip'}
        self.mock_object(
            self.fusionstorage_conf.configuration, 'safe_get',
            return_value=manager_ips)
        self.fusionstorage_conf._manager_ip()
        self.assertDictEqual({'fake_host': 'fake_ip'},
                             self.fusionstorage_conf.configuration.manager_ips)
