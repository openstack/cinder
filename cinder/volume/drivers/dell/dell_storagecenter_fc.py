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

"""Volume driver for Dell Storage Center."""

from oslo_log import log as logging
from oslo_utils import excutils

from cinder import exception
from cinder.i18n import _, _LE
from cinder.volume import driver
from cinder.volume.drivers.dell import dell_storagecenter_common
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


class DellStorageCenterFCDriver(dell_storagecenter_common.DellCommonDriver,
                                driver.FibreChannelDriver):

    """Implements commands for Dell EqualLogic SAN ISCSI management.

    To enable the driver add the following line to the cinder configuration:
        volume_driver=cinder.volume.drivers.dell.DellStorageCenterFCDriver

    Version history:
        1.0.0 - Initial driver
        1.1.0 - Added extra spec support for Storage Profile selection
        1.2.0 - Added consistency group support.
        2.0.0 - Switched to inheriting functional objects rather than volume
                driver.
        2.1.0 - Added support for ManageableVD.
        2.2.0 - Driver retype support for switching volume's Storage Profile
        2.3.0 - Added Legacy Port Mode Support
        2.3.1 - Updated error handling.
    """

    VERSION = '2.3.1'

    def __init__(self, *args, **kwargs):
        super(DellStorageCenterFCDriver, self).__init__(*args, **kwargs)
        self.backend_name =\
            self.configuration.safe_get('volume_backend_name') or 'Dell-FC'

    @fczm_utils.AddFCZone
    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        Assign any created volume to a compute node/host so that it can be
        used from that host.

        The  driver returns a driver_volume_type of 'fibre_channel'.
        The target_wwn can be a single entry or a list of wwns that
        correspond to the list of remote wwn(s) that will export the volume.
        """

        # We use id to name the volume name as it is a
        # known unique name.
        volume_name = volume.get('id')
        LOG.debug('Initialize connection: %s', volume_name)
        with self._client.open_connection() as api:
            try:
                # Find our server.
                wwpns = connector.get('wwpns')
                for wwn in wwpns:
                    scserver = api.find_server(wwn)
                    if scserver is not None:
                        break

                # No? Create it.
                if scserver is None:
                    scserver = api.create_server_multiple_hbas(wwpns)
                # Find the volume on the storage center.
                scvolume = api.find_volume(volume_name)
                if scserver is not None and scvolume is not None:
                    mapping = api.map_volume(scvolume,
                                             scserver)
                    if mapping is not None:
                        # Since we just mapped our volume we had best update
                        # our sc volume object.
                        scvolume = api.find_volume(volume_name)
                        lun, targets, init_targ_map = api.find_wwns(scvolume,
                                                                    scserver)
                        if lun is not None and len(targets) > 0:
                            data = {'driver_volume_type': 'fibre_channel',
                                    'data': {'target_lun': lun,
                                             'target_discovered': True,
                                             'target_wwn': targets,
                                             'initiator_target_map':
                                             init_targ_map}}
                            LOG.debug('Return FC data:')
                            LOG.debug(data)
                            return data
                        LOG.error(_LE('Lun mapping returned null!'))

            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to initialize connection.'))

        # We get here because our mapping is none so blow up.
        raise exception.VolumeBackendAPIException(_('Unable to map volume.'))

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, force=False, **kwargs):
        # Get our volume name
        volume_name = volume.get('id')
        LOG.debug('Terminate connection: %s', volume_name)
        with self._client.open_connection() as api:
            try:
                wwpns = connector.get('wwpns')
                for wwn in wwpns:
                    scserver = api.find_server(wwn)
                    if scserver is not None:
                        break

                # Find the volume on the storage center.
                scvolume = api.find_volume(volume_name)
                # Get our target map so we can return it to free up a zone.
                lun, targets, init_targ_map = api.find_wwns(scvolume,
                                                            scserver)
                # If we have a server and a volume lets unmap them.
                if (scserver is not None and
                        scvolume is not None and
                        api.unmap_volume(scvolume, scserver) is True):
                    LOG.debug('Connection terminated')
                else:
                    raise exception.VolumeBackendAPIException(
                        _('Terminate connection failed'))

                # basic return info...
                info = {'driver_volume_type': 'fibre_channel',
                        'data': {}}

                # if not then we return the target map so that
                # the zone can be freed up.
                if api.get_volume_count(scserver) == 0:
                    info['data'] = {'target_wwn': targets,
                                    'initiator_target_map': init_targ_map}
                return info

            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to terminate connection'))
        raise exception.VolumeBackendAPIException(
            _('Terminate connection unable to connect to backend.'))

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()
            # Update our protocol to the correct one.
            self._stats['storage_protocol'] = 'FC'

        return self._stats
