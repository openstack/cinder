#    Copyright (c) 2015-2017 Dell Inc, or its subsidiaries.
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
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.dell_emc.sc import storagecenter_common

LOG = logging.getLogger(__name__)


@interface.volumedriver
class SCISCSIDriver(storagecenter_common.SCCommonDriver,
                    driver.ISCSIDriver):

    """Implements commands for Dell Storage Center ISCSI management.

    To enable the driver add the following line to the cinder configuration:
        volume_driver=cinder.volume.drivers.dell_emc.sc.\
        storagecenter_iscsi.SCISCSIDriver

    Version history:

    .. code-block:: none

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
        2.4.0 - Added Replication V2 support.
        2.4.1 - Updated Replication support to V2.1.
        2.5.0 - ManageableSnapshotsVD implemented.
        3.0.0 - ProviderID utilized.
        3.1.0 - Failback Supported.
        3.2.0 - Live Volume support.
        3.3.0 - Support for a secondary DSM.
        3.4.0 - Support for excluding a domain.
        3.5.0 - Support for AFO.
        3.6.0 - Server type support.
        3.7.0 - Support for Data Reduction, Group QOS and Volume QOS.
        4.0.0 - Driver moved to dell_emc.
        4.1.0 - Timeouts added to rest calls.
        4.1.1 - excluded_domain_ips support.
        4.1.2 - included_domain_ips IP support.

    """

    VERSION = '4.1.2'
    CI_WIKI_NAME = "DellEMC_SC_CI"

    def __init__(self, *args, **kwargs):
        super(SCISCSIDriver, self).__init__(*args, **kwargs)
        self.backend_name = (
            self.configuration.safe_get('volume_backend_name') or 'Dell-iSCSI')

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
        #         }

        # We use id to name the volume name as it is a
        # known unique name.
        volume_name = volume.get('id')
        provider_id = volume.get('provider_id')
        islivevol = self._is_live_vol(volume)
        initiator_name = connector.get('initiator')
        multipath = connector.get('multipath', False)
        LOG.info('initialize_connection: %(vol)s:%(pid)s:'
                 '%(intr)s. Multipath is %(mp)r',
                 {'vol': volume_name,
                  'pid': provider_id,
                  'intr': initiator_name,
                  'mp': multipath})

        with self._client.open_connection() as api:
            try:
                # Find the volume on the storage center. Note that if this
                # is live volume and we are swapped this will be the back
                # half of the live volume.
                scvolume = api.find_volume(volume_name, provider_id, islivevol)
                if scvolume:
                    # Get the SSN it is on.
                    ssn = scvolume['instanceId'].split('.')[0]
                    # Find our server.
                    scserver = api.find_server(initiator_name, ssn)
                    # No? Create it.
                    if scserver is None:
                        scserver = api.create_server(
                            [initiator_name],
                            self.configuration.dell_server_os, ssn)

                    # if we have a server and a volume lets bring them
                    # together.
                    if scserver is not None:
                        mapping = api.map_volume(scvolume, scserver)
                        if mapping is not None:
                            # Since we just mapped our volume we had best
                            # update our sc volume object.
                            scvolume = api.get_volume(scvolume['instanceId'])
                            # Our return.
                            iscsiprops = {}

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
                            iscsiprops = api.find_iscsi_properties(scvolume,
                                                                   scserver)

                            # If this is a live volume we need to map up our
                            # secondary volume. Note that if we have failed
                            # over we do not wish to do this.
                            if islivevol:
                                sclivevolume = api.get_live_volume(provider_id)
                                # Only map if we are not failed over.
                                if (sclivevolume and not
                                    api.is_failed_over(provider_id,
                                                       sclivevolume)):
                                    secondaryprops = self.initialize_secondary(
                                        api, sclivevolume, initiator_name)
                                    # Combine with iscsiprops
                                    iscsiprops['target_iqns'] += (
                                        secondaryprops['target_iqns'])
                                    iscsiprops['target_portals'] += (
                                        secondaryprops['target_portals'])
                                    iscsiprops['target_luns'] += (
                                        secondaryprops['target_luns'])

                            # Return our iscsi properties.
                            iscsiprops['discard'] = True
                            return {'driver_volume_type': 'iscsi',
                                    'data': iscsiprops}
            # Re-raise any backend exception.
            except exception.VolumeBackendAPIException:
                with excutils.save_and_reraise_exception():
                    LOG.error('Failed to initialize connection')
            # If there is a data structure issue then detail the exception
            # and bail with a Backend Exception.
            except Exception as error:
                LOG.error(error)
                raise exception.VolumeBackendAPIException(error)

        # We get here because our mapping is none or we have no valid iqn to
        # return so blow up.
        raise exception.VolumeBackendAPIException(
            _('Unable to map volume'))

    def initialize_secondary(self, api, sclivevolume, initiatorname):
        """Initialize the secondary connection of a live volume pair.

        :param api: Dell SC api.
        :param sclivevolume: Dell SC live volume object.
        :param initiatorname: Cinder iscsi initiator from the connector.
        :return: ISCSI properties.
        """

        # Find our server.
        secondary = api.find_server(initiatorname,
                                    sclivevolume['secondaryScSerialNumber'])
        # No? Create it.
        if secondary is None:
            secondary = api.create_server(
                [initiatorname], self.configuration.dell_server_os,
                sclivevolume['secondaryScSerialNumber'])
        if secondary:
            if api.map_secondary_volume(sclivevolume, secondary):
                # Get our volume and get our properties.
                secondaryvol = api.get_volume(
                    sclivevolume['secondaryVolume']['instanceId'])
                if secondaryvol:
                    return api.find_iscsi_properties(secondaryvol,
                                                     secondary)
        # Dummy return on failure.
        data = {'target_discovered': False,
                'target_iqn': None,
                'target_iqns': [],
                'target_portal': None,
                'target_portals': [],
                'target_lun': None,
                'target_luns': [],
                }
        LOG.warning('Unable to map live volume secondary volume'
                    ' %(vol)s to secondary server intiator: %(init)r',
                    {'vol': sclivevolume['secondaryVolume']['instanceName'],
                     'init': initiatorname})
        return data

    def force_detach(self, volume):
        """Breaks all volume server connections including to the live volume.

        :param volume: volume to be detached
        :raises VolumeBackendAPIException: On failure to sever connections.
        """
        with self._client.open_connection() as api:
            volume_name = volume.get('id')
            provider_id = volume.get('provider_id')
            try:
                rtn = False
                islivevol = self._is_live_vol(volume)
                scvolume = api.find_volume(volume_name, provider_id, islivevol)
                if scvolume:
                    rtn = api.unmap_all(scvolume)
                    if rtn and islivevol:
                        sclivevolume = api.get_live_volume(provider_id)
                        if sclivevolume:
                            rtn = self.terminate_secondary(api, sclivevolume,
                                                           None)
                return rtn
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error('Failed to terminates %(vol)s connections.',
                              {'vol': volume_name})
        raise exception.VolumeBackendAPIException(
            _('Terminate connection failed'))

    @utils.synchronized('{self.driver_prefix}-{volume.id}')
    def terminate_connection(self, volume, connector, force=False, **kwargs):
        # Special case
        # None `connector` indicates force detach, then detach all even if the
        # volume is multi-attached.
        if connector is None:
            return self.force_detach(volume)

        # Normal terminate connection, then.
        # Grab some quick info.
        volume_name = volume.get('id')
        provider_id = volume.get('provider_id')
        initiator_name = None if not connector else connector.get('initiator')
        LOG.info('Volume in terminate connection: %(vol)s',
                 {'vol': volume})

        is_multiattached = (hasattr(volume, 'volume_attachment') and
                            self.is_multiattach_to_host(
                                volume.get('volume_attachment'),
                                connector['host']))
        if is_multiattached:
            LOG.info('Cannot terminate connection: '
                     '%(vol)s is multiattached.',
                     {'vol': volume_name})
            return True

        with self._client.open_connection() as api:
            try:
                # Find the volume on the storage center. Note that if this
                # is live volume and we are swapped this will be the back
                # half of the live volume.
                islivevol = self._is_live_vol(volume)
                scvolume = api.find_volume(volume_name, provider_id, islivevol)
                if scvolume:
                    # Get the SSN it is on.
                    ssn = scvolume['instanceId'].split('.')[0]

                    # Unmap our secondary if not failed over..
                    if islivevol:
                        sclivevolume = api.get_live_volume(provider_id)
                        if (sclivevolume and not
                            api.is_failed_over(provider_id,
                                               sclivevolume)):
                            self.terminate_secondary(api, sclivevolume,
                                                     initiator_name)

                    # Find our server.
                    scserver = (None if not initiator_name else
                                api.find_server(initiator_name, ssn))

                    # If we have a server and a volume lets pull them apart
                    if ((scserver and
                         api.unmap_volume(scvolume, scserver) is True) or
                       (not scserver and api.unmap_all(scvolume))):
                        LOG.debug('Connection terminated')
                        return
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error('Failed to terminate connection '
                              '%(initiator)s %(vol)s',
                              {'initiator': initiator_name,
                               'vol': volume_name})
        raise exception.VolumeBackendAPIException(
            _('Terminate connection failed'))

    def terminate_secondary(self, api, sclivevolume, initiatorname):
        # Only return False if we tried something and it failed.
        rtn = True
        secondaryvol = api.get_volume(
            sclivevolume['secondaryVolume']['instanceId'])

        if secondaryvol:
            if initiatorname:
                # Find our server.
                secondary = api.find_server(
                    initiatorname, sclivevolume['secondaryScSerialNumber'])
                rtn = api.unmap_volume(secondaryvol, secondary)
            else:
                rtn = api.unmap_all(secondaryvol)
        else:
            LOG.debug('terminate_secondary: secondary volume not found.')
        return rtn
