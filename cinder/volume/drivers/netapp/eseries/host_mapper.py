# Copyright (c) 2015 Alex Meade.  All Rights Reserved.
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

""" This module handles mapping E-Series volumes to E-Series Hosts and Host
Groups.
"""

from oslo_log import log as logging
from six.moves import xrange

from cinder import exception
from cinder.i18n import _
from cinder import utils as cinder_utils
from cinder.volume.drivers.netapp.eseries import exception as eseries_exc
from cinder.volume.drivers.netapp.eseries import utils


LOG = logging.getLogger(__name__)


@cinder_utils.synchronized('map_es_volume')
def map_volume_to_single_host(client, volume, eseries_vol, host,
                              vol_map):
    """Maps the e-series volume to host with initiator."""
    msg = "Attempting to map volume %s to single host."
    LOG.debug(msg % volume['id'])

    # If volume is not mapped on the backend, map directly to host
    if not vol_map:
        mappings = _get_vol_mapping_for_host_frm_array(client, host['hostRef'])
        lun = _get_free_lun(client, host, mappings)
        return client.create_volume_mapping(eseries_vol['volumeRef'],
                                            host['hostRef'], lun)

    # If volume is already mapped to desired host
    if vol_map.get('mapRef') == host['hostRef']:
        return vol_map

    multiattach_cluster_ref = None
    try:
        host_group = client.get_host_group_by_name(
            utils.MULTI_ATTACH_HOST_GROUP_NAME)
        multiattach_cluster_ref = host_group['clusterRef']
    except exception.NotFound:
        pass

    # Volume is mapped to the multiattach host group
    if vol_map.get('mapRef') == multiattach_cluster_ref:
        LOG.debug("Volume %s is mapped to multiattach host group."
                  % volume['id'])

        # If volume is not currently attached according to Cinder, it is
        # safe to delete the mapping
        if not (volume['attach_status'] == 'attached'):
            msg = (_("Volume %(vol)s is not currently attached, "
                     "moving existing mapping to host %(host)s.")
                   % {'vol': volume['id'], 'host': host['label']})
            LOG.debug(msg)
            mappings = _get_vol_mapping_for_host_frm_array(
                client, host['hostRef'])
            lun = _get_free_lun(client, host, mappings)
            return client.move_volume_mapping_via_symbol(
                vol_map.get('mapRef'), host['hostRef'], lun
            )

    # If we got this far, volume must be mapped to something else
    msg = _("Cannot attach already attached volume %s; "
            "multiattach is disabled via the "
            "'netapp_enable_multiattach' configuration option.")
    raise exception.NetAppDriverException(msg % volume['id'])


@cinder_utils.synchronized('map_es_volume')
def map_volume_to_multiple_hosts(client, volume, eseries_vol, target_host,
                                 mapping):
    """Maps the e-series volume to multiattach host group."""

    msg = "Attempting to map volume %s to multiple hosts."
    LOG.debug(msg % volume['id'])

    # If volume is already mapped to desired host, return the mapping
    if mapping['mapRef'] == target_host['hostRef']:
        LOG.debug("Volume %(vol)s already mapped to host %(host)s",
                  {'vol': volume['id'], 'host': target_host['label']})
        return mapping

    # If target host in a host group, ensure it is the multiattach host group
    if target_host['clusterRef'] != utils.NULL_REF:
        host_group = client.get_host_group(target_host[
            'clusterRef'])
        if host_group['label'] != utils.MULTI_ATTACH_HOST_GROUP_NAME:
            msg = _("Specified host to map to volume %(vol)s is in "
                    "unsupported host group with %(group)s.")
            params = {'vol': volume['id'], 'group': host_group['label']}
            raise eseries_exc.UnsupportedHostGroup(msg % params)

    mapped_host_group = None
    multiattach_host_group = None
    try:
        mapped_host_group = client.get_host_group(mapping['mapRef'])
        # If volume is mapped to a foreign host group raise an error
        if mapped_host_group['label'] != utils.MULTI_ATTACH_HOST_GROUP_NAME:
            raise eseries_exc.UnsupportedHostGroup(
                volume_id=volume['id'], group=mapped_host_group['label'])
        multiattach_host_group = mapped_host_group
    except exception.NotFound:
        pass

    if not multiattach_host_group:
        multiattach_host_group = client.get_host_group_by_name(
            utils.MULTI_ATTACH_HOST_GROUP_NAME)

    # If volume is mapped directly to a host, move the host into the
    # multiattach host group. Error if the host is in a foreign host group
    if not mapped_host_group:
        current_host = client.get_host(mapping['mapRef'])
        if current_host['clusterRef'] != utils.NULL_REF:
            host_group = client.get_host_group(current_host[
                'clusterRef'])
            if host_group['label'] != utils.MULTI_ATTACH_HOST_GROUP_NAME:
                msg = _("Currently mapped host for volume %(vol)s is in "
                        "unsupported host group with %(group)s.")
                params = {'vol': volume['id'], 'group': host_group['label']}
                raise eseries_exc.UnsupportedHostGroup(msg % params)
        client.set_host_group_for_host(current_host['hostRef'],
                                       multiattach_host_group['clusterRef'])

    # Move destination host into multiattach host group
    client.set_host_group_for_host(target_host[
        'hostRef'], multiattach_host_group['clusterRef'])

    # Once both existing and target hosts are in the multiattach host group,
    # move the volume mapping to said group.
    if not mapped_host_group:
        msg = "Moving mapping for volume %s to multiattach host group."
        LOG.debug(msg % volume['id'])
        return client.move_volume_mapping_via_symbol(
            mapping.get('lunMappingRef'),
            multiattach_host_group['clusterRef'],
            mapping['lun']
        )

    return mapping


def _get_free_lun(client, host, maps=None):
    """Gets free LUN for given host."""
    ref = host['hostRef']
    luns = maps or _get_vol_mapping_for_host_frm_array(client, ref)
    if host['clusterRef'] != utils.NULL_REF:
        host_group_maps = _get_vol_mapping_for_host_group_frm_array(
            client, host['clusterRef'])
        luns.extend(host_group_maps)
    used_luns = set(map(lambda lun: int(lun['lun']), luns))
    for lun in xrange(utils.MAX_LUNS_PER_HOST):
        if lun not in used_luns:
            return lun
    msg = _("No free LUNs. Host might have exceeded max number of LUNs.")
    raise exception.NetAppDriverException(msg)


def _get_vol_mapping_for_host_frm_array(client, host_ref):
    """Gets all volume mappings for given host from array."""
    mappings = client.get_volume_mappings() or []
    host_maps = filter(lambda x: x.get('mapRef') == host_ref, mappings)
    return host_maps


def _get_vol_mapping_for_host_group_frm_array(client, hg_ref):
    """Gets all volume mappings for given host from array."""
    mappings = client.get_volume_mappings() or []
    hg_maps = filter(lambda x: x.get('mapRef') == hg_ref, mappings)
    return hg_maps


def unmap_volume_from_host(client, volume, host, mapping):
    # Volume is mapped directly to host, so delete the mapping
    if mapping.get('mapRef') == host['hostRef']:
        msg = ("Volume %(vol)s is mapped directly to host %(host)s; removing "
               "mapping.")
        LOG.debug(msg % {'vol': volume['id'], 'host': host['label']})
        client.delete_volume_mapping(mapping['lunMappingRef'])
        return

    try:
        host_group = client.get_host_group(mapping['mapRef'])
    except exception.NotFound:
        # Volumes is mapped but to a different initiator
        raise eseries_exc.VolumeNotMapped(volume_id=volume['id'],
                                          host=host['label'])
    # If volume is mapped to a foreign host group raise error
    if host_group['label'] != utils.MULTI_ATTACH_HOST_GROUP_NAME:
        raise eseries_exc.UnsupportedHostGroup(volume_id=volume['id'],
                                               group=host_group['label'])
    # If target host is not in the multiattach host group
    if host['clusterRef'] != host_group['clusterRef']:
        raise eseries_exc.VolumeNotMapped(volume_id=volume['id'],
                                          host=host['label'])

    # Volume is mapped to multiattach host group
    # Remove mapping if volume should no longer be attached after this
    # operation.
    if volume['status'] == 'detaching':
        msg = ("Volume %s is mapped directly to multiattach host group "
               "but is not currently attached; removing mapping.")
        LOG.debug(msg % volume['id'])
        client.delete_volume_mapping(mapping['lunMappingRef'])


def get_host_mapping_for_vol_frm_array(client, volume):
    """Gets all host mappings for given volume from array."""
    mappings = client.get_volume_mappings() or []
    host_maps = filter(lambda x: x.get('volumeRef') == volume['volumeRef'],
                       mappings)
    return host_maps
