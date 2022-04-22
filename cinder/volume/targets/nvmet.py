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

import os

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
    SHARED_TARGET_SUPPORT = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._nvmet_root = nvmet.Root()

    # #######  Connection initiation methods ########

    def initialize_connection(self, volume, connector):
        """Create an export & map if shared."""
        # Non-shared connections was the original implementation where all the
        # export & mapping was done on export and the connection info was
        # stored in the volume, so let the original implementation handle it.
        if not self.share_targets:
            return super().initialize_connection(volume, connector)

        # For the shared case the export only stores the path of the volume
        volume_path = volume.provider_location
        if not os.path.exists(volume_path):
            raise exception.InvalidConfigurationValue(
                'Target driver configured with shared targets, but volume '
                'exported as non shared.')

        nqn, ns_id = self._map_volume(volume, volume_path, connector)
        uuid = self._get_nvme_uuid(volume)
        return {
            'driver_volume_type': self.protocol,
            'data': self._get_connection_properties(nqn,
                                                    self.target_ips,
                                                    self.target_port,
                                                    self.nvme_transport_type,
                                                    ns_id, uuid),
        }

    def create_export(self, context, volume, volume_path):
        """Create an export & map if not shared."""
        # For shared targets everything gets done on initialize_connection
        if self.share_targets:
            location = volume_path
        else:
            nqn, ns_id = self._map_volume(volume, volume_path)
            location = self.get_nvmeof_location(nqn,
                                                self.target_ips,
                                                self.target_port,
                                                self.nvme_transport_type,
                                                ns_id)

        return {'location': location, 'auth': ''}

    @utils.synchronized('nvmetcli', external=True)
    def _map_volume(self, volume, volume_path, connector=None):
        """Ensure a volume is exported and mapped in nvmet."""
        # Create NVME subsystem for previously created LV
        nqn = self._get_target_nqn(volume.id, connector)
        try:
            uuid = self._get_nvme_uuid(volume)

            ns_id = self._ensure_subsystem_exists(nqn, volume_path, uuid)

            self._ensure_port_exports(nqn, self.target_ips, self.target_port,
                                      self.nvme_transport_type,
                                      self.nvmet_port_id)
        except Exception:
            LOG.error('Failed to add subsystem: %s', nqn)
            raise NVMETTargetAddError(subsystem=nqn)

        LOG.info('Subsystem %s now exported on port %s', nqn, self.target_port)
        return nqn, ns_id

    def _ensure_subsystem_exists(self, nqn, volume_path, uuid):
        """Ensure a subsystem and namespace exist in nvmet."""
        # Assume if subsystem exists, it has the right configuration
        try:
            subsystem = nvmet.Subsystem(nqn)
            LOG.debug('Skip creating subsystem %s as it already exists.', nqn)

            ns_id = self._ensure_namespace_exists(subsystem, volume_path, uuid)
            return ns_id

        except nvmet.NotFound:
            LOG.debug('Creating subsystem %s.', nqn)

        ns_id = self.nvmet_ns_id
        subsystem_section = {
            "allowed_hosts": [],
            "attr": {
                "allow_any_host": "1"
            },
            "namespaces": [self._namespace_dict(uuid, volume_path, ns_id)],
            "nqn": nqn}

        nvmet.Subsystem.setup(subsystem_section)  # privsep
        LOG.debug('Added subsystem: %s', nqn)
        return ns_id

    def _namespace_dict(self, uuid, volume_path, ns_id):
        """Build the dict data for a new namespace in nvmet library format."""
        if self.share_targets:
            nguid = uuid
            LOG.debug('Sharing subsystem, using nguid = uuid = %s', nguid)
        else:
            nguid = str(uuidutils.generate_uuid())
            LOG.debug('Not sharing subsystem, using randmo nguid = %s', nguid)
        return {
            "device": {
                "nguid": nguid,
                "uuid": uuid,
                "path": volume_path,
            },
            "enable": 1,
            "nsid": ns_id
        }

    def _ensure_namespace_exists(self, subsystem, volume_path, uuid):
        """Ensure the namespace exists in nvmet."""
        for ns in subsystem.namespaces:
            if ns.get_attr('device', 'path') == volume_path:
                return ns.nsid

        ns_id = self._get_available_namespace_id(subsystem)
        ns_data = self._namespace_dict(uuid, volume_path, ns_id)
        nvmet.Namespace.setup(subsystem, ns_data)
        return ns_id

    def _get_available_namespace_id(self, subsystem):
        """Get the next available ns_id.

        Shared targets will have multiple namespaces under the same subsystem,
        so we cannot use self.nvmet_ns_id for them all.

        This method searches for an available namespace id in the provided
        subsystem considering all ids below self.nvmet_ns_id as reserved.

        We cannot let the nvmet library assign it automatically because it
        starts assigning from 1.

        For non shared the method returns configured nvmet_ns_id.
        """
        minimum = self.nvmet_ns_id

        if not self.share_targets:
            return minimum

        used = [ns.nsid for ns in subsystem.namespaces if ns.nsid >= minimum]

        if not used:
            return minimum

        higher = max(used)
        # If there are no gaps return the next available id
        if len(used) > higher - minimum:
            if higher == nvmet.Namespace.MAX_NSID:
                raise Exception('Reached max namespaces in subsystem')
            return higher + 1

        # Find an id in the gaps.  Don't include higher, as we know it's used
        available = set(range(minimum, higher)).difference(used)
        return available.pop()

    def _get_nvme_uuid(self, volume):
        return volume.name_id

    def _ensure_port_exports(self, nqn, addrs, port, transport_type, port_id):
        for addr in addrs:
            # Assume if port exists, it has the right configuration
            try:
                nvme_port = nvmet.Port(port_id)
                LOG.debug('Skip creating port %s as it already exists.',
                          port_id)
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
                if nqn in nvme_port.subsystems:
                    LOG.debug('%s already exported on port %s', nqn, port_id)
                else:
                    nvme_port.add_subsystem(nqn)  # privsep
                    LOG.debug('Exported %s on port %s', nqn, port_id)
            port_id += 1

    # #######  Connection termination methods ########

    def terminate_connection(self, volume, connector, **kwargs):
        """Remove the mapping for shared."""
        # TODO: Add support for force and other parameters
        if self.share_targets:
            self._locked_unmap_volume(volume, connector)
            LOG.info('Volume %s is no longer exported', volume.id)

    def remove_export(self, context, volume):
        """Remove the mapping for non shared."""
        if not self.share_targets:
            self._locked_unmap_volume(volume)
            LOG.info('Volume %s is no longer exported', volume.id)

    @utils.synchronized('nvmetcli', external=True)
    def _locked_unmap_volume(self, volume, connector=None):
        """Remove volume's ns from subsystem and subsystem if empty."""
        if connector or not self.share_targets:
            nqns = [self._get_target_nqn(volume.id, connector)]
        else:
            # We need to remove all existing maps (we are sharing)
            LOG.debug('Removing EVERYTHING for volume %s', volume.id)
            nqns = self._get_nqns_for_location(volume.provider_location)

        exceptions = []
        for nqn in nqns:
            try:
                self._unmap_volume(volume, nqn)
            except Exception as exc:
                exceptions.append(exc)

        # TODO: Once we only support Python 3.11+ use ExceptionGroup to raise
        # all the exceptions.
        if exceptions:
            raise exceptions[0]

    def _unmap_volume(self, volume, nqn):
        try:
            subsystem = nvmet.Subsystem(nqn)
        except nvmet.NotFound:
            LOG.info('Skipping unmapping. No NVMe subsystem for volume: %s',
                     volume.id)
            return

        if self.share_targets:
            volume_path = volume.provider_location
            for ns in subsystem.namespaces:
                if ns.get_attr('device', 'path') == volume_path:
                    LOG.debug('Deleting namespace %s', ns.nsid)
                    ns.delete()  # privsep call
                    break

            # If there are still namespaces we cannot remove the subsystem
            if any(s for s in subsystem.namespaces):
                return

        for port in self._nvmet_root.ports:
            if nqn in port.subsystems:
                LOG.debug('Removing %s from port %s', nqn, port.portid)
                port.remove_subsystem(nqn)  # privsep call

        LOG.debug('Deleting %s', nqn)
        subsystem.delete()  # privsep call
        LOG.info('Subsystem %s removed', nqn)

    # #######  General methods ########

    def _get_target_nqn(self, volume_id, connector):
        # For shared targets the subsystem is named after the host
        if self.share_targets:
            postfix = connector['host']
        else:
            postfix = volume_id
        return f'nqn.{self.nvmet_subsystem_name}-{postfix}'

    def _get_nqns_for_location(self, provider_location):
        """Get all subystem nqns for a give provider location.

        This also returns empty subsystems, since we don't know if those were
        created to try to use them for the volume of the provider_location and
        failed during the creation.

        This method needs to be called within the nvmetcli locked section.
        """
        nqns = []
        for subsys in self._nvmet_root.subsystems:
            empty = True  # subsytems is an iterable, can check it with bool
            found = False
            for ns in subsys.namespaces:
                empty = False
                if ns.get_attr('device', 'path') == provider_location:
                    found = True
                    break
            if found or empty:
                nqns.append(subsys.nqn)
        return nqns
