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
from cinder.i18n import _, _LE, _LI
from cinder.volume import driver
from cinder.volume.drivers.dell import dell_storagecenter_common
LOG = logging.getLogger(__name__)


class DellStorageCenterISCSIDriver(dell_storagecenter_common.DellCommonDriver,
                                   driver.ISCSIDriver):

    """Implements commands for Dell StorageCenter ISCSI management.

    To enable the driver add the following line to the cinder configuration:
        volume_driver=cinder.volume.drivers.dell.DellStorageCenterISCSIDriver

    Version history:
        1.0.0 - Initial driver
        1.1.0 - Added extra spec support for Storage Profile selection
        1.2.0 - Added consistency group support.
        2.0.0 - Switched to inheriting functional objects rather than volume
                driver.
        2.1.0 - Added support for ManageableVD.
        2.2.0 - Driver retype support for switching volume's Storage Profile.
                Added API 2.2 support.
        2.3.0 - Added Legacy Port Mode Support
        2.3.1 - Updated error handling.
    """

    VERSION = '2.3.1'

    def __init__(self, *args, **kwargs):
        super(DellStorageCenterISCSIDriver, self).__init__(*args, **kwargs)
        self.backend_name = (
            self.configuration.safe_get('volume_backend_name')
            or 'Dell-iSCSI')

    def initialize_connection(self, volume, connector):
        # Initialize_connection will find or create a server identified by the
        # connector on the Dell backend.  It will then map the volume to it
        # and return the properties as follows..
        # {'driver_volume_type': 'iscsi',
        #  data = {'target_discovered': False,
        #          'target_iqn': preferred iqn,
        #           'target_iqns': all iqns,
        #           'target_portal': preferred portal,
        #           'target_portals': all portals,
        #           'target_lun': preferred lun,
        #           'target_luns': all luns,
        #           'access_mode': access_mode
        #         }

        # We use id to name the volume name as it is a
        # known unique name.
        volume_name = volume.get('id')
        initiator_name = connector.get('initiator')
        multipath = connector.get('multipath', False)
        LOG.info(_LI('initialize_ connection: %(vol)s:%(initiator)s'),
                 {'vol': volume_name,
                  'initiator': initiator_name})

        with self._client.open_connection() as api:
            try:
                # Find our server.
                server = api.find_server(initiator_name)
                # No? Create it.
                if server is None:
                    server = api.create_server(initiator_name)
                # Find the volume on the storage center.
                scvolume = api.find_volume(volume_name)

                # if we have a server and a volume lets bring them together.
                if server is not None and scvolume is not None:
                    mapping = api.map_volume(scvolume,
                                             server)
                    if mapping is not None:
                        # Since we just mapped our volume we had best update
                        # our sc volume object.
                        scvolume = api.find_volume(volume_name)
                        # Our return.
                        iscsiprops = {}
                        ip = None
                        port = None
                        if not multipath:
                            # We want to make sure we point to the specified
                            # ip address for our target_portal return.  This
                            # isn't an issue with multipath since it should
                            # try all the alternate portal.
                            ip = self.configuration.iscsi_ip_address
                            port = self.configuration.iscsi_port

                        # Three cases that should all be satisfied with the
                        # same return of Target_Portal and Target_Portals.
                        # 1. Nova is calling us so we need to return the
                        #    Target_Portal stuff.  It should ignore the
                        #    Target_Portals stuff.
                        # 2. OS brick is calling us in multipath mode so we
                        #    want to return Target_Portals.  It will ignore
                        #    the Target_Portal stuff.
                        # 3. OS brick is calling us in single path mode so
                        #    we want to return Target_Portal and
                        #    Target_Portals as alternates.
                        iscsiprops = (api.find_iscsi_properties(scvolume,
                                                                ip,
                                                                port))

                        # Return our iscsi properties.
                        return {'driver_volume_type': 'iscsi',
                                'data': iscsiprops}
            # Re-raise any backend exception.
            except exception.VolumeBackendAPIException:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to initialize connection'))
            # If there is a data structure issue then detail the exception
            # and bail with a Backend Exception.
            except Exception as error:
                LOG.error(error)
                raise exception.VolumeBackendAPIException(error)

        # We get here because our mapping is none or we have no valid iqn to
        # return so blow up.
        raise exception.VolumeBackendAPIException(
            _('Unable to map volume'))

    def terminate_connection(self, volume, connector, force=False, **kwargs):
        # Grab some initial info.
        initiator_name = connector.get('initiator')
        volume_name = volume.get('id')
        LOG.debug('Terminate connection: %(vol)s:%(initiator)s',
                  {'vol': volume_name,
                   'initiator': initiator_name})
        with self._client.open_connection() as api:
            try:
                scserver = api.find_server(initiator_name)
                # Find the volume on the storage center.
                scvolume = api.find_volume(volume_name)

                # If we have a server and a volume lets pull them apart.
                if (scserver is not None and
                        scvolume is not None and
                        api.unmap_volume(scvolume, scserver) is True):
                    LOG.debug('Connection terminated')
                    return
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to terminate connection '
                                  '%(initiator)s %(vol)s'),
                              {'initiator': initiator_name,
                               'vol': volume_name})
        raise exception.VolumeBackendAPIException(
            _('Terminate connection failed'))
