# Copyright (c) 2014 NetApp, Inc.  All Rights Reserved.
# Copyright (c) 2015 Alex Meade.  All Rights Reserved.
# Copyright (c) 2015 Rushil Chugh.  All Rights Reserved.
# Copyright (c) 2015 Navneet Singh.  All Rights Reserved.
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

import copy
import math
import socket
import time
import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.openstack.common import loopingcall
from cinder import utils as cinder_utils
from cinder.volume import driver
from cinder.volume.drivers.netapp.eseries import client
from cinder.volume.drivers.netapp.eseries import exception as eseries_exc
from cinder.volume.drivers.netapp.eseries import host_mapper
from cinder.volume.drivers.netapp.eseries import utils
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)


CONF = cfg.CONF
CONF.register_opts(na_opts.netapp_basicauth_opts)
CONF.register_opts(na_opts.netapp_connection_opts)
CONF.register_opts(na_opts.netapp_eseries_opts)
CONF.register_opts(na_opts.netapp_transport_opts)
CONF.register_opts(na_opts.netapp_san_opts)


class NetAppEseriesISCSIDriver(driver.ISCSIDriver):
    """Executes commands relating to Volumes."""

    VERSION = "1.0.0"
    REQUIRED_FLAGS = ['netapp_server_hostname', 'netapp_controller_ips',
                      'netapp_login', 'netapp_password',
                      'netapp_storage_pools']
    SLEEP_SECS = 5
    HOST_TYPES = {'aix': 'AIX MPIO',
                  'avt': 'AVT_4M',
                  'factoryDefault': 'FactoryDefault',
                  'hpux': 'HP-UX TPGS',
                  'linux_atto': 'LnxTPGSALUA',
                  'linux_dm_mp': 'LnxALUA',
                  'linux_mpp_rdac': 'Linux',
                  'linux_pathmanager': 'LnxTPGSALUA_PM',
                  'macos': 'MacTPGSALUA',
                  'ontap': 'ONTAP',
                  'svc': 'SVC',
                  'solaris_v11': 'SolTPGSALUA',
                  'solaris_v10': 'Solaris',
                  'vmware': 'VmwTPGSALUA',
                  'windows':
                  'Windows 2000/Server 2003/Server 2008 Non-Clustered',
                  'windows_atto': 'WinTPGSALUA',
                  'windows_clustered':
                  'Windows 2000/Server 2003/Server 2008 Clustered'
                  }
    # NOTE(ameade): This maps what is reported by the e-series api to a
    # consistent set of values that are reported by all NetApp drivers
    # to the cinder scheduler.
    SSC_DISK_TYPE_MAPPING = {
        'scsi': 'SCSI',
        'fibre': 'FCAL',
        'sas': 'SAS',
        'sata': 'SATA',
    }
    SSC_UPDATE_INTERVAL = 60  # seconds
    WORLDWIDENAME = 'worldWideName'

    DEFAULT_HOST_TYPE = 'linux_dm_mp'

    def __init__(self, *args, **kwargs):
        super(NetAppEseriesISCSIDriver, self).__init__(*args, **kwargs)
        na_utils.validate_instantiation(**kwargs)
        self.configuration.append_config_values(na_opts.netapp_basicauth_opts)
        self.configuration.append_config_values(
            na_opts.netapp_connection_opts)
        self.configuration.append_config_values(na_opts.netapp_transport_opts)
        self.configuration.append_config_values(na_opts.netapp_eseries_opts)
        self.configuration.append_config_values(na_opts.netapp_san_opts)
        self._backend_name = self.configuration.safe_get(
            "volume_backend_name") or "NetApp_ESeries"
        self._objects = {'disk_pool_refs': [], 'pools': [],
                         'volumes': {'label_ref': {}, 'ref_vol': {}},
                         'snapshots': {'label_ref': {}, 'ref_snap': {}}}
        self._ssc_stats = {}

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        self.context = context
        na_utils.check_flags(self.REQUIRED_FLAGS, self.configuration)

        self._client = self._create_rest_client(self.configuration)
        self._check_mode_get_or_register_storage_system()
        if self.configuration.netapp_enable_multiattach:
            self._ensure_multi_attach_host_group_exists()

    def _create_rest_client(self, configuration):
        port = configuration.netapp_server_port
        scheme = configuration.netapp_transport_type.lower()
        if port is None:
            if scheme == 'http':
                port = 8080
            elif scheme == 'https':
                port = 8443

        return client.RestClient(
            scheme=scheme,
            host=configuration.netapp_server_hostname,
            port=port,
            service_path=configuration.netapp_webservice_path,
            username=configuration.netapp_login,
            password=configuration.netapp_password)

    def _start_periodic_tasks(self):
        ssc_periodic_task = loopingcall.FixedIntervalLoopingCall(
            self._update_ssc_info)
        ssc_periodic_task.start(interval=self.SSC_UPDATE_INTERVAL)

    def check_for_setup_error(self):
        self._check_host_type()
        self._check_multipath()
        self._check_storage_system()
        self._populate_system_objects()
        self._start_periodic_tasks()

    def _check_host_type(self):
        host_type = (self.configuration.netapp_host_type
                     or self.DEFAULT_HOST_TYPE)
        self.host_type = self.HOST_TYPES.get(host_type)
        if not self.host_type:
            raise exception.NetAppDriverException(
                _('Configured host type is not supported.'))

    def _check_multipath(self):
        if not self.configuration.use_multipath_for_image_xfer:
            LOG.warning(_LW('Production use of "%(backend)s" backend requires '
                            'the Cinder controller to have multipathing '
                            'properly set up and the configuration option '
                            '"%(mpflag)s" to be set to "True".'),
                        {'backend': self._backend_name,
                         'mpflag': 'use_multipath_for_image_xfer'})

    def _ensure_multi_attach_host_group_exists(self):
        try:
            host_group = self._client.get_host_group_by_name(
                utils.MULTI_ATTACH_HOST_GROUP_NAME)
            LOG.info(_LI("The multi-attach E-Series host group '%(label)s' "
                         "already exists with clusterRef %(clusterRef)s"),
                     host_group)
        except exception.NotFound:
            host_group = self._client.create_host_group(
                utils.MULTI_ATTACH_HOST_GROUP_NAME)
            LOG.info(_LI("Created multi-attach E-Series host group %(label)s "
                         "with clusterRef %(clusterRef)s"), host_group)

    def _check_mode_get_or_register_storage_system(self):
        """Does validity checks for storage system registry and health."""
        def _resolve_host(host):
            try:
                ip = na_utils.resolve_hostname(host)
                return ip
            except socket.gaierror as e:
                LOG.error(_LE('Error resolving host %(host)s. Error - %(e)s.'),
                          {'host': host, 'e': e})
                raise exception.NoValidHost(
                    _("Controller IP '%(host)s' could not be resolved: %(e)s.")
                    % {'host': host, 'e': six.text_type(e)})

        ips = self.configuration.netapp_controller_ips
        ips = [i.strip() for i in ips.split(",")]
        ips = [x for x in ips if _resolve_host(x)]
        host = na_utils.resolve_hostname(
            self.configuration.netapp_server_hostname)
        if host in ips:
            LOG.info(_LI('Embedded mode detected.'))
            system = self._client.list_storage_systems()[0]
        else:
            LOG.info(_LI('Proxy mode detected.'))
            system = self._client.register_storage_system(
                ips, password=self.configuration.netapp_sa_password)
        self._client.set_system_id(system.get('id'))

    def _check_storage_system(self):
        """Checks whether system is registered and has good status."""
        try:
            system = self._client.list_storage_system()
        except exception.NetAppDriverException:
            with excutils.save_and_reraise_exception():
                LOG.info(_LI("System with controller addresses [%s] is not "
                             "registered with web service."),
                         self.configuration.netapp_controller_ips)
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
                LOG.info(_LI('Waiting for web service array communication.'))
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
            raise exception.NetAppDriverException(
                _("System %(id)s found with bad status - "
                  "%(status)s.") % msg_dict)
        LOG.info(_LI("System %(id)s has %(status)s status."), msg_dict)
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
        LOG.info(_LI('Configured storage pools %s.'), d_pools)
        pools = [x.strip().lower() if x else None for x in d_pools.split(',')]
        for pool in self._client.list_storage_pools():
            if (pool.get('raidLevel') == 'raidDiskPool'
                    and pool['label'].lower() in pools):
                self._objects['disk_pool_refs'].append(pool['volumeGroupRef'])
                self._objects['pools'].append(pool)

    def _cache_volume(self, obj):
        """Caches volumes for further reference."""
        if (obj.get('volumeUse') == 'standardVolume' and obj.get('label')
                and obj.get('volumeRef')
                and obj.get('volumeGroupRef') in
                self._objects['disk_pool_refs']):
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

    def _get_volume(self, uid):
        label = utils.convert_uuid_to_es_fmt(uid)
        return self._get_volume_with_label_wwn(label)

    def _get_volume_with_label_wwn(self, label=None, wwn=None):
        """Searches volume with label or wwn or both."""
        if not (label or wwn):
            raise exception.InvalidInput(_('Either volume label or wwn'
                                           ' is required as input.'))
        wwn = wwn.replace(':', '').upper() if wwn else None
        eseries_volume = None
        for vol in self._client.list_volumes():
            if label and vol.get('label') != label:
                continue
            if wwn and vol.get(self.WORLDWIDENAME).upper() != wwn:
                continue
            eseries_volume = vol
            self._cache_volume(vol)
            break

        if not eseries_volume:
            raise KeyError()
        return eseries_volume

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
        eseries_volume = self._get_volume(volume['name_id'])
        for pool in self._objects['pools']:
            if pool['volumeGroupRef'] == eseries_volume['volumeGroupRef']:
                return pool['label']
        return None

    def create_volume(self, volume):
        """Creates a volume."""

        LOG.debug('create_volume on %s', volume['host'])

        # get E-series pool label as pool name
        eseries_pool_label = volume_utils.extract_host(volume['host'],
                                                       level='pool')

        if eseries_pool_label is None:
            msg = _("Pool is not available in the volume host field.")
            raise exception.InvalidHost(reason=msg)

        eseries_volume_label = utils.convert_uuid_to_es_fmt(volume['name_id'])

        # get size of the requested volume creation
        size_gb = int(volume['size'])
        vol = self._create_volume(eseries_pool_label, eseries_volume_label,
                                  size_gb)
        self._cache_volume(vol)

    def _create_volume(self, eseries_pool_label, eseries_volume_label,
                       size_gb):
        """Creates volume with given label and size."""

        if self.configuration.netapp_enable_multiattach:
            volumes = self._client.list_volumes()
            # NOTE(ameade): Ensure we do not create more volumes than we could
            # map to the multi attach ESeries host group.
            if len(volumes) > utils.MAX_LUNS_PER_HOST_GROUP:
                msg = (_("Cannot create more than %(req)s volumes on the "
                         "ESeries array when 'netapp_enable_multiattach' is "
                         "set to true.") %
                       {'req': utils.MAX_LUNS_PER_HOST_GROUP})
                raise exception.NetAppDriverException(msg)

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
            LOG.info(_LI("Created volume with "
                         "label %s."), eseries_volume_label)
        except exception.NetAppDriverException as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error creating volume. Msg - %s."), e)

        return vol

    def _schedule_and_create_volume(self, label, size_gb):
        """Creates volume with given label and size."""
        avl_pools = self._get_sorted_avl_storage_pools(size_gb)
        for pool in avl_pools:
            try:
                vol = self._client.create_volume(pool['volumeGroupRef'],
                                                 label, size_gb)
                LOG.info(_LI("Created volume with label %s."), label)
                return vol
            except exception.NetAppDriverException as e:
                LOG.error(_LE("Error creating volume. Msg - %s."), e)
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
            LOG.info(_LI("Created volume with label %s."), label)
        except exception.NetAppDriverException:
            with excutils.save_and_reraise_exception():
                self._client.delete_volume(dst_vol['volumeRef'])
        finally:
            if src_vol:
                try:
                    self._client.delete_snapshot_volume(src_vol['id'])
                except exception.NetAppDriverException as e:
                    LOG.error(_LE("Failure deleting snap vol. Error: %s."), e)
            else:
                LOG.warning(_LW("Snapshot volume not found."))

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
        LOG.info(_LI("Copying src vol %(src)s to dest vol %(dst)s."),
                 {'src': src_vol['label'], 'dst': dst_vol['label']})
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
                if j_st['status'] == 'failed' or j_st['status'] == 'halted':
                    LOG.error(_LE("Vol copy job status %s."), j_st['status'])
                    raise exception.NetAppDriverException(
                        _("Vol copy job for dest %s failed.") %
                        dst_vol['label'])
                LOG.info(_LI("Vol copy job completed for dest %s."),
                         dst_vol['label'])
                break
        finally:
            if job:
                try:
                    self._client.delete_vol_copy_job(job['volcopyRef'])
                except exception.NetAppDriverException:
                    LOG.warning(_LW("Failure deleting "
                                    "job %s."), job['volcopyRef'])
            else:
                LOG.warning(_LW('Volume copy job for src vol %s not found.'),
                            src_vol['id'])
        LOG.info(_LI('Copy job to dest vol %s completed.'), dst_vol['label'])

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
                LOG.warning(_LW("Failure deleting temp snapshot %s."),
                            snapshot['id'])

    def delete_volume(self, volume):
        """Deletes a volume."""
        try:
            vol = self._get_volume(volume['name_id'])
            self._delete_volume(vol['label'])
        except KeyError:
            LOG.info(_LI("Volume %s already deleted."), volume['id'])
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
        os_vol = self.db.volume_get(self.context, snapshot['volume_id'])
        vol = self._get_volume(os_vol['name_id'])
        vol_size_gb = int(vol['totalSizeInBytes']) / units.Gi
        pools = self._get_sorted_avl_storage_pools(vol_size_gb)
        try:
            snap_grp = self._client.create_snapshot_group(
                snapshot_name, vol['volumeRef'], pools[0]['volumeGroupRef'])
            self._cache_snap_grp(snap_grp)
            snap_image = self._client.create_snapshot_image(
                snap_grp['pitGroupRef'])
            self._cache_snap_img(snap_image)
            LOG.info(_LI("Created snap grp with label %s."), snapshot_name)
        except exception.NetAppDriverException:
            with excutils.save_and_reraise_exception():
                if snap_image is None and snap_grp:
                    self.delete_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        try:
            snap_grp = self._get_cached_snapshot_grp(snapshot['id'])
        except KeyError:
            LOG.warning(_LW("Snapshot %s already deleted."), snapshot['id'])
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
        eseries_vol = self._get_volume(volume['name_id'])
        existing_maps = host_mapper.get_host_mapping_for_vol_frm_array(
            self._client, eseries_vol)
        host = self._get_or_create_host(initiator_name, self.host_type)
        # There can only be one or zero mappings on a volume in E-Series
        current_map = existing_maps[0] if existing_maps else None

        if self.configuration.netapp_enable_multiattach and current_map:
            self._ensure_multi_attach_host_group_exists()
            mapping = host_mapper.map_volume_to_multiple_hosts(self._client,
                                                               volume,
                                                               eseries_vol,
                                                               host,
                                                               current_map)
        else:
            mapping = host_mapper.map_volume_to_single_host(
                self._client, volume, eseries_vol, host, current_map,
                self.configuration.netapp_enable_multiattach)

        lun_id = mapping['lun']
        msg_fmt = {'id': volume['id'], 'initiator_name': initiator_name}
        LOG.debug("Mapped volume %(id)s to the initiator %(initiator_name)s.",
                  msg_fmt)

        iscsi_details = self._get_iscsi_service_details()
        iscsi_portal = self._get_iscsi_portal_for_vol(eseries_vol,
                                                      iscsi_details)
        LOG.debug("Successfully fetched target details for volume %(id)s and "
                  "initiator %(initiator_name)s.", msg_fmt)
        iqn = iscsi_portal['iqn']
        address = iscsi_portal['ip']
        port = iscsi_portal['tcp_port']
        properties = na_utils.get_iscsi_connection_properties(lun_id, volume,
                                                              iqn, address,
                                                              port)
        return properties

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

    def _get_or_create_host(self, port_id, host_type):
        """Fetch or create a host by given port."""
        try:
            host = self._get_host_with_port(port_id)
            ht_def = self._get_host_type_definition(host_type)
            if host.get('hostTypeIndex') != ht_def.get('index'):
                try:
                    host = self._client.update_host_type(
                        host['hostRef'], ht_def)
                except exception.NetAppDriverException as e:
                    LOG.warning(_LW("Unable to update host type for host with "
                                    "label %(l)s. %(e)s"),
                                {'l': host['label'], 'e': e.msg})
            return host
        except exception.NotFound as e:
            LOG.warning(_LW("Message - %s."), e.msg)
            return self._create_host(port_id, host_type)

    def _get_host_with_port(self, port_id):
        """Gets or creates a host with given port id."""
        hosts = self._client.list_hosts()
        for host in hosts:
            if host.get('hostSidePorts'):
                ports = host.get('hostSidePorts')
                for port in ports:
                    if (port.get('type') == 'iscsi'
                            and port.get('address') == port_id):
                        return host
        msg = _("Host with port %(port)s not found.")
        raise exception.NotFound(msg % {'port': port_id})

    def _create_host(self, port_id, host_type, host_group=None):
        """Creates host on system with given initiator as port_id."""
        LOG.info(_LI("Creating host with port %s."), port_id)
        label = utils.convert_uuid_to_es_fmt(uuid.uuid4())
        port_label = utils.convert_uuid_to_es_fmt(uuid.uuid4())
        host_type = self._get_host_type_definition(host_type)
        return self._client.create_host_with_port(label, host_type,
                                                  port_id, port_label,
                                                  group_id=host_group)

    def _get_host_type_definition(self, host_type):
        """Gets supported host type if available on storage system."""
        host_types = self._client.list_host_types()
        for ht in host_types:
            if ht.get('name', 'unknown').lower() == host_type.lower():
                return ht
        raise exception.NotFound(_("Host type %s not supported.") % host_type)

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        eseries_vol = self._get_volume(volume['name_id'])
        initiator = connector['initiator']
        host = self._get_host_with_port(initiator)
        mappings = eseries_vol.get('listOfMappings', [])

        # There can only be one or zero mappings on a volume in E-Series
        mapping = mappings[0] if mappings else None

        if not mapping:
            raise eseries_exc.VolumeNotMapped(volume_id=volume['id'],
                                              host=host['label'])
        host_mapper.unmap_volume_from_host(self._client, volume, host, mapping)

    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service."""
        if refresh:
            if not self._ssc_stats:
                self._update_ssc_info()
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Update volume statistics."""
        LOG.debug("Updating volume stats.")
        data = dict()
        data["volume_backend_name"] = self._backend_name
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

                pool_ssc_stats = self._ssc_stats.get(pool["volumeGroupRef"])

                if pool_ssc_stats:
                    cinder_pool.update(pool_ssc_stats)
                data["pools"].append(cinder_pool)

        self._stats = data
        self._garbage_collect_tmp_vols()

    @cinder_utils.synchronized("netapp_update_ssc_info", external=False)
    def _update_ssc_info(self):
        """Periodically runs to update ssc information from the backend.

        The self._ssc_stats attribute is updated with the following format.
        {<volume_group_ref> : {<ssc_key>: <ssc_value>}}
        """
        LOG.info(_LI("Updating storage service catalog information for "
                     "backend '%s'"), self._backend_name)
        self._ssc_stats = \
            self._update_ssc_disk_encryption(self._objects["disk_pool_refs"])
        self._ssc_stats = \
            self._update_ssc_disk_types(self._objects["disk_pool_refs"])

    def _update_ssc_disk_types(self, volume_groups):
        """Updates the given ssc dictionary with new disk type information.

        :param volume_groups: The volume groups this driver cares about
        """
        ssc_stats = copy.deepcopy(self._ssc_stats)
        all_disks = self._client.list_drives()
        relevant_disks = filter(lambda x: x.get('currentVolumeGroupRef') in
                                volume_groups, all_disks)
        for drive in relevant_disks:
            current_vol_group = drive.get('currentVolumeGroupRef')
            if current_vol_group not in ssc_stats:
                ssc_stats[current_vol_group] = {}

            if drive.get("driveMediaType") == 'ssd':
                ssc_stats[current_vol_group]['netapp_disk_type'] = 'SSD'
            else:
                disk_type = drive.get('interfaceType').get('driveType')
                ssc_stats[current_vol_group]['netapp_disk_type'] = \
                    self.SSC_DISK_TYPE_MAPPING.get(disk_type, 'unknown')

        return ssc_stats

    def _update_ssc_disk_encryption(self, volume_groups):
        """Updates the given ssc dictionary with new disk encryption information.

        :param volume_groups: The volume groups this driver cares about
        """
        ssc_stats = copy.deepcopy(self._ssc_stats)
        all_pools = self._client.list_storage_pools()
        relevant_pools = filter(lambda x: x.get('volumeGroupRef') in
                                volume_groups, all_pools)
        for pool in relevant_pools:
            current_vol_group = pool.get('volumeGroupRef')
            if current_vol_group not in ssc_stats:
                ssc_stats[current_vol_group] = {}

            ssc_stats[current_vol_group]['netapp_disk_encryption'] = 'true' \
                if pool['securityType'] == 'enabled' else 'false'

        return ssc_stats

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
            LOG.warning(_LW("No storage pool found with available capacity "
                            "%s."), size_gb)
        return avl_pools

    def extend_volume(self, volume, new_size):
        """Extend an existing volume to the new size."""
        stage_1, stage_2 = 0, 0
        src_vol = self._get_volume(volume['name_id'])
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
            LOG.info(_LI('Extended volume with label %s.'), src_label)
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
            if not na_utils.set_safe_attr(self, 'clean_job_running', True):
                LOG.warning(_LW('Returning as clean tmp '
                                'vol job already running.'))
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
            na_utils.set_safe_attr(self, 'clean_job_running', False)

    @cinder_utils.synchronized('manage_existing')
    def manage_existing(self, volume, existing_ref):
        """Brings an existing storage object under Cinder management."""
        vol = self._get_existing_vol_with_manage_ref(volume, existing_ref)
        label = utils.convert_uuid_to_es_fmt(volume['id'])
        if label == vol['label']:
            LOG.info(_LI("Volume with given ref %s need not be renamed during"
                         " manage operation."), existing_ref)
            managed_vol = vol
        else:
            managed_vol = self._client.update_volume(vol['id'], label)
            self._del_volume_frm_cache(vol['label'])
        self._cache_volume(managed_vol)
        LOG.info(_LI("Manage operation completed for volume with new label"
                     " %(label)s and wwn %(wwn)s."),
                 {'label': label, 'wwn': managed_vol[self.WORLDWIDENAME]})

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.
        """
        vol = self._get_existing_vol_with_manage_ref(volume, existing_ref)
        return int(math.ceil(float(vol['capacity']) / units.Gi))

    def _get_existing_vol_with_manage_ref(self, volume, existing_ref):
        try:
            return self._get_volume_with_label_wwn(
                existing_ref.get('source-name'), existing_ref.get('source-id'))
        except exception.InvalidInput:
            reason = _('Reference must contain either source-name'
                       ' or source-id element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        except KeyError:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_('Volume not found on configured storage pools.'))

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

           Does not delete the underlying backend storage object. Logs a
           message to indicate the volume is no longer under Cinder's control.
        """
        managed_vol = self._get_volume(volume['id'])
        LOG.info(_LI("Unmanaged volume with current label %(label)s and wwn "
                     "%(wwn)s."), {'label': managed_vol['label'],
                                   'wwn': managed_vol[self.WORLDWIDENAME]})
