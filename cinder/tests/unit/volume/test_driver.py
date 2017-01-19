# Copyright (c) 2016 Red Hat Inc.
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

from cinder import exception
from cinder import test
from cinder.volume import driver
from cinder.volume import manager


def my_safe_get(self, value):
    if value == 'replication_device':
        return ['replication']
    return None


@ddt.ddt
class DriverTestCase(test.TestCase):

    @staticmethod
    def _get_driver(relicated, version):
        class NonReplicatedDriver(driver.VolumeDriver):
            pass

        class V21Driver(driver.VolumeDriver):
            def failover_host(*args, **kwargs):
                pass

        class AADriver(V21Driver):
            def failover_completed(*args, **kwargs):
                pass

        if not relicated:
            return NonReplicatedDriver

        if version == 'v2.1':
            return V21Driver

        return AADriver

    @ddt.data('v2.1', 'a/a', 'newfeature')
    def test_supports_replication_feature_none(self, rep_version):
        my_driver = self._get_driver(False, None)
        self.assertFalse(my_driver.supports_replication_feature(rep_version))

    @ddt.data('v2.1', 'a/a', 'newfeature')
    def test_supports_replication_feature_only_21(self, rep_version):
        version = 'v2.1'
        my_driver = self._get_driver(True, version)
        self.assertEqual(rep_version == version,
                         my_driver.supports_replication_feature(rep_version))

    @ddt.data('v2.1', 'a/a', 'newfeature')
    def test_supports_replication_feature_aa(self, rep_version):
        my_driver = self._get_driver(True, 'a/a')
        self.assertEqual(rep_version in ('v2.1', 'a/a'),
                         my_driver.supports_replication_feature(rep_version))

    def test_init_non_replicated(self):
        config = manager.config.Configuration(manager.volume_manager_opts,
                                              config_group='volume')
        # No exception raised
        self._get_driver(False, None)(configuration=config)

    @ddt.data('v2.1', 'a/a')
    @mock.patch('cinder.volume.configuration.Configuration.safe_get',
                my_safe_get)
    def test_init_replicated_non_clustered(self, version):
        def append_config_values(self, volume_opts):
            pass

        config = manager.config.Configuration(manager.volume_manager_opts,
                                              config_group='volume')
        # No exception raised
        self._get_driver(True, version)(configuration=config)

    @mock.patch('cinder.volume.configuration.Configuration.safe_get',
                my_safe_get)
    def test_init_replicated_clustered_not_supported(self):
        config = manager.config.Configuration(manager.volume_manager_opts,
                                              config_group='volume')
        # Raises exception because we are trying to run a replicated service
        # in clustered mode but the driver doesn't support it.
        self.assertRaises(exception.Invalid, self._get_driver(True, 'v2.1'),
                          configuration=config, cluster_name='mycluster')

    @mock.patch('cinder.volume.configuration.Configuration.safe_get',
                my_safe_get)
    def test_init_replicated_clustered_supported(self):
        config = manager.config.Configuration(manager.volume_manager_opts,
                                              config_group='volume')
        # No exception raised
        self._get_driver(True, 'a/a')(configuration=config,
                                      cluster_name='mycluster')

    def test_failover(self):
        """Test default failover behavior of calling failover_host."""
        my_driver = self._get_driver(True, 'a/a')()
        with mock.patch.object(my_driver, 'failover_host') as failover_mock:
            res = my_driver.failover(mock.sentinel.context,
                                     mock.sentinel.volumes,
                                     secondary_id=mock.sentinel.secondary_id)
        self.assertEqual(failover_mock.return_value, res)
        failover_mock.assert_called_once_with(mock.sentinel.context,
                                              mock.sentinel.volumes,
                                              mock.sentinel.secondary_id)
