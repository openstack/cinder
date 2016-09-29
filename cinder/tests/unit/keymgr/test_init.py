# Copyright (c) 2016 The Johns Hopkins University/Applied Physics Laboratory
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

import castellan
from castellan import key_manager
from castellan import options as castellan_opts

from oslo_config import cfg

from cinder import keymgr
from cinder import test


class InitTestCase(test.TestCase):
    def setUp(self):
        super(InitTestCase, self).setUp()
        self.config = cfg.ConfigOpts()
        castellan_opts.set_defaults(self.config)
        self.config.set_default('api_class',
                                'cinder.keymgr.conf_key_mgr.ConfKeyManager',
                                group='key_manager')

    def test_blank_config(self):
        kmgr = keymgr.API(self.config)
        self.assertEqual(type(kmgr), keymgr.conf_key_mgr.ConfKeyManager)

    def test_set_barbican_key_manager(self):
        self.config.set_override(
            'api_class',
            'castellan.key_manager.barbican_key_manager.BarbicanKeyManager',
            group='key_manager')
        kmgr = keymgr.API(self.config)
        self.assertEqual(
            type(kmgr),
            key_manager.barbican_key_manager.BarbicanKeyManager)

    def test_set_mock_key_manager(self):
        self.config.set_override(
            'api_class',
            'castellan.tests.unit.key_manager.mock_key_manager.MockKeyManager',
            group='key_manager')
        kmgr = keymgr.API(self.config)
        self.assertEqual(
            type(kmgr),
            castellan.tests.unit.key_manager.mock_key_manager.MockKeyManager)

    def test_set_conf_key_manager(self):
        self.config.set_override(
            'api_class',
            'cinder.keymgr.conf_key_mgr.ConfKeyManager',
            group='key_manager')
        kmgr = keymgr.API(self.config)
        self.assertEqual(type(kmgr), keymgr.conf_key_mgr.ConfKeyManager)

    def test_deprecated_barbican_key_manager(self):
        self.config.set_override(
            'api_class',
            'cinder.keymgr.barbican.BarbicanKeyManager',
            group='key_manager')
        kmgr = keymgr.API(self.config)
        self.assertEqual(
            type(kmgr),
            key_manager.barbican_key_manager.BarbicanKeyManager)

    def test_deprecated_mock_key_manager(self):
        self.config.set_override(
            'api_class',
            'cinder.tests.unit.keymgr.mock_key_mgr.MockKeyManager',
            group='key_manager')
        kmgr = keymgr.API(self.config)
        self.assertEqual(
            type(kmgr),
            castellan.tests.unit.key_manager.mock_key_manager.MockKeyManager)
