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
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class SCFCDriver(storagecenter_common.SCCommonDriver,
                 driver.FibreChannelDriver):

    """Implements commands for Dell Storage Center FC management.

    To enable the driver add the following line to the cinder configuration:
        volume_driver=cinder.volume.drivers.dell_emc.sc.storagecenter_fc.\
        SCFCDriver

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver
        1.1.0 - Added extra spec support for Storage Profile selection
        1.2.0 - Added consistency group support.
        2.0.0 - Switched to inheriting functional objects rather than volume
                driver.
        2.1.0 - Added support for ManageableVD.
        2.2.0 - Driver retype support for switching volume's Storage Profile
        2.3.0 - Added Legacy Port Mode Support
        2.3.1 - Updated error handling.
        2.4.0 - Added Replication V2 support.
        2.4.1 - Updated Replication support to V2.1.
        2.5.0 - ManageableSnapshotsVD implemented.
        3.0.0 - ProviderID utilized.
        3.1.0 - Failback supported.
        3.2.0 - Live Volume support.
        3.3.0 - Support for a secondary DSM.
        3.4.0 - Support for excluding a domain.
        3.5.0 - Support for AFO.
        3.6.0 - Server type support.
        3.7.0 - Support for Data Reduction, Group QOS and Volume QOS.
        4.0.0 - Driver moved to dell_emc.
        4.1.0 - Timeouts added to rest calls.
        4.1.1 - excluded_domain_ips support.

    """

    VERSION = '4.1.1'

    CI_WIKI_NAME = "Dell_EMC_SC_Series_CI"

    def __init__(self, *args, **kwargs):
        super(SCFCDriver, self).__init__(*args, **kwargs)
        self.backend_name =\
            self.configuration.safe_get('volume_backend_name') or 'Dell-FC'
        self.storage_protocol = 'FC'

    def validate_connector(self, connector):
        """Fail if connector doesn't contain all the data needed by driver.

        Do a check on the connector and ensure that it has wwnns, wwpns.
        """
        self.validate_connector_has_setting(connector, 'wwpns')
        self.validate_connector_has_setting(connector, 'wwnns')

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
        provider_id = volume.get('provider_id')
        islivevol = self._is_live_vol(volume)
        LOG.debug('Initialize connection: %s', volume_name)
        with self._client.open_connection() as api:
            try:
                wwpns = connector.get('wwpns')
                # Find the volume on the storage center. Note that if this
                # is live volume and we are swapped this will be the back
                # half of the live volume.
                scvolume = api.find_volume(volume_name, provider_id, islivevol)
                if scvolume:
                    # Get the SSN it is on.
                    ssn = scvolume['instanceId'].split('.')[0]
                    # Find our server.
                    scserver = self._find_server(api, wwpns, ssn)

                    # No? Create it.
                    if scserver is None:
                        scserver = api.create_server(
                            wwpns, self.configuration.dell_server_os, ssn)
                    # We have a volume and a server. Map them.
                    if scserver is not None:
                        mapping = api.map_volume(scvolume, scserver)
                        if mapping is not None:
                            # Since we just mapped our volume we had
                            # best update our sc volume object.
                            scvolume = api.get_volume(scvolume['instanceId'])
                            lun, targets, init_targ_map = api.find_wwns(
                                scvolume, scserver)

                            # Do we have extra live volume work?
                            if islivevol:
                                # Get our live volume.
                                sclivevolume = api.get_live_volume(provider_id)
                                # Do not map to a failed over volume.
                                if (sclivevolume and not
                                    api.is_failed_over(provider_id,
                                                       sclivevolume)):
                                    # Now map our secondary.
                                    lvlun, lvtargets, lvinit_targ_map = (
                                        self.initialize_secondary(api,
                                                                  sclivevolume,
                                                                  wwpns))
                                    # Unmapped. Add info to our list.
                                    targets += lvtargets
                                    init_targ_map.update(lvinit_targ_map)

                            # Roll up our return data.
                            if lun is not None and len(targets) > 0:
                                data = {'driver_volume_type': 'fibre_channel',
                                        'data': {'target_lun': lun,
                                                 'target_discovered': True,
                                                 'target_wwn': targets,
                                                 'initiator_target_map':
                                                 init_targ_map,
                                                 'discard': True}}
                                LOG.debug('Return FC data: %s', data)
                                fczm_utils.add_fc_zone(data)
                                return data
                            LOG.error('Lun mapping returned null!')

            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error('Failed to initialize connection.')

        # We get here because our mapping is none so blow up.
        raise exception.VolumeBackendAPIException(
            data=_('Unable to map volume.'))

    def _find_server(self, api, wwns, ssn=-1):
        for wwn in wwns:
            scserver = api.find_server(wwn, ssn)
            if scserver is not None:
                return scserver
        return None

    def initialize_secondary(self, api, sclivevolume, wwns):
        """Initialize the secondary connection of a live volume pair.

        :param api: Dell SC api object.
        :param sclivevolume: Dell SC live volume object.
        :param wwns: Cinder list of wwns from the connector.
        :return: lun, targets and initiator target map.
        """
        # Find our server.
        secondary = self._find_server(
            api, wwns, sclivevolume['secondaryScSerialNumber'])

        # No? Create it.
        if secondary is None:
            secondary = api.create_server(
                wwns, self.configuration.dell_server_os,
                sclivevolume['secondaryScSerialNumber'])
        if secondary:
            if api.map_secondary_volume(sclivevolume, secondary):
                # Get mappings.
                secondaryvol = api.get_volume(
                    sclivevolume['secondaryVolume']['instanceId'])
                if secondaryvol:
                    return api.find_wwns(secondaryvol, secondary)
        LOG.warning('Unable to map live volume secondary volume'
                    ' %(vol)s to secondary server wwns: %(wwns)r',
                    {'vol': sclivevolume['secondaryVolume']['instanceName'],
                     'wwns': wwns})
        return None, [], {}

    def force_detach(self, volume):
        """Breaks all volume server connections including to the live volume.

        :param volume: volume to be detached
        :raises VolumeBackendAPIException: On failure to sever connections.
        """
        with self._client.open_connection() as api:
            volume_name = volume.get('id')
            provider_id = volume.get('provider_id')
            try:
                islivevol = self._is_live_vol(volume)
                scvolume = api.find_volume(volume_name, provider_id, islivevol)
                if scvolume:
                    rtn = api.unmap_all(scvolume)
                    # If this fails we blow up.
                    if not rtn:
                        raise exception.VolumeBackendAPIException(
                            _('Terminate connection failed'))
                    # If there is a livevol we just take a shot at
                    # disconnecting.
                    if islivevol:
                        sclivevolume = api.get_live_volume(provider_id)
                        if sclivevolume:
                            self.terminate_secondary(api, sclivevolume, None)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error('Failed to terminates %(vol)s connections.',
                              {'vol': volume_name})

        # We don't know the servers that were involved so we just return
        # the most basic of data.
        info = {'driver_volume_type': 'fibre_channel',
                'data': {}}
        return info

    @utils.synchronized('{self.driver_prefix}-{volume.id}')
    def terminate_connection(self, volume, connector, force=False, **kwargs):
        # Special case
        if connector is None:
            return self.force_detach(volume)

        # Grab some quick info.
        volume_name = volume.get('id')
        provider_id = volume.get('provider_id')
        LOG.debug('Terminate connection: %s', volume_name)
        LOG.debug('Volume details %s', volume)

        # None `connector` indicates force detach, then detach all even if the
        # volume is multi-attached.
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
                wwpns = [] if not connector else connector.get('wwpns', [])
                # Find the volume on the storage center.
                islivevol = self._is_live_vol(volume)
                scvolume = api.find_volume(volume_name, provider_id, islivevol)
                if scvolume:
                    # Get the SSN it is on.
                    ssn = scvolume['instanceId'].split('.')[0]

                    # Will be None if we have no wwpns.
                    scserver = self._find_server(api, wwpns, ssn)

                    # Get our target map so we can return it to free up a zone.
                    lun, targets, init_targ_map = api.find_wwns(scvolume,
                                                                scserver)

                    # Do we have extra live volume work?
                    if islivevol:
                        # Get our live volume.
                        sclivevolume = api.get_live_volume(provider_id)
                        # Do not map to a failed over volume.
                        if (sclivevolume and not
                            api.is_failed_over(provider_id,
                                               sclivevolume)):
                            lvlun, lvtargets, lvinit_targ_map = (
                                self.terminate_secondary(
                                    api, sclivevolume, wwpns))
                            # Add to our return.
                            if lvlun:
                                targets += lvtargets
                                init_targ_map.update(lvinit_targ_map)

                    if (wwpns and scserver and
                            api.unmap_volume(scvolume, scserver) is True):
                        LOG.debug('Connection terminated')
                    elif not wwpns and api.unmap_all(scvolume):
                        LOG.debug('All connections terminated')
                    else:
                        raise exception.VolumeBackendAPIException(
                            data=_('Terminate connection failed'))

                    info = {'driver_volume_type': 'fibre_channel',
                            'data': {}}

                    # if not then we return the target map so that
                    # the zone can be freed up.
                    if scserver and api.get_volume_count(scserver) == 0:
                        info['data'] = {'target_wwn': targets,
                                        'initiator_target_map': init_targ_map}
                        fczm_utils.remove_fc_zone(info)
                    return info

            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error('Failed to terminate connection')
        raise exception.VolumeBackendAPIException(
            data=_('Terminate connection unable to connect to backend.'))

    def terminate_secondary(self, api, sclivevolume, wwns):
        lun = None
        targets = []
        init_targ_map = {}
        # Get our volume.
        secondaryvol = api.get_volume(
            sclivevolume['secondaryVolume']['instanceId'])
        # We have one so let's get to work.
        if secondaryvol:
            # Are we unmapping a specific server?
            if wwns:
                # Find our server.
                secondary = self._find_server(
                    api, wwns, sclivevolume['secondaryScSerialNumber'])
                # Get our map.
                lun, targets, init_targ_map = api.find_wwns(secondaryvol,
                                                            secondary)
                # If we have a server and a volume lets unmap them.
                ret = api.unmap_volume(secondaryvol, secondary)
                LOG.debug('terminate_secondary: '
                          'secondary volume %(name)s unmap '
                          'to secondary server %(server)s result: %(result)r',
                          {'name': secondaryvol['name'],
                           'server': secondary['name'], 'result': ret})
            else:
                # Just unmap all.
                ret = api.unmap_all(secondaryvol)
                LOG.debug('terminate_secondary:  secondary volume %(name)s '
                          'unmap all result: %(result)r',
                          {'name': secondaryvol['name'], 'result': ret})
        else:
            LOG.debug('terminate_secondary: secondary volume not found.')
        # return info if any
        return lun, targets, init_targ_map
