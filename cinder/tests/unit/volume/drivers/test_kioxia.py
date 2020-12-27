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

import unittest
from unittest import mock

from oslo_utils.secretutils import md5

from cinder import exception
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.kioxia import entities
from cinder.volume.drivers.kioxia import kumoscale as kioxia
from cinder.volume.drivers.kioxia import rest_client

VOL_BACKEND_NAME = 'kioxia_kumoscale_1'
VOL_NAME = 'volume-c2fd04e3-320e-44eb-b-2'
VOL_UUID = 'c20aba21-6ef6-446b-b374-45733b4883ba'
VOL_SIZE = 10
VOL_PROTOCOL = 'NVMeoF'
SNAP_UUID = 'c9ef9d49-0d26-44cb-b609-0b8bd2d3db77'
CONN_UUID = '34206309-3733-4cc6-a7d5-9d4dbbe377da'
CONN_HOST_NAME = 'devstack'
CONN_NQN = 'nqn.2014-08.org.nvmexpress:uuid:' \
           'beaae2de-3a97-4be1-a739-6ac4bc5bf138'
success_prov_response = entities.ProvisionerResponse(None, None, "Success",
                                                     "Success")
fail_prov_response = entities.ProvisionerResponse(None, None, "Failure",
                                                  "Failure")
prov_backend1 = entities.Backend(None, None, None, None, 'dummy-pid-1')
prov_backend2 = entities.Backend(None, None, None, None, 'dummy-pid-2')
prov_location1 = entities.Location(VOL_UUID, prov_backend1)
prov_location2 = entities.Location(VOL_UUID, prov_backend2)
prov_volume = entities.VolumeProv(VOL_UUID, None, None, None,
                                  None, None, None, None, None, None,
                                  None, True, None, [prov_location1,
                                                     prov_location2])
prov_volumes_response = entities.ProvisionerResponse([prov_volume])
no_entities_prov_response = entities.ProvisionerResponse([], None, "Success")


class KioxiaVolumeTestCase(test.TestCase):
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_info')
    @mock.patch.object(kioxia.KumoScaleBaseVolumeDriver, '_get_kumoscale')
    def setUp(self, mock_kumoscale, mock_get_info):
        mock_get_info.return_value = success_prov_response
        mock_kumoscale.return_value = \
            rest_client.KioxiaProvisioner(['1.2.3.4'], 'cert', 'token')
        super(KioxiaVolumeTestCase, self).setUp()
        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.volume_backend_name = VOL_BACKEND_NAME
        self.cfg.url = 'dummyURL'
        self.cfg.token = 'dummy.dummy.Rf-dummy-dummy-lE'
        self.cfg.cafile = 'dummy'
        self.cfg.num_replicas = 1
        self.cfg.block_size = 512
        self.cfg.max_iops_per_gb = 1000
        self.cfg.desired_iops_per_gb = 1000
        self.cfg.max_bw_per_gb = 1000
        self.cfg.desired_bw_per_gb = 1000
        self.cfg.same_rack_allowed = False
        self.cfg.max_replica_down_time = 5
        self.cfg.span_allowed = True
        self.cfg.vol_reserved_space_percentage = 20
        self.cfg.provisioning_type = 'THIN'
        self.driver = kioxia.KumoScaleBaseVolumeDriver(configuration=self.cfg)
        self.driver.configuration.get = lambda *args, **kwargs: {}
        self.driver.num_replicas = 2
        self.expected_stats = {
            'volume_backend_name': VOL_BACKEND_NAME,
            'vendor_name': 'KIOXIA',
            'driver_version': self.driver.VERSION,
            'storage_protocol': 'NVMeOF',
            'consistencygroup_support': False,
            'thin_provisioning_support': True,
            'multiattach': False,
            'total_capacity_gb': 1000,
            'free_capacity_gb': 600
        }

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_info')
    def test_get_kumoscale(self, mock_get_info):
        mock_get_info.return_value = success_prov_response
        result = self.driver._get_kumoscale('https://1.2.3.4:8090', 'token',
                                            'cert')
        self.assertEqual(result.mgmt_ips, ['1.2.3.4'])
        self.assertEqual(result.port, '8090')
        self.assertEqual(result.token, 'token')

    @mock.patch.object(rest_client.KioxiaProvisioner, 'create_volume')
    def test_volume_create_success(self, mock_create_volume):
        testvol = _stub_volume()
        mock_create_volume.return_value = success_prov_response
        result = self.driver.create_volume(testvol)
        args, kwargs = mock_create_volume.call_args
        mock_call = args[0]
        self.assertEqual(mock_call.alias, testvol['name'][:27])
        self.assertEqual(mock_call.capacity, testvol['size'])
        self.assertEqual(mock_call.uuid, testvol['id'])
        self.assertEqual(mock_call.protocol, VOL_PROTOCOL)
        self.assertIsNone(result)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'create_volume')
    def test_volume_create_failure(self, mock_create_volume):
        testvol = _stub_volume()
        mock_create_volume.return_value = fail_prov_response
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, testvol)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'create_volume')
    def test_volume_create_exception(self, mock_create_volume):
        testvol = _stub_volume()
        mock_create_volume.side_effect = Exception()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, testvol)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'delete_volume')
    def test_delete_volume_success(self, mock_delete_volume):
        testvol = _stub_volume()
        mock_delete_volume.return_value = success_prov_response
        result = self.driver.delete_volume(testvol)
        mock_delete_volume.assert_any_call(testvol['id'])
        self.assertIsNone(result)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'delete_volume')
    def test_delete_volume_failure(self, mock_delete_volume):
        testvol = _stub_volume()
        mock_delete_volume.return_value = fail_prov_response
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume, testvol)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'delete_volume')
    def test_delete_volume_exception(self, mock_delete_volume):
        testvol = _stub_volume()
        mock_delete_volume.side_effect = Exception()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume, testvol)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection(self, mock_host_probe,
                                   mock_publish,
                                   mock_get_volumes_by_uuid,
                                   mock_get_targets,
                                   mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_target1 = TargetEntity('target.nqn', prov_backend1)
        prov_portal = PortalEntity('1.2.3.4', 4420, 'TCP')
        backend = BackendEntity([prov_portal])
        prov_targets_response = entities.ProvisionerResponse([prov_target1])
        mock_publish.return_value = success_prov_response
        mock_host_probe.return_value = success_prov_response
        mock_get_volumes_by_uuid.return_value = prov_volumes_response
        mock_get_targets.return_value = prov_targets_response
        mock_get_backend_by_id.return_value = \
            entities.ProvisionerResponse([backend])
        result = self.driver.initialize_connection(testvol, testconn)
        mock_host_probe.assert_any_call(testconn['nqn'],
                                        testconn['uuid'],
                                        testconn['host'],
                                        'Agent', 'cinder-driver-0.1', 30)
        mock_publish.assert_any_call(testconn['uuid'], testvol['id'])
        mock_get_volumes_by_uuid.assert_any_call(testvol['id'])
        mock_get_targets.assert_any_call(testconn['uuid'], testvol['id'])
        mock_get_backend_by_id.assert_any_call('dummy-pid-1')
        expected_replica = {'portals': [('1.2.3.4', '4420', 'TCP')],
                            'target_nqn': 'target.nqn',
                            'vol_uuid': testvol['id']}
        expected_data = {
            'vol_uuid': testvol['id'],
            'alias': testvol['name'],
            'writable': True,
            'volume_replicas': [expected_replica]
        }
        expected_result = {
            'driver_volume_type': 'nvmeof',
            'data': expected_data
        }
        self.assertDictEqual(result, expected_result)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection_host_probe_failure(self, mock_host_probe,
                                                      mock_publish,
                                                      mock_get_volumes_by_uuid,
                                                      mock_get_targets,
                                                      mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_target = TargetEntity('target.nqn', prov_backend1)
        prov_portal = PortalEntity('1.2.3.4', 4420, 'TCP')
        backend = BackendEntity([prov_portal])
        prov_targets_response = entities.ProvisionerResponse([prov_target])
        mock_publish.return_value = success_prov_response
        mock_host_probe.return_value = fail_prov_response
        mock_get_volumes_by_uuid.return_value = prov_volumes_response
        mock_get_targets.return_value = prov_targets_response
        mock_get_backend_by_id.return_value = \
            entities.ProvisionerResponse([backend])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection_host_probe_exception(
            self, mock_host_probe, mock_publish, mock_get_volumes_by_uuid,
            mock_get_targets, mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_target = TargetEntity('target.nqn', prov_backend1)
        prov_portal = PortalEntity('1.2.3.4', 4420, 'TCP')
        backend = BackendEntity([prov_portal])
        prov_targets_response = entities.ProvisionerResponse([prov_target])
        mock_publish.return_value = success_prov_response
        mock_host_probe.side_effect = Exception()
        mock_get_volumes_by_uuid.return_value = prov_volumes_response
        mock_get_targets.return_value = prov_targets_response
        mock_get_backend_by_id.return_value = \
            entities.ProvisionerResponse([backend])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection_publish_failure(self, mock_host_probe,
                                                   mock_publish,
                                                   mock_get_volumes_by_uuid,
                                                   mock_get_targets,
                                                   mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_target = TargetEntity('target.nqn', prov_backend1)
        prov_portal = PortalEntity('1.2.3.4', 4420, 'TCP')
        backend = BackendEntity([prov_portal])
        prov_targets_response = entities.ProvisionerResponse([prov_target])
        mock_publish.return_value = fail_prov_response
        mock_host_probe.return_value = success_prov_response
        mock_get_volumes_by_uuid.return_value = prov_volumes_response
        mock_get_targets.return_value = prov_targets_response
        mock_get_backend_by_id.return_value = \
            entities.ProvisionerResponse([backend])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection_publish_exception(self, mock_host_probe,
                                                     mock_publish,
                                                     mock_get_volumes_by_uuid,
                                                     mock_get_targets,
                                                     mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_target = TargetEntity('target.nqn', prov_backend1)
        prov_portal = PortalEntity('1.2.3.4', 4420, 'TCP')
        backend = BackendEntity([prov_portal])
        prov_targets_response = entities.ProvisionerResponse([prov_target])
        mock_publish.side_effect = Exception()
        mock_host_probe.return_value = success_prov_response
        mock_get_volumes_by_uuid.return_value = prov_volumes_response
        mock_get_targets.return_value = prov_targets_response
        mock_get_backend_by_id.return_value = \
            entities.ProvisionerResponse([backend])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection_volumes_failure(self, mock_host_probe,
                                                   mock_publish,
                                                   mock_get_volumes_by_uuid,
                                                   mock_get_targets,
                                                   mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_target = TargetEntity('target.nqn', prov_backend1)
        prov_portal = PortalEntity('1.2.3.4', 4420, 'TCP')
        backend = BackendEntity([prov_portal])
        prov_targets_response = entities.ProvisionerResponse([prov_target])
        mock_publish.return_value = success_prov_response
        mock_host_probe.return_value = success_prov_response
        mock_get_volumes_by_uuid.return_value = fail_prov_response
        mock_get_targets.return_value = prov_targets_response
        mock_get_backend_by_id.return_value = \
            entities.ProvisionerResponse([backend])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection_no_volumes(self, mock_host_probe,
                                              mock_publish,
                                              mock_get_volumes_by_uuid,
                                              mock_get_targets,
                                              mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_target = TargetEntity('target.nqn', prov_backend1)
        prov_portal = PortalEntity('1.2.3.4', 4420, 'TCP')
        backend = BackendEntity([prov_portal])
        prov_targets_response = entities.ProvisionerResponse([prov_target])
        mock_publish.return_value = success_prov_response
        mock_host_probe.return_value = success_prov_response
        mock_get_volumes_by_uuid.return_value = no_entities_prov_response
        mock_get_targets.return_value = prov_targets_response
        mock_get_backend_by_id.return_value = \
            entities.ProvisionerResponse([backend])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection_volumes_exception(self, mock_host_probe,
                                                     mock_publish,
                                                     mock_get_volumes_by_uuid,
                                                     mock_get_targets,
                                                     mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_target = TargetEntity('target.nqn', prov_backend1)
        prov_portal = PortalEntity('1.2.3.4', 4420, 'TCP')
        backend = BackendEntity([prov_portal])
        prov_targets_response = entities.ProvisionerResponse([prov_target])
        mock_publish.return_value = success_prov_response
        mock_host_probe.return_value = success_prov_response
        mock_get_volumes_by_uuid.side_effect = Exception()
        mock_get_targets.return_value = prov_targets_response
        mock_get_backend_by_id.return_value = \
            entities.ProvisionerResponse([backend])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection_targets_failure(self, mock_host_probe,
                                                   mock_publish,
                                                   mock_get_volumes_by_uuid,
                                                   mock_get_targets,
                                                   mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_portal = PortalEntity('1.2.3.4', 4420, 'TCP')
        backend = BackendEntity([prov_portal])
        mock_publish.return_value = success_prov_response
        mock_host_probe.return_value = success_prov_response
        mock_get_volumes_by_uuid.return_value = prov_volumes_response
        mock_get_targets.return_value = fail_prov_response
        mock_get_backend_by_id.return_value = \
            entities.ProvisionerResponse([backend])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection_no_targets(self, mock_host_probe,
                                              mock_publish,
                                              mock_get_volumes_by_uuid,
                                              mock_get_targets,
                                              mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_portal = PortalEntity('1.2.3.4', 4420, 'TCP')
        backend = BackendEntity([prov_portal])
        mock_publish.return_value = success_prov_response
        mock_host_probe.return_value = success_prov_response
        mock_get_volumes_by_uuid.return_value = prov_volumes_response
        mock_get_targets.return_value = no_entities_prov_response
        mock_get_backend_by_id.return_value = \
            entities.ProvisionerResponse([backend])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection_targets_exception(self, mock_host_probe,
                                                     mock_publish,
                                                     mock_get_volumes_by_uuid,
                                                     mock_get_targets,
                                                     mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_portal = PortalEntity('1.2.3.4', 4420, 'TCP')
        backend = BackendEntity([prov_portal])
        mock_publish.return_value = success_prov_response
        mock_host_probe.return_value = success_prov_response
        mock_get_volumes_by_uuid.return_value = prov_volumes_response
        mock_get_targets.side_effect = Exception()
        mock_get_backend_by_id.return_value = \
            entities.ProvisionerResponse([backend])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection_backend_failure(self, mock_host_probe,
                                                   mock_publish,
                                                   mock_get_volumes_by_uuid,
                                                   mock_get_targets,
                                                   mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_target = TargetEntity('target.nqn', prov_backend1)
        prov_targets_response = entities.ProvisionerResponse([prov_target])
        mock_publish.return_value = success_prov_response
        mock_host_probe.return_value = success_prov_response
        mock_get_volumes_by_uuid.return_value = prov_volumes_response
        mock_get_targets.return_value = prov_targets_response
        mock_get_backend_by_id.return_value = fail_prov_response
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection_no_backend(self, mock_host_probe,
                                              mock_publish,
                                              mock_get_volumes_by_uuid,
                                              mock_get_targets,
                                              mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_target = TargetEntity('target.nqn', prov_backend1)
        prov_targets_response = entities.ProvisionerResponse([prov_target])
        mock_publish.return_value = success_prov_response
        mock_host_probe.return_value = success_prov_response
        mock_get_volumes_by_uuid.return_value = prov_volumes_response
        mock_get_targets.return_value = prov_targets_response
        mock_get_backend_by_id.return_value = no_entities_prov_response
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_backend_by_id')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_targets')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_volumes_by_uuid')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'publish')
    @mock.patch.object(rest_client.KioxiaProvisioner, 'host_probe')
    def test_initialize_connection_backend_exception(self, mock_host_probe,
                                                     mock_publish,
                                                     mock_get_volumes_by_uuid,
                                                     mock_get_targets,
                                                     mock_get_backend_by_id):
        testvol = _stub_volume()
        testconn = _stub_connector()
        prov_target = TargetEntity('target.nqn', prov_backend1)
        prov_targets_response = entities.ProvisionerResponse([prov_target])
        mock_publish.return_value = success_prov_response
        mock_host_probe.return_value = success_prov_response
        mock_get_volumes_by_uuid.return_value = prov_volumes_response
        mock_get_targets.return_value = prov_targets_response
        mock_get_backend_by_id.side_effect = Exception()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'unpublish')
    def test_terminate_connection(self, mock_unpublish):
        testvol = _stub_volume()
        testconn = _stub_connector()
        mock_unpublish.return_value = success_prov_response
        result = self.driver.terminate_connection(testvol, testconn)
        mock_unpublish.assert_any_call(testconn['uuid'], testvol['id'])
        self.assertIsNone(result)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'unpublish')
    def test_terminate_connection_unpublish_failure(self, mock_unpublish):
        testvol = _stub_volume()
        testconn = _stub_connector()
        mock_unpublish.return_value = fail_prov_response
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'unpublish')
    def test_terminate_connection_unpublish_exception(self, mock_unpublish):
        testvol = _stub_volume()
        testconn = _stub_connector()
        mock_unpublish.side_effect = Exception()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection, testvol, testconn)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_tenants')
    def test_get_volume_stats(self, mock_get_tenants):
        tenant = TenantEntity(1000, 400)
        mock_get_tenants.return_value = entities.ProvisionerResponse([tenant])
        result = self.driver.get_volume_stats(True)
        mock_get_tenants.assert_any_call()
        self.assertDictEqual(result, self.expected_stats)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_tenants')
    def test_get_volume_stats_tenants_failure(self, mock_get_tenants):
        mock_get_tenants.return_value = fail_prov_response
        self.expected_stats['total_capacity_gb'] = 'unknown'
        self.expected_stats['free_capacity_gb'] = 'unknown'
        self.assertDictEqual(
            self.driver.get_volume_stats(True), self.expected_stats)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_tenants')
    def test_get_volume_stats_no_tenants(self, mock_get_tenants):
        mock_get_tenants.return_value = no_entities_prov_response
        self.expected_stats['total_capacity_gb'] = 'unknown'
        self.expected_stats['free_capacity_gb'] = 'unknown'
        self.assertDictEqual(
            self.driver.get_volume_stats(True), self.expected_stats)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'get_tenants')
    def test_get_volume_stats_tenants_exception(self, mock_get_tenants):
        mock_get_tenants.side_effect = Exception()
        self.expected_stats['total_capacity_gb'] = 'unknown'
        self.expected_stats['free_capacity_gb'] = 'unknown'
        self.assertDictEqual(
            self.driver.get_volume_stats(True), self.expected_stats)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'create_snapshot')
    def test_create_snapshot_success(self, mock_create_snapshot):
        testsnap = _stub_snapshot()
        mock_create_snapshot.return_value = success_prov_response
        result = self.driver.create_snapshot(testsnap)
        args, kwargs = mock_create_snapshot.call_args
        mock_call = args[0]
        self.assertEqual(mock_call.alias, testsnap['name'])
        self.assertEqual(mock_call.volumeID, testsnap['volume_id'])
        self.assertEqual(mock_call.snapshotID, testsnap['id'])
        self.assertIsNone(result)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'create_snapshot')
    def test_create_snapshot_failure(self, mock_create_snapshot):
        testsnap = _stub_snapshot()
        mock_create_snapshot.return_value = fail_prov_response
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, testsnap)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'create_snapshot')
    def test_create_snapshot_exception(self, mock_create_snapshot):
        testsnap = _stub_snapshot()
        mock_create_snapshot.side_effect = Exception()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, testsnap)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'delete_snapshot')
    def test_delete_snapshot_success(self, mock_delete_snapshot):
        testsnap = _stub_snapshot()
        mock_delete_snapshot.return_value = success_prov_response
        result = self.driver.delete_snapshot(testsnap)
        mock_delete_snapshot.assert_any_call(testsnap['id'])
        self.assertIsNone(result)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'delete_snapshot')
    def test_delete_snapshot_failure(self, mock_delete_snapshot):
        testsnap = _stub_snapshot()
        mock_delete_snapshot.return_value = fail_prov_response
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot, testsnap)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'delete_snapshot')
    def test_delete_snapshot_exception(self, mock_delete_snapshot):
        testsnap = _stub_snapshot()
        mock_delete_snapshot.side_effect = Exception()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot, testsnap)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'create_snapshot_volume')
    def test_create_volume_from_snapshot_success(self,
                                                 mock_create_snapshot_volume):
        testsnap = _stub_snapshot()
        testvol = _stub_volume()
        mock_create_snapshot_volume.return_value = success_prov_response
        result = self.driver.create_volume_from_snapshot(testvol, testsnap)
        args, kwargs = mock_create_snapshot_volume.call_args
        mock_call = args[0]
        self.assertEqual(mock_call.alias, testvol['name'])
        self.assertEqual(mock_call.volumeID, testsnap['volume_id'])
        self.assertEqual(mock_call.snapshotID, testsnap['id'])
        self.assertEqual(mock_call.protocol, VOL_PROTOCOL)
        self.assertIsNone(result)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'create_snapshot_volume')
    def test_create_volume_from_snapshot_failure(self,
                                                 mock_create_snapshot_volume):
        testsnap = _stub_snapshot()
        testvol = _stub_volume()
        mock_create_snapshot_volume.return_value = fail_prov_response
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot, testvol,
                          testsnap)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'create_snapshot_volume')
    def test_create_volume_from_snapshot_exception(
            self, mock_create_snapshot_volume):
        testsnap = _stub_snapshot()
        testvol = _stub_volume()
        mock_create_snapshot_volume.side_effect = Exception()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot, testvol,
                          testsnap)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'expand_volume')
    def test_extend_volume_success(self, mock_expand_volume):
        testvol = _stub_volume()
        mock_expand_volume.return_value = success_prov_response
        new_size = VOL_SIZE + 2
        result = self.driver.extend_volume(testvol, new_size)
        mock_expand_volume.assert_any_call(new_size, testvol['id'])
        self.assertIsNone(result)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'expand_volume')
    def test_extend_volume_failure(self, mock_expand_volume):
        testvol = _stub_volume()
        mock_expand_volume.return_value = fail_prov_response
        new_size = VOL_SIZE + 2
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume, testvol, new_size)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'expand_volume')
    def test_extend_volume_exception(self, mock_expand_volume):
        testvol = _stub_volume()
        mock_expand_volume.side_effect = Exception()
        new_size = VOL_SIZE + 2
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume, testvol, new_size)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'clone_volume')
    def test_create_cloned_volume_success(self, mock_clone_volume):
        testvol = _stub_volume()
        mock_clone_volume.return_value = success_prov_response
        result = self.driver.create_cloned_volume(testvol, testvol)
        args, kwargs = mock_clone_volume.call_args
        mock_call = args[0]
        self.assertEqual(mock_call.alias, testvol['name'])
        self.assertEqual(mock_call.capacity, testvol['size'])
        self.assertEqual(mock_call.volumeId, testvol['id'])
        self.assertEqual(mock_call.sourceVolumeId, testvol['id'])
        self.assertIsNone(result)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'clone_volume')
    def test_create_cloned_volume_failure(self, mock_clone_volume):
        testvol = _stub_volume()
        mock_clone_volume.return_value = fail_prov_response
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume, testvol, testvol)

    @mock.patch.object(rest_client.KioxiaProvisioner, 'clone_volume')
    def test_create_cloned_volume_exception(self, mock_clone_volume):
        testvol = _stub_volume()
        mock_clone_volume.side_effect = Exception()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume, testvol, testvol)

    def test_convert_host_name(self):
        name = 'ks-node3-000c2960a794-000c2960a797'
        result = self.driver._convert_host_name(name)
        expected = md5(name.encode('utf-8'), usedforsecurity=False).hexdigest()
        self.assertEqual(result, expected)

    def test_create_export(self):
        result = self.driver.create_export(None, None, None)
        self.assertIsNone(result)

    def test_ensure_export(self):
        result = self.driver.ensure_export(None, None)
        self.assertIsNone(result)

    def test_remove_export(self):
        result = self.driver.remove_export(None, None)
        self.assertIsNone(result)

    def test_check_for_setup_error(self):
        result = self.driver.check_for_setup_error()
        self.assertIsNone(result)


def _stub_volume(*args, **kwargs):
    volume = {'id': kwargs.get('id', VOL_UUID),
              'name': kwargs.get('name', VOL_NAME),
              'project_id': "test-project",
              'display_name': kwargs.get('display_name', VOL_NAME),
              'size': kwargs.get('size', VOL_SIZE),
              'provider_location': kwargs.get('provider_location', None),
              'volume_type_id': kwargs.get('volume_type_id', None)}
    return volume


def _stub_connector(*args, **kwargs):
    connector = {'uuid': kwargs.get('uuid', CONN_UUID),
                 'nqn': kwargs.get('nqn', CONN_NQN),
                 'host': kwargs.get('host', CONN_HOST_NAME)}
    return connector


def _stub_snapshot(*args, **kwargs):
    volume = {'id': kwargs.get('id', SNAP_UUID),
              'name': kwargs.get('name', 'snap2000'),
              'volume_id': kwargs.get('id', VOL_UUID)}
    return volume


class TenantEntity:
    def __init__(self, capacity, consumed):
        self.tenantId = '0'
        self.capacity = capacity
        self.consumedCapacity = consumed


class TargetEntity:
    def __init__(self, name, backend):
        self.targetName = name
        self.backend = backend


class BackendEntity:
    def __init__(self, portals):
        self.portals = portals


class PortalEntity:
    def __init__(self, ip, port, transport):
        self.ip = ip
        self.port = port
        self.transport = transport


if __name__ == '__main__':
    unittest.main()
