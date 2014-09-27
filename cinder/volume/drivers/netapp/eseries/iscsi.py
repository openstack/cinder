# Copyright (c) 2014 NetApp, Inc.
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
iSCSI driver for NetApp E-series storage systems.
"""

import socket
import time
import uuid

from oslo.config import cfg
import six

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import units
from cinder import utils as cinder_utils
from cinder.volume import driver
from cinder.volume.drivers.netapp.eseries import client
from cinder.volume.drivers.netapp.options import netapp_basicauth_opts
from cinder.volume.drivers.netapp.options import netapp_connection_opts
from cinder.volume.drivers.netapp.options import netapp_eseries_opts
from cinder.volume.drivers.netapp.options import netapp_transport_opts
from cinder.volume.drivers.netapp import utils
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)


CONF = cfg.CONF
CONF.register_opts(netapp_basicauth_opts)
CONF.register_opts(netapp_connection_opts)
CONF.register_opts(netapp_eseries_opts)
CONF.register_opts(netapp_transport_opts)


class Driver(driver.ISCSIDriver):
    """Executes commands relating to Volumes."""

    VERSION = "1.0.0"
    required_flags = ['netapp_server_hostname', 'netapp_controller_ips',
                      'netapp_login', 'netapp_password',
                      'netapp_storage_pools']
    SLEEP_SECS = 5
    MAX_LUNS_PER_HOST = 255

    def __init__(self, *args, **kwargs):
        super(Driver, self).__init__(*args, **kwargs)
        utils.validate_instantiation(**kwargs)
        self.configuration.append_config_values(netapp_basicauth_opts)
        self.configuration.append_config_values(netapp_connection_opts)
        self.configuration.append_config_values(netapp_transport_opts)
        self.configuration.append_config_values(netapp_eseries_opts)
        self._objects = {'disk_pool_refs': [], 'pools': [],
                         'volumes': {'label_ref': {}, 'ref_vol': {}},
                         'snapshots': {'label_ref': {}, 'ref_snap': {}}}

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        self._check_flags()
        self._client = client.RestClient(
            scheme=self.configuration.netapp_transport_type,
            host=self.configuration.netapp_server_hostname,
            port=self.configuration.netapp_server_port,
            service_path=self.configuration.netapp_webservice_path,
            username=self.configuration.netapp_login,
            password=self.configuration.netapp_password)
        self._check_mode_get_or_register_storage_system()

    def _check_flags(self):
        """Ensure that the flags we care about are set."""
        required_flags = self.required_flags
        for flag in required_flags:
            if not getattr(self.configuration, flag, None):
                msg = _('%s is not set.') % flag
                raise exception.InvalidInput(reason=msg)

    def check_for_setup_error(self):
        self._check_storage_system()
        self._populate_system_objects()

    def _check_mode_get_or_register_storage_system(self):
        """Does validity checks for storage system registry and health."""
        def _resolve_host(host):
            try:
                ip = utils.resolve_hostname(host)
                return ip
            except socket.gaierror as e:
                LOG.error(_('Error resolving host %(host)s. Error - %(e)s.')
                          % {'host': host, 'e': e})
                return None

        ips = self.configuration.netapp_controller_ips
        ips = [i.strip() for i in ips.split(",")]
        ips = [x for x in ips if _resolve_host(x)]
        host = utils.resolve_hostname(
            self.configuration.netapp_server_hostname)
        if not ips:
            msg = _('Controller ips not valid after resolution.')
            raise exception.NoValidHost(reason=msg)
        if host in ips:
            LOG.info(_('Embedded mode detected.'))
            system = self._client.list_storage_systems()[0]
        else:
            LOG.info(_('Proxy mode detected.'))
            system = self._client.register_storage_system(
                ips, password=self.configuration.netapp_sa_password)
        self._client.set_system_id(system.get('id'))

    def _check_storage_system(self):
        """Checks whether system is registered and has good status."""
        try:
            system = self._client.list_storage_system()
        except exception.NetAppDriverException:
            with excutils.save_and_reraise_exception():
                msg = _("System with controller addresses [%s] is not"
                        " registered with web service.")
                LOG.info(msg % self.configuration.netapp_controller_ips)
        password_not_in_sync = False
        if system.get('status', '').lower() == 'passwordoutofsync':
            password_not_in_sync = True
            new_pwd = self.configuration.netapp_sa_password
            self._client.update_stored_system_password(new_pwd)
            time.sleep(self.SLEEP_SECS)
        sa_comm_timeout = 60
        comm_time = 0
        while True:
            system = self._client.list_storage_system()
            status = system.get('status', '').lower()
            # wait if array not contacted or
            # password was not in sync previously.
            if ((status == 'nevercontacted') or
                    (password_not_in_sync and status == 'passwordoutofsync')):
                LOG.info(_('Waiting for web service array communication.'))
                time.sleep(self.SLEEP_SECS)
                comm_time = comm_time + self.SLEEP_SECS
                if comm_time >= sa_comm_timeout:
                    msg = _("Failure in communication between web service and"
                            " array. Waited %s seconds. Verify array"
                            " configuration parameters.")
                    raise exception.NetAppDriverException(msg %
                                                          sa_comm_timeout)
            else:
                break
        msg_dict = {'id': system.get('id'), 'status': status}
        if (status == 'passwordoutofsync' or status == 'notsupported' or
                status == 'offline'):
            msg = _("System %(id)s found with bad status - %(status)s.")
            raise exception.NetAppDriverException(msg % msg_dict)
        LOG.info(_("System %(id)s has %(status)s status.") % msg_dict)
        return True

    def _populate_system_objects(self):
        """Get all system objects into cache."""
        self._cache_allowed_disk_pool_refs()
        for vol in self._client.list_volumes():
            self._cache_volume(vol)
        for sn in self._client.list_snapshot_groups():
            self._cache_snap_grp(sn)
        for image in self._client.list_snapshot_images():
            self._cache_snap_img(image)

    def _cache_allowed_disk_pool_refs(self):
        """Caches disk pools refs as per pools configured by user."""
        d_pools = self.configuration.netapp_storage_pools
        LOG.info(_('Configured storage pools %s.'), d_pools)
        pools = [x.strip().lower() if x else None for x in d_pools.split(',')]
        for pool in self._client.list_storage_pools():
            if (pool.get('raidLevel') == 'raidDiskPool'
                    and pool['label'].lower() in pools):
                self._objects['disk_pool_refs'].append(pool['volumeGroupRef'])
                self._objects['pools'].append(pool)

    def _cache_volume(self, obj):
        """Caches volumes for further reference."""
        if (obj.get('volumeUse') == 'standardVolume' and obj.get('label')
                and obj.get('volumeRef')):
            self._objects['volumes']['label_ref'][obj['label']]\
                = obj['volumeRef']
            self._objects['volumes']['ref_vol'][obj['volumeRef']] = obj

    def _cache_snap_grp(self, obj):
        """Caches snapshot groups."""
        if (obj.get('label') and obj.get('pitGroupRef') and
                obj.get('baseVolume') in self._objects['volumes']['ref_vol']):
            self._objects['snapshots']['label_ref'][obj['label']] =\
                obj['pitGroupRef']
            self._objects['snapshots']['ref_snap'][obj['pitGroupRef']] = obj

    def _cache_snap_img(self, image):
        """Caches snapshot image under corresponding snapshot group."""
        group_id = image.get('pitGroupRef')
        sn_gp = self._objects['snapshots']['ref_snap']
        if group_id in sn_gp:
            sn_gp[group_id]['images'] = sn_gp[group_id].get('images') or []
            sn_gp[group_id]['images'].append(image)

    def _cache_vol_mapping(self, mapping):
        """Caches volume mapping in volume object."""
        vol_id = mapping['volumeRef']
        volume = self._objects['volumes']['ref_vol'][vol_id]
        volume['listOfMappings'] = volume.get('listOfMappings') or []
        for mapp in volume['listOfMappings']:
            if mapp['lunMappingRef'] == mapping['lunMappingRef']:
                return
        volume['listOfMappings'].append(mapping)

    def _del_volume_frm_cache(self, label):
        """Deletes volume from cache."""
        vol_id = self._objects['volumes']['label_ref'].get(label)
        if vol_id:
            self._objects['volumes']['ref_vol'].pop(vol_id, True)
            self._objects['volumes']['label_ref'].pop(label)
        else:
            LOG.debug("Volume %s not cached.", label)

    def _del_snapshot_frm_cache(self, obj_name):
        """Deletes snapshot group from cache."""
        snap_id = self._objects['snapshots']['label_ref'].get(obj_name)
        if snap_id:
            self._objects['snapshots']['ref_snap'].pop(snap_id, True)
            self._objects['snapshots']['label_ref'].pop(obj_name)
        else:
            LOG.debug("Snapshot %s not cached.", obj_name)

    def _del_vol_mapping_frm_cache(self, mapping):
        """Deletes volume mapping under cached volume."""
        vol_id = mapping['volumeRef']
        volume = self._objects['volumes']['ref_vol'].get(vol_id) or {}
        mappings = volume.get('listOfMappings') or []
        try:
            mappings.remove(mapping)
        except ValueError:
            LOG.debug("Mapping with id %s already removed.",
                      mapping['lunMappingRef'])

    def _get_volume(self, uid):
        label = utils.convert_uuid_to_es_fmt(uid)
        try:
            return self._get_cached_volume(label)
        except KeyError:
            return self._get_latest_volume(uid)

    def _get_latest_volume(self, uid):
        label = utils.convert_uuid_to_es_fmt(uid)
        for vol in self._client.list_volumes():
            if vol.get('label') == label:
                self._cache_volume(vol)
                return self._get_cached_volume(label)
        raise exception.NetAppDriverException(_("Volume %s not found."), uid)

    def _get_cached_volume(self, label):
        vol_id = self._objects['volumes']['label_ref'][label]
        return self._objects['volumes']['ref_vol'][vol_id]

    def _get_cached_snapshot_grp(self, uid):
        label = utils.convert_uuid_to_es_fmt(uid)
        snap_id = self._objects['snapshots']['label_ref'][label]
        return self._objects['snapshots']['ref_snap'][snap_id]

    def _get_cached_snap_grp_image(self, uid):
        group = self._get_cached_snapshot_grp(uid)
        images = group.get('images')
        if images:
            sorted_imgs = sorted(images, key=lambda x: x['pitTimestamp'])
            return sorted_imgs[0]
        msg = _("No pit image found in snapshot group %s.") % group['label']
        raise exception.NotFound(msg)

    def _is_volume_containing_snaps(self, label):
        """Checks if volume contains snapshot groups."""
        vol_id = self._objects['volumes']['label_ref'].get(label)
        snp_grps = self._objects['snapshots']['ref_snap'].values()
        for snap in snp_grps:
            if snap['baseVolume'] == vol_id:
                return True
        return False

    def get_pool(self, volume):
        """Return pool name where volume resides.

        :param volume: The volume hosted by the driver.
        :return: Name of the pool where given volume is hosted.
        """
        eseries_volume = self._get_volume(volume['id'])
        for pool in self._objects['pools']:
            if pool['volumeGroupRef'] == eseries_volume['volumeGroupRef']:
                return pool['label']
        return None

    def create_volume(self, volume):
        """Creates a volume."""

        LOG.debug('create_volume on %s' % volume['host'])

        # get E-series pool label as pool name
        eseries_pool_label = volume_utils.extract_host(volume['host'],
                                                       level='pool')

        if eseries_pool_label is None:
            msg = _("Pool is not available in the volume host field.")
            raise exception.InvalidHost(reason=msg)

        eseries_volume_label = utils.convert_uuid_to_es_fmt(volume['id'])

        # get size of the requested volume creation
        size_gb = int(volume['size'])
        vol = self._create_volume(eseries_pool_label, eseries_volume_label,
                                  size_gb)
        self._cache_volume(vol)

    def _create_volume(self, eseries_pool_label, eseries_volume_label,
                       size_gb):
        """Creates volume with given label and size."""

        target_pool = None

        pools = self._client.list_storage_pools()
        for pool in pools:
            if pool["label"] == eseries_pool_label:
                target_pool = pool
                break

        if not target_pool:
            msg = _("Pools %s does not exist")
            raise exception.NetAppDriverException(msg % eseries_pool_label)

        try:
            vol = self._client.create_volume(target_pool['volumeGroupRef'],
                                             eseries_volume_label, size_gb)
            LOG.info(_("Created volume with label %s."), eseries_volume_label)
        except exception.NetAppDriverException as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Error creating volume. Msg - %s."),
                          six.text_type(e))

        return vol

    def _schedule_and_create_volume(self, label, size_gb):
        """Creates volume with given label and size."""
        avl_pools = self._get_sorted_avl_storage_pools(size_gb)
        for pool in avl_pools:
            try:
                vol = self._client.create_volume(pool['volumeGroupRef'],
                                                 label, size_gb)
                LOG.info(_("Created volume with label %s."), label)
                return vol
            except exception.NetAppDriverException as e:
                LOG.error(_("Error creating volume. Msg - %s."), e)
        msg = _("Failure creating volume %s.")
        raise exception.NetAppDriverException(msg % label)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        label = utils.convert_uuid_to_es_fmt(volume['id'])
        size = volume['size']
        dst_vol = self._schedule_and_create_volume(label, size)
        try:
            src_vol = None
            src_vol = self._create_snapshot_volume(snapshot['id'])
            self._copy_volume_high_prior_readonly(src_vol, dst_vol)
            self._cache_volume(dst_vol)
            LOG.info(_("Created volume with label %s."), label)
        except exception.NetAppDriverException:
            with excutils.save_and_reraise_exception():
                self._client.delete_volume(dst_vol['volumeRef'])
        finally:
            if src_vol:
                try:
                    self._client.delete_snapshot_volume(src_vol['id'])
                except exception.NetAppDriverException as e:
                    LOG.error(_("Failure deleting snap vol. Error: %s."), e)
            else:
                LOG.warn(_("Snapshot volume not found."))

    def _create_snapshot_volume(self, snapshot_id):
        """Creates snapshot volume for given group with snapshot_id."""
        group = self._get_cached_snapshot_grp(snapshot_id)
        LOG.debug("Creating snap vol for group %s", group['label'])
        image = self._get_cached_snap_grp_image(snapshot_id)
        label = utils.convert_uuid_to_es_fmt(uuid.uuid4())
        capacity = int(image['pitCapacity']) / units.Gi
        storage_pools = self._get_sorted_avl_storage_pools(capacity)
        s_id = storage_pools[0]['volumeGroupRef']
        return self._client.create_snapshot_volume(image['pitRef'], label,
                                                   group['baseVolume'], s_id)

    def _copy_volume_high_prior_readonly(self, src_vol, dst_vol):
        """Copies src volume to dest volume."""
        LOG.info(_("Copying src vol %(src)s to dest vol %(dst)s.")
                 % {'src': src_vol['label'], 'dst': dst_vol['label']})
        try:
            job = None
            job = self._client.create_volume_copy_job(src_vol['id'],
                                                      dst_vol['volumeRef'])
            while True:
                j_st = self._client.list_vol_copy_job(job['volcopyRef'])
                if (j_st['status'] == 'inProgress' or j_st['status'] ==
                        'pending' or j_st['status'] == 'unknown'):
                    time.sleep(self.SLEEP_SECS)
                    continue
                if (j_st['status'] == 'failed' or j_st['status'] == 'halted'):
                    LOG.error(_("Vol copy job status %s."), j_st['status'])
                    msg = _("Vol copy job for dest %s failed.")\
                        % dst_vol['label']
                    raise exception.NetAppDriverException(msg)
                LOG.info(_("Vol copy job completed for dest %s.")
                         % dst_vol['label'])
                break
        finally:
            if job:
                try:
                    self._client.delete_vol_copy_job(job['volcopyRef'])
                except exception.NetAppDriverException:
                    LOG.warn(_("Failure deleting job %s."), job['volcopyRef'])
            else:
                LOG.warn(_('Volume copy job for src vol %s not found.'),
                         src_vol['id'])
        LOG.info(_('Copy job to dest vol %s completed.'), dst_vol['label'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        snapshot = {'id': uuid.uuid4(), 'volume_id': src_vref['id']}
        self.create_snapshot(snapshot)
        try:
            self.create_volume_from_snapshot(volume, snapshot)
        finally:
            try:
                self.delete_snapshot(snapshot)
            except exception.NetAppDriverException:
                LOG.warn(_("Failure deleting temp snapshot %s."),
                         snapshot['id'])

    def delete_volume(self, volume):
        """Deletes a volume."""
        try:
            vol = self._get_volume(volume['id'])
            self._delete_volume(vol['label'])
        except KeyError:
            LOG.info(_("Volume %s already deleted."), volume['id'])
            return

    def _delete_volume(self, label):
        """Deletes an array volume."""
        vol_id = self._objects['volumes']['label_ref'].get(label)
        if vol_id:
            self._client.delete_volume(vol_id)
            self._del_volume_frm_cache(label)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        snap_grp, snap_image = None, None
        snapshot_name = utils.convert_uuid_to_es_fmt(snapshot['id'])
        vol = self._get_volume(snapshot['volume_id'])
        vol_size_gb = int(vol['totalSizeInBytes']) / units.Gi
        pools = self._get_sorted_avl_storage_pools(vol_size_gb)
        try:
            snap_grp = self._client.create_snapshot_group(
                snapshot_name, vol['volumeRef'], pools[0]['volumeGroupRef'])
            self._cache_snap_grp(snap_grp)
            snap_image = self._client.create_snapshot_image(
                snap_grp['pitGroupRef'])
            self._cache_snap_img(snap_image)
            LOG.info(_("Created snap grp with label %s."), snapshot_name)
        except exception.NetAppDriverException:
            with excutils.save_and_reraise_exception():
                if snap_image is None and snap_grp:
                    self.delete_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        try:
            snap_grp = self._get_cached_snapshot_grp(snapshot['id'])
        except KeyError:
            LOG.warn(_("Snapshot %s already deleted.") % snapshot['id'])
            return
        self._client.delete_snapshot_group(snap_grp['pitGroupRef'])
        snapshot_name = snap_grp['label']
        self._del_snapshot_frm_cache(snapshot_name)

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a volume."""
        pass

    def create_export(self, context, volume):
        """Exports the volume."""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a volume."""
        pass

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        initiator_name = connector['initiator']
        vol = self._get_latest_volume(volume['id'])
        iscsi_details = self._get_iscsi_service_details()
        iscsi_det = self._get_iscsi_portal_for_vol(vol, iscsi_details)
        mapping = self._map_volume_to_host(vol, initiator_name)
        lun_id = mapping['lun']
        self._cache_vol_mapping(mapping)
        msg = _("Mapped volume %(id)s to the initiator %(initiator_name)s.")
        msg_fmt = {'id': volume['id'], 'initiator_name': initiator_name}
        LOG.debug(msg % msg_fmt)
        msg = _("Successfully fetched target details for volume %(id)s and "
                "initiator %(initiator_name)s.")
        LOG.debug(msg % msg_fmt)
        properties = {}
        properties['target_discovered'] = False
        properties['target_portal'] = '%s:%s' % (iscsi_det['ip'],
                                                 iscsi_det['tcp_port'])
        properties['target_iqn'] = iscsi_det['iqn']
        properties['target_lun'] = lun_id
        properties['volume_id'] = volume['id']
        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()
            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret
        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    def _get_iscsi_service_details(self):
        """Gets iscsi iqn, ip and port information."""
        ports = []
        hw_inventory = self._client.list_hardware_inventory()
        iscsi_ports = hw_inventory.get('iscsiPorts')
        if iscsi_ports:
            for port in iscsi_ports:
                if (port.get('ipv4Enabled') and port.get('iqn') and
                        port.get('ipv4Data') and
                        port['ipv4Data'].get('ipv4AddressData') and
                        port['ipv4Data']['ipv4AddressData']
                        .get('ipv4Address') and port['ipv4Data']
                        ['ipv4AddressData'].get('configState')
                        == 'configured'):
                    iscsi_det = {}
                    iscsi_det['ip'] =\
                        port['ipv4Data']['ipv4AddressData']['ipv4Address']
                    iscsi_det['iqn'] = port['iqn']
                    iscsi_det['tcp_port'] = port.get('tcpListenPort')
                    iscsi_det['controller'] = port.get('controllerId')
                    ports.append(iscsi_det)
        if not ports:
            msg = _('No good iscsi portals found for %s.')
            raise exception.NetAppDriverException(
                msg % self._client.get_system_id())
        return ports

    def _get_iscsi_portal_for_vol(self, volume, portals, anyController=True):
        """Get the iscsi portal info relevant to volume."""
        for portal in portals:
            if portal.get('controller') == volume.get('currentManager'):
                return portal
        if anyController and portals:
            return portals[0]
        msg = _('No good iscsi portal found in supplied list for %s.')
        raise exception.NetAppDriverException(
            msg % self._client.get_system_id())

    @cinder_utils.synchronized('map_es_volume')
    def _map_volume_to_host(self, vol, initiator):
        """Maps the e-series volume to host with initiator."""
        host = self._get_or_create_host(initiator)
        vol_maps = self._get_host_mapping_for_vol_frm_array(vol)
        for vol_map in vol_maps:
            if vol_map.get('mapRef') == host['hostRef']:
                return vol_map
            else:
                self._client.delete_volume_mapping(vol_map['lunMappingRef'])
                self._del_vol_mapping_frm_cache(vol_map)
        mappings = self._get_vol_mapping_for_host_frm_array(host['hostRef'])
        lun = self._get_free_lun(host, mappings)
        return self._client.create_volume_mapping(vol['volumeRef'],
                                                  host['hostRef'], lun)

    def _get_or_create_host(self, port_id, host_type='linux'):
        """Fetch or create a host by given port."""
        try:
            return self._get_host_with_port(port_id, host_type)
        except exception.NotFound as e:
            LOG.warn(_("Message - %s."), e.msg)
            return self._create_host(port_id, host_type)

    def _get_host_with_port(self, port_id, host_type='linux'):
        """Gets or creates a host with given port id."""
        hosts = self._client.list_hosts()
        ht_def = self._get_host_type_definition(host_type)
        for host in hosts:
            if (host.get('hostTypeIndex') == ht_def.get('index')
                    and host.get('hostSidePorts')):
                ports = host.get('hostSidePorts')
                for port in ports:
                    if (port.get('type') == 'iscsi'
                            and port.get('address') == port_id):
                        return host
        msg = _("Host with port %(port)s and type %(type)s not found.")
        raise exception.NotFound(msg % {'port': port_id, 'type': host_type})

    def _create_host(self, port_id, host_type='linux'):
        """Creates host on system with given initiator as port_id."""
        LOG.info(_("Creating host with port %s."), port_id)
        label = utils.convert_uuid_to_es_fmt(uuid.uuid4())
        port_label = utils.convert_uuid_to_es_fmt(uuid.uuid4())
        host_type = self._get_host_type_definition(host_type)
        return self._client.create_host_with_port(label, host_type,
                                                  port_id, port_label)

    def _get_host_type_definition(self, host_type='linux'):
        """Gets supported host type if available on storage system."""
        host_types = self._client.list_host_types()
        for ht in host_types:
            if ht.get('name', 'unknown').lower() == host_type.lower():
                return ht
        raise exception.NotFound(_("Host type %s not supported.") % host_type)

    def _get_free_lun(self, host, maps=None):
        """Gets free lun for given host."""
        ref = host['hostRef']
        luns = maps or self._get_vol_mapping_for_host_frm_array(ref)
        used_luns = set(map(lambda lun: int(lun['lun']), luns))
        for lun in xrange(self.MAX_LUNS_PER_HOST):
            if lun not in used_luns:
                return lun
        msg = _("No free luns. Host might exceeded max luns.")
        raise exception.NetAppDriverException(msg)

    def _get_vol_mapping_for_host_frm_array(self, host_ref):
        """Gets all volume mappings for given host from array."""
        mappings = self._client.get_volume_mappings() or []
        host_maps = filter(lambda x: x.get('mapRef') == host_ref, mappings)
        return host_maps

    def _get_host_mapping_for_vol_frm_array(self, volume):
        """Gets all host mappings for given volume from array."""
        mappings = self._client.get_volume_mappings() or []
        host_maps = filter(lambda x: x.get('volumeRef') == volume['volumeRef'],
                           mappings)
        return host_maps

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        vol = self._get_volume(volume['id'])
        host = self._get_host_with_port(connector['initiator'])
        mapping = self._get_cached_vol_mapping_for_host(vol, host)
        self._client.delete_volume_mapping(mapping['lunMappingRef'])
        self._del_vol_mapping_frm_cache(mapping)

    def _get_cached_vol_mapping_for_host(self, volume, host):
        """Gets cached volume mapping for given host."""
        mappings = volume.get('listOfMappings') or []
        for mapping in mappings:
            if mapping.get('mapRef') == host['hostRef']:
                return mapping
        msg = _("Mapping not found for %(vol)s to host %(ht)s.")
        raise exception.NotFound(msg % {'vol': volume['volumeRef'],
                                        'ht': host['hostRef']})

    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service."""
        if refresh:
            self._update_volume_stats()
        return self._stats

    def _update_volume_stats(self):
        """Update volume statistics."""
        LOG.debug("Updating volume stats.")
        data = dict()
        netapp_backend = "NetApp_ESeries"
        backend_name = self.configuration.safe_get("volume_backend_name")
        data["volume_backend_name"] = (backend_name or netapp_backend)
        data["vendor_name"] = "NetApp"
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = "iSCSI"
        data["pools"] = []

        pools = self._client.list_storage_pools()
        for pool in pools:
            cinder_pool = {}
            cinder_pool["pool_name"] = pool.get("label", 0)
            cinder_pool["QoS_support"] = False
            cinder_pool["reserved_percentage"] = 0
            if pool["volumeGroupRef"] in self._objects["disk_pool_refs"]:
                tot_bytes = int(pool.get("totalRaidedSpace", 0))
                used_bytes = int(pool.get("usedSpace", 0))
                cinder_pool["free_capacity_gb"] = ((tot_bytes - used_bytes) /
                                                   units.Gi)
                cinder_pool["total_capacity_gb"] = tot_bytes / units.Gi
                data["pools"].append(cinder_pool)

        self._stats = data
        self._garbage_collect_tmp_vols()

    def _get_sorted_avl_storage_pools(self, size_gb):
        """Returns storage pools sorted on available capacity."""
        size = size_gb * units.Gi
        pools = self._client.list_storage_pools()
        sorted_pools = sorted(pools, key=lambda x:
                              (int(x.get('totalRaidedSpace', 0))
                               - int(x.get('usedSpace', 0))), reverse=True)
        avl_pools = [x for x in sorted_pools
                     if (x['volumeGroupRef'] in
                         self._objects['disk_pool_refs']) and
                     (int(x.get('totalRaidedSpace', 0)) -
                      int(x.get('usedSpace', 0) >= size))]
        if not avl_pools:
            msg = _("No storage pool found with available capacity %s.")
            LOG.warn(msg % size_gb)
        return avl_pools

    def extend_volume(self, volume, new_size):
        """Extend an existing volume to the new size."""
        stage_1, stage_2 = 0, 0
        src_vol = self._get_volume(volume['id'])
        src_label = src_vol['label']
        stage_label = 'tmp-%s' % utils.convert_uuid_to_es_fmt(uuid.uuid4())
        extend_vol = {'id': uuid.uuid4(), 'size': new_size}
        self.create_cloned_volume(extend_vol, volume)
        new_vol = self._get_volume(extend_vol['id'])
        try:
            stage_1 = self._client.update_volume(src_vol['id'], stage_label)
            stage_2 = self._client.update_volume(new_vol['id'], src_label)
            new_vol = stage_2
            self._cache_volume(new_vol)
            self._cache_volume(stage_1)
            LOG.info(_('Extended volume with label %s.'), src_label)
        except exception.NetAppDriverException:
            if stage_1 == 0:
                with excutils.save_and_reraise_exception():
                    self._client.delete_volume(new_vol['id'])
            if stage_2 == 0:
                with excutils.save_and_reraise_exception():
                    self._client.update_volume(src_vol['id'], src_label)
                    self._client.delete_volume(new_vol['id'])

    def _garbage_collect_tmp_vols(self):
        """Removes tmp vols with no snapshots."""
        try:
            if not utils.set_safe_attr(self, 'clean_job_running', True):
                LOG.warn(_('Returning as clean tmp vol job already running.'))
                return
            for label in self._objects['volumes']['label_ref'].keys():
                if (label.startswith('tmp-') and
                        not self._is_volume_containing_snaps(label)):
                    try:
                        self._delete_volume(label)
                    except exception.NetAppDriverException:
                        LOG.debug("Error deleting vol with label %s.",
                                  label)
        finally:
            utils.set_safe_attr(self, 'clean_job_running', False)
