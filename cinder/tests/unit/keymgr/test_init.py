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

from castellan.key_manager import barbican_key_manager
from castellan import options as castellan_opts

from oslo_config import cfg

from cinder import keymgr
from cinder import test


class InitTestCase(test.TestCase):
    def setUp(self):
        super(InitTestCase, self).setUp()
        self.config = cfg.ConfigOpts()
        castellan_opts.set_defaults(self.config)
        self.config.set_default('backend',
                                'cinder.keymgr.conf_key_mgr.ConfKeyManager',
                                group='key_manager')

    def test_blank_config(self):
        kmgr = keymgr.API(self.config)
        self.assertEqual(type(kmgr), keymgr.conf_key_mgr.ConfKeyManager)

    def test_barbican_backend(self):
        self.config.set_override(
            'backend',
            'barbican',
            group='key_manager')
        kmgr = keymgr.API(self.config)
        self.assertEqual(type(kmgr), barbican_key_manager.BarbicanKeyManager)

    def test_set_conf_key_manager(self):
        self.config.set_override(
            'backend',
            'cinder.keymgr.conf_key_mgr.ConfKeyManager',
            group='key_manager')
        kmgr = keymgr.API(self.config)
        self.assertEqual(type(kmgr), keymgr.conf_key_mgr.ConfKeyManager)
