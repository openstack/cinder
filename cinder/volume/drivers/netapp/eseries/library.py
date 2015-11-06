# Copyright (c) 2015 Alex Meade
# Copyright (c) 2015 Rushil Chugh
# Copyright (c) 2015 Navneet Singh
# Copyright (c) 2015 Yogesh Kshirsagar
# Copyright (c) 2015 Tom Barron
# Copyright (c) 2015 Michael Price
#  All Rights Reserved.
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

import copy
import math
import socket
import time
import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_log import versionutils
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import utils as cinder_utils
from cinder.volume.drivers.netapp.eseries import client
from cinder.volume.drivers.netapp.eseries import exception as eseries_exc
from cinder.volume.drivers.netapp.eseries import host_mapper
from cinder.volume.drivers.netapp.eseries import utils
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import utils as volume_utils
from cinder.zonemanager import utils as fczm_utils


LOG = logging.getLogger(__name__)

CONF = cfg.CONF


@six.add_metaclass(cinder_utils.TraceWrapperMetaclass)
class NetAppESeriesLibrary(object):
    """Executes commands relating to Volumes."""

    DRIVER_NAME = 'NetApp_iSCSI_ESeries'
    AUTOSUPPORT_INTERVAL_SECONDS = 3600  # hourly
    VERSION = "1.0.0"
    REQUIRED_FLAGS = ['netapp_server_hostname', 'netapp_controller_ips',
                      'netapp_login', 'netapp_password']
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
        'ssd': 'SSD',
    }
    SSC_RAID_TYPE_MAPPING = {
        'raidDiskPool': 'DDP',
        'raid0': 'raid0',
        'raid1': 'raid1',
        # RAID3 is being deprecated and is actually implemented as RAID5
        'raid3': 'raid5',
        'raid5': 'raid5',
        'raid6': 'raid6',
    }
    READ_CACHE_Q_SPEC = 'netapp:read_cache'
    WRITE_CACHE_Q_SPEC = 'netapp:write_cache'
    DA_UQ_SPEC = 'netapp_eseries_data_assurance'
    FLASH_CACHE_UQ_SPEC = 'netapp_eseries_flash_read_cache'
    DISK_TYPE_UQ_SPEC = 'netapp_disk_type'
    ENCRYPTION_UQ_SPEC = 'netapp_disk_encryption'
    SPINDLE_SPD_UQ_SPEC = 'netapp_eseries_disk_spindle_speed'
    RAID_UQ_SPEC = 'netapp_raid_type'
    THIN_UQ_SPEC = 'netapp_thin_provisioned'
    SSC_UPDATE_INTERVAL = 60  # seconds
    WORLDWIDENAME = 'worldWideName'

    DEFAULT_HOST_TYPE = 'linux_dm_mp'

    def __init__(self, driver_name, driver_protocol="iSCSI",
                 configuration=None, **kwargs):
        self.configuration = configuration
        self._app_version = kwargs.pop("app_version", "unknown")
        self.configuration.append_config_values(na_opts.netapp_basicauth_opts)
        self.configuration.append_config_values(
            na_opts.netapp_connection_opts)
        self.configuration.append_config_values(na_opts.netapp_transport_opts)
        self.configuration.append_config_values(na_opts.netapp_eseries_opts)
        self.configuration.append_config_values(na_opts.netapp_san_opts)
        self.lookup_service = fczm_utils.create_lookup_service()
        self._backend_name = self.configuration.safe_get(
            "volume_backend_name") or "NetApp_ESeries"
        self.driver_name = driver_name
        self.driver_protocol = driver_protocol
        self._stats = {}
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

        # Start the task that logs autosupport (ASUP) data to the controller
        asup_periodic_task = loopingcall.FixedIntervalLoopingCall(
            self._create_asup, CONF.host)
        asup_periodic_task.start(interval=self.AUTOSUPPORT_INTERVAL_SECONDS,
                                 initial_delay=0)

    def check_for_setup_error(self):
        self._check_host_type()
        self._check_multipath()
        self._check_pools()
        self._check_storage_system()
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

    def _check_pools(self):
        """Ensure that the pool listing contains at least one pool"""
        if not self._get_storage_pools():
            msg = _('No pools are available for provisioning volumes. '
                    'Ensure that the configuration option '
                    'netapp_pool_name_search_pattern is set correctly.')
            raise exception.NetAppDriverException(msg)

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
                    % {'host': host, 'e': e})

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
        self._client._init_features()

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

    def _get_volume(self, uid):
        """Retrieve a volume by its label"""
        if uid is None:
            raise exception.InvalidInput(_('The volume label is required'
                                           ' as input.'))

        uid = utils.convert_uuid_to_es_fmt(uid)

        return self._client.list_volume(uid)

    def _get_snapshot_group_for_snapshot(self, snapshot_id):
        label = utils.convert_uuid_to_es_fmt(snapshot_id)
        for group in self._client.list_snapshot_groups():
            if group['label'] == label:
                return group
        msg = _("Specified snapshot group with label %s could not be found.")
        raise exception.NotFound(msg % label)

    def _get_latest_image_in_snapshot_group(self, snapshot_id):
        group = self._get_snapshot_group_for_snapshot(snapshot_id)
        images = self._client.list_snapshot_images()
        if images:
            filtered_images = filter(lambda img: (img['pitGroupRef'] ==
                                                  group['pitGroupRef']),
                                     images)
            sorted_imgs = sorted(filtered_images, key=lambda x: x[
                'pitTimestamp'])
            return sorted_imgs[0]

        msg = _("No snapshot image found in snapshot group %s.")
        raise exception.NotFound(msg % group['label'])

    def _is_volume_containing_snaps(self, label):
        """Checks if volume contains snapshot groups."""
        vol_id = utils.convert_es_fmt_to_uuid(label)
        for snap in self._client.list_snapshot_groups():
            if snap['baseVolume'] == vol_id:
                return True
        return False

    def get_pool(self, volume):
        """Return pool name where volume resides.

        :param volume: The volume hosted by the driver.
        :return: Name of the pool where given volume is hosted.
        """
        eseries_volume = self._get_volume(volume['name_id'])
        storage_pool = self._client.get_storage_pool(
            eseries_volume['volumeGroupRef'])
        if storage_pool:
            return storage_pool.get('label')

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

        extra_specs = na_utils.get_volume_extra_specs(volume)

        # get size of the requested volume creation
        size_gb = int(volume['size'])
        self._create_volume(eseries_pool_label, eseries_volume_label, size_gb,
                            extra_specs)

    def _create_volume(self, eseries_pool_label, eseries_volume_label,
                       size_gb, extra_specs=None):
        """Creates volume with given label and size."""
        if extra_specs is None:
            extra_specs = {}

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

        # These must be either boolean values, or None
        read_cache = extra_specs.get(self.READ_CACHE_Q_SPEC)
        if read_cache is not None:
            read_cache = na_utils.to_bool(read_cache)

        write_cache = extra_specs.get(self.WRITE_CACHE_Q_SPEC)
        if write_cache is not None:
            write_cache = na_utils.to_bool(write_cache)

        flash_cache = extra_specs.get(self.FLASH_CACHE_UQ_SPEC)
        if flash_cache is not None:
            flash_cache = na_utils.to_bool(flash_cache)

        data_assurance = extra_specs.get(self.DA_UQ_SPEC)
        if data_assurance is not None:
            data_assurance = na_utils.to_bool(data_assurance)

        thin_provision = extra_specs.get(self.THIN_UQ_SPEC)
        if(thin_provision is not None):
            thin_provision = na_utils.to_bool(thin_provision)

        target_pool = None

        pools = self._get_storage_pools()
        for pool in pools:
            if pool["label"] == eseries_pool_label:
                target_pool = pool
                break

        if not target_pool:
            msg = _("Pools %s does not exist")
            raise exception.NetAppDriverException(msg % eseries_pool_label)

        try:
            vol = self._client.create_volume(target_pool['volumeGroupRef'],
                                             eseries_volume_label, size_gb,
                                             read_cache=read_cache,
                                             write_cache=write_cache,
                                             flash_cache=flash_cache,
                                             data_assurance=data_assurance,
                                             thin_provision=thin_provision)
            LOG.info(_LI("Created volume with "
                         "label %s."), eseries_volume_label)
        except exception.NetAppDriverException as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error creating volume. Msg - %s."), e)
                # There was some kind failure creating the volume, make sure no
                # partial flawed work exists
                try:
                    bad_vol = self._get_volume(eseries_volume_label)
                except Exception:
                    # Swallowing the exception intentionally because this is
                    # emergency cleanup to make sure no intermediate volumes
                    # were left. In this whole error situation, the more
                    # common route would be for no volume to have been created.
                    pass
                else:
                    # Some sort of partial volume was created despite the
                    # error.  Lets clean it out so no partial state volumes or
                    # orphans are left.
                    try:
                        self._client.delete_volume(bad_vol["id"])
                    except exception.NetAppDriverException as e2:
                        LOG.error(_LE(
                            "Error cleaning up failed volume creation.  "
                            "Msg - %s."), e2)

        return vol

    def _is_data_assurance_supported(self):
        """Determine if the storage backend is PI (DataAssurance) compatible"""
        return self.driver_protocol != "iSCSI"

    def _schedule_and_create_volume(self, label, size_gb):
        """Creates volume with given label and size."""
        avl_pools = self._get_sorted_available_storage_pools(size_gb)
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
        group = self._get_snapshot_group_for_snapshot(snapshot_id)
        LOG.debug("Creating snap vol for group %s", group['label'])
        image = self._get_latest_image_in_snapshot_group(snapshot_id)
        label = utils.convert_uuid_to_es_fmt(uuid.uuid4())
        capacity = int(image['pitCapacity']) / units.Gi
        storage_pools = self._get_sorted_available_storage_pools(capacity)
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
        snapshot = {'id': uuid.uuid4(), 'volume_id': src_vref['id'],
                    'volume': src_vref}
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
            self._client.delete_volume(vol['volumeRef'])
        except (exception.NetAppDriverException, KeyError):
            LOG.warning(_LW("Volume %s already deleted."), volume['id'])
            return

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        snap_grp, snap_image = None, None
        snapshot_name = utils.convert_uuid_to_es_fmt(snapshot['id'])
        os_vol = snapshot['volume']
        vol = self._get_volume(os_vol['name_id'])
        vol_size_gb = int(vol['totalSizeInBytes']) / units.Gi
        pools = self._get_sorted_available_storage_pools(vol_size_gb)
        try:
            snap_grp = self._client.create_snapshot_group(
                snapshot_name, vol['volumeRef'], pools[0]['volumeGroupRef'])
            snap_image = self._client.create_snapshot_image(
                snap_grp['pitGroupRef'])
            LOG.info(_LI("Created snap grp with label %s."), snapshot_name)
        except exception.NetAppDriverException:
            with excutils.save_and_reraise_exception():
                if snap_image is None and snap_grp:
                    self.delete_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        try:
            snap_grp = self._get_snapshot_group_for_snapshot(snapshot['id'])
        except exception.NotFound:
            LOG.warning(_LW("Snapshot %s already deleted."), snapshot['id'])
            return
        self._client.delete_snapshot_group(snap_grp['pitGroupRef'])

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a volume."""
        pass

    def create_export(self, context, volume):
        """Exports the volume."""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a volume."""
        pass

    def map_volume_to_host(self, volume, eseries_volume, initiators):
        """Ensures the specified initiator has access to the volume."""
        existing_maps = self._client.get_volume_mappings_for_volume(
            eseries_volume)
        host = self._get_or_create_host(initiators, self.host_type)
        # There can only be one or zero mappings on a volume in E-Series
        current_map = existing_maps[0] if existing_maps else None

        if self.configuration.netapp_enable_multiattach and current_map:
            self._ensure_multi_attach_host_group_exists()
            mapping = host_mapper.map_volume_to_multiple_hosts(self._client,
                                                               volume,
                                                               eseries_volume,
                                                               host,
                                                               current_map)
        else:
            mapping = host_mapper.map_volume_to_single_host(
                self._client, volume, eseries_volume, host, current_map,
                self.configuration.netapp_enable_multiattach)
        return mapping

    def initialize_connection_fc(self, volume, connector):
        """Initializes the connection and returns connection info.

        Assigns the specified volume to a compute node/host so that it can be
        used from that host.

        The driver returns a driver_volume_type of 'fibre_channel'.
        The target_wwn can be a single entry or a list of wwns that
        correspond to the list of remote wwn(s) that will export the volume.
        Example return values:
            {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': '500a098280feeba5',
                    'access_mode': 'rw',
                    'initiator_target_map': {
                        '21000024ff406cc3': ['500a098280feeba5'],
                        '21000024ff406cc2': ['500a098280feeba5']
                    }
                }
            }

            or

             {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': ['500a098280feeba5', '500a098290feeba5',
                                   '500a098190feeba5', '500a098180feeba5'],
                    'access_mode': 'rw',
                    'initiator_target_map': {
                        '21000024ff406cc3': ['500a098280feeba5',
                                             '500a098290feeba5'],
                        '21000024ff406cc2': ['500a098190feeba5',
                                             '500a098180feeba5']
                    }
                }
            }
        """

        initiators = [fczm_utils.get_formatted_wwn(wwpn)
                      for wwpn in connector['wwpns']]

        eseries_vol = self._get_volume(volume['name_id'])
        mapping = self.map_volume_to_host(volume, eseries_vol,
                                          initiators)
        lun_id = mapping['lun']

        initiator_info = self._build_initiator_target_map_fc(connector)
        target_wwpns, initiator_target_map, num_paths = initiator_info

        if target_wwpns:
            msg = ("Successfully fetched target details for LUN %(id)s "
                   "and initiator(s) %(initiators)s.")
            msg_fmt = {'id': volume['id'], 'initiators': initiators}
            LOG.debug(msg, msg_fmt)
        else:
            msg = _('Failed to get LUN target details for the LUN %s.')
            raise exception.VolumeBackendAPIException(data=msg % volume['id'])

        target_info = {'driver_volume_type': 'fibre_channel',
                       'data': {'target_discovered': True,
                                'target_lun': int(lun_id),
                                'target_wwn': target_wwpns,
                                'access_mode': 'rw',
                                'initiator_target_map': initiator_target_map}}

        return target_info

    def terminate_connection_fc(self, volume, connector, **kwargs):
        """Disallow connection from connector.

        Return empty data if other volumes are in the same zone.
        The FibreChannel ZoneManager doesn't remove zones
        if there isn't an initiator_target_map in the
        return of terminate_connection.

        :returns: data - the target_wwns and initiator_target_map if the
                         zone is to be removed, otherwise the same map with
                         an empty dict for the 'data' key
        """

        eseries_vol = self._get_volume(volume['name_id'])
        initiators = [fczm_utils.get_formatted_wwn(wwpn)
                      for wwpn in connector['wwpns']]
        host = self._get_host_with_matching_port(initiators)
        mappings = eseries_vol.get('listOfMappings', [])

        # There can only be one or zero mappings on a volume in E-Series
        mapping = mappings[0] if mappings else None

        if not mapping:
            raise eseries_exc.VolumeNotMapped(volume_id=volume['id'],
                                              host=host['label'])
        host_mapper.unmap_volume_from_host(self._client, volume, host, mapping)

        info = {'driver_volume_type': 'fibre_channel',
                'data': {}}

        if len(self._client.get_volume_mappings_for_host(
                host['hostRef'])) == 0:
            # No more exports for this host, so tear down zone.
            LOG.info(_LI("Need to remove FC Zone, building initiator "
                         "target map."))

            initiator_info = self._build_initiator_target_map_fc(connector)
            target_wwpns, initiator_target_map, num_paths = initiator_info

            info['data'] = {'target_wwn': target_wwpns,
                            'initiator_target_map': initiator_target_map}

        return info

    def _build_initiator_target_map_fc(self, connector):
        """Build the target_wwns and the initiator target map."""

        # get WWPNs from controller and strip colons
        all_target_wwpns = self._client.list_target_wwpns()
        all_target_wwpns = [six.text_type(wwpn).replace(':', '')
                            for wwpn in all_target_wwpns]

        target_wwpns = []
        init_targ_map = {}
        num_paths = 0

        if self.lookup_service:
            # Use FC SAN lookup to determine which ports are visible.
            dev_map = self.lookup_service.get_device_mapping_from_network(
                connector['wwpns'],
                all_target_wwpns)

            for fabric_name in dev_map:
                fabric = dev_map[fabric_name]
                target_wwpns += fabric['target_port_wwn_list']
                for initiator in fabric['initiator_port_wwn_list']:
                    if initiator not in init_targ_map:
                        init_targ_map[initiator] = []
                    init_targ_map[initiator] += fabric['target_port_wwn_list']
                    init_targ_map[initiator] = list(set(
                        init_targ_map[initiator]))
                    for target in init_targ_map[initiator]:
                        num_paths += 1
            target_wwpns = list(set(target_wwpns))
        else:
            initiator_wwns = connector['wwpns']
            target_wwpns = all_target_wwpns

            for initiator in initiator_wwns:
                init_targ_map[initiator] = target_wwpns

        return target_wwpns, init_targ_map, num_paths

    def initialize_connection_iscsi(self, volume, connector):
        """Allow connection to connector and return connection info."""
        initiator_name = connector['initiator']
        eseries_vol = self._get_volume(volume['name_id'])
        mapping = self.map_volume_to_host(volume, eseries_vol,
                                          [initiator_name])

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

    def _get_or_create_host(self, port_ids, host_type):
        """Fetch or create a host by given port."""
        try:
            host = self._get_host_with_matching_port(port_ids)
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
            return self._create_host(port_ids, host_type)

    def _get_host_with_matching_port(self, port_ids):
        """Gets or creates a host with given port id."""
        # Remove any extra colons
        port_ids = [six.text_type(wwpn).replace(':', '')
                    for wwpn in port_ids]
        hosts = self._client.list_hosts()
        for port_id in port_ids:
            for host in hosts:
                if host.get('hostSidePorts'):
                    ports = host.get('hostSidePorts')
                    for port in ports:
                        address = port.get('address').upper().replace(':', '')
                        if address == port_id.upper():
                            return host
        msg = _("Host with ports %(ports)s not found.")
        raise exception.NotFound(msg % {'ports': port_ids})

    def _create_host(self, port_ids, host_type, host_group=None):
        """Creates host on system with given initiator as port_id."""
        LOG.info(_LI("Creating host with ports %s."), port_ids)
        host_label = utils.convert_uuid_to_es_fmt(uuid.uuid4())
        host_type = self._get_host_type_definition(host_type)
        port_type = self.driver_protocol.lower()
        return self._client.create_host_with_ports(host_label,
                                                   host_type,
                                                   port_ids,
                                                   group_id=host_group,
                                                   port_type=port_type)

    def _get_host_type_definition(self, host_type):
        """Gets supported host type if available on storage system."""
        host_types = self._client.list_host_types()
        for ht in host_types:
            if ht.get('name', 'unknown').lower() == host_type.lower():
                return ht
        raise exception.NotFound(_("Host type %s not supported.") % host_type)

    def terminate_connection_iscsi(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        eseries_vol = self._get_volume(volume['name_id'])
        initiator = connector['initiator']
        host = self._get_host_with_matching_port([initiator])
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
        data["storage_protocol"] = self.driver_protocol
        data["pools"] = []

        for storage_pool in self._get_storage_pools():
            cinder_pool = {}
            cinder_pool["pool_name"] = storage_pool.get("label")
            cinder_pool["QoS_support"] = False
            cinder_pool["reserved_percentage"] = (
                self.configuration.reserved_percentage)
            cinder_pool["max_oversubscription_ratio"] = (
                self.configuration.max_over_subscription_ratio)
            tot_bytes = int(storage_pool.get("totalRaidedSpace", 0))
            used_bytes = int(storage_pool.get("usedSpace", 0))
            cinder_pool["provisioned_capacity_gb"] = used_bytes / units.Gi
            cinder_pool["free_capacity_gb"] = ((tot_bytes - used_bytes) /
                                               units.Gi)
            cinder_pool["total_capacity_gb"] = tot_bytes / units.Gi

            pool_ssc_stats = self._ssc_stats.get(
                storage_pool["volumeGroupRef"])

            if pool_ssc_stats:
                thin = pool_ssc_stats.get(self.THIN_UQ_SPEC) or False
                cinder_pool.update(pool_ssc_stats)
            else:
                thin = False
            cinder_pool["thin_provisioning_support"] = thin
            # All E-Series pools support thick provisioning
            cinder_pool["thick_provisioning_support"] = True

            data["pools"].append(cinder_pool)

        self._stats = data
        self._garbage_collect_tmp_vols()

    def _create_asup(self, cinder_host):
        if not self._client.features.AUTOSUPPORT:
            msg = _LI("E-series proxy API version %s does not support "
                      "autosupport logging.")
            LOG.info(msg % self._client.api_version)
            return

        firmware_version = self._client.get_firmware_version()
        event_source = ("Cinder driver %s" % self.DRIVER_NAME)
        category = "provisioning"
        event_description = "OpenStack Cinder connected to E-Series proxy"
        model = self._client.get_model_name()
        serial_numbers = self._client.get_serial_numbers()

        key = ("openstack-%s-%s-%s"
               % (cinder_host, serial_numbers[0], serial_numbers[1]))

        # The counter is being set here to a key-value combination
        # comprised of serial numbers and cinder host with a default
        # heartbeat of 1. The counter is set to inform the user that the
        # key does not have a stale value.
        self._client.set_counter("%s-heartbeat" % key, value=1)
        data = {
            'computer-name': cinder_host,
            'event-source': event_source,
            'app-version': self._app_version,
            'category': category,
            'event-description': event_description,
            'controller1-serial': serial_numbers[0],
            'controller2-serial': serial_numbers[1],
            'model': model,
            'system-version': firmware_version,
            'operating-mode': self._client.api_operating_mode
        }
        self._client.add_autosupport_data(key, data)

    @cinder_utils.synchronized("netapp_update_ssc_info", external=False)
    def _update_ssc_info(self):
        """Periodically runs to update ssc information from the backend.

        The self._ssc_stats attribute is updated with the following format.
        {<volume_group_ref> : {<ssc_key>: <ssc_value>}}
        """
        LOG.info(_LI("Updating storage service catalog information for "
                     "backend '%s'"), self._backend_name)

        relevant_pools = self._get_storage_pools()

        if self._client.features.SSC_API_V2:
            self._update_ssc_info_v2(relevant_pools)
        else:
            self._update_ssc_info_v1(relevant_pools)

    def _update_ssc_info_v1(self, relevant_pools):
        """Update ssc data using the legacy API

        :param relevant_pools: The pools that this driver cares about
        """
        msg = _LI("E-series proxy API version %(version)s does not "
                  "support full set of SSC extra specs. The proxy version"
                  " must be at at least %(min_version)s.")
        LOG.info(msg, {'version': self._client.api_version,
                       'min_version':
                       self._client.features.SSC_API_V2.minimum_version})

        self._ssc_stats = (
            self._update_ssc_disk_encryption(relevant_pools))
        self._ssc_stats = (
            self._update_ssc_disk_types(relevant_pools))
        self._ssc_stats = (
            self._update_ssc_raid_type(relevant_pools))

    def _update_ssc_info_v2(self, relevant_pools):
        """Update the ssc dictionary with ssc info for relevant pools

        :param relevant_pools: The pools that this driver cares about
        """
        ssc_stats = copy.deepcopy(self._ssc_stats)

        storage_pool_labels = [pool['label'] for pool in relevant_pools]

        ssc_data = self._client.list_ssc_storage_pools()
        ssc_data = [pool for pool in ssc_data
                    if pool['name'] in storage_pool_labels]

        for pool in ssc_data:
            poolId = pool['poolId']
            if poolId not in ssc_stats:
                ssc_stats[poolId] = {}

            pool_ssc_info = ssc_stats[poolId]

            pool_ssc_info[self.ENCRYPTION_UQ_SPEC] = (
                six.text_type(pool['encrypted']).lower())

            pool_ssc_info[self.SPINDLE_SPD_UQ_SPEC] = (pool['spindleSpeed'])

            flash_cache_capable = pool['flashCacheCapable']
            pool_ssc_info[self.FLASH_CACHE_UQ_SPEC] = (
                six.text_type(flash_cache_capable).lower())

            # Data Assurance is not compatible with some backend types
            da_capable = pool['dataAssuranceCapable'] and (
                self._is_data_assurance_supported())
            pool_ssc_info[self.DA_UQ_SPEC] = (
                six.text_type(da_capable).lower())

            pool_ssc_info[self.RAID_UQ_SPEC] = (
                self.SSC_RAID_TYPE_MAPPING.get(pool['raidLevel'], 'unknown'))

            pool_ssc_info[self.THIN_UQ_SPEC] = (
                six.text_type(pool['thinProvisioningCapable']).lower())

            if pool['pool'].get("driveMediaType") == 'ssd':
                pool_ssc_info[self.DISK_TYPE_UQ_SPEC] = 'SSD'
            else:
                pool_ssc_info[self.DISK_TYPE_UQ_SPEC] = (
                    self.SSC_DISK_TYPE_MAPPING.get(
                        pool['pool'].get('drivePhysicalType'), 'unknown'))

        self._ssc_stats = ssc_stats

    def _update_ssc_disk_types(self, storage_pools):
        """Updates the given ssc dictionary with new disk type information.

        :param storage_pools: The storage pools this driver cares about
        """
        ssc_stats = copy.deepcopy(self._ssc_stats)
        all_disks = self._client.list_drives()

        pool_ids = set(pool.get("volumeGroupRef") for pool in storage_pools)

        relevant_disks = filter(lambda x: x.get('currentVolumeGroupRef') in
                                pool_ids, all_disks)
        for drive in relevant_disks:
            current_vol_group = drive.get('currentVolumeGroupRef')
            if current_vol_group not in ssc_stats:
                ssc_stats[current_vol_group] = {}

            if drive.get("driveMediaType") == 'ssd':
                ssc_stats[current_vol_group][self.DISK_TYPE_UQ_SPEC] = 'SSD'
            else:
                disk_type = drive.get('interfaceType').get('driveType')
                ssc_stats[current_vol_group][self.DISK_TYPE_UQ_SPEC] = (
                    self.SSC_DISK_TYPE_MAPPING.get(disk_type, 'unknown'))

        return ssc_stats

    def _update_ssc_disk_encryption(self, storage_pools):
        """Updates the given ssc dictionary with new disk encryption information.

        :param storage_pools: The storage pools this driver cares about
        """
        ssc_stats = copy.deepcopy(self._ssc_stats)
        for pool in storage_pools:
            current_vol_group = pool.get('volumeGroupRef')
            if current_vol_group not in ssc_stats:
                ssc_stats[current_vol_group] = {}

            ssc_stats[current_vol_group][self.ENCRYPTION_UQ_SPEC] = (
                six.text_type(pool['securityType'] == 'enabled').lower()
            )

        return ssc_stats

    def _update_ssc_raid_type(self, storage_pools):
        """Updates the given ssc dictionary with new RAID type information.

        :param storage_pools: The storage pools this driver cares about
        """
        ssc_stats = copy.deepcopy(self._ssc_stats)
        for pool in storage_pools:
            current_vol_group = pool.get('volumeGroupRef')
            if current_vol_group not in ssc_stats:
                ssc_stats[current_vol_group] = {}

            raid_type = pool.get('raidLevel')
            ssc_stats[current_vol_group]['netapp_raid_type'] = (
                self.SSC_RAID_TYPE_MAPPING.get(raid_type, 'unknown'))

        return ssc_stats

    def _get_storage_pools(self):
        """Retrieve storage pools that match user-configured search pattern."""

        # Inform deprecation of legacy option.
        if self.configuration.safe_get('netapp_storage_pools'):
            msg = _LW("The option 'netapp_storage_pools' is deprecated and "
                      "will be removed in the future releases. Please use "
                      "the option 'netapp_pool_name_search_pattern' instead.")
            versionutils.report_deprecated_feature(LOG, msg)

        pool_regex = na_utils.get_pool_name_filter_regex(self.configuration)

        storage_pools = self._client.list_storage_pools()

        filtered_pools = []
        for pool in storage_pools:
            pool_name = pool['label']

            if pool_regex.match(pool_name):
                msg = ("Pool '%(pool_name)s' matches against regular "
                       "expression: %(pool_pattern)s")
                LOG.debug(msg, {'pool_name': pool_name,
                                'pool_pattern': pool_regex.pattern})
                filtered_pools.append(pool)
            else:
                msg = ("Pool '%(pool_name)s' does not match against regular "
                       "expression: %(pool_pattern)s")
                LOG.debug(msg, {'pool_name': pool_name,
                                'pool_pattern': pool_regex.pattern})

        return filtered_pools

    def _get_sorted_available_storage_pools(self, size_gb):
        """Returns storage pools sorted on available capacity."""
        size = size_gb * units.Gi
        sorted_pools = sorted(self._get_storage_pools(), key=lambda x:
                              (int(x.get('totalRaidedSpace', 0))
                               - int(x.get('usedSpace', 0))), reverse=True)
        avl_pools = filter(lambda x: ((int(x.get('totalRaidedSpace', 0)) -
                                       int(x.get('usedSpace', 0)) >= size)),
                           sorted_pools)

        if not avl_pools:
            LOG.warning(_LW("No storage pool found with available capacity "
                            "%s."), size_gb)
        return avl_pools

    def _is_thin_provisioned(self, volume):
        """Determine if a volume is thin provisioned"""
        return volume.get('objectType') == 'thinVolume' or volume.get(
            'thinProvisioned', False)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume to the new size."""
        src_vol = self._get_volume(volume['name_id'])
        if self._is_thin_provisioned(src_vol):
            self._client.expand_volume(src_vol['id'], new_size)
        else:
            stage_1, stage_2 = 0, 0
            src_label = src_vol['label']
            stage_label = 'tmp-%s' % utils.convert_uuid_to_es_fmt(uuid.uuid4())
            extend_vol = {'id': uuid.uuid4(), 'size': new_size}
            self.create_cloned_volume(extend_vol, volume)
            new_vol = self._get_volume(extend_vol['id'])
            try:
                stage_1 = self._client.update_volume(src_vol['id'],
                                                     stage_label)
                stage_2 = self._client.update_volume(new_vol['id'], src_label)
                new_vol = stage_2
                LOG.info(_LI('Extended volume with label %s.'), src_label)
            except exception.NetAppDriverException:
                if stage_1 == 0:
                    with excutils.save_and_reraise_exception():
                        self._client.delete_volume(new_vol['id'])
                elif stage_2 == 0:
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

            for vol in self._client.list_volumes():
                label = vol['label']
                if (label.startswith('tmp-') and
                        not self._is_volume_containing_snaps(label)):
                    try:
                        self._client.delete_volume(vol['volumeRef'])
                    except exception.NetAppDriverException as e:
                        LOG.debug("Error deleting vol with label %(label)s:"
                                  " %(error)s.", {'label': label, 'error': e})
        finally:
            na_utils.set_safe_attr(self, 'clean_job_running', False)

    @cinder_utils.synchronized('manage_existing')
    def manage_existing(self, volume, existing_ref):
        """Brings an existing storage object under Cinder management."""
        vol = self._get_existing_vol_with_manage_ref(existing_ref)
        label = utils.convert_uuid_to_es_fmt(volume['id'])
        if label == vol['label']:
            LOG.info(_LI("Volume with given ref %s need not be renamed during"
                         " manage operation."), existing_ref)
            managed_vol = vol
        else:
            managed_vol = self._client.update_volume(vol['id'], label)
        LOG.info(_LI("Manage operation completed for volume with new label"
                     " %(label)s and wwn %(wwn)s."),
                 {'label': label, 'wwn': managed_vol[self.WORLDWIDENAME]})

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.
        """
        vol = self._get_existing_vol_with_manage_ref(existing_ref)
        return int(math.ceil(float(vol['capacity']) / units.Gi))

    def _get_existing_vol_with_manage_ref(self, existing_ref):
        try:
            vol_id = existing_ref.get('source-name') or existing_ref.get(
                'source-id')
            return self._client.list_volume(vol_id)
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
