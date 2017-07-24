# Copyright (c) 2014 Hitachi Data Systems, Inc.
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
Volume driver for HNAS NFS storage.
"""

import math
import os
import socket

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_log import versionutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder import utils as cutils
from cinder.volume import configuration
from cinder.volume.drivers.hitachi import hnas_backend
from cinder.volume.drivers.hitachi import hnas_utils
from cinder.volume.drivers import nfs
from cinder.volume import utils


HNAS_NFS_VERSION = '6.0.0'

LOG = logging.getLogger(__name__)

NFS_OPTS = [
    cfg.StrOpt('hds_hnas_nfs_config_file',
               default='/opt/hds/hnas/cinder_nfs_conf.xml',
               help='Legacy configuration file for HNAS NFS Cinder plugin. '
                    'This is not needed if you fill all configuration on '
                    'cinder.conf',
               deprecated_for_removal=True)
]

CONF = cfg.CONF
CONF.register_opts(NFS_OPTS, group=configuration.SHARED_CONF_GROUP)

HNAS_DEFAULT_CONFIG = {'ssc_cmd': 'ssc', 'ssh_port': '22'}


@interface.volumedriver
class HNASNFSDriver(nfs.NfsDriver):
    """Base class for Hitachi NFS driver.

    Executes commands relating to Volumes.

    Version history:

    ..  code-block:: none

        Version 1.0.0: Initial driver version
        Version 2.2.0: Added support to SSH authentication
        Version 3.0.0: Added pool aware scheduling
        Version 4.0.0: Added manage/unmanage features
        Version 4.1.0: Fixed XML parser checks on blank options
        Version 5.0.0: Remove looping in driver initialization
                       Code cleaning up
                       New communication interface between the driver and HNAS
                       Removed the option to use local SSC (ssh_enabled=False)
                       Updated to use versioned objects
                       Changed the class name to HNASNFSDriver
                       Deprecated XML config file
                       Added support to manage/unmanage snapshots features
                       Fixed driver stats reporting
        Version 6.0.0: Deprecated hnas_svcX_vol_type configuration
                       Added list-manageable volumes/snapshots support
                       Rename snapshots to link with its original volume
    """
    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Hitachi_HNAS_CI"
    VERSION = HNAS_NFS_VERSION

    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        msg = _("The Hitachi NAS driver is deprecated and will be "
                "removed in a future release.")
        versionutils.report_deprecated_feature(LOG, msg)
        self._execute = None
        self.context = None
        self.configuration = kwargs.get('configuration', None)

        service_parameters = ['volume_type', 'hdp']
        optional_parameters = ['ssc_cmd', 'cluster_admin_ip0']

        if self.configuration:
            self.configuration.append_config_values(
                hnas_utils.drivers_common_opts)
            self.configuration.append_config_values(NFS_OPTS)
            self.config = {}

            # Trying to get HNAS configuration from cinder.conf
            self.config = hnas_utils.read_cinder_conf(
                self.configuration)

            # If HNAS configuration are not set on cinder.conf, tries to use
            # the deprecated XML configuration file
            if not self.config:
                self.config = hnas_utils.read_xml_config(
                    self.configuration.hds_hnas_nfs_config_file,
                    service_parameters,
                    optional_parameters)

        super(HNASNFSDriver, self).__init__(*args, **kwargs)
        self.backend = hnas_backend.HNASSSHBackend(self.config)

    def _get_service(self, volume):
        """Get service parameters.

        Get the available service parameters for a given volume using
        its type.

        :param volume: dictionary volume reference
        :returns: Tuple containing the service parameters (label,
        export path and export file system) or error if no configuration is
        found.
        :raises ParameterNotFound:
        """
        LOG.debug("_get_service: volume: %(vol)s", {'vol': volume})
        label = utils.extract_host(volume.host, level='pool')

        if label in self.config['services'].keys():
            svc = self.config['services'][label]
            LOG.debug("_get_service: %(lbl)s->%(svc)s",
                      {'lbl': label, 'svc': svc['export']['fs']})
            service = (svc['hdp'], svc['export']['path'], svc['export']['fs'])
        else:
            LOG.info("Available services: %(svc)s",
                     {'svc': self.config['services'].keys()})
            LOG.error("No configuration found for service: %(lbl)s",
                      {'lbl': label})
            raise exception.ParameterNotFound(param=label)

        return service

    def _get_snapshot_name(self, snapshot):
        snap_file_name = ("%(vol_name)s.%(snap_id)s" %
                          {'vol_name': snapshot.volume.name,
                           'snap_id': snapshot.id})
        return snap_file_name

    @cutils.trace
    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: dictionary volume reference
        :param new_size: int size in GB to extend
        :raises InvalidResults:
        """
        nfs_mount = volume.provider_location
        path = self._get_file_path(nfs_mount, volume.name)

        # Resize the image file on share to new size.
        LOG.info("Checking file for resize.")

        if not self._is_file_size_equal(path, new_size):
            LOG.info("Resizing file to %(sz)sG", {'sz': new_size})
            image_utils.resize_image(path, new_size)

        if self._is_file_size_equal(path, new_size):
            LOG.info("LUN %(id)s extended to %(size)s GB.",
                     {'id': volume.id, 'size': new_size})
        else:
            msg = _("Resizing image file failed.")
            LOG.error(msg)
            raise exception.InvalidResults(msg)

    def _is_file_size_equal(self, path, size):
        """Checks if file size at path is equal to size."""
        data = image_utils.qemu_img_info(path)
        virt_size = data.virtual_size / units.Gi

        if virt_size == size:
            return True
        else:
            return False

    @cutils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        :param volume: volume to be created
        :param snapshot: source snapshot
        :returns: the provider_location of the volume created
        """
        nfs_mount = snapshot.volume.provider_location
        snapshot_name = self._get_snapshot_name(snapshot)

        if self._file_not_present(nfs_mount, snapshot_name):
            LOG.info("Creating volume %(vol)s from legacy "
                     "snapshot %(snap)s.",
                     {'vol': volume.name, 'snap': snapshot.name})
            snapshot_name = snapshot.name

        self._clone_volume(snapshot.volume, volume.name, snapshot_name)

        return {'provider_location': nfs_mount}

    @cutils.trace
    def create_snapshot(self, snapshot):
        """Create a snapshot.

        :param snapshot: dictionary snapshot reference
        :returns: the provider_location of the snapshot created
        """
        snapshot_name = self._get_snapshot_name(snapshot)
        self._clone_volume(snapshot.volume, snapshot_name)

        share = snapshot.volume.provider_location
        LOG.debug('Share: %(shr)s', {'shr': share})

        # returns the mount point (not path)
        return {'provider_location': share}

    @cutils.trace
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: dictionary snapshot reference
        """
        nfs_mount = snapshot.volume.provider_location
        snapshot_name = self._get_snapshot_name(snapshot)

        if self._file_not_present(nfs_mount, snapshot_name):
            # Snapshot with new name does not exist. The verification
            # for a file with legacy name will be done.
            snapshot_name = snapshot.name

            if self._file_not_present(nfs_mount, snapshot_name):
                # The file does not exist. Nothing to do.
                return

        self._execute('rm', self._get_file_path(
            nfs_mount, snapshot_name), run_as_root=True)

    def _file_not_present(self, nfs_mount, volume_name):
        """Check if file does not exist.

        :param nfs_mount: string path of the nfs share
        :param volume_name: string volume name
        :returns: boolean (true for file not present and false otherwise)
        """
        try:
            self._execute('ls', self._get_file_path(nfs_mount, volume_name))
        except processutils.ProcessExecutionError as e:
            if "No such file or directory" in e.stderr:
                # If the file isn't present
                return True
            else:
                raise

        return False

    def _get_file_path(self, nfs_share, file_name):
        """Get file path (local fs path) for given name on given nfs share.

        :param nfs_share string, example 172.18.194.100:/var/nfs
        :param file_name string,
        example volume-91ee65ec-c473-4391-8c09-162b00c68a8c
        :returns: the local path according to the parameters
        """
        return os.path.join(self._get_mount_point_for_share(nfs_share),
                            file_name)

    @cutils.trace
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: reference to the volume being created
        :param src_vref: reference to the source volume
        :returns: the provider_location of the cloned volume
        """

        # HNAS always creates cloned volumes in the same pool as the source
        # volumes. So, it is not allowed to use different volume types for
        # clone operations.
        if volume.volume_type_id != src_vref.volume_type_id:
            msg = _("Source and cloned volumes should have the same "
                    "volume type.")
            LOG.error(msg)
            raise exception.InvalidVolumeType(msg)

        vol_size = volume.size
        src_vol_size = src_vref.size

        self._clone_volume(src_vref, volume.name, src_vref.name)

        share = src_vref.provider_location

        if vol_size > src_vol_size:
            volume.provider_location = share
            self.extend_volume(volume, vol_size)

        return {'provider_location': share}

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        :param refresh: if it is True, update the stats first.
        :returns: dictionary with the stats from HNAS

        .. code:: python

          _stats['pools'] = {
              'total_capacity_gb': total size of the pool,
              'free_capacity_gb': the available size,
              'QoS_support': bool to indicate if QoS is supported,
              'reserved_percentage': percentage of size reserved,
              'max_over_subscription_ratio': oversubscription rate,
              'thin_provisioning_support': thin support (True),
              }

        """
        LOG.info("Getting volume stats")

        _stats = super(HNASNFSDriver, self).get_volume_stats(refresh)
        _stats["vendor_name"] = 'Hitachi'
        _stats["driver_version"] = HNAS_NFS_VERSION
        _stats["storage_protocol"] = 'NFS'

        max_osr = self.max_over_subscription_ratio

        for pool in self.pools:
            capacity, free, provisioned = self._get_capacity_info(pool['fs'])
            pool['total_capacity_gb'] = capacity / float(units.Gi)
            pool['free_capacity_gb'] = free / float(units.Gi)
            pool['provisioned_capacity_gb'] = provisioned / float(units.Gi)
            pool['QoS_support'] = 'False'
            pool['reserved_percentage'] = self.reserved_percentage
            pool['max_over_subscription_ratio'] = max_osr
            pool['thin_provisioning_support'] = True

        _stats['pools'] = self.pools

        LOG.debug('Driver stats: %(stat)s', {'stat': _stats})

        return _stats

    def do_setup(self, context):
        """Perform internal driver setup."""
        version_info = self.backend.get_version()
        LOG.info("HNAS NFS driver.")
        LOG.info("HNAS model: %(mdl)s", {'mdl': version_info['model']})
        LOG.info("HNAS version: %(ver)s",
                 {'ver': version_info['version']})
        LOG.info("HNAS hardware: %(hw)s",
                 {'hw': version_info['hardware']})
        LOG.info("HNAS S/N: %(sn)s", {'sn': version_info['serial']})

        self.context = context
        self._load_shares_config(
            getattr(self.configuration, self.driver_prefix + '_shares_config'))
        LOG.info("Review shares: %(shr)s", {'shr': self.shares})

        elist = self.backend.get_export_list()

        # Check for all configured exports
        for svc_name, svc_info in self.config['services'].items():
            server_ip = svc_info['hdp'].split(':')[0]
            mountpoint = svc_info['hdp'].split(':')[1]

            # Ensure export are configured in HNAS
            export_configured = False
            for export in elist:
                if mountpoint == export['name'] and server_ip in export['evs']:
                    svc_info['export'] = export
                    export_configured = True

            # Ensure export are reachable
            try:
                out, err = self._execute('showmount', '-e', server_ip)
            except processutils.ProcessExecutionError:
                LOG.exception("NFS server %(srv)s not reachable!",
                              {'srv': server_ip})
                raise

            export_list = out.split('\n')[1:]
            export_list.pop()
            mountpoint_not_found = mountpoint not in map(
                lambda x: x.split()[0], export_list)
            if (len(export_list) < 1 or
                    mountpoint_not_found or
                    not export_configured):
                LOG.error("Configured share %(share)s is not present"
                          "in %(srv)s.",
                          {'share': mountpoint, 'srv': server_ip})
                msg = _('Section: %(svc_name)s') % {'svc_name': svc_name}
                raise exception.InvalidParameterValue(err=msg)

        LOG.debug("Loading services: %(svc)s", {
            'svc': self.config['services']})

        service_list = self.config['services'].keys()
        for svc in service_list:
            svc = self.config['services'][svc]
            pool = {}
            pool['pool_name'] = svc['pool_name']
            pool['service_label'] = svc['pool_name']
            pool['fs'] = svc['hdp']

            self.pools.append(pool)

        LOG.debug("Configured pools: %(pool)s", {'pool': self.pools})
        LOG.info("HNAS NFS Driver loaded successfully.")

    def _clone_volume(self, src_vol, clone_name, src_name=None):
        """Clones mounted volume using the HNAS file_clone.

        :param src_vol: object source volume
        :param clone_name: string clone name (or snapshot)
        :param src_name: name of the source volume.
        """

        # when the source is a snapshot, we need to pass the source name and
        # use the information of the volume that originated the snapshot to
        # get the clone path.
        if not src_name:
            src_name = src_vol.name

        # volume-ID snapshot-ID, /cinder
        LOG.info("Cloning with volume_name %(vname)s, clone_name %(cname)s"
                 " ,export_path %(epath)s",
                 {'vname': src_name, 'cname': clone_name,
                     'epath': src_vol.provider_location})

        (fs, path, fs_label) = self._get_service(src_vol)

        target_path = '%s/%s' % (path, clone_name)
        source_path = '%s/%s' % (path, src_name)

        self.backend.file_clone(fs_label, source_path, target_path)

    @cutils.trace
    def create_volume(self, volume):
        """Creates a volume.

        :param volume: volume reference
        :returns: the volume provider_location
        """
        self._ensure_shares_mounted()

        (fs_id, path, fslabel) = self._get_service(volume)

        volume.provider_location = fs_id

        LOG.info("Volume service: %(label)s. Casted to: %(loc)s",
                 {'label': fslabel, 'loc': volume.provider_location})

        self._do_create_volume(volume)

        return {'provider_location': fs_id}

    def _convert_vol_ref_share_name_to_share_ip(self, vol_ref):
        """Converts the share point name to an IP address.

        The volume reference may have a DNS name portion in the share name.
        Convert that to an IP address and then restore the entire path.

        :param vol_ref: driver-specific information used to identify a volume
        :returns: a volume reference where share is in IP format or raises
         error
        :raises e.strerror:
        """

        # First strip out share and convert to IP format.
        share_split = vol_ref.split(':')

        try:
            vol_ref_share_ip = cutils.resolve_hostname(share_split[0])
        except socket.gaierror as e:
            LOG.exception('Invalid hostname %(host)s',
                          {'host': share_split[0]})
            LOG.debug('error: %(err)s', {'err': e.strerror})
            raise

        # Now place back into volume reference.
        vol_ref_share = vol_ref_share_ip + ':' + share_split[1]

        return vol_ref_share

    def _get_share_mount_and_vol_from_vol_ref(self, vol_ref):
        """Get the NFS share, the NFS mount, and the volume from reference.

        Determine the NFS share point, the NFS mount point, and the volume
        (with possible path) from the given volume reference. Raise exception
        if unsuccessful.

        :param vol_ref: driver-specific information used to identify a volume
        :returns: NFS Share, NFS mount, volume path or raise error
        :raises ManageExistingInvalidReference:
        """
        # Check that the reference is valid.
        if 'source-name' not in vol_ref:
            reason = _('Reference must contain source-name element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=vol_ref, reason=reason)
        vol_ref_name = vol_ref['source-name']

        self._ensure_shares_mounted()

        # If a share was declared as '1.2.3.4:/a/b/c' in the nfs_shares_config
        # file, but the admin tries to manage the file located at
        # 'my.hostname.com:/a/b/c/d.vol', this might cause a lookup miss below
        # when searching self._mounted_shares to see if we have an existing
        # mount that would work to access the volume-to-be-managed (a string
        # comparison is done instead of IP comparison).
        vol_ref_share = self._convert_vol_ref_share_name_to_share_ip(
            vol_ref_name)
        for nfs_share in self._mounted_shares:
            cfg_share = self._convert_vol_ref_share_name_to_share_ip(nfs_share)
            (orig_share, work_share,
             file_path) = vol_ref_share.partition(cfg_share)
            if work_share == cfg_share:
                file_path = file_path[1:]  # strip off leading path divider
                LOG.debug("Found possible share %(shr)s; checking mount.",
                          {'shr': work_share})
                nfs_mount = self._get_mount_point_for_share(nfs_share)
                vol_full_path = os.path.join(nfs_mount, file_path)
                if os.path.isfile(vol_full_path):
                    LOG.debug("Found share %(share)s and vol %(path)s on "
                              "mount %(mnt)s.",
                              {'share': nfs_share, 'path': file_path,
                               'mnt': nfs_mount})
                    return nfs_share, nfs_mount, file_path
            else:
                LOG.debug("vol_ref %(ref)s not on share %(share)s.",
                          {'ref': vol_ref_share, 'share': nfs_share})

        raise exception.ManageExistingInvalidReference(
            existing_ref=vol_ref,
            reason=_('Volume/Snapshot not found on configured storage '
                     'backend.'))

    @cutils.trace
    def manage_existing(self, volume, existing_vol_ref):
        """Manages an existing volume.

        The specified Cinder volume is to be taken into Cinder management.
        The driver will verify its existence and then rename it to the
        new Cinder volume name. It is expected that the existing volume
        reference is an NFS share point and some [/path]/volume;
        e.g., 10.10.32.1:/openstack/vol_to_manage
        or 10.10.32.1:/openstack/some_directory/vol_to_manage

        :param volume: cinder volume to manage
        :param existing_vol_ref: driver-specific information used to identify a
                                 volume
        :returns: the provider location
        :raises VolumeBackendAPIException:
        """

        # Attempt to find NFS share, NFS mount, and volume path from vol_ref.
        (nfs_share, nfs_mount, vol_name
         ) = self._get_share_mount_and_vol_from_vol_ref(existing_vol_ref)

        LOG.info("Asked to manage NFS volume %(vol)s, "
                 "with vol ref %(ref)s.",
                 {'vol': volume.id,
                  'ref': existing_vol_ref['source-name']})

        vol_id = utils.extract_id_from_volume_name(vol_name)
        if utils.check_already_managed_volume(vol_id):
            raise exception.ManageExistingAlreadyManaged(volume_ref=vol_name)

        self._check_pool_and_share(volume, nfs_share)

        if vol_name == volume.name:
            LOG.debug("New Cinder volume %(vol)s name matches reference name: "
                      "no need to rename.", {'vol': volume.name})
        else:
            src_vol = os.path.join(nfs_mount, vol_name)
            dst_vol = os.path.join(nfs_mount, volume.name)
            try:
                self._try_execute("mv", src_vol, dst_vol, run_as_root=False,
                                  check_exit_code=True)
                LOG.debug("Setting newly managed Cinder volume name "
                          "to %(vol)s.", {'vol': volume.name})
                self._set_rw_permissions_for_all(dst_vol)
            except (OSError, processutils.ProcessExecutionError) as err:
                msg = (_("Failed to manage existing volume "
                         "%(name)s, because rename operation "
                         "failed: Error msg: %(msg)s.") %
                       {'name': existing_vol_ref['source-name'],
                        'msg': six.text_type(err)})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        return {'provider_location': nfs_share}

    def _check_pool_and_share(self, volume, nfs_share):
        """Validates the pool and the NFS share.

        Checks if the NFS share for the volume-type chosen matches the
        one passed in the volume reference. Also, checks if the pool
        for the volume type matches the pool for the host passed.

        :param volume: cinder volume reference
        :param nfs_share: NFS share passed to manage
        :raises ManageExistingVolumeTypeMismatch:
        """
        pool_from_vol_type = hnas_utils.get_pool(self.config, volume)

        pool_from_host = utils.extract_host(volume.host, level='pool')

        if (pool_from_vol_type == 'default' and
                'default' not in self.config['services']):
            msg = (_("Failed to manage existing volume %(volume)s because the "
                     "chosen volume type %(vol_type)s does not have a "
                     "service_label configured in its extra-specs and there "
                     "is no pool configured with hnas_svcX_volume_type as "
                     "'default' in cinder.conf.") %
                   {'volume': volume.id,
                    'vol_type': getattr(volume.volume_type, 'id', None)})
            LOG.error(msg)
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

        pool = self.config['services'][pool_from_vol_type]['hdp']
        if pool != nfs_share:
            msg = (_("Failed to manage existing volume because the pool of "
                     "the volume type chosen (%(pool)s) does not match the "
                     "NFS share passed in the volume reference (%(share)s).")
                   % {'share': nfs_share, 'pool': pool})
            LOG.error(msg)
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

        if pool_from_host != pool_from_vol_type:
            msg = (_("Failed to manage existing volume because the pool of "
                     "the volume type chosen (%(pool)s) does not match the "
                     "pool of the host %(pool_host)s") %
                   {'pool': pool_from_vol_type,
                    'pool_host': pool_from_host})
            LOG.error(msg)
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

    @cutils.trace
    def manage_existing_get_size(self, volume, existing_vol_ref):
        """Returns the size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.

        :param volume: cinder volume to manage
        :param existing_vol_ref: existing volume to take under management
        :returns: the size of the volume or raise error
        :raises VolumeBackendAPIException:
        """
        return self._manage_existing_get_size(existing_vol_ref)

    @cutils.trace
    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        It does not delete the underlying backend storage object. A log entry
        will be made to notify the Admin that the volume is no longer being
        managed.

        :param volume: cinder volume to unmanage
        """
        vol_str = CONF.volume_name_template % volume.id
        path = self._get_mount_point_for_share(volume.provider_location)

        new_str = "unmanage-" + vol_str

        vol_path = os.path.join(path, vol_str)
        new_path = os.path.join(path, new_str)

        try:
            self._try_execute("mv", vol_path, new_path,
                              run_as_root=False, check_exit_code=True)

            LOG.info("The volume with path %(old)s is no longer being "
                     "managed by Cinder. However, it was not deleted "
                     "and can be found in the new path %(cr)s.",
                     {'old': vol_path, 'cr': new_path})

        except (OSError, ValueError):
            LOG.exception("The NFS Volume %(cr)s does not exist.",
                          {'cr': new_path})

    def _get_file_size(self, file_path):
        file_size = float(cutils.get_file_size(file_path)) / units.Gi
        # Round up to next Gb
        return int(math.ceil(file_size))

    def _manage_existing_get_size(self, existing_ref):
        # Attempt to find NFS share, NFS mount, and path from vol_ref.
        (nfs_share, nfs_mount, path
         ) = self._get_share_mount_and_vol_from_vol_ref(existing_ref)

        try:
            LOG.debug("Asked to get size of NFS ref %(ref)s.",
                      {'ref': existing_ref['source-name']})

            file_path = os.path.join(nfs_mount, path)
            size = self._get_file_size(file_path)
        except (OSError, ValueError):
            exception_message = (_("Failed to manage existing volume/snapshot "
                                   "%(name)s, because of error in getting "
                                   "its size."),
                                 {'name': existing_ref['source-name']})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.debug("Reporting size of NFS ref %(ref)s as %(size)d GB.",
                  {'ref': existing_ref['source-name'], 'size': size})

        return size

    def _check_snapshot_parent(self, volume, old_snap_name, share):
        volume_name = 'volume-' + volume.id
        (fs, path, fs_label) = self._get_service(volume)
        # 172.24.49.34:/nfs_cinder

        export_path = self.backend.get_export_path(share.split(':')[1],
                                                   fs_label)
        volume_path = os.path.join(export_path, volume_name)

        return self.backend.check_snapshot_parent(volume_path, old_snap_name,
                                                  fs_label)

    def _get_snapshot_origin_from_name(self, snap_name):
        """Gets volume name from snapshot names"""
        if 'unmanage' in snap_name:
            return snap_name.split('.')[0][9:]

        return snap_name.split('.')[0]

    @cutils.trace
    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        :param snapshot:     Cinder volume snapshot to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume snapshot
        """

        # Attempt to find NFS share, NFS mount, and volume path from ref.
        (nfs_share, nfs_mount, src_snapshot_name
         ) = self._get_share_mount_and_vol_from_vol_ref(existing_ref)

        LOG.info("Asked to manage NFS snapshot %(snap)s for volume "
                 "%(vol)s, with vol ref %(ref)s.",
                 {'snap': snapshot.id,
                  'vol': snapshot.volume_id,
                  'ref': existing_ref['source-name']})

        volume = snapshot.volume
        parent_name = self._get_snapshot_origin_from_name(src_snapshot_name)

        if parent_name != volume.name:
            # Check if the snapshot belongs to the volume for the legacy case
            if not self._check_snapshot_parent(
                    volume, src_snapshot_name, nfs_share):
                msg = (_("This snapshot %(snap)s doesn't belong "
                         "to the volume parent %(vol)s.") %
                       {'snap': src_snapshot_name, 'vol': volume.id})
                raise exception.ManageExistingInvalidReference(
                    existing_ref=existing_ref, reason=msg)

        snapshot_name = self._get_snapshot_name(snapshot)

        if src_snapshot_name == snapshot_name:
            LOG.debug("New Cinder snapshot %(snap)s name matches reference "
                      "name. No need to rename.", {'snap': snapshot_name})
        else:
            src_snap = os.path.join(nfs_mount, src_snapshot_name)
            dst_snap = os.path.join(nfs_mount, snapshot_name)
            try:
                self._try_execute("mv", src_snap, dst_snap, run_as_root=False,
                                  check_exit_code=True)
                LOG.info("Setting newly managed Cinder snapshot name "
                         "to %(snap)s.", {'snap': snapshot_name})
                self._set_rw_permissions_for_all(dst_snap)
            except (OSError, processutils.ProcessExecutionError) as err:
                msg = (_("Failed to manage existing snapshot "
                         "%(name)s, because rename operation "
                         "failed: Error msg: %(msg)s.") %
                       {'name': existing_ref['source-name'],
                        'msg': six.text_type(err)})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        return {'provider_location': nfs_share}

    @cutils.trace
    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        return self._manage_existing_get_size(existing_ref)

    @cutils.trace
    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management.

        Does not delete the underlying backend storage object.

        :param snapshot: Cinder volume snapshot to unmanage
        """

        path = self._get_mount_point_for_share(snapshot.provider_location)
        snapshot_name = self._get_snapshot_name(snapshot)

        if self._file_not_present(snapshot.provider_location, snapshot_name):
            LOG.info("Unmanaging legacy snapshot %(snap)s.",
                     {'snap': snapshot.name})
            snapshot_name = snapshot.name

        new_name = "unmanage-" + snapshot_name

        old_path = os.path.join(path, snapshot_name)
        new_path = os.path.join(path, new_name)

        try:
            self._execute("mv", old_path, new_path,
                          run_as_root=False, check_exit_code=True)
            LOG.info("The snapshot with path %(old)s is no longer being "
                     "managed by Cinder. However, it was not deleted and "
                     "can be found in the new path %(cr)s.",
                     {'old': old_path, 'cr': new_path})

        except (OSError, ValueError):
            LOG.exception("The NFS snapshot %(old)s does not exist.",
                          {'old': old_path})

    def _get_volumes_from_export(self, export_path):
        mnt_point = self._get_mount_point_for_share(export_path)

        vols = self._execute("ls", mnt_point, run_as_root=False,
                             check_exit_code=True)

        vols = vols[0].split('\n')
        if '' in vols:
            vols.remove('')

        return list(vols)

    def _get_snapshot_origin(self, snap_path, fs_label):
        relatives = self.backend.get_cloned_file_relatives(snap_path, fs_label)

        origin = []

        if not relatives:
            return
        elif len(relatives) > 1:
            for relative in relatives:
                if 'snapshot' not in relative:
                    origin.append(relative)
        else:
            origin.append(relatives[0])

        return origin

    def _get_manageable_resource_info(self, cinder_resources, resource_type,
                                      marker, limit, offset, sort_keys,
                                      sort_dirs):
        """Gets the resources on the backend available for management by Cinder.

        Receives the parameters from "get_manageable_volumes" and
        "get_manageable_snapshots" and gets the available resources

        :param cinder_resources: A list of resources in this host that Cinder
        currently manages
        :param resource_type: If it's a volume or a snapshot
        :param marker: The last item of the previous page; we return the
        next results after this value (after sorting)
        :param limit: Maximum number of items to return
        :param offset: Number of items to skip after marker
        :param sort_keys: List of keys to sort results by (valid keys
        are 'identifier' and 'size')
        :param sort_dirs: List of directions to sort by, corresponding to
        sort_keys (valid directions are 'asc' and 'desc')

        :returns: list of dictionaries, each specifying a volume or snapshot
        (resource) in the host, with the following keys:
            - reference (dictionary): The reference for a resource,
            which can be passed to "manage_existing_snapshot".
            - size (int): The size of the resource according to the storage
              backend, rounded up to the nearest GB.
            - safe_to_manage (boolean): Whether or not this resource is
            safe to manage according to the storage backend.
            - reason_not_safe (string): If safe_to_manage is False,
              the reason why.
            - cinder_id (string): If already managed, provide the Cinder ID.
            - extra_info (string): Any extra information to return to the
            user
            - source_reference (string): Similar to "reference", but for the
              snapshot's source volume.
        """

        entries = []
        exports = {}
        bend_rsrc = {}
        cinder_ids = [resource.id for resource in cinder_resources]

        for service in self.config['services']:
            exp_path = self.config['services'][service]['hdp']
            exports[exp_path] = (
                self.config['services'][service]['export']['fs'])

        for exp in exports.keys():
            # bend_rsrc has all the resources in the specified exports
            # volumes {u'172.24.54.39:/Export-Cinder':
            #   ['volume-325e7cdc-8f65-40a8-be9a-6172c12c9394',
            # '     snapshot-1bfb6f0d-9497-4c12-a052-5426a76cacdc','']}
            bend_rsrc[exp] = self._get_volumes_from_export(exp)
            mnt_point = self._get_mount_point_for_share(exp)

            for resource in bend_rsrc[exp]:
                # Ignoring resources of unwanted types
                if ((resource_type == 'volume' and
                        ('.' in resource or 'snapshot' in resource)) or
                    (resource_type == 'snapshot' and '.' not in resource and
                        'snapshot' not in resource)):
                    continue

                path = '%s/%s' % (exp, resource)
                mnt_path = '%s/%s' % (mnt_point, resource)
                size = self._get_file_size(mnt_path)

                rsrc_inf = {'reference': {'source-name': path},
                            'size': size, 'cinder_id': None,
                            'extra_info': None}

                if resource_type == 'volume':
                    potential_id = utils.extract_id_from_volume_name(resource)
                elif 'snapshot' in resource:
                    # This is for the snapshot legacy case
                    potential_id = utils.extract_id_from_snapshot_name(
                        resource)
                else:
                    potential_id = resource.split('.')[1]

                # When a resource is already managed by cinder, it's not
                # recommended to manage it again. So we set safe_to_manage =
                # False. Otherwise, it is set safe_to_manage = True.
                if potential_id in cinder_ids:
                    rsrc_inf['safe_to_manage'] = False
                    rsrc_inf['reason_not_safe'] = 'already managed'
                    rsrc_inf['cinder_id'] = potential_id
                else:
                    rsrc_inf['safe_to_manage'] = True
                    rsrc_inf['reason_not_safe'] = None

                # If it's a snapshot, we try to get its source volume. However,
                # this search is not reliable in some cases. So, if it's not
                # possible to return a precise result, we return unknown as
                # source-reference, throw a warning message and fill the
                # extra-info.
                if resource_type == 'snapshot':
                    if 'snapshot' not in resource:
                        origin = self._get_snapshot_origin_from_name(resource)
                        if 'unmanage' in origin:
                            origin = origin[16:]
                        else:
                            origin = origin[7:]
                        rsrc_inf['source_reference'] = {'id': origin}
                    else:
                        path = path.split(':')[1]
                        origin = self._get_snapshot_origin(path, exports[exp])

                        if not origin:
                            # if origin is empty, the file is not a clone
                            continue
                        elif len(origin) == 1:
                            origin = origin[0].split('/')[2]
                            origin = utils.extract_id_from_volume_name(origin)
                            rsrc_inf['source_reference'] = {'id': origin}
                        else:
                            LOG.warning("Could not determine the volume "
                                        "that owns the snapshot %(snap)s",
                                        {'snap': resource})
                            rsrc_inf['source_reference'] = {'id': 'unknown'}
                            rsrc_inf['extra_info'] = ('Could not determine '
                                                      'the volume that owns '
                                                      'the snapshot')

                entries.append(rsrc_inf)

        return utils.paginate_entries_list(entries, marker, limit, offset,
                                           sort_keys, sort_dirs)

    @cutils.trace
    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """List volumes on the backend available for management by Cinder."""

        return self._get_manageable_resource_info(cinder_volumes, 'volume',
                                                  marker, limit, offset,
                                                  sort_keys, sort_dirs)

    @cutils.trace
    def get_manageable_snapshots(self, cinder_snapshots, marker, limit, offset,
                                 sort_keys, sort_dirs):
        """List snapshots on the backend available for management by Cinder."""

        return self._get_manageable_resource_info(cinder_snapshots, 'snapshot',
                                                  marker, limit, offset,
                                                  sort_keys, sort_dirs)
