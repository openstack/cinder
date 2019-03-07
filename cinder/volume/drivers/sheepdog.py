#    Copyright 2012 OpenStack Foundation
#    Copyright (c) 2013 Zelin.io
#    Copyright (C) 2015 Nippon Telegraph and Telephone Corporation.
#    All Rights Reserved.
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
SheepDog Volume Driver.

"""
import errno
import eventlet
import io
import random
import re

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver


LOG = logging.getLogger(__name__)

sheepdog_opts = [
    cfg.StrOpt('sheepdog_store_address',
               default='127.0.0.1',
               help=('IP address of sheep daemon.')),
    cfg.PortOpt('sheepdog_store_port',
                default=7000,
                help=('Port of sheep daemon.'))
]

CONF = cfg.CONF
CONF.import_opt("image_conversion_dir", "cinder.image.image_utils")
CONF.register_opts(sheepdog_opts, group=configuration.SHARED_CONF_GROUP)


class SheepdogClient(object):
    """Sheepdog command executor."""

    QEMU_SHEEPDOG_PREFIX = 'sheepdog:'
    DOG_RESP_CONNECTION_ERROR = 'failed to connect to'
    DOG_RESP_CLUSTER_RUNNING = 'Cluster status: running'
    DOG_RESP_CLUSTER_NOT_FORMATTED = ('Cluster status: '
                                      'Waiting for cluster to be formatted')
    DOG_RESP_CLUSTER_WAITING = ('Cluster status: '
                                'Waiting for other nodes to join cluster')
    DOG_RESP_VDI_ALREADY_EXISTS = ': VDI exists already'
    DOG_RESP_VDI_NOT_FOUND = ': No VDI found'
    DOG_RESP_VDI_SHRINK_NOT_SUPPORT = 'Shrinking VDIs is not implemented'
    DOG_RESP_VDI_SIZE_TOO_LARGE = 'New VDI size is too large'
    DOG_RESP_SNAPSHOT_VDI_NOT_FOUND = ': No VDI found'
    DOG_RESP_SNAPSHOT_NOT_FOUND = ': Failed to find requested tag'
    DOG_RESP_SNAPSHOT_EXISTED = 'tag (%(snapname)s) is existed'
    QEMU_IMG_RESP_CONNECTION_ERROR = ('Failed to connect socket: '
                                      'Connection refused')
    QEMU_IMG_RESP_ALREADY_EXISTS = ': VDI exists already'
    QEMU_IMG_RESP_SNAPSHOT_NOT_FOUND = 'Failed to find the requested tag'
    QEMU_IMG_RESP_VDI_NOT_FOUND = 'No vdi found'
    QEMU_IMG_RESP_SIZE_TOO_LARGE = 'An image is too large.'

    def __init__(self, node_list, port):
        self.node_list = node_list
        self.port = port

    def get_addr(self):
        """Get a random node in sheepdog cluster."""
        return self.node_list[random.randint(0, len(self.node_list) - 1)]

    def local_path(self, volume):
        """Return a sheepdog location path."""
        return "sheepdog:%(addr)s:%(port)s:%(name)s" % {
            'addr': self.get_addr(),
            'port': self.port,
            'name': volume['name']}

    def _run_dog(self, command, subcommand, *params):
        """Execute dog command wrapper."""
        addr = self.get_addr()
        cmd = ('env', 'LC_ALL=C', 'LANG=C', 'dog', command, subcommand,
               '-a', addr, '-p', self.port) + params
        try:
            (_stdout, _stderr) = utils.execute(*cmd)
            if _stderr.startswith(self.DOG_RESP_CONNECTION_ERROR):
                # NOTE(tishizaki)
                # Dog command does not return error_code although
                # dog command cannot connect to sheep process.
                # That is a Sheepdog's bug.
                # To avoid a Sheepdog's bug, now we need to check stderr.
                # If Sheepdog has been fixed, this check logic is needed
                # by old Sheepdog users.
                reason = (_('Failed to connect to sheep daemon. '
                          'addr: %(addr)s, port: %(port)s'),
                          {'addr': addr, 'port': self.port})
                raise exception.SheepdogError(reason=reason)
            return (_stdout, _stderr)
        except OSError as e:
            with excutils.save_and_reraise_exception():
                if e.errno == errno.ENOENT:
                    msg = 'Sheepdog is not installed. OSError: command is %s.'
                else:
                    msg = 'OSError: command is %s.'
                LOG.error(msg, cmd)
        except processutils.ProcessExecutionError as e:
            _stderr = e.stderr
            if _stderr.startswith(self.DOG_RESP_CONNECTION_ERROR):
                reason = (_('Failed to connect to sheep daemon. '
                          'addr: %(addr)s, port: %(port)s'),
                          {'addr': addr, 'port': self.port})
                raise exception.SheepdogError(reason=reason)
            raise exception.SheepdogCmdError(
                cmd=e.cmd,
                exit_code=e.exit_code,
                stdout=e.stdout.replace('\n', '\\n'),
                stderr=e.stderr.replace('\n', '\\n'))

    def _run_qemu_img(self, command, *params):
        """Executes qemu-img command wrapper."""
        addr = self.get_addr()
        cmd = ['env', 'LC_ALL=C', 'LANG=C', 'qemu-img', command]
        for param in params:
            if param.startswith(self.QEMU_SHEEPDOG_PREFIX):
                # replace 'sheepdog:vdiname[:snapshotname]' to
                #         'sheepdog:addr:port:vdiname[:snapshotname]'
                param = param.replace(self.QEMU_SHEEPDOG_PREFIX,
                                      '%(prefix)s%(addr)s:%(port)s:' %
                                      {'prefix': self.QEMU_SHEEPDOG_PREFIX,
                                       'addr': addr, 'port': self.port},
                                      1)
            cmd.append(param)
        try:
            return utils.execute(*cmd)
        except OSError as e:
            with excutils.save_and_reraise_exception():
                if e.errno == errno.ENOENT:
                    msg = ('Qemu-img is not installed. OSError: command is '
                           '%(cmd)s.')
                else:
                    msg = 'OSError: command is %(cmd)s.'
                LOG.error(msg, {'cmd': tuple(cmd)})
        except processutils.ProcessExecutionError as e:
            _stderr = e.stderr
            if self.QEMU_IMG_RESP_CONNECTION_ERROR in _stderr:
                reason = (_('Failed to connect to sheep daemon. '
                            'addr: %(addr)s, port: %(port)s'),
                          {'addr': addr, 'port': self.port})
                raise exception.SheepdogError(reason=reason)
            raise exception.SheepdogCmdError(
                cmd=e.cmd,
                exit_code=e.exit_code,
                stdout=e.stdout.replace('\n', '\\n'),
                stderr=e.stderr.replace('\n', '\\n'))

    def check_cluster_status(self):
        try:
            (_stdout, _stderr) = self._run_dog('cluster', 'info')
        except exception.SheepdogCmdError as e:
            cmd = e.kwargs['cmd']
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to check cluster status.'
                          '(command: %s)', cmd)

        if _stdout.startswith(self.DOG_RESP_CLUSTER_RUNNING):
            LOG.debug('Sheepdog cluster is running.')
            return

        reason = _('Invalid sheepdog cluster status.')
        if _stdout.startswith(self.DOG_RESP_CLUSTER_NOT_FORMATTED):
            reason = _('Cluster is not formatted. '
                       'You should probably perform "dog cluster format".')
        elif _stdout.startswith(self.DOG_RESP_CLUSTER_WAITING):
            reason = _('Waiting for all nodes to join cluster. '
                       'Ensure all sheep daemons are running.')
        raise exception.SheepdogError(reason=reason)

    def create(self, vdiname, size):
        try:
            self._run_dog('vdi', 'create', vdiname, '%sG' % size)
        except exception.SheepdogCmdError as e:
            _stderr = e.kwargs['stderr']
            with excutils.save_and_reraise_exception():
                if _stderr.rstrip('\\n').endswith(
                        self.DOG_RESP_VDI_ALREADY_EXISTS):
                    LOG.error('Volume already exists. %s', vdiname)
                else:
                    LOG.error('Failed to create volume. %s', vdiname)

    def delete(self, vdiname):
        try:
            (_stdout, _stderr) = self._run_dog('vdi', 'delete', vdiname)
            if _stderr.rstrip().endswith(self.DOG_RESP_VDI_NOT_FOUND):
                LOG.warning('Volume not found. %s', vdiname)
        except exception.SheepdogCmdError as e:
            _stderr = e.kwargs['stderr']
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to delete volume. %s', vdiname)

    def create_snapshot(self, vdiname, snapname):
        try:
            self._run_dog('vdi', 'snapshot', '-s', snapname, vdiname)
        except exception.SheepdogCmdError as e:
            cmd = e.kwargs['cmd']
            _stderr = e.kwargs['stderr']
            with excutils.save_and_reraise_exception():
                if _stderr.rstrip('\\n').endswith(
                        self.DOG_RESP_SNAPSHOT_VDI_NOT_FOUND):
                    LOG.error('Volume "%s" not found. Please check the '
                              'results of "dog vdi list".',
                              vdiname)
                elif _stderr.rstrip('\\n').endswith(
                        self.DOG_RESP_SNAPSHOT_EXISTED %
                        {'snapname': snapname}):
                    LOG.error('Snapshot "%s" already exists.', snapname)
                else:
                    LOG.error('Failed to create snapshot. (command: %s)',
                              cmd)

    def delete_snapshot(self, vdiname, snapname):
        try:
            (_stdout, _stderr) = self._run_dog('vdi', 'delete', '-s',
                                               snapname, vdiname)
            if _stderr.rstrip().endswith(self.DOG_RESP_SNAPSHOT_NOT_FOUND):
                LOG.warning('Snapshot "%s" not found.', snapname)
            elif _stderr.rstrip().endswith(self.DOG_RESP_VDI_NOT_FOUND):
                LOG.warning('Volume "%s" not found.', vdiname)
        except exception.SheepdogCmdError as e:
            cmd = e.kwargs['cmd']
            _stderr = e.kwargs['stderr']
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to delete snapshot. (command: %s)',
                          cmd)

    def clone(self, src_vdiname, src_snapname, dst_vdiname, size):
        try:
            self._run_qemu_img('create', '-b',
                               'sheepdog:%(src_vdiname)s:%(src_snapname)s' %
                               {'src_vdiname': src_vdiname,
                                'src_snapname': src_snapname},
                               'sheepdog:%s' % dst_vdiname, '%sG' % size)
        except exception.SheepdogCmdError as e:
            cmd = e.kwargs['cmd']
            _stderr = e.kwargs['stderr']
            with excutils.save_and_reraise_exception():
                if self.QEMU_IMG_RESP_ALREADY_EXISTS in _stderr:
                    LOG.error('Clone volume "%s" already exists. '
                              'Please check the results of "dog vdi list".',
                              dst_vdiname)
                elif self.QEMU_IMG_RESP_VDI_NOT_FOUND in _stderr:
                    LOG.error('Src Volume "%s" not found. '
                              'Please check the results of "dog vdi list".',
                              src_vdiname)
                elif self.QEMU_IMG_RESP_SNAPSHOT_NOT_FOUND in _stderr:
                    LOG.error('Snapshot "%s" not found. '
                              'Please check the results of "dog vdi list".',
                              src_snapname)
                elif self.QEMU_IMG_RESP_SIZE_TOO_LARGE in _stderr:
                    LOG.error('Volume size "%sG" is too large.', size)
                else:
                    LOG.error('Failed to clone volume.(command: %s)', cmd)

    def resize(self, vdiname, size):
        size = int(size) * units.Gi
        try:
            (_stdout, _stderr) = self._run_dog('vdi', 'resize', vdiname, size)
        except exception.SheepdogCmdError as e:
            _stderr = e.kwargs['stderr']
            with excutils.save_and_reraise_exception():
                if _stderr.rstrip('\\n').endswith(
                        self.DOG_RESP_VDI_NOT_FOUND):
                    LOG.error('Failed to resize vdi. vdi not found. %s',
                              vdiname)
                elif _stderr.startswith(self.DOG_RESP_VDI_SHRINK_NOT_SUPPORT):
                    LOG.error('Failed to resize vdi. '
                              'Shrinking vdi not supported. '
                              'vdi: %(vdiname)s new size: %(size)s',
                              {'vdiname': vdiname, 'size': size})
                elif _stderr.startswith(self.DOG_RESP_VDI_SIZE_TOO_LARGE):
                    LOG.error('Failed to resize vdi. '
                              'Too large volume size. '
                              'vdi: %(vdiname)s new size: %(size)s',
                              {'vdiname': vdiname, 'size': size})
                else:
                    LOG.error('Failed to resize vdi. '
                              'vdi: %(vdiname)s new size: %(size)s',
                              {'vdiname': vdiname, 'size': size})

    def get_volume_stats(self):
        try:
            (_stdout, _stderr) = self._run_dog('node', 'info', '-r')
        except exception.SheepdogCmdError as e:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to get volume status. %s', e)
        return _stdout

    def get_vdi_info(self, vdiname):
        # Get info of the specified vdi.
        try:
            (_stdout, _stderr) = self._run_dog('vdi', 'list', vdiname, '-r')
        except exception.SheepdogCmdError as e:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to get vdi info. %s', e)
        return _stdout

    def update_node_list(self):
        try:
            (_stdout, _stderr) = self._run_dog('node', 'list', '-r')
        except exception.SheepdogCmdError as e:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to get node list. %s', e)
        node_list = []
        stdout = _stdout.strip('\n')
        for line in stdout.split('\n'):
            node_list.append(line.split()[1].split(':')[0])
        self.node_list = node_list


class SheepdogIOWrapper(io.RawIOBase):
    """File-like object with Sheepdog backend."""

    def __init__(self, addr, port, volume, snapshot_name=None):
        self._addr = addr
        self._port = port
        self._vdiname = volume['name']
        self._snapshot_name = snapshot_name
        self._offset = 0
        # SheepdogIOWrapper instance becomes invalid if a write error occurs.
        self._valid = True

    def _execute(self, cmd, data=None):
        try:
            # NOTE(yamada-h): processutils.execute causes busy waiting
            # under eventlet.
            # To avoid wasting CPU resources, it should not be used for
            # the command which takes long time to execute.
            # For workaround, we replace a subprocess module with
            # the original one while only executing a read/write command.
            _processutils_subprocess = processutils.subprocess
            processutils.subprocess = eventlet.patcher.original('subprocess')
            return processutils.execute(*cmd, process_input=data)[0]
        except (processutils.ProcessExecutionError, OSError):
            self._valid = False
            msg = _('Sheepdog I/O Error, command was: "%s".') % ' '.join(cmd)
            raise exception.VolumeDriverException(message=msg)
        finally:
            processutils.subprocess = _processutils_subprocess

    def read(self, length=None):
        if not self._valid:
            msg = _('An error occurred while reading volume "%s".'
                    ) % self._vdiname
            raise exception.VolumeDriverException(message=msg)

        cmd = ['dog', 'vdi', 'read', '-a', self._addr, '-p', self._port]
        if self._snapshot_name:
            cmd.extend(('-s', self._snapshot_name))
        cmd.extend((self._vdiname, self._offset))
        if length:
            cmd.append(length)
        data = self._execute(cmd)
        self._offset += len(data)
        return data

    def write(self, data):
        if not self._valid:
            msg = _('An error occurred while writing to volume "%s".'
                    ) % self._vdiname
            raise exception.VolumeDriverException(message=msg)

        length = len(data)
        cmd = ('dog', 'vdi', 'write', '-a', self._addr, '-p', self._port,
               self._vdiname, self._offset, length)
        self._execute(cmd, data)
        self._offset += length
        return length

    def seek(self, offset, whence=0):
        if not self._valid:
            msg = _('An error occurred while seeking for volume "%s".'
                    ) % self._vdiname
            raise exception.VolumeDriverException(message=msg)

        if whence == 0:
            # SEEK_SET or 0 - start of the stream (the default);
            # offset should be zero or positive
            new_offset = offset
        elif whence == 1:
            # SEEK_CUR or 1 - current stream position; offset may be negative
            new_offset = self._offset + offset
        else:
            # SEEK_END or 2 - end of the stream; offset is usually negative
            # TODO(yamada-h): Support SEEK_END
            raise IOError(_("Invalid argument - whence=%s not supported.") %
                          whence)

        if new_offset < 0:
            raise IOError(_("Invalid argument - negative seek offset."))

        self._offset = new_offset

    def tell(self):
        return self._offset

    def flush(self):
        pass

    def fileno(self):
        """Sheepdog does not have support for fileno so we raise IOError.

        Raising IOError is recommended way to notify caller that interface is
        not supported - see http://docs.python.org/2/library/io.html#io.IOBase
        """
        raise IOError(_("fileno is not supported by SheepdogIOWrapper"))


@interface.volumedriver
class SheepdogDriver(driver.VolumeDriver):
    """Executes commands relating to Sheepdog Volumes."""

    VERSION = "1.0.0"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Cinder_Jenkins"

    def __init__(self, *args, **kwargs):
        super(SheepdogDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(sheepdog_opts)
        addr = self.configuration.sheepdog_store_address
        self.port = self.configuration.sheepdog_store_port
        self.stats_pattern = re.compile(r'[\w\s%]*Total\s(\d+)\s(\d+)*')
        self._stats = {}
        self.node_list = [addr]
        self.client = SheepdogClient(self.node_list, self.port)

    @staticmethod
    def get_driver_options():
        return sheepdog_opts

    def check_for_setup_error(self):
        """Check cluster status and update node list."""
        self.client.check_cluster_status()
        self.client.update_node_list()

    def _is_cloneable(self, image_location, image_meta):
        """Check the image can be clone or not."""
        if image_location is None:
            return False

        prefix = 'sheepdog://'
        if not image_location.startswith(prefix):
            LOG.debug("Image is not stored in sheepdog.")
            return False

        if image_meta['disk_format'] != 'raw':
            LOG.debug("Image clone requires image format to be "
                      "'raw' but image %s(%s) is '%s'.",
                      image_location,
                      image_meta['id'],
                      image_meta['disk_format'])
            return False

        # check whether volume is stored in sheepdog
        # The image location would be like
        # "sheepdog://192.168.10.2:7000:Alice"
        (ip, port, name) = image_location[len(prefix):].split(":", 2)

        stdout = self.client.get_vdi_info(name)
        # Dog command return 0 and has a null output if the volume not exists
        if stdout:
            return True
        else:
            LOG.debug("Can not find vdi %(image)s, is not cloneable",
                      {'image': name})
            return False

    def clone_image(self, context, volume,
                    image_location, image_meta,
                    image_service):
        """Create a volume efficiently from an existing image."""
        image_location = image_location[0] if image_location else None
        if not self._is_cloneable(image_location, image_meta):
            return {}, False

        volume_ref = {'name': image_meta['id'], 'size': image_meta['size']}
        self.create_cloned_volume(volume, volume_ref)
        self.client.resize(volume.name, volume.size)

        vol_path = self.client.local_path(volume)
        return {'provider_location': vol_path}, True

    def create_cloned_volume(self, volume, src_vref):
        """Clone a sheepdog volume from another volume."""
        snapshot_name = 'tmp-snap-%s-%s' % (src_vref['name'], volume.id)
        snapshot = {
            'name': snapshot_name,
            'volume_name': src_vref['name'],
            'volume_size': src_vref['size'],
        }

        self.client.create_snapshot(snapshot['volume_name'], snapshot_name)

        try:
            self.client.clone(snapshot['volume_name'], snapshot_name,
                              volume.name, volume.size)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to create cloned volume %s.',
                          volume.name)
        finally:
            # Delete temp Snapshot
            self.client.delete_snapshot(snapshot['volume_name'], snapshot_name)

    def create_volume(self, volume):
        """Create a sheepdog volume."""
        self.client.create(volume.name, volume.size)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a sheepdog volume from a snapshot."""
        self.client.clone(snapshot.volume_name, snapshot.name,
                          volume.name, volume.size)

    def delete_volume(self, volume):
        """Delete a logical volume."""
        self.client.delete(volume.name)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        with image_utils.temporary_file() as tmp:
            # (wenhao): we don't need to convert to raw for sheepdog.
            image_utils.fetch_verify_image(context, image_service,
                                           image_id, tmp)

            # remove the image created by import before this function.
            # see volume/drivers/manager.py:_create_volume
            self.client.delete(volume.name)
            # convert and store into sheepdog
            image_utils.convert_image(tmp, self.client.local_path(volume),
                                      'raw')
            self.client.resize(volume.name, volume.size)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        image_id = image_meta['id']
        with image_utils.temporary_file() as tmp:
            # image_utils.convert_image doesn't support "sheepdog:" source,
            # so we use the qemu-img directly.
            # Sheepdog volume is always raw-formatted.
            cmd = ('qemu-img',
                   'convert',
                   '-f', 'raw',
                   '-t', 'none',
                   '-O', 'raw',
                   self.client.local_path(volume),
                   tmp)
            self._try_execute(*cmd)

            with open(tmp, 'rb') as image_file:
                image_service.update(context, image_id, {}, image_file)

    def create_snapshot(self, snapshot):
        """Create a sheepdog snapshot."""
        self.client.create_snapshot(snapshot.volume_name, snapshot.name)

    def delete_snapshot(self, snapshot):
        """Delete a sheepdog snapshot."""
        self.client.delete_snapshot(snapshot.volume_name, snapshot.name)

    def ensure_export(self, context, volume):
        """Safely and synchronously recreate an export for a logical volume."""
        pass

    def create_export(self, context, volume, connector):
        """Export a volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a logical volume."""
        pass

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'sheepdog',
            'data': {
                'name': volume['name'],
                'hosts': [self.client.get_addr()],
                'ports': ["%d" % self.port],
            }
        }

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def _update_volume_stats(self):
        stats = {}

        backend_name = "sheepdog"
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        stats["volume_backend_name"] = backend_name or 'sheepdog'
        stats['vendor_name'] = 'Open Source'
        stats['driver_version'] = self.VERSION
        stats['storage_protocol'] = 'sheepdog'
        stats['total_capacity_gb'] = 'unknown'
        stats['free_capacity_gb'] = 'unknown'
        stats['reserved_percentage'] = 0
        stats['QoS_support'] = False

        stdout = self.client.get_volume_stats()
        m = self.stats_pattern.match(stdout)
        total = float(m.group(1))
        used = float(m.group(2))
        stats['total_capacity_gb'] = total / units.Gi
        stats['free_capacity_gb'] = (total - used) / units.Gi

        self._stats = stats

    def get_volume_stats(self, refresh=False):
        if refresh:
            self._update_volume_stats()
        return self._stats

    def extend_volume(self, volume, new_size):
        """Extend an Existing Volume."""
        self.client.resize(volume.name, new_size)
        LOG.debug('Extend volume from %(old_size)s GB to %(new_size)s GB.',
                  {'old_size': volume.size, 'new_size': new_size})
