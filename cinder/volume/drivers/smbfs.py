# Copyright (c) 2014 Cloudbase Solutions SRL
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

import decorator

import inspect
import json
import os

from os_brick.remotefs import remotefs
from oslo_concurrency import processutils as putils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LI, _LW
from cinder.image import image_utils
from cinder import utils
from cinder.volume.drivers import remotefs as remotefs_drv


VERSION = '1.1.0'

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('smbfs_shares_config',
               default='/etc/cinder/smbfs_shares',
               help='File with the list of available smbfs shares.'),
    cfg.StrOpt('smbfs_allocation_info_file_path',
               default='$state_path/allocation_data',
               help=('The path of the automatically generated file containing '
                     'information about volume disk space allocation.')),
    cfg.StrOpt('smbfs_default_volume_format',
               default='qcow2',
               choices=['raw', 'qcow2', 'vhd', 'vhdx'],
               help=('Default format that will be used when creating volumes '
                     'if no volume format is specified.')),
    cfg.BoolOpt('smbfs_sparsed_volumes',
                default=True,
                help=('Create volumes as sparsed files which take no space '
                      'rather than regular files when using raw format, '
                      'in which case volume creation takes lot of time.')),
    cfg.FloatOpt('smbfs_used_ratio',
                 default=0.95,
                 help=('Percent of ACTUAL usage of the underlying volume '
                       'before no new volumes can be allocated to the volume '
                       'destination.')),
    cfg.FloatOpt('smbfs_oversub_ratio',
                 default=1.0,
                 help=('This will compare the allocated to available space on '
                       'the volume destination.  If the ratio exceeds this '
                       'number, the destination will no longer be valid.')),
    cfg.StrOpt('smbfs_mount_point_base',
               default='$state_path/mnt',
               help=('Base dir containing mount points for smbfs shares.')),
    cfg.StrOpt('smbfs_mount_options',
               default='noperm,file_mode=0775,dir_mode=0775',
               help=('Mount options passed to the smbfs client. See '
                     'mount.cifs man page for details.')),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)


def update_allocation_data(delete=False):
    @decorator.decorator
    def wrapper(func, inst, *args, **kwargs):
        ret_val = func(inst, *args, **kwargs)

        call_args = inspect.getcallargs(func, inst, *args, **kwargs)
        volume = call_args['volume']
        requested_size = call_args.get('size_gb', None)

        if delete:
            allocated_size_gb = None
        else:
            allocated_size_gb = requested_size or volume['size']

        inst.update_disk_allocation_data(volume, allocated_size_gb)
        return ret_val
    return wrapper


class SmbfsDriver(remotefs_drv.RemoteFSSnapDriver):
    """SMBFS based cinder volume driver."""

    driver_volume_type = 'smbfs'
    driver_prefix = 'smbfs'
    volume_backend_name = 'Generic_SMBFS'
    SHARE_FORMAT_REGEX = r'//.+/.+'
    VERSION = VERSION

    _MINIMUM_QEMU_IMG_VERSION = '1.7'

    _DISK_FORMAT_VHD = 'vhd'
    _DISK_FORMAT_VHD_LEGACY = 'vpc'
    _DISK_FORMAT_VHDX = 'vhdx'
    _DISK_FORMAT_RAW = 'raw'
    _DISK_FORMAT_QCOW2 = 'qcow2'

    def __init__(self, execute=putils.execute, *args, **kwargs):
        self._remotefsclient = None
        super(SmbfsDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)
        root_helper = utils.get_root_helper()
        self.base = getattr(self.configuration,
                            'smbfs_mount_point_base')
        opts = getattr(self.configuration,
                       'smbfs_mount_options')
        self._remotefsclient = remotefs.RemoteFsClient(
            'cifs', root_helper, execute=execute,
            smbfs_mount_point_base=self.base,
            smbfs_mount_options=opts)
        self.img_suffix = None
        self._alloc_info_file_path = CONF.smbfs_allocation_info_file_path

    def _qemu_img_info(self, path, volume_name):
        return super(SmbfsDriver, self)._qemu_img_info_base(
            path, volume_name, self.configuration.smbfs_mount_point_base)

    @remotefs_drv.locked_volume_id_operation
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info.

        :param volume: volume reference
        :param connector: connector reference
        """
        # Find active image
        active_file = self.get_active_image_from_info(volume)
        active_file_path = os.path.join(self._local_volume_dir(volume),
                                        active_file)
        info = self._qemu_img_info(active_file_path, volume['name'])
        fmt = info.file_format

        data = {'export': volume['provider_location'],
                'format': fmt,
                'name': active_file}
        if volume['provider_location'] in self.shares:
            data['options'] = self.shares[volume['provider_location']]
        return {
            'driver_volume_type': self.driver_volume_type,
            'data': data,
            'mount_point_base': self._get_mount_point_base()
        }

    def do_setup(self, context):
        image_utils.check_qemu_img_version(self._MINIMUM_QEMU_IMG_VERSION)

        config = self.configuration.smbfs_shares_config
        if not config:
            msg = (_("SMBFS config file not set (smbfs_shares_config)."))
            LOG.error(msg)
            raise exception.SmbfsException(msg)
        if not os.path.exists(config):
            msg = (_("SMBFS config file at %(config)s doesn't exist.") %
                   {'config': config})
            LOG.error(msg)
            raise exception.SmbfsException(msg)
        if not os.path.isabs(self.base):
            msg = _("Invalid mount point base: %s") % self.base
            LOG.error(msg)
            raise exception.SmbfsException(msg)
        if not self.configuration.smbfs_oversub_ratio > 0:
            msg = _(
                "SMBFS config 'smbfs_oversub_ratio' invalid.  Must be > 0: "
                "%s") % self.configuration.smbfs_oversub_ratio

            LOG.error(msg)
            raise exception.SmbfsException(msg)

        if not 0 < self.configuration.smbfs_used_ratio <= 1:
            msg = _("SMBFS config 'smbfs_used_ratio' invalid.  Must be > 0 "
                    "and <= 1.0: %s") % self.configuration.smbfs_used_ratio
            LOG.error(msg)
            raise exception.SmbfsException(msg)

        self.shares = {}  # address : options
        self._ensure_shares_mounted()
        self._setup_allocation_data()

    def _setup_allocation_data(self):
        if not os.path.exists(self._alloc_info_file_path):
            fileutils.ensure_tree(
                os.path.dirname(self._alloc_info_file_path))
            self._allocation_data = {}
            self._update_allocation_data_file()
        else:
            with open(self._alloc_info_file_path, 'r') as f:
                self._allocation_data = json.load(f)

    def update_disk_allocation_data(self, volume, virtual_size_gb=None):
        volume_name = volume['name']
        smbfs_share = volume['provider_location']
        if smbfs_share:
            share_hash = self._get_hash_str(smbfs_share)
        else:
            return

        share_alloc_data = self._allocation_data.get(share_hash, {})
        old_virtual_size = share_alloc_data.get(volume_name, 0)
        total_allocated = share_alloc_data.get('total_allocated', 0)

        if virtual_size_gb:
            share_alloc_data[volume_name] = virtual_size_gb
            total_allocated += virtual_size_gb - old_virtual_size
        elif share_alloc_data.get(volume_name):
            # The volume is deleted.
            del share_alloc_data[volume_name]
            total_allocated -= old_virtual_size

        share_alloc_data['total_allocated'] = total_allocated
        self._allocation_data[share_hash] = share_alloc_data
        self._update_allocation_data_file()

    def _update_allocation_data_file(self):
        with open(self._alloc_info_file_path, 'w') as f:
            json.dump(self._allocation_data, f)

    def _get_total_allocated(self, smbfs_share):
        share_hash = self._get_hash_str(smbfs_share)
        share_alloc_data = self._allocation_data.get(share_hash, {})
        total_allocated = share_alloc_data.get('total_allocated', 0) << 30
        return float(total_allocated)

    def local_path(self, volume):
        """Get volume path (mounted locally fs path) for given volume.

        :param volume: volume reference
        """
        volume_path_template = self._get_local_volume_path_template(volume)
        volume_path = self._lookup_local_volume_path(volume_path_template)
        if volume_path:
            return volume_path

        # The image does not exist, so retrieve the volume format
        # in order to build the path.
        fmt = self.get_volume_format(volume)
        if fmt in (self._DISK_FORMAT_VHD, self._DISK_FORMAT_VHDX):
            volume_path = volume_path_template + '.' + fmt
        else:
            volume_path = volume_path_template
        return volume_path

    def _get_local_volume_path_template(self, volume):
        local_dir = self._local_volume_dir(volume)
        local_path_template = os.path.join(local_dir, volume['name'])
        return local_path_template

    def _lookup_local_volume_path(self, volume_path_template):
        for ext in ['', self._DISK_FORMAT_VHD, self._DISK_FORMAT_VHDX]:
            volume_path = (volume_path_template + '.' + ext
                           if ext else volume_path_template)
            if os.path.exists(volume_path):
                return volume_path

    def _local_path_volume_info(self, volume):
        return '%s%s' % (self.local_path(volume), '.info')

    def _get_new_snap_path(self, snapshot):
        vol_path = self.local_path(snapshot['volume'])
        snap_path, ext = os.path.splitext(vol_path)
        snap_path += '.' + snapshot['id'] + ext
        return snap_path

    def get_volume_format(self, volume, qemu_format=False):
        volume_path_template = self._get_local_volume_path_template(volume)
        volume_path = self._lookup_local_volume_path(volume_path_template)

        if volume_path:
            info = self._qemu_img_info(volume_path, volume['name'])
            volume_format = info.file_format
        else:
            volume_format = (
                self._get_volume_format_spec(volume) or
                self.configuration.smbfs_default_volume_format)

        if qemu_format and volume_format == self._DISK_FORMAT_VHD:
            volume_format = self._DISK_FORMAT_VHD_LEGACY
        elif volume_format == self._DISK_FORMAT_VHD_LEGACY:
            volume_format = self._DISK_FORMAT_VHD

        return volume_format

    @remotefs_drv.locked_volume_id_operation
    @update_allocation_data(delete=True)
    def delete_volume(self, volume):
        """Deletes a logical volume."""
        if not volume['provider_location']:
            LOG.warning(_LW('Volume %s does not have provider_location '
                            'specified, skipping.'), volume['name'])
            return

        self._ensure_share_mounted(volume['provider_location'])
        volume_dir = self._local_volume_dir(volume)
        mounted_path = os.path.join(volume_dir,
                                    self.get_active_image_from_info(volume))
        if os.path.exists(mounted_path):
            self._delete(mounted_path)
        else:
            LOG.debug("Skipping deletion of volume %s as it does not exist.",
                      mounted_path)

        info_path = self._local_path_volume_info(volume)
        self._delete(info_path)

    def _create_windows_image(self, volume_path, volume_size, volume_format):
        """Creates a VHD or VHDX file of a given size."""
        # vhd is regarded as vpc by qemu
        if volume_format == self._DISK_FORMAT_VHD:
            volume_format = self._DISK_FORMAT_VHD_LEGACY

        self._execute('qemu-img', 'create', '-f', volume_format,
                      volume_path, str(volume_size * units.Gi),
                      run_as_root=True)

    @remotefs_drv.locked_volume_id_operation
    @update_allocation_data()
    def create_volume(self, volume):
        return super(SmbfsDriver, self).create_volume(volume)

    def _do_create_volume(self, volume):
        """Create a volume on given smbfs_share.

        :param volume: volume reference
        """
        volume_format = self.get_volume_format(volume)
        volume_path = self.local_path(volume)
        volume_size = volume['size']

        LOG.debug("Creating new volume at %s.", volume_path)

        if os.path.exists(volume_path):
            msg = _('File already exists at %s.') % volume_path
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        if volume_format in (self._DISK_FORMAT_VHD, self._DISK_FORMAT_VHDX):
            self._create_windows_image(volume_path, volume_size,
                                       volume_format)
        else:
            self.img_suffix = None
            if volume_format == self._DISK_FORMAT_QCOW2:
                self._create_qcow2_file(volume_path, volume_size)
            elif self.configuration.smbfs_sparsed_volumes:
                self._create_sparsed_file(volume_path, volume_size)
            else:
                self._create_regular_file(volume_path, volume_size)

        self._set_rw_permissions_for_all(volume_path)

    def _get_capacity_info(self, smbfs_share):
        """Calculate available space on the SMBFS share.

        :param smbfs_share: example //172.18.194.100/share
        """

        mount_point = self._get_mount_point_for_share(smbfs_share)

        df, _ = self._execute('stat', '-f', '-c', '%S %b %a', mount_point,
                              run_as_root=True)
        block_size, blocks_total, blocks_avail = map(float, df.split())
        total_available = block_size * blocks_avail
        total_size = block_size * blocks_total

        total_allocated = self._get_total_allocated(smbfs_share)
        return total_size, total_available, total_allocated

    def _find_share(self, volume_size_in_gib):
        """Choose SMBFS share among available ones for given volume size.

        For instances with more than one share that meets the criteria, the
        share with the least "allocated" space will be selected.

        :param volume_size_in_gib: int size in GB
        """

        if not self._mounted_shares:
            raise exception.SmbfsNoSharesMounted()

        target_share = None
        target_share_reserved = 0

        for smbfs_share in self._mounted_shares:
            if not self._is_share_eligible(smbfs_share, volume_size_in_gib):
                continue
            total_allocated = self._get_total_allocated(smbfs_share)
            if target_share is not None:
                if target_share_reserved > total_allocated:
                    target_share = smbfs_share
                    target_share_reserved = total_allocated
            else:
                target_share = smbfs_share
                target_share_reserved = total_allocated

        if target_share is None:
            raise exception.SmbfsNoSuitableShareFound(
                volume_size=volume_size_in_gib)

        LOG.debug('Selected %s as target smbfs share.', target_share)

        return target_share

    def _is_share_eligible(self, smbfs_share, volume_size_in_gib):
        """Verifies SMBFS share is eligible to host volume with given size.

        First validation step: ratio of actual space (used_space / total_space)
        is less than 'smbfs_used_ratio'. Second validation step: apparent space
        allocated (differs from actual space used when using sparse files)
        and compares the apparent available
        space (total_available * smbfs_oversub_ratio) to ensure enough space is
        available for the new volume.

        :param smbfs_share: smbfs share
        :param volume_size_in_gib: int size in GB
        """

        used_ratio = self.configuration.smbfs_used_ratio
        oversub_ratio = self.configuration.smbfs_oversub_ratio
        requested_volume_size = volume_size_in_gib * units.Gi

        total_size, total_available, total_allocated = \
            self._get_capacity_info(smbfs_share)

        apparent_size = max(0, total_size * oversub_ratio)
        apparent_available = max(0, apparent_size - total_allocated)
        used = (total_size - total_available) / total_size

        if used > used_ratio:
            LOG.debug('%s is above smbfs_used_ratio.', smbfs_share)
            return False
        if apparent_available <= requested_volume_size:
            LOG.debug('%s is above smbfs_oversub_ratio.', smbfs_share)
            return False
        if total_allocated / total_size >= oversub_ratio:
            LOG.debug('%s reserved space is above smbfs_oversub_ratio.',
                      smbfs_share)
            return False
        return True

    def _create_snapshot_online(self, snapshot, backing_filename,
                                new_snap_path):
        msg = _("This driver does not support snapshotting in-use volumes.")
        raise exception.SmbfsException(msg)

    def _delete_snapshot_online(self, context, snapshot, info):
        msg = _("This driver does not support deleting in-use snapshots.")
        raise exception.SmbfsException(msg)

    def _do_create_snapshot(self, snapshot, backing_filename, new_snap_path):
        self._check_snapshot_support(snapshot)
        super(SmbfsDriver, self)._do_create_snapshot(
            snapshot, backing_filename, new_snap_path)

    def _check_snapshot_support(self, snapshot):
        volume_format = self.get_volume_format(snapshot['volume'])
        # qemu-img does not yet support differencing vhd/vhdx
        if volume_format in (self._DISK_FORMAT_VHD, self._DISK_FORMAT_VHDX):
            err_msg = _("Snapshots are not supported for this volume "
                        "format: %s") % volume_format
            raise exception.InvalidVolume(err_msg)

    @remotefs_drv.locked_volume_id_operation
    @update_allocation_data()
    def extend_volume(self, volume, size_gb):
        LOG.info(_LI('Extending volume %s.'), volume['id'])
        self._extend_volume(volume, size_gb)

    def _extend_volume(self, volume, size_gb):
        volume_path = self.local_path(volume)

        self._check_extend_volume_support(volume, size_gb)
        LOG.info(_LI('Resizing file to %sG...'), size_gb)

        self._do_extend_volume(volume_path, size_gb, volume['name'])

    def _do_extend_volume(self, volume_path, size_gb, volume_name):
        info = self._qemu_img_info(volume_path, volume_name)
        fmt = info.file_format

        # Note(lpetrut): as for version 2.0, qemu-img cannot resize
        # vhd/x images. For the moment, we'll just use an intermediary
        # conversion in order to be able to do the resize.
        if fmt in (self._DISK_FORMAT_VHDX, self._DISK_FORMAT_VHD_LEGACY):
            temp_image = volume_path + '.tmp'
            image_utils.convert_image(volume_path, temp_image,
                                      self._DISK_FORMAT_RAW)
            image_utils.resize_image(temp_image, size_gb)
            image_utils.convert_image(temp_image, volume_path, fmt)
            self._delete(temp_image)
        else:
            image_utils.resize_image(volume_path, size_gb)

        if not self._is_file_size_equal(volume_path, size_gb):
            raise exception.ExtendVolumeError(
                reason='Resizing image file failed.')

    def _check_extend_volume_support(self, volume, size_gb):
        volume_path = self.local_path(volume)
        active_file = self.get_active_image_from_info(volume)
        active_file_path = os.path.join(self._local_volume_dir(volume),
                                        active_file)

        if active_file_path != volume_path:
            msg = _('Extend volume is only supported for this '
                    'driver when no snapshots exist.')
            raise exception.InvalidVolume(msg)

        extend_by = int(size_gb) - volume['size']
        if not self._is_share_eligible(volume['provider_location'],
                                       extend_by):
            raise exception.ExtendVolumeError(reason='Insufficient space to '
                                              'extend volume %s to %sG.'
                                              % (volume['id'], size_gb))

    @remotefs_drv.locked_volume_id_operation
    @update_allocation_data()
    def create_volume_from_snapshot(self, volume, snapshot):
        return self._create_volume_from_snapshot(volume, snapshot)

    def _copy_volume_from_snapshot(self, snapshot, volume, volume_size):
        """Copy data from snapshot to destination volume.

        This is done with a qemu-img convert to raw/qcow2 from the snapshot
        qcow2.
        """

        LOG.debug("Snapshot: %(snap)s, volume: %(vol)s, "
                  "volume_size: %(size)s",
                  {'snap': snapshot['id'],
                   'vol': volume['id'],
                   'size': volume_size})

        info_path = self._local_path_volume_info(snapshot['volume'])
        snap_info = self._read_info_file(info_path)
        vol_dir = self._local_volume_dir(snapshot['volume'])
        out_format = self.get_volume_format(volume, qemu_format=True)

        forward_file = snap_info[snapshot['id']]
        forward_path = os.path.join(vol_dir, forward_file)

        # Find the file which backs this file, which represents the point
        # when this snapshot was created.
        img_info = self._qemu_img_info(forward_path,
                                       snapshot['volume']['name'])
        path_to_snap_img = os.path.join(vol_dir, img_info.backing_file)

        LOG.debug("Will copy from snapshot at %s", path_to_snap_img)

        image_utils.convert_image(path_to_snap_img,
                                  self.local_path(volume),
                                  out_format)
        self._extend_volume(volume, volume_size)

        self._set_rw_permissions_for_all(self.local_path(volume))

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        volume_format = self.get_volume_format(volume, qemu_format=True)

        image_utils.fetch_to_volume_format(
            context, image_service, image_id,
            self.local_path(volume), volume_format,
            self.configuration.volume_dd_blocksize)

        self._do_extend_volume(self.local_path(volume),
                               volume['size'],
                               volume['name'])

        data = image_utils.qemu_img_info(self.local_path(volume))
        virt_size = data.virtual_size / units.Gi
        if virt_size != volume['size']:
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=(_("Expected volume size was %d") % volume['size'])
                + (_(" but size is now %d.") % virt_size))

    @remotefs_drv.locked_volume_id_operation
    @update_allocation_data()
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        return self._create_cloned_volume(volume, src_vref)

    def _ensure_share_mounted(self, smbfs_share):
        mnt_flags = []
        if self.shares.get(smbfs_share) is not None:
            mnt_flags = self.shares[smbfs_share]
            # The domain name must be removed from the
            # user name when using Samba.
            mnt_flags = self.parse_credentials(mnt_flags).split()
        self._remotefsclient.mount(smbfs_share, mnt_flags)

    def parse_options(self, option_str):
        opts_dict = {}
        opts_list = []
        if option_str:
            for i in option_str.split():
                if i == '-o':
                    continue
                for j in i.split(','):
                    tmp_opt = j.split('=')
                    if len(tmp_opt) > 1:
                        opts_dict[tmp_opt[0]] = tmp_opt[1]
                    else:
                        opts_list.append(tmp_opt[0])
        return opts_list, opts_dict

    def parse_credentials(self, mnt_flags):
        options_list, options_dict = self.parse_options(mnt_flags)
        username = (options_dict.pop('user', None) or
                    options_dict.pop('username', None))
        if username:
            # Remove the Domain from the user name
            options_dict['username'] = username.split('\\')[-1]
        else:
            options_dict['username'] = 'guest'
        named_options = ','.join("%s=%s" % (key, val) for (key, val)
                                 in options_dict.items())
        options_list = ','.join(options_list)
        flags = '-o ' + ','.join([named_options, options_list])

        return flags.strip(',')

    def _get_volume_format_spec(self, volume):
        extra_specs = []

        metadata_specs = volume.get('volume_metadata') or []
        extra_specs += metadata_specs

        vol_type = volume.get('volume_type')
        if vol_type:
            volume_type_specs = vol_type.get('extra_specs') or []
            extra_specs += volume_type_specs

        for spec in extra_specs:
            if 'volume_format' in spec.key:
                return spec.value
        return None

    def _is_file_size_equal(self, path, size):
        """Checks if file size at path is equal to size."""
        data = image_utils.qemu_img_info(path)
        virt_size = data.virtual_size / units.Gi
        return virt_size == size
