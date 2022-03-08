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

from oslo_log import log as logging
from oslo_utils import uuidutils

from cinder import exception
from cinder.privsep.targets import nvmet
from cinder import utils
from cinder.volume.targets import nvmeof


LOG = logging.getLogger(__name__)


class NVMETTargetAddError(exception.CinderException):
    message = "Failed to add subsystem: %(subsystem)s"


class NVMETTargetDeleteError(exception.CinderException):
    message = "Failed to delete subsystem: %(subsystem)s"


class NVMET(nvmeof.NVMeOF):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._nvmet_root = nvmet.Root()

    @utils.synchronized('nvmetcli', external=True)
    def create_nvmeof_target(self,
                             volume_id,
                             subsystem_name,  # Ignoring this, using config
                             target_ip,
                             target_port,
                             transport_type,
                             nvmet_port_id,
                             ns_id,
                             volume_path):
        # Create NVME subsystem for previously created LV
        nqn = self._get_target_nqn(volume_id)
        try:
            self._ensure_subsystem_exists(nqn, ns_id, volume_path)
            self._ensure_port_exports(nqn, target_ip, target_port,
                                      transport_type, nvmet_port_id)
        except Exception:
            LOG.error('Failed to add subsystem: %s', nqn)
            raise NVMETTargetAddError(subsystem=nqn)

        LOG.info('Subsystem %s now exported on port %s', nqn, target_port)
        return {
            'location': self.get_nvmeof_location(
                nqn,
                target_ip,
                target_port,
                transport_type,
                ns_id),
            'auth': ''}

    def _ensure_subsystem_exists(self, nqn, nvmet_ns_id, volume_path):
        # Assume if subsystem exists, it has the right configuration
        try:
            nvmet.Subsystem(nqn)
            LOG.debug('Skip creating subsystem %s as it already exists.', nqn)
            return
        except nvmet.NotFound:
            LOG.debug('Creating subsystem %s.', nqn)

        subsystem_section = {
            "allowed_hosts": [],
            "attr": {
                "allow_any_host": "1"
            },
            "namespaces": [
                {
                    "device": {
                        "nguid": str(uuidutils.generate_uuid()),
                        "path": volume_path,
                    },
                    "enable": 1,
                    "nsid": nvmet_ns_id
                }
            ],
            "nqn": nqn}

        nvmet.Subsystem.setup(subsystem_section)  # privsep
        LOG.debug('Added subsystem: %s', nqn)

    def _ensure_port_exports(self, nqn, addr, port, transport_type, port_id):
        # Assume if port exists, it has the right configuration
        try:
            port = nvmet.Port(port_id)
            LOG.debug('Skip creating port %s as it already exists.', port_id)
        except nvmet.NotFound:
            LOG.debug('Creating port %s.', port_id)

            # Port section
            port_section = {
                "addr": {
                    "adrfam": "ipv4",
                    "traddr": addr,
                    "treq": "not specified",
                    "trsvcid": port,
                    "trtype": transport_type,
                },
                "portid": port_id,
                "referrals": [],
                "subsystems": [nqn]
            }
            nvmet.Port.setup(self._nvmet_root, port_section)  # privsep
            LOG.debug('Added port: %s', port_id)

        else:
            if nqn in port.subsystems:
                LOG.debug('%s already exported on port %s', nqn, port_id)
            else:
                port.add_subsystem(nqn)  # privsep
                LOG.debug('Exported %s on port %s', nqn, port_id)

    @utils.synchronized('nvmetcli', external=True)
    def delete_nvmeof_target(self, volume):
        subsystem_name = self._get_target_nqn(volume.id)
        LOG.debug('Removing subsystem: %s', subsystem_name)

        for port in self._nvmet_root.ports:
            if subsystem_name in port.subsystems:
                LOG.debug('Removing %s from port %s',
                          subsystem_name, port.portid)
                port.remove_subsystem(subsystem_name)

        try:
            subsys = nvmet.Subsystem(subsystem_name)
            LOG.debug('Deleting %s', subsystem_name)
            subsys.delete()  # privsep call
            LOG.info('Subsystem %s removed', subsystem_name)
        except nvmet.NotFound:
            LOG.info('Skipping remove_export. No NVMe subsystem for volume: '
                     '%s', volume.id)
        except Exception:
            LOG.error('Failed to delete subsystem: %s', subsystem_name)
            raise NVMETTargetDeleteError(subsystem=subsystem_name)
        LOG.info('Volume %s is no longer exported', volume.id)

    def _get_available_nvmf_subsystems(self):
        nvme_root = nvmet.Root()
        subsystems = nvme_root.dump()
        return subsystems

    def _get_target_nqn(self, volume_id):
        return "nqn.%s-%s" % (self.nvmet_subsystem_name, volume_id)
