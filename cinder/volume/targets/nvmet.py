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

import tempfile

from oslo_concurrency import processutils as putils
from oslo_log import log as logging
from oslo_serialization import jsonutils as json
from oslo_utils import excutils
from oslo_utils import uuidutils

from cinder import exception
from cinder.privsep import nvmcli
import cinder.privsep.path
from cinder import utils
from cinder.volume.targets import nvmeof


LOG = logging.getLogger(__name__)


class NVMETTargetAddError(exception.CinderException):
    message = "Failed to add subsystem: %(subsystem)s"


class NVMETTargetDeleteError(exception.CinderException):
    message = "Failed to delete subsystem: %(subsystem)s"


class NVMET(nvmeof.NVMeOF):

    @utils.synchronized('nvmetcli', external=True)
    def create_nvmeof_target(self,
                             volume_id,
                             subsystem_name,
                             target_ip,
                             target_port,
                             transport_type,
                             nvmet_port_id,
                             ns_id,
                             volume_path):

        # Create NVME subsystem for previously created LV
        nvmf_subsystems = self._get_available_nvmf_subsystems()

        # Check if subsystem already exists
        search_for_subsystem = self._get_nvmf_subsystem(
            nvmf_subsystems, volume_id)
        if search_for_subsystem is None:
            newly_added_subsystem = self._add_nvmf_subsystem(
                nvmf_subsystems,
                target_ip,
                target_port,
                nvmet_port_id,
                subsystem_name,
                ns_id, volume_id, volume_path)
            if newly_added_subsystem is None:
                LOG.error('Failed to add subsystem: %s', subsystem_name)
                raise NVMETTargetAddError(subsystem=subsystem_name)
            LOG.info('Added subsystem: %s', newly_added_subsystem)
            search_for_subsystem = newly_added_subsystem
        else:
            LOG.debug('Skip creating subsystem %s as '
                      'it already exists.', search_for_subsystem)
        return {
            'location': self.get_nvmeof_location(
                search_for_subsystem,
                target_ip,
                target_port,
                transport_type,
                ns_id),
            'auth': ''}

    def _restore(self, nvmf_subsystems):
        # Dump updated JSON dict to append new subsystem
        with tempfile.NamedTemporaryFile(mode='w') as tmp_fd:
            tmp_fd.write(json.dumps(nvmf_subsystems))
            tmp_fd.flush()
            try:
                out, err = nvmcli.restore(tmp_fd.name)
            except putils.ProcessExecutionError:
                with excutils.save_and_reraise_exception():
                    LOG.exception('Error from nvmetcli restore')

    def _add_nvmf_subsystem(self, nvmf_subsystems, target_ip, target_port,
                            nvmet_port_id, nvmet_subsystem_name, nvmet_ns_id,
                            volume_id, volume_path):

        subsystem_name = self._get_target_info(nvmet_subsystem_name, volume_id)
        # Create JSON sections for the new subsystem to be created
        # Port section
        port_section = {
            "addr": {
                "adrfam": "ipv4",
                "traddr": target_ip,
                "treq": "not specified",
                "trsvcid": target_port,
                "trtype": "rdma"
            },
            "portid": nvmet_port_id,
            "referrals": [],
            "subsystems": [subsystem_name]
        }
        nvmf_subsystems['ports'].append(port_section)

        # Subsystem section
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
            "nqn": subsystem_name}
        nvmf_subsystems['subsystems'].append(subsystem_section)

        LOG.info(
            'Trying to load the following subsystems: %s', nvmf_subsystems)

        self._restore(nvmf_subsystems)

        return subsystem_name

    @utils.synchronized('nvmetcli', external=True)
    def delete_nvmeof_target(self, volume):
        nvmf_subsystems = self._get_available_nvmf_subsystems()
        subsystem_name = self._get_nvmf_subsystem(
            nvmf_subsystems, volume['id'])
        if subsystem_name:
            removed_subsystem = self._delete_nvmf_subsystem(
                nvmf_subsystems, subsystem_name)
            if removed_subsystem is None:
                LOG.error(
                    'Failed to delete subsystem: %s', subsystem_name)
                raise NVMETTargetDeleteError(subsystem=subsystem_name)
            elif removed_subsystem == subsystem_name:
                LOG.info(
                    'Managed to delete subsystem: %s', subsystem_name)
                return removed_subsystem
        else:
            LOG.info("Skipping remove_export. No NVMe subsystem "
                     "for volume: %s", volume['id'])

    def _delete_nvmf_subsystem(self, nvmf_subsystems, subsystem_name):
        LOG.debug(
            'Removing this subsystem: %s', subsystem_name)

        for port in nvmf_subsystems['ports']:
            if subsystem_name in port['subsystems']:
                port['subsystems'].remove(subsystem_name)
                break
        for subsys in nvmf_subsystems['subsystems']:
            if subsys['nqn'] == subsystem_name:
                nvmf_subsystems['subsystems'].remove(subsys)
                break

        LOG.debug(
            'Newly loaded subsystems will be: %s', nvmf_subsystems)
        self._restore(nvmf_subsystems)
        return subsystem_name

    def _get_nvmf_subsystem(self, nvmf_subsystems, volume_id):
        subsystem_name = self._get_target_info(
            self.nvmet_subsystem_name, volume_id)
        for subsys in nvmf_subsystems['subsystems']:
            if subsys['nqn'] == subsystem_name:
                return subsystem_name

    def _get_available_nvmf_subsystems(self):
        __, tmp_file_path = tempfile.mkstemp(prefix='nvmet')

        # nvmetcli doesn't support printing to stdout yet,
        try:
            out, err = nvmcli.save(tmp_file_path)
        except putils.ProcessExecutionError:
            with excutils.save_and_reraise_exception():
                LOG.exception('Error from nvmetcli save')
                self._delete_file(tmp_file_path)

        # temp file must be readable by this process user
        # in order to avoid executing cat as root
        with utils.temporary_chown(tmp_file_path):
            try:
                out = cinder.privsep.path.readfile(tmp_file_path)
            except putils.ProcessExecutionError:
                with excutils.save_and_reraise_exception():
                    LOG.exception('Failed to read: %s', tmp_file_path)
                    self._delete_file(tmp_file_path)
            nvmf_subsystems = json.loads(out)

        self._delete_file(tmp_file_path)

        return nvmf_subsystems

    def _get_target_info(self, subsystem, volume_id):
        return "nqn.%s-%s" % (subsystem, volume_id)

    def _delete_file(self, file_path):
        try:
            cinder.privsep.path.removefile(file_path)
        except putils.ProcessExecutionError:
            LOG.exception('Failed to delete file: %s', file_path)
