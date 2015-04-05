#    Copyright 2015 Dell Inc.
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

'''Volume driver for Dell Storage Center.'''

from oslo_log import log as logging
from oslo_utils import excutils

from cinder import exception
from cinder.i18n import _, _LE
from cinder.volume.drivers.dell import dell_storagecenter_common
from cinder.volume.drivers import san

LOG = logging.getLogger(__name__)


class DellStorageCenterISCSIDriver(san.SanISCSIDriver,
                                   dell_storagecenter_common.DellCommonDriver):

    '''Implements commands for Dell StorageCenter ISCSI management.

    To enable the driver add the following line to the cinder configuration:
        volume_driver=cinder.volume.drivers.dell.DellStorageCenterISCSIDriver
    '''

    VERSION = '1.0.1'

    def __init__(self, *args, **kwargs):
        super(DellStorageCenterISCSIDriver, self).__init__(*args, **kwargs)
        self.backend_name = (
            self.configuration.safe_get('volume_backend_name')
            or 'Dell-iSCSI')

    def initialize_connection(self, volume, connector):
        # We use id to name the volume name as it is a
        # known unique name.
        volume_name = volume.get('id')
        initiator_name = connector.get('initiator')
        multipath = connector.get('multipath', False)
        LOG.debug('initialize_ connection: %(n)s:%(i)s',
                  {'n': volume_name,
                   'i': initiator_name})

        with self._client.open_connection() as api:
            try:
                ssn = api.find_sc(self.configuration.dell_sc_ssn)
                # Find our server.
                server = api.find_server(ssn,
                                         initiator_name)
                # No? Create it.
                if server is None:
                    server_folder = self.configuration.dell_sc_server_folder
                    server = api.create_server(ssn,
                                               server_folder,
                                               initiator_name)
                # Find the volume on the storage center.
                scvolume = api.find_volume(ssn,
                                           volume_name)

                # if we have a server and a volume lets bring them together.
                if server is not None and scvolume is not None:
                    mapping = api.map_volume(scvolume,
                                             server)
                    if mapping is not None:
                        # Since we just mapped our volume we had best update
                        # our sc volume object.
                        scvolume = api.find_volume(ssn,
                                                   volume_name)

                        if multipath:
                            # Just return our properties with all the mappings
                            idx, iscsiproperties = (
                                api.find_iscsi_properties(scvolume,
                                                          None,
                                                          None))
                            return {'driver_volume_type': 'iscsi',
                                    'data': iscsiproperties}
                        else:
                            # Only return the iqn for the user specified port.
                            ip = self.configuration.iscsi_ip_address
                            port = self.configuration.iscsi_port
                            idx, iscsiproperties = (
                                api.find_iscsi_properties(scvolume,
                                                          ip,
                                                          port))
                            properties = {}
                            properties['target_discovered'] = False
                            portals = iscsiproperties['target_portals']
                            # We'll key off of target_portals.  If we have
                            # one listed we can assume that we found what
                            # we are looking for.  Otherwise error.
                            if len(portals) > 0:
                                properties['target_portal'] = portals[idx]
                                properties['target_iqn'] = (
                                    iscsiproperties['target_iqns'][idx])
                                properties['target_lun'] = (
                                    iscsiproperties['target_luns'][idx])
                                properties['access_mode'] = (
                                    iscsiproperties['access_mode'])
                                LOG.debug(properties)
                                return {'driver_volume_type': 'iscsi',
                                        'data': properties
                                        }
                            else:
                                LOG.error(
                                    _LE('Volume mapped to invalid path.'))
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to initialize connection '
                                  ' %(i)s %(n)s'),
                              {'i': initiator_name,
                               'n': volume_name})

        # We get here because our mapping is none or we have no valid iqn to
        # return so blow up.
        raise exception.VolumeBackendAPIException(
            _('Unable to map volume'))

    def terminate_connection(self, volume, connector, force=False, **kwargs):
        # Grab some initial info.
        initiator_name = connector.get('initiator')
        volume_name = volume.get('id')
        LOG.debug('Terminate connection: %(n)s:%(i)s',
                  {'n': volume_name,
                   'i': initiator_name})
        with self._client.open_connection() as api:
            try:
                ssn = api.find_sc(self.configuration.dell_sc_ssn)
                scserver = api.find_server(ssn,
                                           initiator_name)
                # Find the volume on the storage center.
                scvolume = api.find_volume(ssn,
                                           volume_name)

                # If we have a server and a volume lets pull them apart.
                if (scserver is not None and
                        scvolume is not None and
                        api.unmap_volume(scvolume, scserver) is True):
                    LOG.debug('Connection terminated')
                    return
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to terminate connection '
                                  '%(i)s %(n)s'),
                              {'i': initiator_name,
                               'n': volume_name})
        raise exception.VolumeBackendAPIException(
            _('Terminate connection failed'))
