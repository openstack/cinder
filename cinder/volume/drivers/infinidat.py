# Copyright 2016 Infinidat Ltd.
# All Rights Reserved.
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
"""
INFINIDAT InfiniBox Volume Driver
"""

from contextlib import contextmanager

import mock
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
import requests
import six

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume.drivers.san import san
from cinder.volume import utils as vol_utils
from cinder.zonemanager import utils as fczm_utils


LOG = logging.getLogger(__name__)

VENDOR_NAME = 'INFINIDAT'
DELETE_URI = 'volumes/%s?approved=true'

infinidat_opts = [
    cfg.StrOpt('infinidat_pool_name',
               help='Name of the pool from which volumes are allocated'),
]

CONF = cfg.CONF
CONF.register_opts(infinidat_opts)


@interface.volumedriver
class InfiniboxVolumeDriver(san.SanDriver):
    VERSION = '1.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "INFINIDAT_Cinder_CI"

    def __init__(self, *args, **kwargs):
        super(InfiniboxVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(infinidat_opts)
        self._lookup_service = fczm_utils.create_lookup_service()

    def do_setup(self, context):
        """Driver initialization"""
        self._session = requests.Session()
        self._session.auth = (self.configuration.san_login,
                              self.configuration.san_password)
        management_address = self.configuration.san_ip
        self._base_url = 'http://%s/api/rest/' % management_address
        backend_name = self.configuration.safe_get('volume_backend_name')
        self._backend_name = backend_name or self.__class__.__name__
        self._volume_stats = None
        LOG.debug('setup complete. base url: %s', self._base_url)

    def _request(self, action, uri, data=None):
        LOG.debug('--> %(action)s %(uri)s %(data)r',
                  {'action': action, 'uri': uri, 'data': data})
        response = self._session.request(action,
                                         self._base_url + uri,
                                         json=data)
        LOG.debug('<-- %(status_code)s %(response_json)r',
                  {'status_code': response.status_code,
                   'response_json': response.json()})
        try:
            response.raise_for_status()
        except requests.HTTPError as ex:
            # text_type(ex) includes http code and url
            msg = _('InfiniBox storage array returned %(exception)s\n'
                    'Data: %(data)s\n'
                    'Response: %(response_json)s') % {
                        'exception': six.text_type(ex),
                        'data': repr(data),
                        'response_json': repr(response.json())}
            LOG.exception(msg)
            if response.status_code == 404:
                raise exception.NotFound()
            else:
                raise exception.VolumeBackendAPIException(data=msg)
        return response.json()['result']

    def _get(self, uri):
        return self._request('GET', uri)

    def _post(self, uri, data):
        return self._request('POST', uri, data)

    def _delete(self, uri):
        return self._request('DELETE', uri)

    def _put(self, uri, data):
        return self._request('PUT', uri, data)

    def _cleanup_wwpn(self, wwpn):
        return wwpn.replace(':', '')

    def _make_volume_name(self, cinder_volume):
        return 'openstack-vol-%s' % cinder_volume.id

    def _make_snapshot_name(self, cinder_snapshot):
        return 'openstack-snap-%s' % cinder_snapshot.id

    def _make_host_name(self, wwpn):
        wwn_for_name = self._cleanup_wwpn(wwpn)
        return 'openstack-host-%s' % wwn_for_name

    def _get_infinidat_volume_by_name(self, name):
        volumes = self._get('volumes?name=%s' % name)
        if len(volumes) != 1:
            msg = _('Volume "%s" not found') % name
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)
        return volumes[0]

    def _get_infinidat_snapshot_by_name(self, name):
        snapshots = self._get('volumes?name=%s' % name)
        if len(snapshots) != 1:
            msg = _('Snapshot "%s" not found') % name
            LOG.error(msg)
            raise exception.InvalidSnapshot(reason=msg)
        return snapshots[0]

    def _get_infinidat_volume_id(self, cinder_volume):
        volume_name = self._make_volume_name(cinder_volume)
        return self._get_infinidat_volume_by_name(volume_name)['id']

    def _get_infinidat_snapshot_id(self, cinder_snapshot):
        snap_name = self._make_snapshot_name(cinder_snapshot)
        return self._get_infinidat_snapshot_by_name(snap_name)['id']

    def _get_infinidat_pool(self):
        pool_name = self.configuration.infinidat_pool_name
        pools = self._get('pools?name=%s' % pool_name)
        if len(pools) != 1:
            msg = _('Pool "%s" not found') % pool_name
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        return pools[0]

    def _get_host(self, wwpn):
        host_name = self._make_host_name(wwpn)
        infinidat_hosts = self._get('hosts?name=%s' % host_name)
        if len(infinidat_hosts) == 1:
            return infinidat_hosts[0]

    def _get_or_create_host(self, wwpn):
        host_name = self._make_host_name(wwpn)
        infinidat_host = self._get_host(wwpn)
        if infinidat_host is None:
            # create host
            infinidat_host = self._post('hosts', dict(name=host_name))
            # add port to host
            self._post('hosts/%s/ports' % infinidat_host['id'],
                       dict(type='FC', address=self._cleanup_wwpn(wwpn)))
        return infinidat_host

    def _get_mapping(self, host_id, volume_id):
        existing_mapping = self._get("hosts/%s/luns" % host_id)
        for mapping in existing_mapping:
            if mapping['volume_id'] == volume_id:
                return mapping

    def _get_or_create_mapping(self, host_id, volume_id):
        mapping = self._get_mapping(host_id, volume_id)
        if mapping:
            return mapping
        # volume not mapped. map it
        uri = 'hosts/%s/luns?approved=true' % host_id
        return self._post(uri, dict(volume_id=volume_id))

    def _get_online_fc_ports(self):
        nodes = self._get('components/nodes?fields=fc_ports')
        for node in nodes:
            for port in node['fc_ports']:
                if (port['link_state'].lower() == 'up'
                   and port['state'] == 'OK'):
                    yield self._cleanup_wwpn(port['wwpn'])

    @fczm_utils.add_fc_zone
    def initialize_connection(self, volume, connector):
        """Map an InfiniBox volume to the host"""
        volume_name = self._make_volume_name(volume)
        infinidat_volume = self._get_infinidat_volume_by_name(volume_name)
        for wwpn in connector['wwpns']:
            infinidat_host = self._get_or_create_host(wwpn)
            mapping = self._get_or_create_mapping(infinidat_host['id'],
                                                  infinidat_volume['id'])
            lun = mapping['lun']

        # Create initiator-target mapping.
        target_wwpns = list(self._get_online_fc_ports())
        target_wwpns, init_target_map = self._build_initiator_target_map(
            connector, target_wwpns)
        return dict(driver_volume_type='fibre_channel',
                    data=dict(target_discovered=False,
                              target_wwn=target_wwpns,
                              target_lun=lun,
                              initiator_target_map=init_target_map))

    @fczm_utils.remove_fc_zone
    def terminate_connection(self, volume, connector, **kwargs):
        """Unmap an InfiniBox volume from the host"""
        volume_id = self._get_infinidat_volume_id(volume)
        result_data = dict()
        for wwpn in connector['wwpns']:
            host_name = self._make_host_name(wwpn)
            infinidat_hosts = self._get('hosts?name=%s' % host_name)
            if len(infinidat_hosts) != 1:
                # not found. ignore.
                continue
            host_id = infinidat_hosts[0]['id']
            # unmap
            uri = ('hosts/%s/luns/volume_id/%s' % (host_id, volume_id) +
                   '?approved=true')
            try:
                self._delete(uri)
            except (exception.NotFound):
                continue      # volume mapping not found
        # check if the host now doesn't have mappings, to delete host_entry
        # if needed
        infinidat_hosts = self._get('hosts?name=%s' % host_name)
        if len(infinidat_hosts) == 1 and len(infinidat_hosts[0]['luns']) == 0:
            # Create initiator-target mapping.
            target_wwpns = list(self._get_online_fc_ports())
            target_wwpns, init_target_map = self._build_initiator_target_map(
                connector, target_wwpns)
            result_data = dict(target_wwn=target_wwpns,
                               initiator_target_map=init_target_map)
        return dict(driver_volume_type='fibre_channel',
                    data=result_data)

    def get_volume_stats(self, refresh=False):
        if self._volume_stats is None or refresh:
            pool = self._get_infinidat_pool()
            free_capacity_gb = float(pool['free_physical_space']) / units.Gi
            total_capacity_gb = float(pool['physical_capacity']) / units.Gi
            self._volume_stats = dict(volume_backend_name=self._backend_name,
                                      vendor_name=VENDOR_NAME,
                                      driver_version=self.VERSION,
                                      storage_protocol='FC',
                                      consistencygroup_support='False',
                                      total_capacity_gb=total_capacity_gb,
                                      free_capacity_gb=free_capacity_gb)
        return self._volume_stats

    def _create_volume(self, volume):
        # get pool id from name
        pool = self._get_infinidat_pool()
        # create volume
        volume_name = self._make_volume_name(volume)
        provtype = "THIN" if self.configuration.san_thin_provision else "THICK"
        data = dict(pool_id=pool['id'],
                    provtype=provtype,
                    name=volume_name,
                    size=volume.size * units.Gi)
        return self._post('volumes', data)

    def create_volume(self, volume):
        """Create a new volume on the backend."""
        # this is the same as _create_volume but without the return statement
        self._create_volume(volume)

    def delete_volume(self, volume):
        """Delete a volume from the backend."""
        try:
            volume_name = self._make_volume_name(volume)
            volume = self._get_infinidat_volume_by_name(volume_name)
            if volume['has_children']:
                # can't delete a volume that has a live snapshot
                raise exception.VolumeIsBusy(volume_name=volume_name)
            self._delete(DELETE_URI % volume['id'])
        except (exception.InvalidVolume, exception.NotFound):
            return      # volume not found

    def extend_volume(self, volume, new_size):
        """Extend the size of a volume."""
        volume_id = self._get_infinidat_volume_id(volume)
        self._put('volumes/%s?approved=true' % volume_id,
                  dict(size=new_size * units.Gi))

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        volume_id = self._get_infinidat_volume_id(snapshot.volume)
        name = self._make_snapshot_name(snapshot)
        self._post('volumes', dict(parent_id=volume_id, name=name))

    @contextmanager
    def _device_connect_context(self, volume):
        connector = utils.brick_get_connector_properties()
        connection = self.initialize_connection(volume, connector)
        try:
            yield self._connect_device(connection)
        finally:
            self.terminate_connection(volume, connector)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create volume from snapshot.

        InfiniBox does not yet support detached clone so use dd to copy data.
        This could be a lengthy operation.

        - create a clone from snapshot and map it
        - create a volume and map it
        - copy data from clone to volume
        - unmap volume and clone and delete the clone
        """
        snapshot_id = self._get_infinidat_snapshot_id(snapshot)
        clone_name = self._make_volume_name(volume) + '-internal'
        infinidat_clone = self._post('volumes', dict(parent_id=snapshot_id,
                                                     name=clone_name))
        # we need a cinder-volume-like object to map the clone by name
        # (which is derived from the cinder id) but the clone is internal
        # so there is no such object. mock one
        clone = mock.Mock(id=str(volume.id) + '-internal')
        try:
            infinidat_volume = self._create_volume(volume)
            try:
                src_ctx = self._device_connect_context(clone)
                dst_ctx = self._device_connect_context(volume)
                with src_ctx as src_dev, dst_ctx as dst_dev:
                    dd_block_size = self.configuration.volume_dd_blocksize
                    vol_utils.copy_volume(src_dev['device']['path'],
                                          dst_dev['device']['path'],
                                          snapshot.volume.size * units.Ki,
                                          dd_block_size,
                                          sparse=True)
            except Exception:
                self._delete(DELETE_URI % infinidat_volume['id'])
                raise
        finally:
            self._delete(DELETE_URI % infinidat_clone['id'])

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        try:
            snapshot_name = self._make_snapshot_name(snapshot)
            snapshot = self._get_infinidat_snapshot_by_name(snapshot_name)
            self._delete(DELETE_URI % snapshot['id'])
        except (exception.InvalidSnapshot, exception.NotFound):
            return      # snapshot not found

    def _asssert_volume_not_mapped(self, volume):
        # copy is not atomic so we can't clone while the volume is mapped
        volume_name = self._make_volume_name(volume)
        infinidat_volume = self._get_infinidat_volume_by_name(volume_name)
        mappings = self._get("volumes/%s/luns" % infinidat_volume['id'])
        if len(mappings) == 0:
            return

        # volume has mappings
        msg = _("INFINIDAT Cinder driver does not support clone of an "
                "attached volume. "
                "To get this done, create a snapshot from the attached "
                "volume and then create a volume from the snapshot.")
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone from source volume.

        InfiniBox does not yet support detached clone so use dd to copy data.
        This could be a lengthy operation.

        * map source volume
        * create and map new volume
        * copy data from source to new volume
        * unmap both volumes
        """
        self._asssert_volume_not_mapped(src_vref)
        infinidat_volume = self._create_volume(volume)
        try:
            src_ctx = self._device_connect_context(src_vref)
            dst_ctx = self._device_connect_context(volume)
            with src_ctx as src_dev, dst_ctx as dst_dev:
                dd_block_size = self.configuration.volume_dd_blocksize
                vol_utils.copy_volume(src_dev['device']['path'],
                                      dst_dev['device']['path'],
                                      src_vref.size * units.Ki,
                                      dd_block_size,
                                      sparse=True)
        except Exception:
            self._delete(DELETE_URI % infinidat_volume['id'])
            raise

    def _build_initiator_target_map(self, connector, all_target_wwns):
        """Build the target_wwns and the initiator target map."""
        target_wwns = []
        init_targ_map = {}

        if self._lookup_service is not None:
            # use FC san lookup.
            dev_map = self._lookup_service.get_device_mapping_from_network(
                connector.get('wwpns'),
                all_target_wwns)

            for fabric_name in dev_map:
                fabric = dev_map[fabric_name]
                target_wwns += fabric['target_port_wwn_list']
                for initiator in fabric['initiator_port_wwn_list']:
                    if initiator not in init_targ_map:
                        init_targ_map[initiator] = []
                    init_targ_map[initiator] += fabric['target_port_wwn_list']
                    init_targ_map[initiator] = list(set(
                        init_targ_map[initiator]))
            target_wwns = list(set(target_wwns))
        else:
            initiator_wwns = connector.get('wwpns', [])
            target_wwns = all_target_wwns

            for initiator in initiator_wwns:
                init_targ_map[initiator] = target_wwns

        return target_wwns, init_targ_map
