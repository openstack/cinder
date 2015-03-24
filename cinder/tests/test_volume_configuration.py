# Copyright (c) 2012 Rackspace Hosting
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

"""Tests for the configuration wrapper in volume drivers."""


from oslo_config import cfg
from oslo_log import log as logging

from cinder import test
from cinder.volume import configuration


LOG = logging.getLogger(__name__)


volume_opts = [
    cfg.StrOpt('str_opt', default='STR_OPT'),
    cfg.BoolOpt('bool_opt', default=False)
]
more_volume_opts = [
    cfg.IntOpt('int_opt', default=1),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)
CONF.register_opts(more_volume_opts)


class VolumeConfigurationTest(test.TestCase):

    def test_group_grafts_opts(self):
        c = configuration.Configuration(volume_opts, config_group='foo')
        self.assertEqual(c.str_opt, CONF.foo.str_opt)
        self.assertEqual(c.bool_opt, CONF.foo.bool_opt)

    def test_opts_no_group(self):
        c = configuration.Configuration(volume_opts)
        self.assertEqual(c.str_opt, CONF.str_opt)
        self.assertEqual(c.bool_opt, CONF.bool_opt)

    def test_grafting_multiple_opts(self):
        c = configuration.Configuration(volume_opts, config_group='foo')
        c.append_config_values(more_volume_opts)
        self.assertEqual(c.str_opt, CONF.foo.str_opt)
        self.assertEqual(c.bool_opt, CONF.foo.bool_opt)
        self.assertEqual(c.int_opt, CONF.foo.int_opt)

    def test_safe_get(self):
        c = configuration.Configuration(volume_opts, config_group='foo')
        self.assertIsNone(c.safe_get('none_opt'))
