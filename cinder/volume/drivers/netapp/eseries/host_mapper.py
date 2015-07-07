# Copyright (c) 2015 Alex Meade.  All Rights Reserved.
# Copyright (c) 2015 Yogesh Kshirsagar.  All Rights Reserved.
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

import collections
import random

from oslo_log import log as logging
from six.moves import range

from cinder import exception
from cinder.i18n import _
from cinder import utils as cinder_utils
from cinder.volume.drivers.netapp.eseries import exception as eseries_exc
from cinder.volume.drivers.netapp.eseries import utils


LOG = logging.getLogger(__name__)


@cinder_utils.trace_method
@cinder_utils.synchronized('map_es_volume')
def map_volume_to_single_host(client, volume, eseries_vol, host,
                              vol_map, multiattach_enabled):
    """Maps the e-series volume to host with initiator."""
    LOG.debug("Attempting to map volume %s to single host.", volume['id'])

    # If volume is not mapped on the backend, map directly to host
    if not vol_map:
        mappings = client.get_volume_mappings_for_host(host['hostRef'])
        lun = _get_free_lun(client, host, multiattach_enabled, mappings)
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
        LOG.debug("Volume %s is mapped to multiattach host group.",
                  volume['id'])

        # If volume is not currently attached according to Cinder, it is
        # safe to delete the mapping
        if not (volume['attach_status'] == 'attached'):
            LOG.debug("Volume %(vol)s is not currently attached, moving "
                      "existing mapping to host %(host)s.",
                      {'vol': volume['id'], 'host': host['label']})
            mappings = client.get_volume_mappings_for_host(
                host['hostRef'])
            lun = _get_free_lun(client, host, multiattach_enabled, mappings)
            return client.move_volume_mapping_via_symbol(
                vol_map.get('mapRef'), host['hostRef'], lun
            )

    # If we got this far, volume must be mapped to something else
    msg = _("Cannot attach already attached volume %s; "
            "multiattach is disabled via the "
            "'netapp_enable_multiattach' configuration option.")
    raise exception.NetAppDriverException(msg % volume['id'])


@cinder_utils.trace_method
@cinder_utils.synchronized('map_es_volume')
def map_volume_to_multiple_hosts(client, volume, eseries_vol, target_host,
                                 mapping):
    """Maps the e-series volume to multiattach host group."""

    LOG.debug("Attempting to map volume %s to multiple hosts.", volume['id'])

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
        LOG.debug("Moving mapping for volume %s to multiattach host group.",
                  volume['id'])
        return client.move_volume_mapping_via_symbol(
            mapping.get('lunMappingRef'),
            multiattach_host_group['clusterRef'],
            mapping['lun']
        )

    return mapping


def _get_free_lun(client, host, multiattach_enabled, mappings):
    """Returns least used LUN ID available on the given host."""
    if not _is_host_full(client, host):
        unused_luns = _get_unused_lun_ids(mappings)
        if unused_luns:
            chosen_lun = random.sample(unused_luns, 1)
            return chosen_lun[0]
        elif multiattach_enabled:
            msg = _("No unused LUN IDs are available on the host; "
                    "multiattach is enabled which requires that all LUN IDs "
                    "to be unique across the entire host group.")
            raise exception.NetAppDriverException(msg)
        used_lun_counts = _get_used_lun_id_counter(mappings)
        # most_common returns an arbitrary tuple of members with same frequency
        for lun_id, __ in reversed(used_lun_counts.most_common()):
            if _is_lun_id_available_on_host(client, host, lun_id):
                return lun_id
    msg = _("No free LUN IDs left. Maximum number of volumes that can be "
            "attached to host (%s) has been exceeded.")
    raise exception.NetAppDriverException(msg % utils.MAX_LUNS_PER_HOST)


def _get_unused_lun_ids(mappings):
    """Returns unused LUN IDs given mappings."""
    used_luns = _get_used_lun_ids_for_mappings(mappings)

    unused_luns = (set(range(utils.MAX_LUNS_PER_HOST)) - set(used_luns))
    return unused_luns


def _get_used_lun_id_counter(mapping):
    """Returns used LUN IDs with count as a dictionary."""
    used_luns = _get_used_lun_ids_for_mappings(mapping)
    used_lun_id_counter = collections.Counter(used_luns)
    return used_lun_id_counter


def _is_host_full(client, host):
    """Checks whether maximum volumes attached to a host have been reached."""
    luns = client.get_volume_mappings_for_host(host['hostRef'])
    return len(luns) >= utils.MAX_LUNS_PER_HOST


def _is_lun_id_available_on_host(client, host, lun_id):
    """Returns a boolean value depending on whether a LUN ID is available."""
    mapping = client.get_volume_mappings_for_host(host['hostRef'])
    used_lun_ids = _get_used_lun_ids_for_mappings(mapping)
    return lun_id not in used_lun_ids


def _get_used_lun_ids_for_mappings(mappings):
    """Returns used LUNs when provided with mappings."""
    used_luns = set(map(lambda lun: int(lun['lun']), mappings))
    # E-Series uses LUN ID 0 for special purposes and should not be
    # assigned for general use
    used_luns.add(0)
    return used_luns


def unmap_volume_from_host(client, volume, host, mapping):
    # Volume is mapped directly to host, so delete the mapping
    if mapping.get('mapRef') == host['hostRef']:
        LOG.debug("Volume %(vol)s is mapped directly to host %(host)s; "
                  "removing mapping.", {'vol': volume['id'],
                                        'host': host['label']})
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
        LOG.debug("Volume %s is mapped directly to multiattach host group but "
                  "is not currently attached; removing mapping.", volume['id'])
        client.delete_volume_mapping(mapping['lunMappingRef'])
