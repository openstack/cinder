# Copyright (c) 2016 EMC Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


"""Driver for EMC CoprHD FC volumes."""

import re

from oslo_log import log as logging

from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.coprhd import common as coprhd_common
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class EMCCoprHDFCDriver(driver.FibreChannelDriver):
    """CoprHD FC Driver."""
    VERSION = "3.0.0.0"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "EMC_CoprHD_CI"

    def __init__(self, *args, **kwargs):
        super(EMCCoprHDFCDriver, self).__init__(*args, **kwargs)
        self.common = self._get_common_driver()

    def _get_common_driver(self):
        return coprhd_common.EMCCoprHDDriverCommon(
            protocol='FC',
            default_backend_name=self.__class__.__name__,
            configuration=self.configuration)

    def check_for_setup_error(self):
        self.common.check_for_setup_error()

    def create_volume(self, volume):
        """Creates a Volume."""
        self.common.create_volume(volume, self)
        self.common.set_volume_tags(volume, ['_obj_volume_type'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned Volume."""
        self.common.create_cloned_volume(volume, src_vref)
        self.common.set_volume_tags(volume, ['_obj_volume_type'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self.common.create_volume_from_snapshot(snapshot, volume)
        self.common.set_volume_tags(volume, ['_obj_volume_type'])

    def extend_volume(self, volume, new_size):
        """expands the size of the volume."""
        self.common.expand_volume(volume, new_size)

    def delete_volume(self, volume):
        """Deletes a volume."""
        self.common.delete_volume(volume)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.common.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.common.delete_snapshot(snapshot)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        pass

    def create_export(self, context, volume, connector=None):
        """Driver entry point to get the export info for a new volume."""
        pass

    def remove_export(self, context, volume):
        """Driver exntry point to remove an export for a volume."""
        pass

    def create_consistencygroup(self, context, group):
        """Creates a consistencygroup."""
        return self.common.create_consistencygroup(context, group)

    def update_consistencygroup(self, context, group, add_volumes=None,
                                remove_volumes=None):
        """Updates volumes in consistency group."""
        return self.common.update_consistencygroup(group, add_volumes,
                                                   remove_volumes)

    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group."""
        return self.common.delete_consistencygroup(context, group, volumes)

    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a cgsnapshot."""
        return self.common.create_cgsnapshot(cgsnapshot, snapshots)

    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a cgsnapshot."""
        return self.common.delete_cgsnapshot(cgsnapshot, snapshots)

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    @fczm_utils.AddFCZone
    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info."""

        properties = {}
        properties['volume_id'] = volume['id']
        properties['target_discovered'] = False
        properties['target_wwn'] = []

        init_ports = self._build_initport_list(connector)
        itls = self.common.initialize_connection(volume,
                                                 'FC',
                                                 init_ports,
                                                 connector['host'])

        target_wwns = None
        initiator_target_map = None

        if itls:
            properties['target_lun'] = itls[0]['hlu']
            target_wwns, initiator_target_map = (
                self._build_initiator_target_map(itls, connector))

        properties['target_wwn'] = target_wwns
        properties['initiator_target_map'] = initiator_target_map

        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()
            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        LOG.debug('FC properties: %s', properties)
        return {
            'driver_volume_type': 'fibre_channel',
            'data': properties,
        }

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to detach a volume from an instance."""

        init_ports = self._build_initport_list(connector)
        itls = self.common.terminate_connection(volume,
                                                'FC',
                                                init_ports,
                                                connector['host'])

        volumes_count = self.common.get_exports_count_by_initiators(init_ports)
        if volumes_count > 0:
            # return empty data
            data = {'driver_volume_type': 'fibre_channel', 'data': {}}
        else:
            target_wwns, initiator_target_map = (
                self._build_initiator_target_map(itls, connector))
            data = {
                'driver_volume_type': 'fibre_channel',
                'data': {
                    'target_wwn': target_wwns,
                    'initiator_target_map': initiator_target_map}}

        LOG.debug('Return FC data: %s', data)
        return data

    def _build_initiator_target_map(self, itls, connector):

        target_wwns = []
        for itl in itls:
            target_wwns.append(itl['target']['port'].replace(':', '').lower())

        initiator_wwns = connector['wwpns']
        initiator_target_map = {}
        for initiator in initiator_wwns:
            initiator_target_map[initiator] = target_wwns

        return target_wwns, initiator_target_map

    def _build_initport_list(self, connector):
        init_ports = []
        for i in range(len(connector['wwpns'])):
            initiator_port = ':'.join(re.findall(
                '..',
                connector['wwpns'][i])).upper()   # Add ":" every two digits
            init_ports.append(initiator_port)

        return init_ports

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self.update_volume_stats()

        return self._stats

    def update_volume_stats(self):
        """Retrieve stats info from virtual pool/virtual array."""
        LOG.debug("Updating volume stats")
        self._stats = self.common.update_volume_stats()

    def retype(self, ctxt, volume, new_type, diff, host):
        """Change the volume type."""
        return self.common.retype(ctxt, volume, new_type, diff, host)
