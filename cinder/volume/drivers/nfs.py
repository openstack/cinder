# Copyright (c) 2012 NetApp, Inc.
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

import errno
import os
import time

from os_brick.remotefs import remotefs as remotefs_brick
from oslo_concurrency import processutils as putils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_log import versionutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.image import image_utils
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers import remotefs

VERSION = '1.3.0'

LOG = logging.getLogger(__name__)

NFS_USED_RATIO_DEFAULT = 0.95
NFS_OVERSUB_RATIO_DEFAULT = 1.0

nfs_opts = [
    cfg.StrOpt('nfs_shares_config',
               default='/etc/cinder/nfs_shares',
               help='File with the list of available NFS shares'),
    cfg.BoolOpt('nfs_sparsed_volumes',
                default=True,
                help=('Create volumes as sparsed files which take no space.'
                      'If set to False volume is created as regular file.'
                      'In such case volume creation takes a lot of time.')),
    # TODO(tbarron): remove nfs_used_ratio in the Mitaka release.
    cfg.FloatOpt('nfs_used_ratio',
                 default=NFS_USED_RATIO_DEFAULT,
                 help=('Percent of ACTUAL usage of the underlying volume '
                       'before no new volumes can be allocated to the volume '
                       'destination. Note that this option is deprecated '
                       'in favor of "reserved_percentage" and will be removed '
                       'in the Mitaka release.')),
    # TODO(tbarron): remove nfs_oversub_ratio in the Mitaka release.
    cfg.FloatOpt('nfs_oversub_ratio',
                 default=NFS_OVERSUB_RATIO_DEFAULT,
                 help=('This will compare the allocated to available space on '
                       'the volume destination.  If the ratio exceeds this '
                       'number, the destination will no longer be valid. '
                       'Note that this option is deprecated in favor of '
                       '"max_oversubscription_ratio" and will be removed '
                       'in the Mitaka release.')),
    cfg.StrOpt('nfs_mount_point_base',
               default='$state_path/mnt',
               help=('Base dir containing mount points for NFS shares.')),
    cfg.StrOpt('nfs_mount_options',
               help=('Mount options passed to the NFS client. See section '
                     'of the NFS man page for details.')),
    cfg.IntOpt('nfs_mount_attempts',
               default=3,
               help=('The number of attempts to mount NFS shares before '
                     'raising an error.  At least one attempt will be '
                     'made to mount an NFS share, regardless of the '
                     'value specified.')),
]

CONF = cfg.CONF
CONF.register_opts(nfs_opts)


class NfsDriver(driver.ExtendVD, remotefs.RemoteFSDriver):
    """NFS based cinder driver.

    Creates file on NFS share for using it as block device on hypervisor.
    """

    driver_volume_type = 'nfs'
    driver_prefix = 'nfs'
    volume_backend_name = 'Generic_NFS'
    VERSION = VERSION

    def __init__(self, execute=putils.execute, *args, **kwargs):
        self._remotefsclient = None
        super(NfsDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(nfs_opts)
        root_helper = utils.get_root_helper()
        # base bound to instance is used in RemoteFsConnector.
        self.base = getattr(self.configuration,
                            'nfs_mount_point_base',
                            CONF.nfs_mount_point_base)
        self.base = os.path.realpath(self.base)
        opts = getattr(self.configuration,
                       'nfs_mount_options',
                       CONF.nfs_mount_options)

        nas_mount_options = getattr(self.configuration,
                                    'nas_mount_options',
                                    None)
        if nas_mount_options is not None:
            LOG.debug('overriding nfs_mount_options with nas_mount_options')
            opts = nas_mount_options

        self._remotefsclient = remotefs_brick.RemoteFsClient(
            'nfs', root_helper, execute=execute,
            nfs_mount_point_base=self.base,
            nfs_mount_options=opts)

        self._sparse_copy_volume_data = True
        self.reserved_percentage = self._get_reserved_percentage()
        self.over_subscription_ratio = self._get_over_subscription_ratio()

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(NfsDriver, self).do_setup(context)

        config = self.configuration.nfs_shares_config
        if not config:
            msg = (_("There's no NFS config file configured (%s)") %
                   'nfs_shares_config')
            LOG.warning(msg)
            raise exception.NfsException(msg)
        if not os.path.exists(config):
            msg = (_("NFS config file at %(config)s doesn't exist") %
                   {'config': config})
            LOG.warning(msg)
            raise exception.NfsException(msg)

        self.shares = {}  # address : options

        # Check if /sbin/mount.nfs is installed on this system;
        # note that we don't need to be root, to see if the package
        # is installed.
        # We rely on the absolute path /sbin/mount.nfs; this seems to be
        # common on most distributions (SUSE, RedHat, CentOS, Ubuntu, Debian)
        # and it does not depend on correct PATH of the executing user,
        # when trying to find the relative binary.
        package = '/sbin/mount.nfs'
        try:
            self._execute(package, check_exit_code=False,
                          run_as_root=False)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                msg = _('%s is not installed') % package
                raise exception.NfsException(msg)
            else:
                raise

        # Now that all configuration data has been loaded (shares),
        # we can "set" our final NAS file security options.
        self.set_nas_security_options(self._is_voldb_empty_at_startup)

    def _ensure_share_mounted(self, nfs_share):
        mnt_flags = []
        if self.shares.get(nfs_share) is not None:
            mnt_flags = self.shares[nfs_share].split()
        num_attempts = max(1, self.configuration.nfs_mount_attempts)
        for attempt in range(num_attempts):
            try:
                self._remotefsclient.mount(nfs_share, mnt_flags)
                return
            except Exception as e:
                if attempt == (num_attempts - 1):
                    LOG.error(_LE('Mount failure for %(share)s after '
                                  '%(count)d attempts.'), {
                              'share': nfs_share,
                              'count': num_attempts})
                    raise exception.NfsException(six.text_type(e))
                LOG.debug('Mount attempt %(attempt)d failed: %(exc)s.\n'
                          'Retrying mount ...',
                          {'attempt': attempt, 'exc': e})
                time.sleep(1)

    def _find_share(self, volume_size_in_gib):
        """Choose NFS share among available ones for given volume size.

        For instances with more than one share that meets the criteria, the
        share with the least "allocated" space will be selected.

        :param volume_size_in_gib: int size in GB
        """

        if not self._mounted_shares:
            raise exception.NfsNoSharesMounted()

        target_share = None
        target_share_reserved = 0

        for nfs_share in self._mounted_shares:
            if not self._is_share_eligible(nfs_share, volume_size_in_gib):
                continue
            _total_size, _total_available, total_allocated = \
                self._get_capacity_info(nfs_share)
            if target_share is not None:
                if target_share_reserved > total_allocated:
                    target_share = nfs_share
                    target_share_reserved = total_allocated
            else:
                target_share = nfs_share
                target_share_reserved = total_allocated

        if target_share is None:
            raise exception.NfsNoSuitableShareFound(
                volume_size=volume_size_in_gib)

        LOG.debug('Selected %s as target NFS share.', target_share)

        return target_share

    def _is_share_eligible(self, nfs_share, volume_size_in_gib):
        """Verifies NFS share is eligible to host volume with given size.

        First validation step: ratio of actual space (used_space / total_space)
        is less than 'nfs_used_ratio'. Second validation step: apparent space
        allocated (differs from actual space used when using sparse files)
        and compares the apparent available
        space (total_available * nfs_oversub_ratio) to ensure enough space is
        available for the new volume.

        :param nfs_share: NFS share
        :param volume_size_in_gib: int size in GB
        """
        # Because the generic NFS driver aggregates over all shares
        # when reporting capacity and usage stats to the scheduler,
        # we still have to perform some scheduler-like capacity
        # checks here, and these have to take into account
        # configuration for reserved space and oversubscription.
        # It would be better to do all this in the scheduler, but
        # this requires either pool support for the generic NFS
        # driver or limiting each NFS backend driver to a single share.

        # 'nfs_used_ratio' is deprecated, so derive used_ratio from
        # reserved_percentage.
        used_percentage = 100 - self.reserved_percentage
        used_ratio = used_percentage / 100.0

        oversub_ratio = self.over_subscription_ratio
        requested_volume_size = volume_size_in_gib * units.Gi

        total_size, total_available, total_allocated = \
            self._get_capacity_info(nfs_share)
        apparent_size = max(0, total_size * oversub_ratio)
        apparent_available = max(0, apparent_size - total_allocated)

        actual_used_ratio = (total_size - total_available) / float(total_size)
        if actual_used_ratio > used_ratio:
            # NOTE(morganfainberg): We check the used_ratio first since
            # with oversubscription it is possible to not have the actual
            # available space but be within our oversubscription limit
            # therefore allowing this share to still be selected as a valid
            # target.
            LOG.debug('%s is above nfs_used_ratio', nfs_share)
            return False
        if apparent_available <= requested_volume_size:
            LOG.debug('%s is above nfs_oversub_ratio', nfs_share)
            return False
        if total_allocated / total_size >= oversub_ratio:
            LOG.debug('%s reserved space is above nfs_oversub_ratio',
                      nfs_share)
            return False
        return True

    def _get_mount_point_for_share(self, nfs_share):
        """Needed by parent class."""
        return self._remotefsclient.get_mount_point(nfs_share)

    def _get_capacity_info(self, nfs_share):
        """Calculate available space on the NFS share.

        :param nfs_share: example 172.18.194.100:/var/nfs
        """
        run_as_root = self._execute_as_root

        mount_point = self._get_mount_point_for_share(nfs_share)

        df, _ = self._execute('stat', '-f', '-c', '%S %b %a', mount_point,
                              run_as_root=run_as_root)
        block_size, blocks_total, blocks_avail = map(float, df.split())
        total_available = block_size * blocks_avail
        total_size = block_size * blocks_total

        du, _ = self._execute('du', '-sb', '--apparent-size', '--exclude',
                              '*snapshot*', mount_point,
                              run_as_root=run_as_root)
        total_allocated = float(du.split()[0])
        return total_size, total_available, total_allocated

    def _get_mount_point_base(self):
        return self.base

    def extend_volume(self, volume, new_size):
        """Extend an existing volume to the new size."""
        LOG.info(_LI('Extending volume %s.'), volume['id'])
        extend_by = int(new_size) - volume['size']
        if not self._is_share_eligible(volume['provider_location'],
                                       extend_by):
            raise exception.ExtendVolumeError(reason='Insufficient space to'
                                              ' extend volume %s to %sG'
                                              % (volume['id'], new_size))
        path = self.local_path(volume)
        LOG.info(_LI('Resizing file to %sG...'), new_size)
        image_utils.resize_image(path, new_size,
                                 run_as_root=self._execute_as_root)
        if not self._is_file_size_equal(path, new_size):
            raise exception.ExtendVolumeError(
                reason='Resizing image file failed.')

    def _is_file_size_equal(self, path, size):
        """Checks if file size at path is equal to size."""
        data = image_utils.qemu_img_info(path,
                                         run_as_root=self._execute_as_root)
        virt_size = data.virtual_size / units.Gi
        return virt_size == size

    def set_nas_security_options(self, is_new_cinder_install):
        """Determine the setting to use for Secure NAS options.

        Value of each NAS Security option is checked and updated. If the
        option is currently 'auto', then it is set to either true or false
        based upon if this is a new Cinder installation. The RemoteFS variable
        '_execute_as_root' will be updated for this driver.

        :param is_new_cinder_install: bool indication of new Cinder install
        """
        doc_html = "http://docs.openstack.org/admin-guide-cloud" \
                   "/blockstorage_nfs_backend.html"

        self._ensure_shares_mounted()
        if not self._mounted_shares:
            raise exception.NfsNoSharesMounted()

        nfs_mount = self._get_mount_point_for_share(self._mounted_shares[0])

        self.configuration.nas_secure_file_permissions = \
            self._determine_nas_security_option_setting(
                self.configuration.nas_secure_file_permissions,
                nfs_mount, is_new_cinder_install)

        LOG.debug('NAS variable secure_file_permissions setting is: %s',
                  self.configuration.nas_secure_file_permissions)

        if self.configuration.nas_secure_file_permissions == 'false':
            LOG.warning(_LW("The NAS file permissions mode will be 666 "
                            "(allowing other/world read & write access). "
                            "This is considered an insecure NAS environment. "
                            "Please see %s for information on a secure "
                            "NFS configuration."),
                        doc_html)

        self.configuration.nas_secure_file_operations = \
            self._determine_nas_security_option_setting(
                self.configuration.nas_secure_file_operations,
                nfs_mount, is_new_cinder_install)

        # If secure NAS, update the '_execute_as_root' flag to not
        # run as the root user; run as process' user ID.
        if self.configuration.nas_secure_file_operations == 'true':
            self._execute_as_root = False

        LOG.debug('NAS variable secure_file_operations setting is: %s',
                  self.configuration.nas_secure_file_operations)

        if self.configuration.nas_secure_file_operations == 'false':
            LOG.warning(_LW("The NAS file operations will be run as "
                            "root: allowing root level access at the storage "
                            "backend. This is considered an insecure NAS "
                            "environment. Please see %s "
                            "for information on a secure NAS configuration."),
                        doc_html)

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return the keys and values updated from NFS for migrated volume.

        This method should rename the back-end volume name(id) on the
        destination host back to its original name(id) on the source host.

        :param ctxt: The context used to run the method update_migrated_volume
        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :return model_update to update DB with any needed changes
        """
        # TODO(vhou) This method may need to be updated after
        # NFS snapshots are introduced.
        name_id = None
        if original_volume_status == 'available':
            current_name = CONF.volume_name_template % new_volume['id']
            original_volume_name = CONF.volume_name_template % volume['id']
            current_path = self.local_path(new_volume)
            # Replace the volume name with the original volume name
            original_path = current_path.replace(current_name,
                                                 original_volume_name)
            try:
                os.rename(current_path, original_path)
            except OSError:
                LOG.error(_LE('Unable to rename the logical volume '
                              'for volume: %s'), volume['id'])
                # If the rename fails, _name_id should be set to the new
                # volume id and provider_location should be set to the
                # one from the new volume as well.
                name_id = new_volume['_name_id'] or new_volume['id']
        else:
            # The back-end will not be renamed.
            name_id = new_volume['_name_id'] or new_volume['id']
        return {'_name_id': name_id,
                'provider_location': new_volume['provider_location']}

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        super(NfsDriver, self)._update_volume_stats()
        self._stats['sparse_copy_volume'] = True
        data = self._stats

        global_capacity = data['total_capacity_gb']
        global_free = data['free_capacity_gb']

        thin_enabled = self.configuration.nfs_sparsed_volumes
        if thin_enabled:
            provisioned_capacity = self._get_provisioned_capacity()
        else:
            provisioned_capacity = round(global_capacity - global_free, 2)

        data['provisioned_capacity_gb'] = provisioned_capacity
        data['max_over_subscription_ratio'] = self.over_subscription_ratio
        data['reserved_percentage'] = self.reserved_percentage
        data['thin_provisioning_support'] = thin_enabled
        data['thick_provisioning_support'] = not thin_enabled

        self._stats = data

    def _get_over_subscription_ratio(self):
        legacy_oversub_ratio = self.configuration.nfs_oversub_ratio
        if legacy_oversub_ratio == NFS_OVERSUB_RATIO_DEFAULT:
            return self.configuration.max_over_subscription_ratio

        # Honor legacy option if its value is not the default.
        msg = _LW("The option 'nfs_oversub_ratio' is deprecated and will "
                  "be removed in the Mitaka release.  Please set "
                  "'max_over_subscription_ratio = %s' instead.") % (
                      self.configuration.nfs_oversub_ratio)
        versionutils.report_deprecated_feature(LOG, msg)

        if not self.configuration.nfs_oversub_ratio > 0:
            msg = _("NFS config 'nfs_oversub_ratio' invalid.  Must be > 0: "
                    "%s.") % self.configuration.nfs_oversub_ratio
            LOG.error(msg)
            raise exception.InvalidConfigurationValue(msg)

        return legacy_oversub_ratio

    def _get_reserved_percentage(self):
        legacy_used_ratio = self.configuration.nfs_used_ratio
        legacy_reserved_ratio = 1 - legacy_used_ratio
        legacy_percentage = legacy_reserved_ratio * 100
        if legacy_used_ratio == NFS_USED_RATIO_DEFAULT:
            return self.configuration.reserved_percentage

        # Honor legacy option if its value is not the default.
        msg = _LW("The option 'nfs_used_ratio' is deprecated and will "
                  "be removed in the Mitaka release.  Please set "
                  "'reserved_percentage = %d' instead.") % (
                      legacy_percentage)
        versionutils.report_deprecated_feature(LOG, msg)

        if not ((self.configuration.nfs_used_ratio > 0) and
                (self.configuration.nfs_used_ratio <= 1)):
            msg = _("NFS config 'nfs_used_ratio' invalid.  Must be > 0 "
                    "and <= 1.0: %s.") % self.configuration.nfs_used_ratio
            LOG.error(msg)
            raise exception.InvalidConfigurationValue(msg)

        return legacy_percentage
