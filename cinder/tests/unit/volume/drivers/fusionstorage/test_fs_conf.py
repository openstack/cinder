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
import os
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
        config.add_section('backend_name')
        config.set('backend_name', 'dsware_rest_url', 'https://fake_rest_site')
        config.set('backend_name', 'san_login', 'fake_user')
        config.set('backend_name', 'san_password', 'fake_passwd')
        config.set('backend_name', 'dsware_storage_pools', 'fake_pool')

        config.add_section('manager_ip')
        config.set('manager_ip', 'fake_host', 'fake_ip')
        config.write(open(self.conf.cinder_fusionstorage_conf_file, 'w'))

    @mock.patch.object(fs_conf.FusionStorageConf, '_encode_authentication')
    @mock.patch.object(fs_conf.FusionStorageConf, '_pools_name')
    @mock.patch.object(fs_conf.FusionStorageConf, '_san_address')
    @mock.patch.object(fs_conf.FusionStorageConf, '_san_user')
    @mock.patch.object(fs_conf.FusionStorageConf, '_san_password')
    def test_update_config_value(self, mock_san_password, mock_san_user,
                                 mock_san_address, mock_pools_name,
                                 mock_encode_authentication):
        self.fusionstorage_conf.update_config_value()
        mock_encode_authentication.assert_called_once_with()
        mock_pools_name.assert_called_once_with()
        mock_san_address.assert_called_once_with()
        mock_san_user.assert_called_once_with()
        mock_san_password.assert_called_once_with()

    @mock.patch.object(os.path, 'exists')
    def test__encode_authentication(self, mock_exists):
        config = configparser.ConfigParser()
        config.read(self.conf.cinder_fusionstorage_conf_file)
        mock_exists.return_value = False

        user_name = 'fake_user'
        self.mock_object(
            self.fusionstorage_conf.configuration, 'safe_get',
            return_value=user_name)
        self.fusionstorage_conf._encode_authentication()

        password = 'fake_passwd'
        self.mock_object(
            self.fusionstorage_conf.configuration, 'safe_get',
            return_value=password)
        self.fusionstorage_conf._encode_authentication()

    @mock.patch.object(os.path, 'exists')
    @mock.patch.object(configparser.ConfigParser, 'set')
    def test__rewrite_conf(self, mock_set, mock_exists):
        mock_exists.return_value = False
        mock_set.return_value = "success"
        self.fusionstorage_conf._rewrite_conf('fake_name', 'fake_pwd')

    def test__san_address(self):
        address = 'https://fake_rest_site'
        self.mock_object(
            self.fusionstorage_conf.configuration, 'safe_get',
            return_value=address)
        self.fusionstorage_conf._san_address()
        self.assertEqual('https://fake_rest_site',
                         self.fusionstorage_conf.configuration.san_address)

    def test__san_user(self):
        user = '!&&&ZmFrZV91c2Vy'
        self.mock_object(
            self.fusionstorage_conf.configuration, 'safe_get',
            return_value=user)
        self.fusionstorage_conf._san_user()
        self.assertEqual(
            'fake_user', self.fusionstorage_conf.configuration.san_user)

        user = 'fake_user_2'
        self.mock_object(
            self.fusionstorage_conf.configuration, 'safe_get',
            return_value=user)
        self.fusionstorage_conf._san_user()
        self.assertEqual(
            'fake_user_2', self.fusionstorage_conf.configuration.san_user)

    def test__san_password(self):
        password = '!&&&ZmFrZV9wYXNzd2Q='
        self.mock_object(
            self.fusionstorage_conf.configuration, 'safe_get',
            return_value=password)
        self.fusionstorage_conf._san_password()
        self.assertEqual(
            'fake_passwd', self.fusionstorage_conf.configuration.san_password)

        password = 'fake_passwd_2'
        self.mock_object(
            self.fusionstorage_conf.configuration, 'safe_get',
            return_value=password)
        self.fusionstorage_conf._san_password()
        self.assertEqual('fake_passwd_2',
                         self.fusionstorage_conf.configuration.san_password)

    def test__pools_name(self):
        pools_name = 'fake_pool'
        self.mock_object(
            self.fusionstorage_conf.configuration, 'safe_get',
            return_value=pools_name)
        self.fusionstorage_conf._pools_name()
        self.assertListEqual(
            ['fake_pool'], self.fusionstorage_conf.configuration.pools_name)

    def test__manager_ip(self):
        manager_ips = {'fake_host': 'fake_ip'}
        self.mock_object(
            self.fusionstorage_conf.configuration, 'safe_get',
            return_value=manager_ips)
        self.fusionstorage_conf._manager_ip()
        self.assertDictEqual({'fake_host': 'fake_ip'},
                             self.fusionstorage_conf.configuration.manager_ips)
