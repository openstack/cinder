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

from unittest import mock

from oslo_utils import timeutils

from cinder import context
from cinder.tests.unit.targets import targets_fixture as tf
from cinder import utils
from cinder.volume.targets import nvmet


class TestNVMETDriver(tf.TargetDriverFixture):

    def setUp(self):
        super(TestNVMETDriver, self).setUp()

        self.configuration.target_protocol = 'nvmet_rdma'
        self.target = nvmet.NVMET(root_helper=utils.get_root_helper(),
                                  configuration=self.configuration)

        self.target_ip = '192.168.0.1'
        self.target_port = '1234'
        self.nvmet_subsystem_name = self.configuration.target_prefix
        self.nvmet_ns_id = self.configuration.nvmet_ns_id
        self.nvmet_port_id = self.configuration.nvmet_port_id
        self.nvme_transport_type = 'rdma'

        self.fake_volume_id = 'c446b9a2-c968-4260-b95f-a18a7b41c004'
        self.testvol_path = (
            '/dev/stack-volumes-lvmdriver-1/volume-%s' % self.fake_volume_id)
        self.fake_project_id = 'ed2c1fd4-5555-1111-aa15-123b93f75cba'
        self.testvol = (
            {'project_id': self.fake_project_id,
             'name': 'testvol',
             'size': 1,
             'id': self.fake_volume_id,
             'volume_type_id': None,
             'provider_location': self.target.get_nvmeof_location(
                 "nqn.%s-%s" % (self.nvmet_subsystem_name,
                                self.fake_volume_id),
                 self.target_ip, self.target_port, self.nvme_transport_type,
                 self.nvmet_ns_id),
             'provider_auth': None,
             'provider_geometry': None,
             'created_at': timeutils.utcnow(),
             'host': 'fake_host@lvm#lvm'})

    @mock.patch.object(nvmet.NVMET, '_get_nvmf_subsystem')
    @mock.patch.object(nvmet.NVMET, '_get_available_nvmf_subsystems')
    @mock.patch.object(nvmet.NVMET, '_add_nvmf_subsystem')
    def test_create_export(self, mock_add_nvmf_subsystem,
                           mock_get_available_nvmf_subsystems,
                           mock_get_nvmf_subsystem):

        mock_testvol = self.testvol
        mock_testvol_path = self.testvol_path
        ctxt = context.get_admin_context()
        mock_get_available_nvmf_subsystems.return_value = {
            "subsystems": [],
            "hosts": [],
            "ports": [
                {"subsystems": [],
                 "referrals": [],
                 "portid": 1,
                 "addr":
                 {"treq": "not specified",
                          "trtype": "rdma",
                          "adrfam": "ipv4",
                          "trsvcid": self.target_port,
                          "traddr":
                              self.target_ip
                  }
                 }]
        }
        mock_get_nvmf_subsystem.return_value = (
            "nqn.%s-%s" % (self.nvmet_subsystem_name,
                           mock_testvol['id']))

        mock_add_nvmf_subsystem.return_value = (
            "nqn.%s-%s" % (self.nvmet_subsystem_name,
                           mock_testvol['id']))

        expected_return = {
            'location': self.target.get_nvmeof_location(
                mock_add_nvmf_subsystem.return_value, self.target_ip,
                self.target_port, self.nvme_transport_type, self.nvmet_ns_id),
            'auth': ''
        }

        self.target.target_ip = self.target_ip
        self.target.target_port = self.target_port
        self.assertEqual(expected_return,
                         self.target.create_export(
                             ctxt, mock_testvol,
                             mock_testvol_path))

    @mock.patch.object(nvmet.NVMET, '_get_nvmf_subsystem')
    @mock.patch.object(nvmet.NVMET, '_get_available_nvmf_subsystems')
    @mock.patch.object(nvmet.NVMET, '_add_nvmf_subsystem')
    def test_create_export_with_error_add_nvmf_subsystem(
            self,
            mock_add_nvmf_subsystem,
            mock_get_available_nvmf_subsystems,
            mock_get_nvmf_subsystem):

        mock_testvol = self.testvol
        mock_testvol_path = self.testvol_path
        ctxt = context.get_admin_context()
        mock_get_available_nvmf_subsystems.return_value = {
            "subsystems": [],
            "hosts": [],
            "ports": [
                {"subsystems": [],
                 "referrals": [],
                 "portid": 1,
                 "addr":
                 {"treq": "not specified",
                          "trtype": "rdma",
                          "adrfam": "ipv4",
                          "trsvcid": self.target_port,
                          "traddr":
                              self.target_ip
                  }
                 }]
        }
        mock_get_nvmf_subsystem.return_value = None

        mock_add_nvmf_subsystem.return_value = None

        self.target.target_ip = self.target_ip
        self.target.target_port = self.target_port
        self.assertRaises(nvmet.NVMETTargetAddError,
                          self.target.create_export,
                          ctxt,
                          mock_testvol,
                          mock_testvol_path)

    @mock.patch.object(nvmet.NVMET, '_get_nvmf_subsystem')
    @mock.patch.object(nvmet.NVMET, '_get_available_nvmf_subsystems')
    @mock.patch.object(nvmet.NVMET, '_delete_nvmf_subsystem')
    def test_remove_export(self, mock_delete_nvmf_subsystem,
                           mock_get_available_nvmf_subsystems,
                           mock_get_nvmf_subsystem):
        mock_testvol = self.testvol
        mock_testvol_path = self.testvol_path
        ctxt = context.get_admin_context()
        mock_get_available_nvmf_subsystems.return_value = {
            "subsystems": [
                {"allowed_hosts": [],
                 "nqn": "nqn.%s-%s" % (
                     self.nvmet_subsystem_name,
                     mock_testvol['id']),
                 "attr": {"allow_any_host": "1"},
                 "namespaces": [
                 {"device":
                  {"path": mock_testvol_path,
                   "nguid":
                   "86fab0e0-825d-4f25-a449-28b93c5e8dd6"
                   },
                  "enable": 1, "nsid":
                  self.nvmet_ns_id,
                  }]}],
            "hosts": [],
            "ports": [
                {"subsystems": [
                    "nqn.%s-%s" % (self.nvmet_subsystem_name,
                                   mock_testvol['id'])],
                 "referrals": [],
                 "portid": self.nvmet_port_id,
                 "addr":
                 {"treq": "not specified",
                  "trtype": "rdma",
                  "adrfam": "ipv4",
                  "trsvcid": self.target_port,
                  "traddr": self.target_ip}}
            ]
        }

        mock_get_nvmf_subsystem.return_value = (
            "nqn.%s-%s" % (self.nvmet_subsystem_name,
                           mock_testvol['id']))
        mock_delete_nvmf_subsystem.return_value = (
            "nqn.%s-%s" % (self.nvmet_subsystem_name,
                           mock_testvol['id']))
        expected_return = mock_delete_nvmf_subsystem.return_value
        self.assertEqual(expected_return,
                         self.target.remove_export(ctxt, mock_testvol))

    @mock.patch.object(nvmet.NVMET, '_get_nvmf_subsystem')
    @mock.patch.object(nvmet.NVMET, '_get_available_nvmf_subsystems')
    def test_remove_export_with_empty_subsystems(
            self,
            mock_get_available_nvmf_subsystems,
            mock_get_nvmf_subsystem):
        mock_testvol = self.testvol
        ctxt = context.get_admin_context()
        mock_get_available_nvmf_subsystems.return_value = {
            "subsystems": [],
            "hosts": [],
            "ports": []
        }
        mock_get_nvmf_subsystem.return_value = None
        self.assertIsNone(self.target.remove_export(ctxt, mock_testvol))

    @mock.patch.object(nvmet.NVMET, '_get_nvmf_subsystem')
    @mock.patch.object(nvmet.NVMET, '_get_available_nvmf_subsystems')
    @mock.patch.object(nvmet.NVMET, '_delete_nvmf_subsystem')
    def test_remove_export_with_delete_nvmf_subsystem_fails(
            self,
            moc_delete_nvmf_subsystem,
            mock_get_available_nvmf_subsystems,
            mock_get_nvmf_subsystem):
        mock_testvol = self.testvol
        mock_testvol_path = self.testvol_path
        ctxt = context.get_admin_context()
        mock_get_available_nvmf_subsystems.return_value = {
            "subsystems": [
                {"allowed_hosts": [],
                 "nqn": "nqn.%s-%s" % (
                     self.nvmet_subsystem_name,
                     mock_testvol['id']),
                 "attr": {"allow_any_host": "1"},
                 "namespaces": [
                 {"device":
                  {"path": mock_testvol_path,
                   "nguid":
                   "86fab0e0-825d-4f25-a449-28b93c5e8dd6"
                   },
                  "enable": 1, "nsid":
                  self.nvmet_ns_id,
                  }]}],
            "hosts": [],
            "ports": [
                {"subsystems": [
                    "nqn.%s-%s" % (self.nvmet_subsystem_name,
                                   mock_testvol['id'])],
                 "referrals": [],
                 "portid": self.nvmet_port_id,
                 "addr":
                 {"treq": "not specified",
                  "trtype": "rdma",
                  "adrfam": "ipv4",
                  "trsvcid": self.target_port,
                  "traddr": self.target_ip}}
            ]
        }
        mock_get_nvmf_subsystem.return_value = (
            "nqn.%s-%s" % (self.nvmet_subsystem_name,
                           mock_testvol['id']))
        moc_delete_nvmf_subsystem.return_value = None
        self.assertRaises(nvmet.NVMETTargetDeleteError,
                          self.target.remove_export,
                          ctxt,
                          mock_testvol)
