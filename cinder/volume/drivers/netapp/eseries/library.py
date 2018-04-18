# Copyright (c) 2015 Alex Meade
# Copyright (c) 2015 Rushil Chugh
# Copyright (c) 2015 Navneet Singh
# Copyright (c) 2015 Yogesh Kshirsagar
# Copyright (c) 2015 Jose Porrua
# Copyright (c) 2015 Michael Price
# Copyright (c) 2015 Tom Barron
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
from cinder.i18n import _
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
    HOST_TYPES = {'factoryDefault': 'FactoryDefault',
                  'linux_atto': 'LnxTPGSALUA',
                  'linux_dm_mp': 'LnxALUA',
                  'linux_mpp_rdac': 'LNX',
                  'linux_pathmanager': 'LnxTPGSALUA_PM',
                  'linux_sf': 'LnxTPGSALUA_SF',
                  'ontap': 'ONTAP_ALUA',
                  'ontap_rdac': 'ONTAP_RDAC',
                  'vmware': 'VmwTPGSALUA',
                  'windows': 'W2KNETNCL',
                  'windows_atto': 'WinTPGSALUA',
                  'windows_clustered': 'W2KNETCL',
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
    SA_COMM_TIMEOUT = 30
    WORLDWIDENAME = 'worldWideName'

    DEFAULT_HOST_TYPE = 'linux_dm_mp'
    DEFAULT_CHAP_USER_NAME = 'eserieschapuser'

    # Define name marker string to use in snapshot groups that are for copying
    # volumes.  This is to differentiate them from ordinary snapshot groups.
    SNAPSHOT_VOL_COPY_SUFFIX = 'SGCV'
    # Define a name marker string used to identify snapshot volumes that have
    # an underlying snapshot that is awaiting deletion.
    SNAPSHOT_VOL_DEL_SUFFIX = '_DEL'
    # Maximum number of snapshots per snapshot group
    MAX_SNAPSHOT_COUNT = 32
    # Maximum number of snapshot groups
    MAX_SNAPSHOT_GROUP_COUNT = 4
    RESERVED_SNAPSHOT_GROUP_COUNT = 1
    SNAPSHOT_PERSISTENT_STORE_KEY = 'cinder-snapshots'
    SNAPSHOT_PERSISTENT_STORE_LOCK = str(uuid.uuid4())

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
        self._version_check()
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

    def _version_check(self):
        """Ensure that the minimum version of the REST API is available"""
        if not self._client.features.REST_1_4_RELEASE:
            min_version = (
                self._client.features.REST_1_4_RELEASE.minimum_version)
            raise exception.NetAppDriverException(
                'This version (%(cur)s of the NetApp SANtricity Webservices '
                'Proxy is not supported. Install version %(supp)s or '
                'later.' % {'cur': self._client.api_version,
                            'supp': min_version})

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
        # It is important that this be called before any other methods that
        # interact with the storage-system. It blocks until the
        # storage-system comes online.
        self._check_storage_system()
        self._check_pools()
        self._start_periodic_tasks()

    def _check_host_type(self):
        """Validate that the configured host-type is available for the array.

        Not all host-types are available on every firmware version.
        """
        requested_host_type = (self.configuration.netapp_host_type
                               or self.DEFAULT_HOST_TYPE)
        actual_host_type = (
            self.HOST_TYPES.get(requested_host_type, requested_host_type))

        for host_type in self._client.list_host_types():
            if(host_type.get('code') == actual_host_type or
               host_type.get('name') == actual_host_type):
                self.host_type = host_type.get('code')
                return
        exc_msg = _("The host-type '%s' is not supported on this storage "
                    "system.")
        raise exception.NetAppDriverException(exc_msg % requested_host_type)

    def _check_multipath(self):
        if not self.configuration.use_multipath_for_image_xfer:
            LOG.warning('Production use of "%(backend)s" backend requires '
                        'the Cinder controller to have multipathing '
                        'properly set up and the configuration option '
                        '"%(mpflag)s" to be set to "True".',
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
            LOG.info("The multi-attach E-Series host group '%(label)s' "
                     "already exists with clusterRef %(clusterRef)s",
                     host_group)
        except exception.NotFound:
            host_group = self._client.create_host_group(
                utils.MULTI_ATTACH_HOST_GROUP_NAME)
            LOG.info("Created multi-attach E-Series host group %(label)s "
                     "with clusterRef %(clusterRef)s", host_group)

    def _check_mode_get_or_register_storage_system(self):
        """Does validity checks for storage system registry and health."""
        def _resolve_host(host):
            try:
                ip = na_utils.resolve_hostname(host)
                return ip
            except socket.gaierror as e:
                LOG.error('Error resolving host %(host)s. Error - %(e)s.',
                          {'host': host, 'e': e})
                raise exception.NoValidBackend(
                    _("Controller IP '%(host)s' could not be resolved: %(e)s.")
                    % {'host': host, 'e': e})

        ips = self.configuration.netapp_controller_ips
        ips = [i.strip() for i in ips.split(",")]
        ips = [x for x in ips if _resolve_host(x)]
        host = na_utils.resolve_hostname(
            self.configuration.netapp_server_hostname)
        if host in ips:
            LOG.info('Embedded mode detected.')
            system = self._client.list_storage_systems()[0]
        else:
            LOG.info('Proxy mode detected.')
            system = self._client.register_storage_system(
                ips, password=self.configuration.netapp_sa_password)
        self._client.set_system_id(system.get('id'))
        self._client._init_features()

    def _check_password_status(self, system):
        """Determine if the storage system's password status is valid.

        The password status has the following possible states: unknown, valid,
        invalid.

        If the password state cannot be retrieved from the storage system,
        an empty string will be returned as the status, and the password
        status will be assumed to be valid. This is done to ensure that
        access to a storage system will not be blocked in the event of a
        problem with the API.

        This method returns a tuple consisting of the storage system's
        password status and whether or not the status is valid.

        Example: (invalid, True)

        :returns: (str, bool)
        """

        status = system.get('passwordStatus')
        status = status.lower() if status else ''
        return status, status not in ['invalid', 'unknown']

    def _check_storage_system_status(self, system):
        """Determine if the storage system's status is valid.

        The storage system status has the following possible states:
        neverContacted, offline, optimal, needsAttn.

        If the storage system state cannot be retrieved, an empty string will
        be returned as the status, and the storage system's status will be
        assumed to be valid. This is done to ensure that access to a storage
        system will not be blocked in the event of a problem with the API.

        This method returns a tuple consisting of the storage system's
        password status and whether or not the status is valid.

        Example: (needsAttn, True)

        :returns: (str, bool)
        """
        status = system.get('status')
        status = status.lower() if status else ''
        return status, status not in ['nevercontacted', 'offline']

    def _check_storage_system(self):
        """Checks whether system is registered and has good status."""
        try:
            self._client.list_storage_system()
        except exception.NetAppDriverException:
            with excutils.save_and_reraise_exception():
                LOG.info("System with controller addresses [%s] is not "
                         "registered with web service.",
                         self.configuration.netapp_controller_ips)

        # Update the stored password
        # We do this to trigger the webservices password validation routine
        new_pwd = self.configuration.netapp_sa_password
        self._client.update_stored_system_password(new_pwd)

        start_time = int(time.time())

        def check_system_status():
            system = self._client.list_storage_system()
            pass_status, pass_status_valid = (
                self._check_password_status(system))
            status, status_valid = self._check_storage_system_status(system)
            msg_dict = {'id': system.get('id'), 'status': status,
                        'pass_status': pass_status}
            # wait if array not contacted or
            # password was not in sync previously.
            if not (pass_status_valid and status_valid):
                if not pass_status_valid:
                    LOG.info('Waiting for web service to validate the '
                             'configured password.')
                else:
                    LOG.info('Waiting for web service array communication.')
                if int(time.time() - start_time) >= self.SA_COMM_TIMEOUT:
                    if not status_valid:
                        raise exception.NetAppDriverException(
                            _("System %(id)s found with bad status - "
                              "%(status)s.") % msg_dict)
                    else:
                        raise exception.NetAppDriverException(
                            _("System %(id)s found with bad password status - "
                              "%(pass_status)s.") % msg_dict)

            # The system was found to have a good status
            else:
                LOG.info("System %(id)s has %(status)s status.", msg_dict)
                raise loopingcall.LoopingCallDone()

        checker = loopingcall.FixedIntervalLoopingCall(f=check_system_status)
        checker.start(interval = self.SLEEP_SECS,
                      initial_delay=self.SLEEP_SECS).wait()

        return True

    def _get_volume(self, uid):
        """Retrieve a volume by its label"""
        if uid is None:
            raise exception.InvalidInput(_('The volume label is required'
                                           ' as input.'))

        uid = utils.convert_uuid_to_es_fmt(uid)

        return self._client.list_volume(uid)

    def _get_snapshot_group_for_snapshot(self, snapshot):
        snapshot = self._get_snapshot(snapshot)
        try:
            return self._client.list_snapshot_group(snapshot['pitGroupRef'])
        except (exception.NetAppDriverException,
                eseries_exc.WebServiceException):
            msg = _("Specified snapshot group with id %s could not be found.")
            raise exception.NotFound(msg % snapshot['pitGroupRef'])

    def _get_snapshot_legacy(self, snapshot):
        """Find a E-Series snapshot by the name of the snapshot group.

        Snapshots were previously identified by the unique name of the
        snapshot group. A snapshot volume is now utilized to uniquely
        identify the snapshot, so any snapshots previously defined in this
        way must be updated.

        :param snapshot_id: Cinder snapshot identifer
        :return: An E-Series snapshot image
        """
        label = utils.convert_uuid_to_es_fmt(snapshot['id'])
        for group in self._client.list_snapshot_groups():
            if group['label'] == label:
                image = self._get_oldest_image_in_snapshot_group(group['id'])
                group_label = utils.convert_uuid_to_es_fmt(uuid.uuid4())
                # Modify the group label so we don't have a name collision
                self._client.update_snapshot_group(group['id'],
                                                   group_label)

                snapshot.update({'provider_id': image['id']})
                snapshot.save()

                return image

        raise exception.NotFound(_('Snapshot with id of %s could not be '
                                   'found.') % snapshot['id'])

    def _get_snapshot(self, snapshot):
        """Find a E-Series snapshot by its Cinder identifier

        An E-Series snapshot image does not have a configuration name/label,
        so we define a snapshot volume underneath of it that will help us to
        identify it. We retrieve the snapshot volume with the matching name,
        and then we find its underlying snapshot.

        :param snapshot_id: Cinder snapshot identifer
        :return: An E-Series snapshot image
        """
        try:
            return self._client.list_snapshot_image(
                snapshot.get('provider_id'))
        except (eseries_exc.WebServiceException,
                exception.NetAppDriverException):
            try:
                LOG.debug('Unable to locate snapshot by its id, falling '
                          'back to legacy behavior.')
                return self._get_snapshot_legacy(snapshot)
            except exception.NetAppDriverException:
                raise exception.NotFound(_('Snapshot with id of %s could not'
                                           ' be found.') % snapshot['id'])

    def _get_snapshot_group(self, snapshot_group_id):
        try:
            return self._client.list_snapshot_group(snapshot_group_id)
        except exception.NetAppDriverException:
            raise exception.NotFound(_('Unable to retrieve snapshot group '
                                       'with id of %s.') % snapshot_group_id)

    def _get_ordered_images_in_snapshot_group(self, snapshot_group_id):
        images = self._client.list_snapshot_images()
        if images:
            filtered_images = [img for img in images if img['pitGroupRef'] ==
                               snapshot_group_id]
            sorted_imgs = sorted(filtered_images, key=lambda x: x[
                'pitTimestamp'])
            return sorted_imgs
        return list()

    def _get_oldest_image_in_snapshot_group(self, snapshot_group_id):
        group = self._get_snapshot_group(snapshot_group_id)
        images = self._get_ordered_images_in_snapshot_group(snapshot_group_id)
        if images:
            return images[0]

        msg = _("No snapshot image found in snapshot group %s.")
        raise exception.NotFound(msg % group['label'])

    def _get_latest_image_in_snapshot_group(self, snapshot_group_id):
        group = self._get_snapshot_group(snapshot_group_id)
        images = self._get_ordered_images_in_snapshot_group(snapshot_group_id)
        if images:
            return images[-1]

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
        :returns: Name of the pool where given volume is hosted.
        """
        eseries_volume = self._get_volume(volume['name_id'])
        storage_pool = self._client.get_storage_pool(
            eseries_volume['volumeGroupRef'])
        if storage_pool:
            return storage_pool.get('label')

    def _add_volume_to_consistencygroup(self, volume):
        if volume.get('consistencygroup_id'):
            es_cg = self._get_consistencygroup(volume['consistencygroup'])
            self._update_consistency_group_members(es_cg, [volume], [])

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

        self._add_volume_to_consistencygroup(volume)

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
            LOG.info("Created volume with label %s.", eseries_volume_label)
        except exception.NetAppDriverException as e:
            with excutils.save_and_reraise_exception():
                LOG.error("Error creating volume. Msg - %s.", e)
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
                        LOG.error(
                            "Error cleaning up failed volume creation.  "
                            "Msg - %s.", e2)

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
                LOG.info("Created volume with label %s.", label)
                return vol
            except exception.NetAppDriverException as e:
                LOG.error("Error creating volume. Msg - %s.", e)
        msg = _("Failure creating volume %s.")
        raise exception.NetAppDriverException(msg % label)

    def _create_volume_from_snapshot(self, volume, image):
        """Define a new volume based on an E-Series snapshot image.

        This method should be synchronized on the snapshot id.

        :param volume: a Cinder volume
        :param image: an E-Series snapshot image
        :return: the clone volume
        """
        label = utils.convert_uuid_to_es_fmt(volume['id'])
        size = volume['size']

        dst_vol = self._schedule_and_create_volume(label, size)
        src_vol = None
        try:
            src_vol = self._create_snapshot_volume(image)
            self._copy_volume_high_priority_readonly(src_vol, dst_vol)
            LOG.info("Created volume with label %s.", label)
        except exception.NetAppDriverException:
            with excutils.save_and_reraise_exception():
                self._client.delete_volume(dst_vol['volumeRef'])
        finally:
            if src_vol:
                try:
                    self._client.delete_snapshot_volume(src_vol['id'])
                except exception.NetAppDriverException as e:
                    LOG.error("Failure restarting snap vol. Error: %s.", e)
            else:
                LOG.warning("Snapshot volume creation failed for "
                            "snapshot %s.", image['id'])

        return dst_vol

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        es_snapshot = self._get_snapshot(snapshot)
        cinder_utils.synchronized(snapshot['id'])(
            self._create_volume_from_snapshot)(volume, es_snapshot)

        self._add_volume_to_consistencygroup(volume)

    def _copy_volume_high_priority_readonly(self, src_vol, dst_vol):
        """Copies src volume to dest volume."""
        LOG.info("Copying src vol %(src)s to dest vol %(dst)s.",
                 {'src': src_vol['label'], 'dst': dst_vol['label']})
        job = None
        try:
            job = self._client.create_volume_copy_job(
                src_vol['id'], dst_vol['volumeRef'])

            def wait_for_copy():
                j_st = self._client.list_vol_copy_job(job['volcopyRef'])
                if (j_st['status'] in ['inProgress', 'pending', 'unknown']):
                    return
                if j_st['status'] == 'failed' or j_st['status'] == 'halted':
                    LOG.error("Vol copy job status %s.", j_st['status'])
                    raise exception.NetAppDriverException(
                        _("Vol copy job for dest %s failed.") %
                        dst_vol['label'])
                LOG.info("Vol copy job completed for dest %s.",
                         dst_vol['label'])
                raise loopingcall.LoopingCallDone()

            checker = loopingcall.FixedIntervalLoopingCall(wait_for_copy)
            checker.start(interval=self.SLEEP_SECS,
                          initial_delay=self.SLEEP_SECS,
                          stop_on_exception=True).wait()
        finally:
            if job:
                try:
                    self._client.delete_vol_copy_job(job['volcopyRef'])
                except exception.NetAppDriverException:
                    LOG.warning("Failure deleting job %s.", job['volcopyRef'])
            else:
                LOG.warning('Volume copy job for src vol %s not found.',
                            src_vol['id'])
        LOG.info('Copy job to dest vol %s completed.', dst_vol['label'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        es_vol = self._get_volume(src_vref['id'])

        es_snapshot = self._create_es_snapshot_for_clone(es_vol)

        try:
            self._create_volume_from_snapshot(volume, es_snapshot)
            self._add_volume_to_consistencygroup(volume)
        finally:
            try:
                self._client.delete_snapshot_group(es_snapshot['pitGroupRef'])
            except exception.NetAppDriverException:
                LOG.warning("Failure deleting temp snapshot %s.",
                            es_snapshot['id'])

    def delete_volume(self, volume):
        """Deletes a volume."""
        try:
            vol = self._get_volume(volume['name_id'])
            self._client.delete_volume(vol['volumeRef'])
        except (exception.NetAppDriverException, exception.VolumeNotFound):
            LOG.warning("Volume %s already deleted.", volume['id'])
            return

    def _is_cgsnapshot(self, snapshot_image):
        """Determine if an E-Series snapshot image is part of a cgsnapshot"""
        cg_id = snapshot_image.get('consistencyGroupId')
        # A snapshot that is not part of a consistency group may have a
        # cg_id of either none or a string of all 0's, so we check for both
        return not (cg_id is None or utils.NULL_REF == cg_id)

    def _create_snapshot_volume(self, image):
        """Creates snapshot volume for given group with snapshot_id."""
        group = self._get_snapshot_group(image['pitGroupRef'])

        LOG.debug("Creating snap vol for group %s", group['label'])

        label = utils.convert_uuid_to_es_fmt(uuid.uuid4())

        if self._is_cgsnapshot(image):
            return self._client.create_cg_snapshot_view(
                image['consistencyGroupId'], label, image['id'])
        else:
            return self._client.create_snapshot_volume(
                image['pitRef'], label, image['baseVol'])

    def _create_snapshot_group(self, label, volume, percentage_capacity=20.0):
        """Define a new snapshot group for a volume

        :param label: the label for the snapshot group
        :param volume: an E-Series volume
        :param percentage_capacity: an optional repository percentage
        :return: a new snapshot group
        """

        # Newer versions of the REST API are capable of automatically finding
        # the best pool candidate
        if not self._client.features.REST_1_3_RELEASE:
            vol_size_gb = int(volume['totalSizeInBytes']) / units.Gi
            pools = self._get_sorted_available_storage_pools(vol_size_gb)
            volume_pool = next(pool for pool in pools if volume[
                'volumeGroupRef'] == pool['id'])

            # A disk pool can only utilize a candidate from its own pool
            if volume_pool.get('raidLevel') == 'raidDiskPool':
                pool_id_to_use = volume_pool['volumeGroupRef']

            # Otherwise, choose the best available pool
            else:
                pool_id_to_use = pools[0]['volumeGroupRef']
            group = self._client.create_snapshot_group(
                label, volume['volumeRef'], pool_id_to_use,
                repo_percent=percentage_capacity)

        else:
            group = self._client.create_snapshot_group(
                label, volume['volumeRef'], repo_percent=percentage_capacity)

        return group

    def _get_snapshot_groups_for_volume(self, vol):
        """Find all snapshot groups associated with an E-Series volume

        :param vol: An E-Series volume object
        :return: A list of snapshot groups
        :raise NetAppDriverException: if the list of snapshot groups cannot be
        retrieved
        """
        return [grp for grp in self._client.list_snapshot_groups()
                if grp['baseVolume'] == vol['id']]

    def _get_available_snapshot_group(self, vol):
        """Find a snapshot group that has remaining capacity for snapshots.

        In order to minimize repository usage, we prioritize the snapshot
        group with remaining snapshot capacity that has most recently had a
        snapshot defined on it.

        :param vol: An E-Series volume object
        :return: A valid snapshot group that has available snapshot capacity,
         or None
        :raise NetAppDriverException: if the list of snapshot groups cannot be
        retrieved
        """
        groups_for_v = self._get_snapshot_groups_for_volume(vol)

        # Filter out reserved snapshot groups
        groups = [g for g in groups_for_v
                  if self.SNAPSHOT_VOL_COPY_SUFFIX not in g['label']]

        # Filter out groups that are part of a consistency group
        groups = [g for g in groups if not g['consistencyGroup']]
        # Find all groups with free snapshot capacity
        groups = [group for group in groups if group.get('snapshotCount') <
                  self.MAX_SNAPSHOT_COUNT]

        # Order by the last defined snapshot on the group
        if len(groups) > 1:
            group_by_id = {g['id']: g for g in groups}

            snap_imgs = list()
            for group in groups:
                try:
                    snap_imgs.append(
                        self._get_latest_image_in_snapshot_group(group['id']))
                except exception.NotFound:
                    pass

            snap_imgs = sorted(snap_imgs, key=lambda x: x['pitSequenceNumber'])

            if snap_imgs:
                # The newest image
                img = snap_imgs[-1]
                return group_by_id[img['pitGroupRef']]
            else:
                return groups[0] if groups else None

        # Skip the snapshot image checks if there is only one snapshot group
        elif groups:
            return groups[0]
        else:
            return None

    def _create_es_snapshot_for_clone(self, vol):
        group_name = (utils.convert_uuid_to_es_fmt(uuid.uuid4()) +
                      self.SNAPSHOT_VOL_COPY_SUFFIX)
        return self._create_es_snapshot(vol, group_name)

    def _create_es_snapshot(self, vol, group_name=None):
        snap_grp, snap_image = None, None
        try:
            snap_grp = self._get_available_snapshot_group(vol)
            # If a snapshot group is not available, create one if possible
            if snap_grp is None:
                snap_groups_for_vol = self._get_snapshot_groups_for_volume(
                    vol)

                # We need a reserved snapshot group
                if (group_name is not None and
                        (self.SNAPSHOT_VOL_COPY_SUFFIX in group_name)):

                    # First we search for an existing reserved group
                    for grp in snap_groups_for_vol:
                        if grp['label'].endswith(
                                self.SNAPSHOT_VOL_COPY_SUFFIX):
                            snap_grp = grp
                            break

                    # No reserved group exists, so we create it
                    if (snap_grp is None and
                            (len(snap_groups_for_vol) <
                             self.MAX_SNAPSHOT_GROUP_COUNT)):
                        snap_grp = self._create_snapshot_group(group_name,
                                                               vol)

                # Ensure we don't exceed the snapshot group limit
                elif (len(snap_groups_for_vol) <
                      (self.MAX_SNAPSHOT_GROUP_COUNT -
                       self.RESERVED_SNAPSHOT_GROUP_COUNT)):

                    label = group_name if group_name is not None else (
                        utils.convert_uuid_to_es_fmt(uuid.uuid4()))

                    snap_grp = self._create_snapshot_group(label, vol)
                    LOG.info("Created snap grp with label %s.", label)

                # We couldn't retrieve or create a snapshot group
                if snap_grp is None:
                    raise exception.SnapshotLimitExceeded(
                        allowed=(self.MAX_SNAPSHOT_COUNT *
                                 (self.MAX_SNAPSHOT_GROUP_COUNT -
                                  self.RESERVED_SNAPSHOT_GROUP_COUNT)))

            return self._client.create_snapshot_image(
                snap_grp['id'])

        except exception.NetAppDriverException:
            with excutils.save_and_reraise_exception():
                if snap_image is None and snap_grp:
                    self._delete_snapshot_group(snap_grp['id'])

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: The Cinder snapshot
        :param group_name: An optional label for the snapshot group
        :returns: An E-Series snapshot image
        """

        os_vol = snapshot['volume']
        vol = self._get_volume(os_vol['name_id'])

        snap_image = cinder_utils.synchronized(vol['id'])(
            self._create_es_snapshot)(vol)
        model_update = {
            'provider_id': snap_image['id']
        }

        return model_update

    def _delete_es_snapshot(self, es_snapshot):
        """Perform a soft-delete on an E-Series snapshot.

        Mark the snapshot image as no longer needed, so that it can be
        purged from the backend when no other snapshots are dependent upon it.

        :param es_snapshot: an E-Series snapshot image
        :return: None
        """
        index = self._get_soft_delete_map()
        snapgroup_ref = es_snapshot['pitGroupRef']
        if snapgroup_ref in index:
            bitset = na_utils.BitSet(int((index[snapgroup_ref])))
        else:
            bitset = na_utils.BitSet(0)

        images = [img for img in self._client.list_snapshot_images() if
                  img['pitGroupRef'] == snapgroup_ref]
        for i, image in enumerate(sorted(images, key=lambda x: x[
                'pitSequenceNumber'])):
            if(image['pitSequenceNumber'] == es_snapshot[
                    'pitSequenceNumber']):
                bitset.set(i)
                break

        index_update, keys_to_del = (
            self._cleanup_snapshot_images(images, bitset))

        self._merge_soft_delete_changes(index_update, keys_to_del)

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        try:
            es_snapshot = self._get_snapshot(snapshot)
        except exception.NotFound:
            LOG.warning("Snapshot %s already deleted.", snapshot['id'])
        else:
            os_vol = snapshot['volume']
            vol = self._get_volume(os_vol['name_id'])

            cinder_utils.synchronized(vol['id'])(self._delete_es_snapshot)(
                es_snapshot)

    def _get_soft_delete_map(self):
        """Retrieve the snapshot index from the storage backend"""
        return self._client.list_backend_store(
            self.SNAPSHOT_PERSISTENT_STORE_KEY)

    @cinder_utils.synchronized(SNAPSHOT_PERSISTENT_STORE_LOCK)
    def _merge_soft_delete_changes(self, index_update, keys_to_del):
        """Merge changes to the snapshot index and save it on the backend

        This method merges provided changes into the index, locking, to ensure
        that concurrent changes that don't overlap are not overwritten. No
        update will occur if neither an update or keys to delete are provided.

        :param index_update: a dict of keys/value pairs to update in the index
        :param keys_to_del: a list of keys to purge from the index
        """
        if index_update or keys_to_del:
            index = self._get_soft_delete_map()
            if index_update:
                index.update(index_update)
            if keys_to_del:
                for key in keys_to_del:
                    if key in index:
                        del index[key]

            self._client.save_backend_store(
                self.SNAPSHOT_PERSISTENT_STORE_KEY, index)

    def _cleanup_snapshot_images(self, images, bitset):
        """Delete snapshot images that are marked for removal from the backend.

        This method will iterate over all snapshots (beginning with the
        oldest), that are defined on the same snapshot group as the provided
        snapshot image. If the snapshot is marked for deletion, it will be
        purged from the backend. Otherwise, the method will return because
        no further snapshots can be purged.

        The bitset will be updated based on the return from this method.
        Any updates to the index will be provided as a dict, and any keys
        to be removed from the index should be returned as (dict, list).

        :param images: a list of E-Series snapshot images
        :param bitset: a bitset representing the snapshot images that are
        no longer needed on the backend (and may be deleted when possible)
        :return (dict, list): a tuple containing a dict of updates for the
        index and a list of keys to remove from the index
        """
        snap_grp_ref = images[0]['pitGroupRef']
        # All images are marked as deleted, we can delete the snapshot group
        if bitset == 2 ** len(images) - 1:
            try:
                self._delete_snapshot_group(snap_grp_ref)
            except exception.NetAppDriverException as e:
                LOG.warning("Unable to remove snapshot group - %s.", e.msg)
            return None, [snap_grp_ref]
        else:
            # Order by their sequence number, from oldest to newest
            snapshots = sorted(images,
                               key=lambda x: x['pitSequenceNumber'])
            deleted = 0

            for i, snapshot in enumerate(snapshots):
                if bitset.is_set(i):
                    self._delete_snapshot_image(snapshot)
                    deleted += 1
                else:
                    # Snapshots must be deleted in order, so if the current
                    # snapshot is not pending deletion, we don't want to
                    # process any more
                    break

            if deleted:
                # Update the bitset based on the deleted snapshots
                bitset >>= deleted
                LOG.debug('Deleted %(count)s snapshot images from snapshot '
                          'group: %(grp)s.', {'count': deleted,
                                              'grp': snap_grp_ref})
                if deleted >= len(images):
                    try:
                        self._delete_snapshot_group(snap_grp_ref)
                    except exception.NetAppDriverException as e:
                        LOG.warning("Unable to remove snapshot group - %s.",
                                    e.msg)
                    return None, [snap_grp_ref]

            return {snap_grp_ref: repr(bitset)}, None

    def _delete_snapshot_group(self, group_id):
        try:
            self._client.delete_snapshot_group(group_id)
        except eseries_exc.WebServiceException as e:
            raise exception.NetAppDriverException(e.msg)

    def _delete_snapshot_image(self, es_snapshot):
        """Remove a snapshot image from the storage backend

        If a snapshot group has no remaining snapshot images associated with
        it, it will be deleted as well. When the snapshot is deleted,
        any snapshot volumes that are associated with it will be orphaned,
        so they are also deleted.

        :param es_snapshot: An E-Series snapshot image
        :param snapshot_volumes: Snapshot volumes associated with the snapshot
        """
        self._client.delete_snapshot_image(es_snapshot['id'])

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

        .. code-block:: python

            {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': '500a098280feeba5',
                    'initiator_target_map': {
                        '21000024ff406cc3': ['500a098280feeba5'],
                        '21000024ff406cc2': ['500a098280feeba5']
                    }
                }
            }

        or

        .. code-block:: python

             {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': ['500a098280feeba5', '500a098290feeba5',
                                   '500a098190feeba5', '500a098180feeba5'],
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
            LOG.info("Need to remove FC Zone, building initiator target map.")

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
        if self.configuration.use_chap_auth:
            if self._client.features.CHAP_AUTHENTICATION:
                chap_username, chap_password = self._configure_chap(iqn)
                properties['data']['auth_username'] = chap_username
                properties['data']['auth_password'] = chap_password
                properties['data']['auth_method'] = 'CHAP'
                properties['data']['discovery_auth_username'] = chap_username
                properties['data']['discovery_auth_password'] = chap_password
                properties['data']['discovery_auth_method'] = 'CHAP'
            else:
                msg = _("E-series proxy API version %(current_version)s does "
                        "not support CHAP authentication. The proxy version "
                        "must be at least %(min_version)s.")
                min_version = (self._client.features.
                               CHAP_AUTHENTICATION.minimum_version)
                msg = msg % {'current_version': self._client.api_version,
                             'min_version': min_version}

                LOG.info(msg)
                raise exception.NetAppDriverException(msg)
        return properties

    def _configure_chap(self, target_iqn):
        chap_username = self.DEFAULT_CHAP_USER_NAME
        chap_password = volume_utils.generate_password()
        self._client.set_chap_authentication(target_iqn,
                                             chap_username,
                                             chap_password)
        return chap_username, chap_password

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
                    LOG.warning("Unable to update host type for host with "
                                "label %(l)s. %(e)s",
                                {'l': host['label'], 'e': e.msg})
            return host
        except exception.NotFound as e:
            LOG.warning("Message - %s.", e.msg)
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
        LOG.info("Creating host with ports %s.", port_ids)
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
        storage_volumes = self._client.list_volumes()

        for storage_pool in self._get_storage_pools():
            cinder_pool = {}
            cinder_pool["pool_name"] = storage_pool.get("label")
            cinder_pool["QoS_support"] = False
            cinder_pool["reserved_percentage"] = (
                self.configuration.reserved_percentage)
            cinder_pool["max_over_subscription_ratio"] = (
                self.configuration.max_over_subscription_ratio)
            tot_bytes = int(storage_pool.get("totalRaidedSpace", 0))
            used_bytes = int(storage_pool.get("usedSpace", 0))

            provisioned_capacity = 0
            for volume in storage_volumes:
                if (volume["volumeGroupRef"] == storage_pool.get('id') and
                        not volume['label'].startswith('repos_')):
                    provisioned_capacity += float(volume["capacity"])

            cinder_pool["provisioned_capacity_gb"] = (provisioned_capacity /
                                                      units.Gi)
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
            LOG.info("E-series proxy API version %s does not support "
                     "autosupport logging.", self._client.api_version)
            return

        event_source = ("Cinder driver %s" % self.DRIVER_NAME)
        category = "provisioning"
        event_description = "OpenStack Cinder connected to E-Series proxy"
        asup_info = self._client.get_asup_info()
        model = asup_info.get('model')
        firmware_version = asup_info.get('firmware_version')
        serial_numbers = asup_info.get('serial_numbers')
        chassis_sn = asup_info.get('chassis_sn')

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
            'chassis-serial-number': chassis_sn,
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
        LOG.info("Updating storage service catalog information for "
                 "backend '%s'", self._backend_name)

        relevant_pools = self._get_storage_pools()

        if self._client.features.SSC_API_V2:
            self._update_ssc_info_v2(relevant_pools)
        else:
            self._update_ssc_info_v1(relevant_pools)

    def _update_ssc_info_v1(self, relevant_pools):
        """Update ssc data using the legacy API

        :param relevant_pools: The pools that this driver cares about
        """
        LOG.info("E-series proxy API version %(version)s does not "
                 "support full set of SSC extra specs. The proxy version"
                 " must be at at least %(min_version)s.",
                 {'version': self._client.api_version,
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

            pool_ssc_info['consistencygroup_support'] = True

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

        relevant_disks = [x for x in all_disks
                          if x.get('currentVolumeGroupRef') in pool_ids]
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
            msg = ("The option 'netapp_storage_pools' is deprecated and "
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
            LOG.warning("No storage pool found with available capacity %s.",
                        size_gb)
        return avl_pools

    def _is_thin_provisioned(self, volume):
        """Determine if a volume is thin provisioned"""
        return volume.get('objectType') == 'thinVolume' or volume.get(
            'thinProvisioned', False)

    def _get_pool_operation_progress(self, pool_id, action=None):
        """Retrieve the progress of a long running operation on a pool

        The return will be a tuple containing: a bool representing whether
        or not the operation is complete, a set of actions that are
        currently running on the storage pool, and the estimated time
        remaining in minutes.

        An action type may be passed in such that once no actions of that type
        remain active on the pool, the operation will be considered
        completed. If no action str is passed in, it is assumed that
        multiple actions compose the operation, and none are terminal,
        so the operation will not be considered completed until there are no
        actions remaining to be completed on any volume on the pool.

        :param pool_id: The id of a storage pool
        :param action: The anticipated action
        :returns: A tuple (bool, set(str), int)
        """
        actions = set()
        eta = 0
        for progress in self._client.get_pool_operation_progress(pool_id):
            actions.add(progress.get('currentAction'))
            eta += progress.get('estimatedTimeToCompletion', 0)
        if action is not None:
            complete = action not in actions
        else:
            complete = not actions
        return complete, actions, eta

    def extend_volume(self, volume, new_size):
        """Extend an existing volume to the new size."""
        src_vol = self._get_volume(volume['name_id'])
        thin_provisioned = self._is_thin_provisioned(src_vol)
        self._client.expand_volume(src_vol['id'], new_size, thin_provisioned)

        # If the volume is thin or defined on a disk pool, there is no need
        # to block.
        if not (thin_provisioned or src_vol.get('diskPool')):
            # Wait for the expansion to start

            def check_progress():
                complete, actions, eta = (
                    self._get_pool_operation_progress(src_vol[
                                                      'volumeGroupRef'],
                                                      'remappingDve'))
                if complete:
                    raise loopingcall.LoopingCallDone()
                else:
                    LOG.info("Waiting for volume expansion of %(vol)s to "
                             "complete, current remaining actions are "
                             "%(action)s. ETA: %(eta)s mins.",
                             {'vol': volume['name_id'],
                              'action': ', '.join(actions), 'eta': eta})

            checker = loopingcall.FixedIntervalLoopingCall(
                check_progress)

            checker.start(interval=self.SLEEP_SECS,
                          initial_delay=self.SLEEP_SECS,
                          stop_on_exception=True).wait()

    def create_cgsnapshot(self, cgsnapshot, snapshots):
        """Creates a cgsnapshot."""
        cg_id = cgsnapshot['consistencygroup_id']
        cg_name = utils.convert_uuid_to_es_fmt(cg_id)

        # Retrieve the E-Series consistency group
        es_cg = self._get_consistencygroup_by_name(cg_name)

        # Define an E-Series CG Snapshot
        es_snaphots = self._client.create_consistency_group_snapshot(
            es_cg['id'])

        # Build the snapshot updates
        snapshot_updates = list()
        for snap in snapshots:
            es_vol = self._get_volume(snap['volume']['id'])
            for es_snap in es_snaphots:
                if es_snap['baseVol'] == es_vol['id']:
                    snapshot_updates.append({
                        'id': snap['id'],
                        # Directly track the backend snapshot ID
                        'provider_id': es_snap['id'],
                        'status': 'available'
                    })

        return None, snapshot_updates

    def delete_cgsnapshot(self, cgsnapshot, snapshots):
        """Deletes a cgsnapshot."""

        cg_id = cgsnapshot['consistencygroup_id']
        cg_name = utils.convert_uuid_to_es_fmt(cg_id)

        # Retrieve the E-Series consistency group
        es_cg = self._get_consistencygroup_by_name(cg_name)

        # Find the smallest sequence number defined on the group
        min_seq_num = min(es_cg['uniqueSequenceNumber'])

        es_snapshots = self._client.get_consistency_group_snapshots(
            es_cg['id'])
        es_snap_ids = set(snap.get('provider_id') for snap in snapshots)

        # We need to find a single snapshot that is a part of the CG snap
        seq_num = None
        for snap in es_snapshots:
            if snap['id'] in es_snap_ids:
                seq_num = snap['pitSequenceNumber']
                break

        if seq_num is None:
            raise exception.CgSnapshotNotFound(cgsnapshot_id=cg_id)

        # Perform a full backend deletion of the cgsnapshot
        if int(seq_num) <= int(min_seq_num):
            self._client.delete_consistency_group_snapshot(
                es_cg['id'], seq_num)
            return None, None
        else:
            # Perform a soft-delete, removing this snapshot from cinder
            # management, and marking it as available for deletion.
            return cinder_utils.synchronized(cg_id)(
                self._soft_delete_cgsnapshot)(
                es_cg, seq_num)

    def _soft_delete_cgsnapshot(self, es_cg, snap_seq_num):
        """Mark a cgsnapshot as available for deletion from the backend.

        E-Series snapshots cannot be deleted out of order, as older
        snapshots in the snapshot group are dependent on the newer
        snapshots. A "soft delete" results in the cgsnapshot being removed
        from Cinder management, with the snapshot marked as available for
        deletion once all snapshots dependent on it are also deleted.

        :param es_cg: E-Series consistency group
        :param snap_seq_num: unique sequence number of the cgsnapshot
        :return: an update to the snapshot index
        """

        index = self._get_soft_delete_map()
        cg_ref = es_cg['id']
        if cg_ref in index:
            bitset = na_utils.BitSet(int((index[cg_ref])))
        else:
            bitset = na_utils.BitSet(0)

        seq_nums = (
            set([snap['pitSequenceNumber'] for snap in
                 self._client.get_consistency_group_snapshots(cg_ref)]))

        # Determine the relative index of the snapshot's sequence number
        for i, seq_num in enumerate(sorted(seq_nums)):
            if snap_seq_num == seq_num:
                bitset.set(i)
                break

        index_update = (
            self._cleanup_cg_snapshots(cg_ref, seq_nums, bitset))

        self._merge_soft_delete_changes(index_update, None)

        return None, None

    def _cleanup_cg_snapshots(self, cg_ref, seq_nums, bitset):
        """Delete cg snapshot images that are marked for removal

        The snapshot index tracks all snapshots that have been removed from
        Cinder, and are therefore available for deletion when this operation
        is possible.

        CG snapshots are tracked by unique sequence numbers that are
        associated with 1 or more snapshot images. The sequence numbers are
        tracked (relative to the 32 images allowed per group), within the
        snapshot index.

        This method will purge CG snapshots that have been marked as
        available for deletion within the backend persistent store.

        :param cg_ref: reference to an E-Series consistent group
        :param seq_nums: set of unique sequence numbers associated with the
        consistency group
        :param bitset: the bitset representing which sequence numbers are
        marked for deletion
        :return: update for the snapshot index
        """
        deleted = 0
        # Order by their sequence number, from oldest to newest
        for i, seq_num in enumerate(sorted(seq_nums)):
            if bitset.is_set(i):
                self._client.delete_consistency_group_snapshot(cg_ref,
                                                               seq_num)
                deleted += 1
            else:
                # Snapshots must be deleted in order, so if the current
                # snapshot is not pending deletion, we don't want to
                # process any more
                break

        if deleted:
            # We need to update the bitset to reflect the fact that older
            # snapshots have been deleted, so snapshot relative indexes
            # have now been updated.
            bitset >>= deleted

            LOG.debug('Deleted %(count)s snapshot images from '
                      'consistency group: %(grp)s.', {'count': deleted,
                                                      'grp': cg_ref})
        # Update the index
        return {cg_ref: repr(bitset)}

    def create_consistencygroup(self, cinder_cg):
        """Define a consistency group."""
        self._create_consistency_group(cinder_cg)

        return {'status': 'available'}

    def _create_consistency_group(self, cinder_cg):
        """Define a new consistency group on the E-Series backend"""
        name = utils.convert_uuid_to_es_fmt(cinder_cg['id'])
        return self._client.create_consistency_group(name)

    def _get_consistencygroup(self, cinder_cg):
        """Retrieve an E-Series consistency group"""
        name = utils.convert_uuid_to_es_fmt(cinder_cg['id'])
        return self._get_consistencygroup_by_name(name)

    def _get_consistencygroup_by_name(self, name):
        """Retrieve an E-Series consistency group by name"""

        for cg in self._client.list_consistency_groups():
            if name == cg['name']:
                return cg

        raise exception.ConsistencyGroupNotFound(consistencygroup_id=name)

    def delete_consistencygroup(self, group, volumes):
        """Deletes a consistency group."""

        volume_update = list()

        for volume in volumes:
            LOG.info('Deleting volume %s.', volume['id'])
            volume_update.append({
                'status': 'deleted', 'id': volume['id'],
            })
            self.delete_volume(volume)

        try:
            cg = self._get_consistencygroup(group)
        except exception.ConsistencyGroupNotFound:
            LOG.warning('Consistency group already deleted.')
        else:
            self._client.delete_consistency_group(cg['id'])
            try:
                self._merge_soft_delete_changes(None, [cg['id']])
            except (exception.NetAppDriverException,
                    eseries_exc.WebServiceException):
                LOG.warning('Unable to remove CG from the deletion map.')

        model_update = {'status': 'deleted'}

        return model_update, volume_update

    def _update_consistency_group_members(self, es_cg,
                                          add_volumes, remove_volumes):
        """Add or remove consistency group members

        :param es_cg: The E-Series consistency group
        :param add_volumes: A list of Cinder volumes to add to the
        consistency group
        :param remove_volumes: A list of Cinder volumes to remove from the
        consistency group
        :return: None
        """
        for volume in remove_volumes:
            es_vol = self._get_volume(volume['id'])
            LOG.info(
                'Removing volume %(v)s from consistency group %(''cg)s.',
                {'v': es_vol['label'], 'cg': es_cg['label']})
            self._client.remove_consistency_group_member(es_vol['id'],
                                                         es_cg['id'])

        for volume in add_volumes:
            es_vol = self._get_volume(volume['id'])
            LOG.info('Adding volume %(v)s to consistency group %(cg)s.',
                     {'v': es_vol['label'], 'cg': es_cg['label']})
            self._client.add_consistency_group_member(
                es_vol['id'], es_cg['id'])

    def update_consistencygroup(self, group,
                                add_volumes, remove_volumes):
        """Add or remove volumes from an existing consistency group"""
        cg = self._get_consistencygroup(group)

        self._update_consistency_group_members(
            cg, add_volumes, remove_volumes)

        return None, None, None

    def create_consistencygroup_from_src(self, group, volumes,
                                         cgsnapshot, snapshots,
                                         source_cg, source_vols):
        """Define a consistency group based on an existing group

        Define a new consistency group from a source consistency group. If
        only a source_cg is provided, then clone each base volume and add
        it to a new consistency group. If a cgsnapshot is provided,
        clone each snapshot image to a new volume and add it to the cg.

        :param group: The new consistency group to define
        :param volumes: The volumes to add to the consistency group
        :param cgsnapshot: The cgsnapshot to base the group on
        :param snapshots: The list of snapshots on the source cg
        :param source_cg: The source consistency group
        :param source_vols: The volumes added to the source cg
        """
        cg = self._create_consistency_group(group)
        if cgsnapshot:
            for vol, snap in zip(volumes, snapshots):
                image = self._get_snapshot(snap)
                self._create_volume_from_snapshot(vol, image)
        else:
            for vol, src in zip(volumes, source_vols):
                es_vol = self._get_volume(src['id'])
                es_snapshot = self._create_es_snapshot_for_clone(es_vol)
                try:
                    self._create_volume_from_snapshot(vol, es_snapshot)
                finally:
                    self._delete_es_snapshot(es_snapshot)

        self._update_consistency_group_members(cg, volumes, [])

        return None, None

    def _garbage_collect_tmp_vols(self):
        """Removes tmp vols with no snapshots."""
        try:
            if not na_utils.set_safe_attr(self, 'clean_job_running', True):
                LOG.warning('Returning as clean tmp vol job already running.')
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
            LOG.info("Volume with given ref %s need not be renamed during"
                     " manage operation.", existing_ref)
            managed_vol = vol
        else:
            managed_vol = self._client.update_volume(vol['id'], label)
        LOG.info("Manage operation completed for volume with new label"
                 " %(label)s and wwn %(wwn)s.",
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
            if vol_id is None:
                raise exception.InvalidInput(message='No valid identifier '
                                                     'was available for the '
                                                     'volume.')
            return self._client.list_volume(vol_id)
        except exception.InvalidInput:
            reason = _('Reference must contain either source-name'
                       ' or source-id element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        except exception.VolumeNotFound:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_('Volume not found on configured storage pools.'))

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

           Does not delete the underlying backend storage object. Logs a
           message to indicate the volume is no longer under Cinder's control.
        """
        managed_vol = self._get_volume(volume['id'])
        LOG.info("Unmanaged volume with current label %(label)s and wwn "
                 "%(wwn)s.", {'label': managed_vol['label'],
                              'wwn': managed_vol[self.WORLDWIDENAME]})
