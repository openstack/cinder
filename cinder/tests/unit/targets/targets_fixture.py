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

import copy
import os
import shutil
import tempfile
from unittest import mock

from oslo_utils import fileutils
from oslo_utils import timeutils

from cinder.tests.unit import test
from cinder.volume import configuration as conf


class TargetDriverFixture(test.TestCase):
    def setUp(self):
        super(TargetDriverFixture, self).setUp()
        self.configuration = conf.Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.safe_get = mock.Mock(side_effect=self.fake_safe_get)
        self.configuration.target_ip_address = '10.9.8.7'
        self.configuration.target_port = 3260

        self.fake_volumes_dir = tempfile.mkdtemp()
        fileutils.ensure_tree(self.fake_volumes_dir)

        self.fake_project_id = 'ed2c1fd4-5fc0-11e4-aa15-123b93f75cba'
        self.fake_project_id_2 = 'ed2c1fd4-5fc0-11e4-aa15-123b93f75cba'
        self.fake_volume_id = 'ed2c2222-5fc0-11e4-aa15-123b93f75cba'

        self.addCleanup(self._cleanup)

        self.testvol =\
            {'project_id': self.fake_project_id,
             'name': 'testvol',
             'size': 1,
             'id': self.fake_volume_id,
             'volume_type_id': None,
             'provider_location': '10.10.7.1:3260 '
                                  'iqn.2010-10.org.openstack:'
                                  'volume-%s 0' % self.fake_volume_id,
             'provider_auth': 'CHAP stack-1-a60e2611875f40199931f2'
                              'c76370d66b 2FE0CQ8J196R',
             'provider_geometry': '512 512',
             'created_at': timeutils.utcnow(),
             'host': 'fake_host@lvm#lvm'}

        self.testvol_no_prov_loc = copy.copy(self.testvol)
        self.testvol_no_prov_loc['provider_location'] = None

        self.iscsi_target_prefix = 'iqn.2010-10.org.openstack:'
        self.target_string = ('127.0.0.1:3260,1 ' +
                              self.iscsi_target_prefix +
                              'volume-%s' % self.testvol['id'])

        self.testvol_2 =\
            {'project_id': self.fake_project_id_2,
             'name': 'testvol2',
             'size': 1,
             'id': self.fake_volume_id,
             'volume_type_id': None,
             'provider_location': ('%(ip)s:%(port)d%(iqn)svolume-%(vol)s 2' %
                                   {'ip': self.configuration.target_ip_address,
                                    'port': self.configuration.target_port,
                                    'iqn': self.iscsi_target_prefix,
                                    'vol': self.fake_volume_id}),
             'provider_auth': 'CHAP stack-1-a60e2611875f40199931f2'
                              'c76370d66b 2FE0CQ8J196R',
             'provider_geometry': '512 512',
             'created_at': timeutils.utcnow(),
             'host': 'fake_host@lvm#lvm'}

        self.expected_iscsi_properties = \
            {'auth_method': 'CHAP',
             'auth_password': '2FE0CQ8J196R',
             'auth_username': 'stack-1-a60e2611875f40199931f2c76370d66b',
             'encrypted': False,
             'logical_block_size': '512',
             'physical_block_size': '512',
             'target_discovered': False,
             'target_iqn': 'iqn.2010-10.org.openstack:volume-%s' %
                           self.fake_volume_id,
             'target_lun': 0,
             'target_portal': '10.10.7.1:3260',
             'volume_id': self.fake_volume_id}

        self.VOLUME_ID = '83c2e877-feed-46be-8435-77884fe55b45'
        self.VOLUME_NAME = 'volume-' + self.VOLUME_ID
        self.test_vol = (self.iscsi_target_prefix +
                         self.VOLUME_NAME)

    def _cleanup(self):
        if os.path.exists(self.fake_volumes_dir):
            shutil.rmtree(self.fake_volumes_dir)

    def fake_safe_get(self, value):
        if value == 'volumes_dir':
            return self.fake_volumes_dir
        elif value == 'target_protocol':
            return self.configuration.target_protocol
        elif value == 'target_prefix':
            return self.iscsi_target_prefix
