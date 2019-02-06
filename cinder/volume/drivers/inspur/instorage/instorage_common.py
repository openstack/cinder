# Copyright 2017 Inspur Corp.
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
#

import math
import random
import re
import time
import unicodedata

from eventlet import greenthread
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils as json
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import strutils
from oslo_utils import units
import paramiko
import six

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder import ssh_utils
from cinder import utils as cinder_utils
from cinder.volume import driver
from cinder.volume.drivers.inspur.instorage import (
    replication as instorage_rep)
from cinder.volume.drivers.inspur.instorage import instorage_const
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume import utils
from cinder.volume import volume_types

INTERVAL_1_SEC = 1
DEFAULT_TIMEOUT = 20
LOG = logging.getLogger(__name__)

instorage_mcs_opts = [
    cfg.BoolOpt('instorage_mcs_vol_autoexpand',
                default=True,
                help='Storage system autoexpand parameter for volumes '
                     '(True/False)'),
    cfg.BoolOpt('instorage_mcs_vol_compression',
                default=False,
                help='Storage system compression option for volumes'),
    cfg.BoolOpt('instorage_mcs_vol_intier',
                default=True,
                help='Enable InTier for volumes'),
    cfg.BoolOpt('instorage_mcs_allow_tenant_qos',
                default=False,
                help='Allow tenants to specify QOS on create'),
    cfg.IntOpt('instorage_mcs_vol_grainsize',
               default=256,
               min=32, max=256,
               help='Storage system grain size parameter for volumes '
                    '(32/64/128/256)'),
    cfg.IntOpt('instorage_mcs_vol_rsize',
               default=2,
               min=-1, max=100,
               help='Storage system space-efficiency parameter for volumes '
                    '(percentage)'),
    cfg.IntOpt('instorage_mcs_vol_warning',
               default=0,
               min=-1, max=100,
               help='Storage system threshold for volume capacity warnings '
                    '(percentage)'),
    cfg.IntOpt('instorage_mcs_localcopy_timeout',
               default=120,
               min=1, max=600,
               help='Maximum number of seconds to wait for LocalCopy to be '
                    'prepared.'),
    cfg.IntOpt('instorage_mcs_localcopy_rate',
               default=50,
               min=1, max=100,
               help='Specifies the InStorage LocalCopy copy rate to be used '
               'when creating a full volume copy. The default is rate '
               'is 50, and the valid rates are 1-100.'),
    cfg.StrOpt('instorage_mcs_vol_iogrp',
               default='0',
               help='The I/O group in which to allocate volumes. It can be a '
               'comma-separated list in which case the driver will select an '
               'io_group based on least number of volumes associated with the '
               'io_group.'),
    cfg.StrOpt('instorage_san_secondary_ip',
               default=None,
               help='Specifies secondary management IP or hostname to be '
                    'used if san_ip is invalid or becomes inaccessible.'),
    cfg.ListOpt('instorage_mcs_volpool_name',
                default=['volpool'],
                help='Comma separated list of storage system storage '
                     'pools for volumes.'),
]

CONF = cfg.CONF
CONF.register_opts(instorage_mcs_opts)


class InStorageMCSCommonDriver(driver.VolumeDriver, san.SanDriver):
    """Inspur InStorage MCS abstract base class for iSCSI/FC volume drivers.

    Version history:

    .. code-block:: none

        1.0 - Initial driver
    """

    VERSION = "1.0.0"
    VDISKCOPYOPS_INTERVAL = 600
    DEFAULT_GR_SLEEP = random.randint(20, 500) / 100.0

    def __init__(self, *args, **kwargs):
        super(InStorageMCSCommonDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(instorage_mcs_opts)
        self._backend_name = self.configuration.safe_get('volume_backend_name')
        self.active_ip = self.configuration.san_ip
        self.inactive_ip = self.configuration.instorage_san_secondary_ip
        self._local_backend_assistant = InStorageAssistant(self._run_ssh)
        self._aux_backend_assistant = None
        self._assistant = self._local_backend_assistant
        self._vdiskcopyops = {}
        self._vdiskcopyops_loop = None
        self.protocol = None
        self.replication = None
        self._state = {'storage_nodes': {},
                       'enabled_protocols': set(),
                       'compression_enabled': False,
                       'available_iogrps': [],
                       'system_name': None,
                       'system_id': None,
                       'code_level': None,
                       }
        self._active_backend_id = kwargs.get('active_backend_id')

        # This dictionary is used to map each replication target to certain
        # replication manager object.
        self.replica_manager = {}

        # One driver can be configured with only one replication target
        # to failover.
        self._replica_target = {}

        # This boolean is used to indicate whether replication is supported
        # by this storage.
        self._replica_enabled = False

        # This list is used to save the supported replication modes.
        self._supported_replica_types = []

        # This is used to save the available pools in failed-over status
        self._secondary_pools = None

    @staticmethod
    def get_driver_options():
        return instorage_mcs_opts

    @cinder_utils.trace
    def do_setup(self, ctxt):
        """Check that we have all configuration details from the storage."""
        # InStorage has the limitation that can not burst more than 3 new ssh
        # connections within 1 second. So slow down the initialization.
        # however, this maybe removed later.
        greenthread.sleep(1)

        # Update the instorage state
        self._update_instorage_state()

        # v2.1 replication setup
        self._get_instorage_config()

        # Validate that the pool exists
        self._validate_pools_exist()

    def _update_instorage_state(self):
        # Get storage system name, id, and code level
        self._state.update(self._assistant.get_system_info())

        # Check if compression is supported
        self._state['compression_enabled'] = (self._assistant.
                                              compression_enabled())

        # Get the available I/O groups
        self._state['available_iogrps'] = (self._assistant.
                                           get_available_io_groups())

        # Get the iSCSI and FC names of the InStorage/MCS nodes
        self._state['storage_nodes'] = self._assistant.get_node_info()

        # Add the iSCSI IP addresses and WWPNs to the storage node info
        self._assistant.add_iscsi_ip_addrs(self._state['storage_nodes'])
        self._assistant.add_fc_wwpns(self._state['storage_nodes'])

        # For each node, check what connection modes it supports.  Delete any
        # nodes that do not support any types (may be partially configured).
        to_delete = []
        for k, node in self._state['storage_nodes'].items():
            if ((len(node['ipv4']) or len(node['ipv6'])) and
                    len(node['iscsi_name'])):
                node['enabled_protocols'].append('iSCSI')
                self._state['enabled_protocols'].add('iSCSI')
            if len(node['WWPN']):
                node['enabled_protocols'].append('FC')
                self._state['enabled_protocols'].add('FC')
            if not len(node['enabled_protocols']):
                to_delete.append(k)
        for delkey in to_delete:
            del self._state['storage_nodes'][delkey]

    def _get_backend_pools(self):
        if not self._active_backend_id:
            return self.configuration.instorage_mcs_volpool_name
        elif not self._secondary_pools:
            self._secondary_pools = [self._replica_target.get('pool_name')]
        return self._secondary_pools

    def _validate_pools_exist(self):
        # Validate that the pool exists
        pools = self._get_backend_pools()
        for pool in pools:
            try:
                self._assistant.get_pool_attrs(pool)
            except exception.VolumeBackendAPIException:
                msg = _('Failed getting details for pool %s.') % pool
                raise exception.InvalidInput(reason=msg)

    @cinder_utils.trace
    def check_for_setup_error(self):
        """Ensure that the flags are set properly."""

        # Check that we have the system ID information
        if self._state['system_name'] is None:
            exception_msg = _('Unable to determine system name.')
            raise exception.VolumeBackendAPIException(data=exception_msg)
        if self._state['system_id'] is None:
            exception_msg = _('Unable to determine system id.')
            raise exception.VolumeBackendAPIException(data=exception_msg)

        # Make sure we have at least one node configured
        if not len(self._state['storage_nodes']):
            msg = _('do_setup: No configured nodes.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        if self.protocol not in self._state['enabled_protocols']:
            raise exception.InvalidInput(
                reason=_('The storage device does not support %(prot)s. '
                         'Please configure the device to support %(prot)s or '
                         'switch to a driver using a different protocol.')
                % {'prot': self.protocol})

        required_flags = ['san_ip', 'san_ssh_port', 'san_login',
                          'instorage_mcs_volpool_name']
        for flag in required_flags:
            if not self.configuration.safe_get(flag):
                raise exception.InvalidInput(reason=_('%s is not set.') % flag)

        # Ensure that either password or keyfile were set
        if not (self.configuration.san_password or
                self.configuration.san_private_key):
            raise exception.InvalidInput(
                reason=_('Password or SSH private key is required for '
                         'authentication: set either san_password or '
                         'san_private_key option.'))

        opts = self._assistant.build_default_opts(self.configuration)
        self._assistant.check_vdisk_opts(self._state, opts)

    def _run_ssh(self, cmd_list, check_exit_code=True, attempts=1):
        """SSH tool"""
        cinder_utils.check_ssh_injection(cmd_list)
        command = ' '.join(cmd_list)
        if not self.sshpool:
            try:
                self.sshpool = self._set_up_sshpool(self.active_ip)
            except paramiko.SSHException:
                LOG.warning('Unable to use san_ip to create SSHPool. Now '
                            'attempting to use instorage_san_secondary_ip '
                            'to create SSHPool.')
                if self._switch_ip():
                    self.sshpool = self._set_up_sshpool(self.active_ip)
                else:
                    LOG.error('Unable to create SSHPool using san_ip '
                              'and not able to use '
                              'instorage_san_secondary_ip since it is '
                              'not configured.')
                    raise
        try:
            return self._ssh_execute(self.sshpool, command,
                                     check_exit_code, attempts)

        except Exception:
            # Need to check if creating an SSHPool instorage_san_secondary_ip
            # before raising an error.
            try:
                if self._switch_ip():
                    LOG.warning("Unable to execute SSH command with "
                                "%(inactive)s. Attempting to execute SSH "
                                "command with %(active)s.",
                                {'inactive': self.inactive_ip,
                                 'active': self.active_ip})
                    self.sshpool = self._set_up_sshpool(self.active_ip)
                    return self._ssh_execute(self.sshpool, command,
                                             check_exit_code, attempts)
                else:
                    LOG.warning('Not able to use '
                                'instorage_san_secondary_ip since it is '
                                'not configured.')
                    raise
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error("Error running SSH command: %s",
                              command)

    def _set_up_sshpool(self, ip):
        password = self.configuration.san_password
        privatekey = self.configuration.san_private_key
        min_size = self.configuration.ssh_min_pool_conn
        max_size = self.configuration.ssh_max_pool_conn
        sshpool = ssh_utils.SSHPool(
            ip,
            self.configuration.san_ssh_port,
            self.configuration.ssh_conn_timeout,
            self.configuration.san_login,
            password=password,
            privatekey=privatekey,
            min_size=min_size,
            max_size=max_size)

        return sshpool

    def _ssh_execute(self, sshpool, command,
                     check_exit_code=True, attempts=1):
        try:
            with sshpool.item() as ssh:
                while attempts > 0:
                    attempts -= 1
                    try:
                        return processutils.ssh_execute(
                            ssh,
                            command,
                            check_exit_code=check_exit_code)
                    except Exception as e:
                        LOG.exception('Error has occurred')
                        last_exception = e
                        greenthread.sleep(self.DEFAULT_GR_SLEEP)
                    try:
                        raise processutils.ProcessExecutionError(
                            exit_code=last_exception.exit_code,
                            stdout=last_exception.stdout,
                            stderr=last_exception.stderr,
                            cmd=last_exception.cmd)
                    except AttributeError:
                        raise processutils.ProcessExecutionError(
                            exit_code=-1,
                            stdout="",
                            stderr="Error running SSH command",
                            cmd=command)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Error running SSH command: %s", command)

    def _switch_ip(self):
        # Change active_ip if instorage_san_secondary_ip is set.
        if self.configuration.instorage_san_secondary_ip is None:
            return False

        self.inactive_ip, self.active_ip = self.active_ip, self.inactive_ip
        LOG.info('Switch active_ip from %(old)s to %(new)s.',
                 {'old': self.inactive_ip,
                  'new': self.active_ip})
        return True

    def ensure_export(self, ctxt, volume):
        """Check that the volume exists on the storage."""
        vol_name = self._get_target_vol(volume)
        volume_defined = self._assistant.is_vdisk_defined(vol_name)

        if not volume_defined:
            LOG.error('ensure_export: Volume %s not found on storage.',
                      volume['name'])

    def create_export(self, ctxt, volume, connector):
        pass

    def remove_export(self, ctxt, volume):
        pass

    def _get_vdisk_params(self, type_id, volume_type=None,
                          volume_metadata=None):
        return self._assistant.get_vdisk_params(
            self.configuration,
            self._state,
            type_id,
            volume_type=volume_type,
            volume_metadata=volume_metadata)

    @cinder_utils.trace
    def create_volume(self, volume):
        opts = self._get_vdisk_params(
            volume.volume_type_id,
            volume_metadata=volume.get('volume_metadata'))
        pool = utils.extract_host(volume.host, 'pool')

        opts['iogrp'] = self._assistant.select_io_group(self._state, opts)
        self._assistant.create_vdisk(volume.name, six.text_type(volume.size),
                                     'gb', pool, opts)
        if opts['qos']:
            self._assistant.add_vdisk_qos(volume.name, opts['qos'])

        model_update = None
        ctxt = context.get_admin_context()
        rep_type = self._get_volume_replicated_type(ctxt, volume)

        if rep_type:
            replica_obj = self._get_replica_obj(rep_type)
            replica_obj.volume_replication_setup(ctxt, volume)
            model_update = {
                'replication_status': fields.ReplicationStatus.ENABLED}

        return model_update

    def create_volume_from_snapshot(self, volume, snapshot):
        if snapshot.volume_size > volume.size:
            msg = (_("create_volume_from_snapshot: snapshot %(snapshot_name)s "
                     "size is %(snapshot_size)dGB and doesn't fit in target "
                     "volume %(volume_name)s of size %(volume_size)dGB.") %
                   {'snapshot_name': snapshot.name,
                    'snapshot_size': snapshot.volume_size,
                    'volume_name': volume.name,
                    'volume_size': volume.size})
            LOG.error(msg)
            raise exception.InvalidInput(message=msg)

        opts = self._get_vdisk_params(
            volume.volume_type_id,
            volume_metadata=volume.get('volume_metadata'))
        pool = utils.extract_host(volume.host, 'pool')
        self._assistant.create_copy(snapshot.name, volume.name,
                                    snapshot.id, self.configuration,
                                    opts, True, pool=pool)
        # The volume size is equal to the snapshot size in most
        # of the cases. But in some scenario, the volume size
        # may be bigger than the source volume size.
        # InStorage does not support localcopy between two volumes
        # with two different size. So InStorage will copy volume
        # from snapshot first and then extend the volume to
        # the target size.
        if volume.size > snapshot.volume_size:
            # extend the new created target volume to expected size.
            self._extend_volume_op(volume, volume.size,
                                   snapshot.volume_size)
        if opts['qos']:
            self._assistant.add_vdisk_qos(volume.name, opts['qos'])

        ctxt = context.get_admin_context()
        rep_type = self._get_volume_replicated_type(ctxt, volume)

        if rep_type:
            self._validate_replication_enabled()
            replica_obj = self._get_replica_obj(rep_type)
            replica_obj.volume_replication_setup(ctxt, volume)
            return {'replication_status': fields.ReplicationStatus.ENABLED}

    def create_cloned_volume(self, tgt_volume, src_volume):
        """Creates a clone of the specified volume."""

        if src_volume.size > tgt_volume.size:
            msg = (_("create_cloned_volume: source volume %(src_vol)s "
                     "size is %(src_size)dGB and doesn't fit in target "
                     "volume %(tgt_vol)s of size %(tgt_size)dGB.") %
                   {'src_vol': src_volume.name,
                    'src_size': src_volume.size,
                    'tgt_vol': tgt_volume.name,
                    'tgt_size': tgt_volume.size})
            LOG.error(msg)
            raise exception.InvalidInput(message=msg)

        opts = self._get_vdisk_params(
            tgt_volume.volume_type_id,
            volume_metadata=tgt_volume.get('volume_metadata'))
        pool = utils.extract_host(tgt_volume.host, 'pool')
        self._assistant.create_copy(src_volume.name, tgt_volume.name,
                                    src_volume.id, self.configuration,
                                    opts, True, pool=pool)

        # The source volume size is equal to target volume size
        # in most of the cases. But in some scenarios, the target
        # volume size may be bigger than the source volume size.
        # InStorage does not support localcopy between two volumes
        # with two different sizes. So InStorage will copy volume
        # from source volume first and then extend target
        # volume to original size.
        if tgt_volume.size > src_volume.size:
            # extend the new created target volume to expected size.
            self._extend_volume_op(tgt_volume, tgt_volume.size,
                                   src_volume.size)

        if opts['qos']:
            self._assistant.add_vdisk_qos(tgt_volume.name, opts['qos'])

        ctxt = context.get_admin_context()
        rep_type = self._get_volume_replicated_type(ctxt, tgt_volume)

        if rep_type:
            self._validate_replication_enabled()
            replica_obj = self._get_replica_obj(rep_type)
            replica_obj.volume_replication_setup(ctxt, tgt_volume)
            return {'replication_status': fields.ReplicationStatus.ENABLED}

    def extend_volume(self, volume, new_size):
        self._extend_volume_op(volume, new_size)

    @cinder_utils.trace
    def _extend_volume_op(self, volume, new_size, old_size=None):
        volume_name = self._get_target_vol(volume)
        ret = self._assistant.ensure_vdisk_no_lc_mappings(volume_name,
                                                          allow_snaps=False)
        if not ret:
            msg = (_('_extend_volume_op: Extending a volume with snapshots is '
                     'not supported.'))
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        if old_size is None:
            old_size = volume.size
        extend_amt = int(new_size) - old_size

        rel_info = self._assistant.get_relationship_info(volume_name)
        if rel_info:
            LOG.warning('_extend_volume_op: Extending a volume with '
                        'remote copy is not recommended.')
            try:
                tgt_vol = instorage_const.REPLICA_AUX_VOL_PREFIX + volume.name
                rep_type = rel_info['copy_type']
                self._local_backend_assistant.delete_relationship(
                    volume.name)
                self._local_backend_assistant.extend_vdisk(volume.name,
                                                           extend_amt)
                self._aux_backend_assistant.extend_vdisk(tgt_vol, extend_amt)
                tgt_sys = self._aux_backend_assistant.get_system_info()
                self._local_backend_assistant.create_relationship(
                    volume.name, tgt_vol, tgt_sys.get('system_name'),
                    True if instorage_const.ASYNC == rep_type else False)
            except Exception as e:
                msg = (_('Failed to extend a volume with remote copy '
                         '%(volume)s. Exception: '
                         '%(err)s.') % {'volume': volume.id,
                                        'err': six.text_type(e)})
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
        else:
            self._assistant.extend_vdisk(volume_name, extend_amt)

    @cinder_utils.trace
    def delete_volume(self, volume):
        ctxt = context.get_admin_context()

        rep_type = self._get_volume_replicated_type(ctxt, volume)
        if rep_type:
            self._aux_backend_assistant.delete_rc_volume(volume.name,
                                                         target_vol=True)
            if not self._active_backend_id:
                self._local_backend_assistant.delete_rc_volume(volume.name)
            else:
                # If it's in fail over state, also try to delete the volume
                # in master backend
                try:
                    self._local_backend_assistant.delete_rc_volume(
                        volume.name)
                except Exception as ex:
                    LOG.error('Failed to get delete volume %(volume)s in '
                              'master backend. Exception: %(err)s.',
                              {'volume': volume.name, 'err': ex})
        else:
            if self._active_backend_id:
                msg = (_('Error: delete non-replicate volume in failover mode'
                         ' is not allowed.'))
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
            else:
                self._assistant.delete_vdisk(volume.name, False)

        if volume.id in self._vdiskcopyops:
            del self._vdiskcopyops[volume.id]

            if not self._vdiskcopyops:
                self._vdiskcopyops_loop.stop()
                self._vdiskcopyops_loop = None

    def create_snapshot(self, snapshot):
        source_vol = snapshot.volume
        pool = utils.extract_host(source_vol.host, 'pool')
        opts = self._get_vdisk_params(source_vol.volume_type_id)
        self._assistant.create_copy(snapshot.volume_name, snapshot.name,
                                    snapshot.volume_id, self.configuration,
                                    opts, False, pool=pool)

    def delete_snapshot(self, snapshot):
        self._assistant.delete_vdisk(snapshot.name, False)

    def add_vdisk_copy(self, volume, dest_pool, vol_type):
        return self._assistant.add_vdisk_copy(volume, dest_pool,
                                              vol_type, self._state,
                                              self.configuration)

    def _add_vdisk_copy_op(self, ctxt, volume, new_op):
        if volume.id in self._vdiskcopyops:
            self._vdiskcopyops[volume.id]['copyops'].append(new_op)
        else:
            self._vdiskcopyops[volume.id] = {'name': volume.name,
                                             'copyops': [new_op]}

        # We added the first copy operation, so start the looping call
        if len(self._vdiskcopyops) == 1:
            self._vdiskcopyops_loop = loopingcall.FixedIntervalLoopingCall(
                self._check_volume_copy_ops)
            self._vdiskcopyops_loop.start(interval=self.VDISKCOPYOPS_INTERVAL)

    def _rm_vdisk_copy_op(self, ctxt, vol_id, orig_copy_id, new_copy_id):
        try:
            self._vdiskcopyops[vol_id]['copyops'].remove((orig_copy_id,
                                                          new_copy_id))
            if not self._vdiskcopyops[vol_id]['copyops']:
                del self._vdiskcopyops[vol_id]
            if not self._vdiskcopyops:
                self._vdiskcopyops_loop.stop()
                self._vdiskcopyops_loop = None
        except KeyError:
            LOG.error('_rm_vdisk_copy_op: Volume %s does not have any '
                      'registered vdisk copy operations.', vol_id)
            return
        except ValueError:
            LOG.error('_rm_vdisk_copy_op: Volume %(vol)s does not have '
                      'the specified vdisk copy operation: orig=%(orig)s '
                      'new=%(new)s.',
                      {'vol': vol_id, 'orig': orig_copy_id,
                       'new': new_copy_id})
            return

    def _check_volume_copy_ops(self):
        LOG.debug("Enter: update volume copy status.")
        ctxt = context.get_admin_context()
        copy_items = list(self._vdiskcopyops.items())
        for vol_id, copy_ops_data in copy_items:
            vol_name = copy_ops_data['name']
            copy_ops = copy_ops_data['copyops']

            if not self._assistant.is_vdisk_defined(vol_name):
                LOG.warning('Volume %s does not exist.', vol_id)
                del self._vdiskcopyops[vol_id]
                if not self._vdiskcopyops:
                    self._vdiskcopyops_loop.stop()
                    self._vdiskcopyops_loop = None
                continue

            for copy_op in copy_ops:
                try:
                    synced = self._assistant.check_vdisk_copy_synced(
                        vol_name, copy_op[1])
                except Exception:
                    LOG.info('_check_volume_copy_ops: Volume %(vol)s does '
                             'not have the specified vdisk copy '
                             'operation: orig=%(orig)s new=%(new)s.',
                             {'vol': vol_id, 'orig': copy_op[0],
                              'new': copy_op[1]})
                else:
                    if synced:
                        self._assistant.rm_vdisk_copy(
                            vol_name, copy_op[0])
                        self._rm_vdisk_copy_op(ctxt, vol_id, copy_op[0],
                                               copy_op[1])
        LOG.debug("Exit: update volume copy status.")

    @cinder_utils.trace
    def migrate_volume(self, ctxt, volume, host):
        """Migrate directly if source and dest are managed by same storage.

        We create a new vdisk copy in the desired pool, and add the original
        vdisk copy to the admin_metadata of the volume to be deleted. The
        deletion will occur using a periodic task once the new copy is synced.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        false_ret = (False, None)
        dest_pool = self._assistant.can_migrate_to_host(host, self._state)
        if dest_pool is None:
            return false_ret

        ctxt = context.get_admin_context()
        volume_type_id = volume.volume_type_id
        if volume_type_id is not None:
            vol_type = volume_types.get_volume_type(ctxt, volume_type_id)
        else:
            vol_type = None

        self._check_volume_copy_ops()
        new_op = self.add_vdisk_copy(volume.name, dest_pool, vol_type)
        self._add_vdisk_copy_op(ctxt, volume, new_op)
        return (True, None)

    @cinder_utils.trace
    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        Returns a boolean indicating whether the retype occurred.

        :param ctxt: Context
        :param volume: A volume object describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        def retype_iogrp_property(volume, new, old):
            if new != old:
                self._assistant.change_vdisk_iogrp(volume.name,
                                                   self._state, (new, old))

        no_copy_keys = ['warning', 'autoexpand', 'intier']
        copy_keys = ['rsize', 'grainsize', 'compression']
        all_keys = no_copy_keys + copy_keys
        old_opts = self._get_vdisk_params(
            volume.volume_type_id,
            volume_metadata=volume.get('volume_matadata'))
        new_opts = self._get_vdisk_params(new_type['id'],
                                          volume_type=new_type)

        vdisk_changes = []
        need_copy = False
        for key in all_keys:
            if old_opts[key] != new_opts[key]:
                if key in copy_keys:
                    need_copy = True
                    break
                elif key in no_copy_keys:
                    vdisk_changes.append(key)

        if (utils.extract_host(volume.host, 'pool') !=
                utils.extract_host(host['host'], 'pool')):
            need_copy = True

        # Check if retype affects volume replication
        model_update = None
        new_rep_type = self._get_specs_replicated_type(new_type)
        old_rep_type = self._get_volume_replicated_type(ctxt, volume)
        old_io_grp = self._assistant.get_volume_io_group(volume.name)

        # There are three options for rep_type: None, sync, async
        if new_rep_type != old_rep_type:
            if (old_io_grp not in
                    InStorageAssistant._get_valid_requested_io_groups(
                        self._state, new_opts)):
                msg = (_('Unable to retype: it is not allowed to change '
                         'replication type and io group at the same time.'))
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
            if new_rep_type and old_rep_type:
                msg = (_('Unable to retype: it is not allowed to change '
                         '%(old_rep_type)s volume to %(new_rep_type)s '
                         'volume.') %
                       {'old_rep_type': old_rep_type,
                        'new_rep_type': new_rep_type})
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
            # If volume is replicated, can't copy
            if need_copy:
                msg = (_('Unable to retype: Current action needs volume-copy,'
                         ' it is not allowed when new type is replication.'
                         ' Volume = %s') % volume.id)
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)

        new_io_grp = self._assistant.select_io_group(self._state, new_opts)

        if need_copy:
            self._check_volume_copy_ops()
            dest_pool = self._assistant.can_migrate_to_host(host, self._state)
            if dest_pool is None:
                return False

            retype_iogrp_property(volume,
                                  new_io_grp, old_io_grp)
            try:
                new_op = self.add_vdisk_copy(volume.name,
                                             dest_pool,
                                             new_type)
                self._add_vdisk_copy_op(ctxt, volume, new_op)
            except exception.VolumeDriverException:
                # roll back changing iogrp property
                retype_iogrp_property(volume, old_io_grp, new_io_grp)
                msg = (_('Unable to retype:  A copy of volume %s exists. '
                         'Retyping would exceed the limit of 2 copies.'),
                       volume.id)
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
        else:
            retype_iogrp_property(volume, new_io_grp, old_io_grp)

            self._assistant.change_vdisk_options(volume.name, vdisk_changes,
                                                 new_opts, self._state)

        if new_opts['qos']:
            # Add the new QoS setting to the volume. If the volume has an
            # old QoS setting, it will be overwritten.
            self._assistant.update_vdisk_qos(volume.name, new_opts['qos'])
        elif old_opts['qos']:
            # If the old_opts contain QoS keys, disable them.
            self._assistant.disable_vdisk_qos(volume.name, old_opts['qos'])

        # Delete replica if needed
        if old_rep_type and not new_rep_type:
            self._aux_backend_assistant.delete_rc_volume(volume.name,
                                                         target_vol=True)
            model_update = {
                'replication_status': fields.ReplicationStatus.DISABLED,
                'replication_driver_data': None,
                'replication_extended_status': None}
        # Add replica if needed
        if not old_rep_type and new_rep_type:
            replica_obj = self._get_replica_obj(new_rep_type)
            replica_obj.volume_replication_setup(ctxt, volume)
            model_update = {
                'replication_status': fields.ReplicationStatus.ENABLED}

        return True, model_update

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return model update from InStorage for migrated volume.

        This method should rename the back-end volume name(id) on the
        destination host back to its original name(id) on the source host.

        :param ctxt: The context used to run the method update_migrated_volume
        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :returns: model_update to update DB with any needed changes
        """
        current_name = CONF.volume_name_template % new_volume.id
        original_volume_name = CONF.volume_name_template % volume.id
        try:
            self._assistant.rename_vdisk(current_name, original_volume_name)
        except exception.VolumeBackendAPIException:
            LOG.error('Unable to rename the logical volume '
                      'for volume: %s', volume.id)
            return {'_name_id': new_volume._name_id or new_volume.id}
        # If the back-end name(id) for the volume has been renamed,
        # it is OK for the volume to keep the original name(id) and there is
        # no need to use the column "_name_id" to establish the mapping
        # relationship between the volume id and the back-end volume
        # name(id).
        # Set the key "_name_id" to None for a successful rename.
        model_update = {'_name_id': None}
        return model_update

    def manage_existing(self, volume, ref):
        """Manages an existing vdisk.

        Renames the vdisk to match the expected name for the volume.
        Error checking done by manage_existing_get_size is not repeated -
        if we got here then we have a vdisk that isn't in use (or we don't
        care if it is in use.
        """
        # Check that the reference is valid
        vdisk = self._manage_input_check(ref)
        vdisk_io_grp = self._assistant.get_volume_io_group(vdisk['name'])
        if vdisk_io_grp not in self._state['available_iogrps']:
            msg = (_("Failed to manage existing volume due to "
                     "the volume to be managed is not in a valid "
                     "I/O group."))
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

        # Add replication check
        ctxt = context.get_admin_context()
        rep_type = self._get_volume_replicated_type(ctxt, volume)
        vol_rep_type = None
        rel_info = self._assistant.get_relationship_info(vdisk['name'])
        if rel_info:
            vol_rep_type = rel_info['copy_type']
            aux_info = self._aux_backend_assistant.get_system_info()
            if rel_info['aux_cluster_id'] != aux_info['system_id']:
                msg = (_("Failed to manage existing volume due to the aux "
                         "cluster for volume %(volume)s is %(aux_id)s. The "
                         "configured cluster id is %(cfg_id)s") %
                       {'volume': vdisk['name'],
                        'aux_id': rel_info['aux_cluster_id'],
                        'cfg_id': aux_info['system_id']})
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

        if vol_rep_type != rep_type:
            msg = (_("Failed to manage existing volume due to "
                     "the replication type of the volume to be managed is "
                     "mismatch with the provided replication type."))
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

        if volume.volume_type_id:
            opts = self._get_vdisk_params(
                volume.volume_type_id,
                volume_metadata=volume.get('volume_metadata'))
            vdisk_copy = self._assistant.get_vdisk_copy_attrs(
                vdisk['name'], '0')

            if vdisk_copy['autoexpand'] == 'on' and opts['rsize'] == -1:
                msg = (_("Failed to manage existing volume due to "
                         "the volume to be managed is thin, but "
                         "the volume type chosen is thick."))
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

            if not vdisk_copy['autoexpand'] and opts['rsize'] != -1:
                msg = (_("Failed to manage existing volume due to "
                         "the volume to be managed is thick, but "
                         "the volume type chosen is thin."))
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

            if (vdisk_copy['compressed_copy'] == 'no' and
                    opts['compression']):
                msg = (_("Failed to manage existing volume due to the "
                         "volume to be managed is not compress, but "
                         "the volume type chosen is compress."))
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

            if (vdisk_copy['compressed_copy'] == 'yes' and
                    not opts['compression']):
                msg = (_("Failed to manage existing volume due to the "
                         "volume to be managed is compress, but "
                         "the volume type chosen is not compress."))
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

            if (vdisk_io_grp not in
                    InStorageAssistant._get_valid_requested_io_groups(
                        self._state, opts)):
                msg = (_("Failed to manage existing volume due to "
                         "I/O group mismatch. The I/O group of the "
                         "volume to be managed is %(vdisk_iogrp)s. I/O group "
                         "of the chosen type is %(opt_iogrp)s.") %
                       {'vdisk_iogrp': vdisk['IO_group_name'],
                        'opt_iogrp': opts['iogrp']})
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)
        pool = utils.extract_host(volume.host, 'pool')
        if vdisk['mdisk_grp_name'] != pool:
            msg = (_("Failed to manage existing volume due to the "
                     "pool of the volume to be managed does not "
                     "match the backend pool. Pool of the "
                     "volume to be managed is %(vdisk_pool)s. Pool "
                     "of the backend is %(backend_pool)s.") %
                   {'vdisk_pool': vdisk['mdisk_grp_name'],
                    'backend_pool':
                        self._get_backend_pools()})
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

        model_update = {}
        self._assistant.rename_vdisk(vdisk['name'], volume.name)
        if vol_rep_type:
            aux_vol = instorage_const.REPLICA_AUX_VOL_PREFIX + volume.name
            self._aux_backend_assistant.rename_vdisk(
                rel_info['aux_vdisk_name'], aux_vol)
            model_update = {
                'replication_status': fields.ReplicationStatus.ENABLED}
        return model_update

    def manage_existing_get_size(self, volume, ref):
        """Return size of an existing Vdisk for manage_existing.

        existing_ref is a dictionary of the form:
        {'source-id': <uid of disk>} or
        {'source-name': <name of the disk>}

        Optional elements are:
          'manage_if_in_use':  True/False (default is False)
            If set to True, a volume will be managed even if it is currently
            attached to a host system.
        """

        # Check that the reference is valid
        vdisk = self._manage_input_check(ref)

        # Check if the disk is in use, if we need to.
        manage_if_in_use = ref.get('manage_if_in_use', False)
        if (not manage_if_in_use and
                self._assistant.is_vdisk_in_use(vdisk['name'])):
            reason = _('The specified vdisk is mapped to a host.')
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)

        return int(math.ceil(float(vdisk['capacity']) / units.Gi))

    def unmanage(self, volume):
        """Remove the specified volume from Cinder management."""
        pass

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If we haven't gotten stats yet or 'refresh' is True,
        run update the stats first.
        """
        if not self._stats or refresh:
            self._update_volume_stats()

        return self._stats

    # ## Group method ## #
    def create_group(self, context, group):
        """Create a group.

        Inspur InStorage will create group until group-snapshot creation,
        db will maintain the volumes and group relationship.
        """

        # now we only support consistent group
        if not utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        LOG.debug("Creating group.")
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        return model_update

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source.

        :param context: the context of the caller.
        :param group: the dictionary of the group to be created.
        :param volumes: a list of volume dictionaries in the group.
        :param group_snapshot: the dictionary of the group_snapshot as source.
        :param snapshots: a list of snapshot dictionaries
                in the group_snapshot.
        :param source_group: the dictionary of a group as source.
        :param source_vols: a list of volume dictionaries in the source_group.
        :returns: model_update, volumes_model_update
        """

        # now we only support consistent group
        if not utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        LOG.debug('Enter: create_group_from_src.')
        if group_snapshot and snapshots:
            group_name = 'group-' + group_snapshot.id
            sources = snapshots

        elif source_group and source_vols:
            group_name = 'group-' + source_group.id
            sources = source_vols

        else:
            error_msg = _("create_group_from_src must be creating from"
                          " a group snapshot, or a source group.")
            raise exception.InvalidInput(reason=error_msg)

        LOG.debug('create_group_from_src: group_name %(group_name)s'
                  ' %(sources)s', {'group_name': group_name,
                                   'sources': sources})
        self._assistant.create_lc_consistgrp(group_name)  # create group
        timeout = self.configuration.instorage_mcs_localcopy_timeout
        model_update, snapshots_model = (
            self._assistant.create_group_from_source(group, group_name,
                                                     sources, volumes,
                                                     self._state,
                                                     self.configuration,
                                                     timeout))
        LOG.debug("Leave: create_group_from_src.")
        return model_update, snapshots_model

    def delete_group(self, context, group, volumes):
        """Deletes a group.

        Inspur InStorage will delete the volumes of the group.
        """

        # now we only support consistent group
        if not utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        LOG.debug("Deleting group.")
        model_update = {'status': fields.ConsistencyGroupStatus.DELETED}
        volumes_model_update = []

        for volume in volumes:
            try:
                self._assistant.delete_vdisk(volume.name, True)
                volumes_model_update.append(
                    {'id': volume.id,
                     'status': fields.ConsistencyGroupStatus.DELETED})
            except exception.VolumeBackendAPIException as err:
                model_update['status'] = (
                    fields.ConsistencyGroupStatus.ERROR_DELETING)
                LOG.error("Failed to delete the volume %(vol)s of group. "
                          "Exception: %(exception)s.",
                          {'vol': volume.name, 'exception': err})
                volumes_model_update.append(
                    {'id': volume.id,
                     'status': fields.ConsistencyGroupStatus.ERROR_DELETING})

        return model_update, volumes_model_update

    def update_group(self, ctxt, group, add_volumes=None,
                     remove_volumes=None):
        """Adds or removes volume(s) to/from an existing group."""

        if not utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        LOG.debug("Updating group.")
        # as we don't keep group info on device, nonthing need to be done
        return None, None, None

    def create_group_snapshot(self, ctxt, group_snapshot, snapshots):
        """Creates a cgsnapshot."""

        # now we only support consistent group
        if not utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()

        # Use cgsnapshot id as cg name
        group_name = 'group_snap-' + group_snapshot.id
        # Create new cg as cg_snapshot
        self._assistant.create_lc_consistgrp(group_name)

        timeout = self.configuration.instorage_mcs_localcopy_timeout
        model_update, snapshots_model = (
            self._assistant.run_group_snapshots(group_name,
                                                snapshots,
                                                self._state,
                                                self.configuration,
                                                timeout))

        return model_update, snapshots_model

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a cgsnapshot."""

        # now we only support consistent group
        if not utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()

        group_snapshot_id = group_snapshot.id
        group_name = 'group_snap-' + group_snapshot_id
        model_update, snapshots_model = (
            self._assistant.delete_group_snapshots(group_name,
                                                   snapshots))

        return model_update, snapshots_model

    def get_pool(self, volume):
        attr = self._assistant.get_vdisk_attributes(volume.name)

        if attr is None:
            msg = (_('get_pool: Failed to get attributes for volume '
                     '%s') % volume.id)
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        return attr['mdisk_grp_name']

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug("Updating volume stats.")
        data = {}

        data['vendor_name'] = 'Inspur'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = self.protocol
        data['pools'] = []

        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = (backend_name or
                                       self._state['system_name'])

        data['pools'] = [self._build_pool_stats(pool)
                         for pool in
                         self._get_backend_pools()]
        if self._replica_enabled:
            data['replication'] = self._replica_enabled
            data['replication_enabled'] = self._replica_enabled
            data['replication_targets'] = self._get_replication_targets()
        self._stats = data

    def _build_pool_stats(self, pool):
        """Build pool status"""
        QoS_support = True
        pool_stats = {}
        try:
            pool_data = self._assistant.get_pool_attrs(pool)
            if pool_data:
                in_tier = pool_data['in_tier'] in ['on', 'auto']
                total_capacity_gb = float(pool_data['capacity']) / units.Gi
                free_capacity_gb = float(pool_data['free_capacity']) / units.Gi
                provisioned_capacity_gb = float(
                    pool_data['virtual_capacity']) / units.Gi

                rsize = self.configuration.safe_get(
                    'instorage_mcs_vol_rsize')
                # rsize of -1 or 100 means fully allocate the mdisk
                use_thick_provisioning = rsize == -1 or rsize == 100
                over_sub_ratio = self.configuration.safe_get(
                    'max_over_subscription_ratio')
                location_info = ('InStorageMCSDriver:%(sys_id)s:%(pool)s' %
                                 {'sys_id': self._state['system_id'],
                                  'pool': pool_data['name']})
                pool_stats = {
                    'pool_name': pool_data['name'],
                    'total_capacity_gb': total_capacity_gb,
                    'free_capacity_gb': free_capacity_gb,
                    'provisioned_capacity_gb': provisioned_capacity_gb,
                    'compression_support': self._state['compression_enabled'],
                    'reserved_percentage':
                        self.configuration.reserved_percentage,
                    'QoS_support': QoS_support,
                    'consistent_group_snapshot_enabled': True,
                    'location_info': location_info,
                    'intier_support': in_tier,
                    'multiattach': False,
                    'thin_provisioning_support': not use_thick_provisioning,
                    'thick_provisioning_support': use_thick_provisioning,
                    'max_over_subscription_ratio': over_sub_ratio,
                }
            if self._replica_enabled:
                pool_stats.update({
                    'replication_enabled': self._replica_enabled,
                    'replication_type': self._supported_replica_types,
                    'replication_targets': self._get_replication_targets(),
                    'replication_count': len(self._get_replication_targets())
                })

        except exception.VolumeBackendAPIException:
            msg = _('Failed getting details for pool %s.') % pool
            raise exception.VolumeBackendAPIException(data=msg)

        return pool_stats

    def _get_replication_targets(self):
        return [self._replica_target['backend_id']]

    def _manage_input_check(self, ref):
        """Verify the input of manage function."""
        # Check that the reference is valid
        if 'source-name' in ref:
            manage_source = ref['source-name']
            vdisk = self._assistant.get_vdisk_attributes(manage_source)
        elif 'source-id' in ref:
            manage_source = ref['source-id']
            vdisk = self._assistant.vdisk_by_uid(manage_source)
        else:
            reason = _('Reference must contain source-id or '
                       'source-name element.')
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)

        if vdisk is None:
            reason = (_('No vdisk with the UID specified by ref %s.')
                      % manage_source)
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)
        return vdisk

    # #### V2.1 replication methods #### #
    @cinder_utils.trace
    def failover_host(self, context, volumes, secondary_id=None):
        if not self._replica_enabled:
            msg = _("Replication is not properly enabled on backend.")
            LOG.error(msg)
            raise exception.UnableToFailOver(reason=msg)

        if instorage_const.FAILBACK_VALUE == secondary_id:
            # In this case the administrator would like to fail back.
            secondary_id, volumes_update = self._replication_failback(context,
                                                                      volumes)
        elif (secondary_id == self._replica_target['backend_id'] or
              secondary_id is None):
            # In this case the administrator would like to fail over.
            secondary_id, volumes_update = self._replication_failover(context,
                                                                      volumes)
        else:
            msg = (_("Invalid secondary id %s.") % secondary_id)
            LOG.error(msg)
            raise exception.InvalidReplicationTarget(reason=msg)

        return secondary_id, volumes_update

    def _replication_failback(self, ctxt, volumes):
        """Fail back all the volume on the secondary backend."""
        volumes_update = []
        if not self._active_backend_id:
            LOG.info("Host has been failed back. doesn't need "
                     "to fail back again")
            return None, volumes_update

        try:
            self._local_backend_assistant.get_system_info()
        except Exception:
            msg = (_("Unable to failback due to primary is not reachable."))
            LOG.error(msg)
            raise exception.UnableToFailOver(reason=msg)

        normal_volumes, rep_volumes = self._classify_volume(ctxt, volumes)

        # start synchronize from aux volume to master volume
        self._sync_with_aux(ctxt, rep_volumes)
        self._wait_replica_ready(ctxt, rep_volumes)

        rep_volumes_update = self._failback_replica_volumes(ctxt,
                                                            rep_volumes)
        volumes_update.extend(rep_volumes_update)

        normal_volumes_update = self._failback_normal_volumes(normal_volumes)
        volumes_update.extend(normal_volumes_update)

        self._assistant = self._local_backend_assistant
        self._active_backend_id = None

        # Update the instorage state
        self._update_instorage_state()
        self._update_volume_stats()
        return instorage_const.FAILBACK_VALUE, volumes_update

    @cinder_utils.trace
    def _failback_replica_volumes(self, ctxt, rep_volumes):
        volumes_update = []

        for volume in rep_volumes:
            rep_type = self._get_volume_replicated_type(ctxt, volume)
            replica_obj = self._get_replica_obj(rep_type)
            tgt_volume = instorage_const.REPLICA_AUX_VOL_PREFIX + volume.name
            rep_info = self._assistant.get_relationship_info(tgt_volume)
            if not rep_info:
                replication_status = fields.ReplicationStatus.FAILOVER_ERROR
                volumes_update.append(
                    {'volume_id': volume.id,
                     'updates': {
                         'replication_status': replication_status,
                         'status': 'error'}})
                LOG.error('_failback_replica_volumes:no rc-releationship '
                          'is established between master: %(master)s and '
                          'aux %(aux)s. Please re-establish the '
                          'relationship and synchronize the volumes on '
                          'backend storage.',
                          {'master': volume.name, 'aux': tgt_volume})
                continue
            LOG.debug('_failover_replica_volumes: vol=%(vol)s, master_vol='
                      '%(master_vol)s, aux_vol=%(aux_vol)s, state=%(state)s, '
                      'primary=%(primary)s',
                      {'vol': volume.name,
                       'master_vol': rep_info['master_vdisk_name'],
                       'aux_vol': rep_info['aux_vdisk_name'],
                       'state': rep_info['state'],
                       'primary': rep_info['primary']})
            try:
                model_updates = replica_obj.replication_failback(volume)
                volumes_update.append(
                    {'volume_id': volume.id,
                     'updates': model_updates})
            except exception.VolumeDriverException:
                LOG.error('Unable to fail back volume %(volume_id)s',
                          {'volume_id': volume.id})
                replication_status = fields.ReplicationStatus.FAILOVER_ERROR
                volumes_update.append(
                    {'volume_id': volume.id,
                     'updates': {'replication_status': replication_status,
                                 'status': 'error'}})
        return volumes_update

    def _failback_normal_volumes(self, normal_volumes):
        volumes_update = []
        for vol in normal_volumes:
            pre_status = 'available'
            if ('replication_driver_data' in vol and
                    vol.replication_driver_data):
                rep_data = json.loads(vol.replication_driver_data)
                pre_status = rep_data['previous_status']
            volumes_update.append(
                {'volume_id': vol.id,
                 'updates': {'status': pre_status,
                             'replication_driver_data': ''}})
        return volumes_update

    @cinder_utils.trace
    def _sync_with_aux(self, ctxt, volumes):
        try:
            rep_mgr = self._get_replica_mgr()
            rep_mgr.establish_target_partnership()
        except Exception as ex:
            LOG.warning('Fail to establish partnership in backend. '
                        'error=%(ex)s', {'error': ex})
        for volume in volumes:
            tgt_volume = instorage_const.REPLICA_AUX_VOL_PREFIX + volume.name
            rep_info = self._assistant.get_relationship_info(tgt_volume)
            if not rep_info:
                LOG.error('_sync_with_aux: no rc-releationship is '
                          'established between master: %(master)s and aux '
                          '%(aux)s. Please re-establish the relationship '
                          'and synchronize the volumes on backend '
                          'storage.', {'master': volume.name,
                                       'aux': tgt_volume})
                continue
            LOG.debug('_sync_with_aux: volume: %(volume)s rep_info:master_vol='
                      '%(master_vol)s, aux_vol=%(aux_vol)s, state=%(state)s, '
                      'primary=%(primary)s',
                      {'volume': volume.name,
                       'master_vol': rep_info['master_vdisk_name'],
                       'aux_vol': rep_info['aux_vdisk_name'],
                       'state': rep_info['state'],
                       'primary': rep_info['primary']})
            try:
                if rep_info['state'] != instorage_const.REP_CONSIS_SYNC:
                    if rep_info['primary'] == 'master':
                        self._assistant.start_relationship(tgt_volume)
                    else:
                        self._assistant.start_relationship(tgt_volume,
                                                           primary='aux')
            except Exception as ex:
                LOG.warning('Fail to copy data from aux to master. master:'
                            ' %(master)s and aux %(aux)s. Please '
                            're-establish the relationship and synchronize'
                            ' the volumes on backend storage. error='
                            '%(ex)s', {'master': volume.name,
                                       'aux': tgt_volume,
                                       'error': ex})

    def _wait_replica_ready(self, ctxt, volumes):
        for volume in volumes:
            tgt_volume = instorage_const.REPLICA_AUX_VOL_PREFIX + volume.name
            try:
                self._wait_replica_vol_ready(ctxt, tgt_volume)
            except Exception as ex:
                LOG.error('_wait_replica_ready: wait for volume:%(volume)s'
                          ' remote copy synchronization failed due to '
                          'error:%(err)s.', {'volume': tgt_volume,
                                             'err': ex})

    @cinder_utils.trace
    def _wait_replica_vol_ready(self, ctxt, volume):
        def _replica_vol_ready():
            rep_info = self._assistant.get_relationship_info(volume)
            if not rep_info:
                msg = (_('_wait_replica_vol_ready: no rc-releationship '
                         'is established for volume:%(volume)s. Please '
                         're-establish the rc-relationship and '
                         'synchronize the volumes on backend storage.'),
                       {'volume': volume})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            LOG.debug('_replica_vol_ready:volume: %(volume)s rep_info: '
                      'master_vol=%(master_vol)s, aux_vol=%(aux_vol)s, '
                      'state=%(state)s, primary=%(primary)s',
                      {'volume': volume,
                       'master_vol': rep_info['master_vdisk_name'],
                       'aux_vol': rep_info['aux_vdisk_name'],
                       'state': rep_info['state'],
                       'primary': rep_info['primary']})
            if rep_info['state'] == instorage_const.REP_CONSIS_SYNC:
                return True
            if rep_info['state'] == instorage_const.REP_IDL_DISC:
                msg = (_('Wait synchronize failed. volume: %(volume)s'),
                       {'volume': volume})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            return False

        self._assistant._wait_for_a_condition(
            _replica_vol_ready, timeout=instorage_const.DEFAULT_RC_TIMEOUT,
            interval=instorage_const.DEFAULT_RC_INTERVAL,
            raise_exception=True)

    def _replication_failover(self, ctxt, volumes):
        volumes_update = []
        if self._active_backend_id:
            LOG.info("Host has been failed over to %s",
                     self._active_backend_id)
            return self._active_backend_id, volumes_update

        try:
            self._aux_backend_assistant.get_system_info()
        except Exception as ex:
            msg = (_("Unable to failover due to replication target is not "
                     "reachable. error=%(ex)s"), {'error': ex})
            LOG.error(msg)
            raise exception.UnableToFailOver(reason=msg)

        normal_volumes, rep_volumes = self._classify_volume(ctxt, volumes)

        rep_volumes_update = self._failover_replica_volumes(ctxt, rep_volumes)
        volumes_update.extend(rep_volumes_update)

        normal_volumes_update = self._failover_normal_volumes(normal_volumes)
        volumes_update.extend(normal_volumes_update)

        self._assistant = self._aux_backend_assistant
        self._active_backend_id = self._replica_target['backend_id']
        self._secondary_pools = [self._replica_target['pool_name']]

        # Update the instorage state
        self._update_instorage_state()
        self._update_volume_stats()
        return self._active_backend_id, volumes_update

    @cinder_utils.trace
    def _failover_replica_volumes(self, ctxt, rep_volumes):
        volumes_update = []

        for volume in rep_volumes:
            rep_type = self._get_volume_replicated_type(ctxt, volume)
            replica_obj = self._get_replica_obj(rep_type)
            # Try do the fail-over.
            try:
                rep_info = self._aux_backend_assistant.get_relationship_info(
                    instorage_const.REPLICA_AUX_VOL_PREFIX + volume.name)
                if not rep_info:
                    rep_status = fields.ReplicationStatus.FAILOVER_ERROR
                    volumes_update.append(
                        {'volume_id': volume.id,
                         'updates': {'replication_status': rep_status,
                                     'status': 'error'}})
                    LOG.error('_failover_replica_volumes: no rc-'
                              'releationship is established for master:'
                              '%(master)s. Please re-establish the rc-'
                              'relationship and synchronize the volumes on'
                              ' backend storage.',
                              {'master': volume.name})
                    continue
                LOG.debug('_failover_replica_volumes: vol=%(vol)s, '
                          'master_vol=%(master_vol)s, aux_vol=%(aux_vol)s, '
                          'state=%(state)s, primary=%(primary)s',
                          {'vol': volume.name,
                           'master_vol': rep_info['master_vdisk_name'],
                           'aux_vol': rep_info['aux_vdisk_name'],
                           'state': rep_info['state'],
                           'primary': rep_info['primary']})
                model_updates = replica_obj.failover_volume_host(ctxt, volume)
                volumes_update.append(
                    {'volume_id': volume.id,
                     'updates': model_updates})
            except exception.VolumeDriverException:
                LOG.error('Unable to failover to aux volume. Please make '
                          'sure that the aux volume is ready.')
                volumes_update.append(
                    {'volume_id': volume.id,
                     'updates': {'status': 'error',
                                 'replication_status':
                                     fields.ReplicationStatus.FAILOVER_ERROR}})
        return volumes_update

    def _failover_normal_volumes(self, normal_volumes):
        volumes_update = []
        for volume in normal_volumes:
            # If the volume is not of replicated type, we need to
            # force the status into error state so a user knows they
            # do not have access to the volume.
            rep_data = json.dumps({'previous_status': volume.status})
            volumes_update.append(
                {'volume_id': volume.id,
                 'updates': {'status': 'error',
                             'replication_driver_data': rep_data}})
        return volumes_update

    def _classify_volume(self, ctxt, volumes):
        normal_volumes = []
        replica_volumes = []

        for v in volumes:
            volume_type = self._get_volume_replicated_type(ctxt, v)
            if volume_type and v.status == 'available':
                replica_volumes.append(v)
            else:
                normal_volumes.append(v)

        return normal_volumes, replica_volumes

    def _get_replica_obj(self, rep_type):
        replica_manager = self.replica_manager[
            self._replica_target['backend_id']]
        return replica_manager.get_replica_obj(rep_type)

    def _get_replica_mgr(self):
        replica_manager = self.replica_manager[
            self._replica_target['backend_id']]
        return replica_manager

    def _get_target_vol(self, volume):
        tgt_vol = volume.name
        if self._active_backend_id:
            ctxt = context.get_admin_context()
            rep_type = self._get_volume_replicated_type(ctxt, volume)
            if rep_type:
                tgt_vol = instorage_const.REPLICA_AUX_VOL_PREFIX + volume.name
        return tgt_vol

    def _validate_replication_enabled(self):
        if not self._replica_enabled:
            msg = _("Replication is not properly configured on backend.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _get_specs_replicated_type(self, volume_type):
        replication_type = None
        extra_specs = volume_type.get("extra_specs", {})
        rep_val = extra_specs.get('replication_enabled')
        if rep_val == "<is> True":
            replication_type = extra_specs.get('replication_type',
                                               instorage_const.ASYNC)
            # The format for replication_type in extra spec is in
            # "<in> async". Otherwise, the code will
            # not reach here.
            if replication_type != instorage_const.ASYNC:
                # Pick up the replication type specified in the
                # extra spec from the format like "<in> async".
                replication_type = replication_type.split()[1]
            if replication_type not in instorage_const.VALID_REP_TYPES:
                msg = (_("Invalid replication type %s.") % replication_type)
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)
        return replication_type

    def _get_volume_replicated_type(self, ctxt, volume):
        replication_type = None
        if volume.get("volume_type_id"):
            volume_type = volume_types.get_volume_type(
                ctxt, volume.volume_type_id)
            replication_type = self._get_specs_replicated_type(volume_type)

        return replication_type

    def _get_instorage_config(self):
        self._do_replication_setup()

        if self._active_backend_id and self._replica_target:
            self._assistant = self._aux_backend_assistant

        self._replica_enabled = (True if (self._assistant.
                                          replication_licensed() and
                                          self._replica_target) else False)
        if self._replica_enabled:
            self._supported_replica_types = instorage_const.VALID_REP_TYPES

    def _do_replication_setup(self):
        rep_devs = self.configuration.safe_get('replication_device')
        if not rep_devs:
            return

        if len(rep_devs) > 1:
            raise exception.InvalidInput(
                reason=_('Multiple replication devices are configured. '
                         'Now only one replication_device is supported.'))

        required_flags = ['san_ip', 'backend_id', 'san_login',
                          'san_password', 'pool_name']
        for flag in required_flags:
            if flag not in rep_devs[0]:
                raise exception.InvalidInput(
                    reason=_('%s is not set.') % flag)

        rep_target = {}
        rep_target['san_ip'] = rep_devs[0].get('san_ip')
        rep_target['backend_id'] = rep_devs[0].get('backend_id')
        rep_target['san_login'] = rep_devs[0].get('san_login')
        rep_target['san_password'] = rep_devs[0].get('san_password')
        rep_target['pool_name'] = rep_devs[0].get('pool_name')

        # Each replication target will have a corresponding replication.
        self._replication_initialize(rep_target)

    def _replication_initialize(self, target):
        rep_manager = instorage_rep.InStorageMCSReplicationManager(
            self, target, InStorageAssistant)

        if self._active_backend_id:
            if self._active_backend_id != target['backend_id']:
                msg = (_("Invalid secondary id %s.") % self._active_backend_id)
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)
        # Setup partnership only in non-failover state
        else:
            try:
                rep_manager.establish_target_partnership()
            except exception.VolumeDriverException:
                LOG.error('The replication src %(src)s has not '
                          'successfully established partnership with the '
                          'replica target %(tgt)s.',
                          {'src': self.configuration.san_ip,
                           'tgt': target['backend_id']})

        self._aux_backend_assistant = rep_manager.get_target_assistant()
        self.replica_manager[target['backend_id']] = rep_manager
        self._replica_target = target


class InStorageAssistant(object):

    # All the supported QoS key are saved in this dict. When a new
    # key is going to add, three values MUST be set:
    # 'default': to indicate the value, when the parameter is disabled.
    # 'param': to indicate the corresponding parameter in the command.
    # 'type': to indicate the type of this value.
    WAIT_TIME = 5
    mcs_qos_keys = {'IOThrottling': {'default': '0',
                                     'param': 'rate',
                                     'type': int}}

    def __init__(self, run_ssh):
        self.ssh = InStorageSSH(run_ssh)
        self.check_lcmapping_interval = 3

    @staticmethod
    def handle_keyerror(cmd, out):
        msg = (_('Could not find key in output of command %(cmd)s: %(out)s.')
               % {'out': out, 'cmd': cmd})
        raise exception.VolumeBackendAPIException(data=msg)

    def compression_enabled(self):
        """Return whether or not compression is enabled for this system."""
        resp = self.ssh.lslicense()
        keys = ['license_compression_enclosures',
                'license_compression_capacity']
        for key in keys:
            if resp.get(key, '0') != '0':
                return True
        try:
            resp = self.ssh.lsguicapabilities()
            if resp.get('compression', '0') == 'yes':
                return True
        except exception.VolumeBackendAPIException:
            LOG.exception("Failed to fetch licensing scheme.")
        return False

    def replication_licensed(self):
        """Return whether or not replication is enabled for this system."""
        return True

    def get_system_info(self):
        """Return system's name, ID, and code level."""
        resp = self.ssh.lssystem()
        level = resp['code_level']
        match_obj = re.search('([0-9].){3}[0-9]', level)
        if match_obj is None:
            msg = _('Failed to get code level (%s).') % level
            raise exception.VolumeBackendAPIException(data=msg)
        code_level = match_obj.group().split('.')
        return {'code_level': tuple([int(x) for x in code_level]),
                'system_name': resp['name'],
                'system_id': resp['id']}

    def get_node_info(self):
        """Return dictionary containing information on system's nodes."""
        nodes = {}
        resp = self.ssh.lsnode()
        for node_data in resp:
            try:
                if node_data['status'] != 'online':
                    continue
                node = {}
                node['id'] = node_data['id']
                node['name'] = node_data['name']
                node['IO_group'] = node_data['IO_group_id']
                node['iscsi_name'] = node_data['iscsi_name']
                node['WWNN'] = node_data['WWNN']
                node['status'] = node_data['status']
                node['WWPN'] = []
                node['ipv4'] = []
                node['ipv6'] = []
                node['enabled_protocols'] = []
                nodes[node['id']] = node
            except KeyError:
                self.handle_keyerror('lsnode', node_data)
        return nodes

    def get_pool_attrs(self, pool):
        """Return attributes for the specified pool."""
        return self.ssh.lsmdiskgrp(pool)

    def get_available_io_groups(self):
        """Return list of available IO groups."""
        iogrps = []
        resp = self.ssh.lsiogrp()
        for iogrp in resp:
            try:
                if int(iogrp['node_count']) > 0:
                    iogrps.append(int(iogrp['id']))
            except KeyError:
                self.handle_keyerror('lsiogrp', iogrp)
            except ValueError:
                msg = (_('Expected integer for node_count, '
                         'mcsinq lsiogrp returned: %(node)s.') %
                       {'node': iogrp['node_count']})
                raise exception.VolumeBackendAPIException(data=msg)
        return iogrps

    def get_vdisk_count_by_io_group(self):
        res = {}
        resp = self.ssh.lsiogrp()
        for iogrp in resp:
            try:
                if int(iogrp['node_count']) > 0:
                    res[int(iogrp['id'])] = int(iogrp['vdisk_count'])
            except KeyError:
                self.handle_keyerror('lsiogrp', iogrp)
            except ValueError:
                msg = (_('Expected integer for node_count, '
                         'mcsinq lsiogrp returned: %(node)s') %
                       {'node': iogrp['node_count']})
                raise exception.VolumeBackendAPIException(data=msg)
        return res

    def select_io_group(self, state, opts):
        selected_iog = 0
        iog_list = InStorageAssistant._get_valid_requested_io_groups(
            state, opts)
        if len(iog_list) == 0:
            raise exception.InvalidInput(
                reason=_('Given I/O group(s) %(iogrp)s not valid; available '
                         'I/O groups are %(avail)s.')
                % {'iogrp': opts['iogrp'],
                   'avail': state['available_iogrps']})
        iog_vdc = self.get_vdisk_count_by_io_group()
        LOG.debug("IO group current balance %s", iog_vdc)
        min_vdisk_count = iog_vdc[iog_list[0]]
        selected_iog = iog_list[0]
        for iog in iog_list:
            if iog_vdc[iog] < min_vdisk_count:
                min_vdisk_count = iog_vdc[iog]
                selected_iog = iog
        LOG.debug("Selected io_group is %d", selected_iog)
        return selected_iog

    def get_volume_io_group(self, vol_name):
        vdisk = self.ssh.lsvdisk(vol_name)
        if vdisk:
            resp = self.ssh.lsiogrp()
            for iogrp in resp:
                if iogrp['name'] == vdisk['IO_group_name']:
                    return int(iogrp['id'])
        return None

    def add_iscsi_ip_addrs(self, storage_nodes):
        """Add iSCSI IP addresses to system node information."""
        resp = self.ssh.lsportip()
        for ip_data in resp:
            try:
                state = ip_data['state']
                if ip_data['node_id'] in storage_nodes and (
                        state == 'configured' or state == 'online'):
                    node = storage_nodes[ip_data['node_id']]
                    if len(ip_data['IP_address']):
                        node['ipv4'].append(ip_data['IP_address'])
                    if len(ip_data['IP_address_6']):
                        node['ipv6'].append(ip_data['IP_address_6'])
            except KeyError:
                self.handle_keyerror('lsportip', ip_data)

    def add_fc_wwpns(self, storage_nodes):
        """Add FC WWPNs to system node information."""
        for key in storage_nodes:
            node = storage_nodes[key]
            wwpns = set(node['WWPN'])
            resp = self.ssh.lsportfc(node_id=node['id'])
            for port_info in resp:
                if (port_info['type'] == 'fc' and
                        port_info['status'] == 'active'):
                    wwpns.add(port_info['WWPN'])
            node['WWPN'] = list(wwpns)
            LOG.info('WWPN on node %(node)s: %(wwpn)s.',
                     {'node': node['id'], 'wwpn': node['WWPN']})

    def get_conn_fc_wwpns(self, host):
        wwpns = set()
        resp = self.ssh.lsfabric(host=host)
        for wwpn in resp.select('local_wwpn'):
            if wwpn is not None:
                wwpns.add(wwpn)
        return list(wwpns)

    def add_chap_secret_to_host(self, host_name):
        """Generate and store a randomly-generated CHAP secret for the host."""
        chap_secret = utils.generate_password()
        self.ssh.add_chap_secret(chap_secret, host_name)
        return chap_secret

    def get_chap_secret_for_host(self, host_name):
        """Generate and store a randomly-generated CHAP secret for the host."""
        resp = self.ssh.lsiscsiauth()
        host_found = False
        for host_data in resp:
            try:
                if host_data['name'] == host_name:
                    host_found = True
                    if host_data['iscsi_auth_method'] == 'chap':
                        return host_data['iscsi_chap_secret']
            except KeyError:
                self.handle_keyerror('lsiscsiauth', host_data)
        if not host_found:
            msg = _('Failed to find host %s.') % host_name
            raise exception.VolumeBackendAPIException(data=msg)
        return None

    def get_host_from_connector(self, connector, volume_name=None):
        """Return the InStorage host described by the connector."""
        LOG.debug('Enter: get_host_from_connector: %s.', connector)

        # If we have FC information, we have a faster lookup option
        host_name = None
        if 'wwpns' in connector:
            for wwpn in connector['wwpns']:
                resp = self.ssh.lsfabric(wwpn=wwpn)
                for wwpn_info in resp:
                    try:
                        if (wwpn_info['remote_wwpn'] and
                                wwpn_info['name'] and
                                wwpn_info['remote_wwpn'].lower() ==
                                wwpn.lower()):
                            host_name = wwpn_info['name']
                            break
                    except KeyError:
                        self.handle_keyerror('lsfabric', wwpn_info)
                if host_name:
                    break
        if host_name:
            LOG.debug('Leave: get_host_from_connector: host %s.', host_name)
            return host_name

        def update_host_list(host, host_list):
            idx = host_list.index(host)
            del host_list[idx]
            host_list.insert(0, host)

        # That didn't work, so try exhaustive search
        hosts_info = self.ssh.lshost()
        host_list = list(hosts_info.select('name'))
        # If we have a "real" connector, we might be able to find the
        # host entry with fewer queries if we move the host entries
        # that contain the connector's host property value to the front
        # of the list
        if 'host' in connector:
            # order host_list such that the host entries that
            # contain the connector's host name are at the
            # beginning of the list
            for host in host_list:
                if re.search(connector['host'], host):
                    update_host_list(host, host_list)
        # If we have a volume name we have a potential fast path
        # for finding the matching host for that volume.
        # Add the host_names that have mappings for our volume to the
        # head of the list of host names to search them first
        if volume_name:
            hosts_map_info = self.ssh.lsvdiskhostmap(volume_name)
            hosts_map_info_list = list(hosts_map_info.select('host_name'))
            # remove the fast path host names from the end of the list
            # and move to the front so they are only searched for once.
            for host in hosts_map_info_list:
                update_host_list(host, host_list)
        found = False
        for name in host_list:
            try:
                resp = self.ssh.lshost(host=name)
            except exception.VolumeBackendAPIException as ex:
                LOG.debug("Exception message: %s", ex.msg)
                if 'CMMVC5754E' in ex.msg:
                    LOG.debug("CMMVC5754E found in CLI exception.")
                    # CMMVC5754E: The specified object does not exist
                    # The host has been deleted while walking the list.
                    # This is a result of a host change on the MCS that
                    # is out of band to this request.
                    continue
                # unexpected error so reraise it
                with excutils.save_and_reraise_exception():
                    pass
            if 'initiator' in connector:
                for iscsi in resp.select('iscsi_name'):
                    if iscsi == connector['initiator']:
                        host_name = name
                        found = True
                        break
            elif 'wwpns' in connector and len(connector['wwpns']):
                connector_wwpns = [str(x).lower() for x in connector['wwpns']]
                for wwpn in resp.select('WWPN'):
                    if wwpn and wwpn.lower() in connector_wwpns:
                        host_name = name
                        found = True
                        break
            if found:
                break

        LOG.debug('Leave: get_host_from_connector: host %s.', host_name)
        return host_name

    def create_host(self, connector):
        """Create a new host on the storage system.

        We create a host name and associate it with the given connection
        information.  The host name will be a cleaned up version of the given
        host name (at most 55 characters), plus a random 8-character suffix to
        avoid collisions. The total length should be at most 63 characters.
        """
        LOG.debug('Enter: create_host: host %s.', connector['host'])

        # Before we start, make sure host name is a string and that we have
        # one port at least .
        host_name = connector['host']
        if not isinstance(host_name, six.string_types):
            msg = _('create_host: Host name is not unicode or string.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        ports = []
        if 'initiator' in connector:
            ports.append(['initiator', '%s' % connector['initiator']])
        if 'wwpns' in connector:
            for wwpn in connector['wwpns']:
                ports.append(['wwpn', '%s' % wwpn])
        if not len(ports):
            msg = _('create_host: No initiators or wwpns supplied.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        # Build a host name for the InStorage host - first clean up the name
        if isinstance(host_name, six.text_type):
            host_name = unicodedata.normalize('NFKD', host_name).encode(
                'ascii', 'replace').decode('ascii')

        for num in range(0, 128):
            ch = str(chr(num))
            if not ch.isalnum() and ch not in [' ', '.', '-', '_']:
                host_name = host_name.replace(ch, '-')

        # InStorage doesn't expect hostname that doesn't starts with letter or
        # _.
        if not re.match('^[A-Za-z]', host_name):
            host_name = '_' + host_name

        # Add a random 8-character suffix to avoid collisions
        rand_id = str(random.randint(0, 99999999)).zfill(8)
        host_name = '%s-%s' % (host_name[:55], rand_id)

        # Create a host with one port
        port = ports.pop(0)
        self.ssh.mkhost(host_name, port[0], port[1])

        # Add any additional ports to the host
        for port in ports:
            self.ssh.addhostport(host_name, port[0], port[1])

        LOG.debug('Leave: create_host: host %(host)s - %(host_name)s.',
                  {'host': connector['host'], 'host_name': host_name})
        return host_name

    def delete_host(self, host_name):
        self.ssh.rmhost(host_name)

    def check_host_mapped_vols(self, host_name):
        return self.ssh.lshostvdiskmap(host_name)

    def map_vol_to_host(self, volume_name, host_name, multihostmap):
        """Create a mapping between a volume to a host."""

        LOG.debug('Enter: map_vol_to_host: volume %(volume_name)s to '
                  'host %(host_name)s.',
                  {'volume_name': volume_name, 'host_name': host_name})

        # Check if this volume is already mapped to this host
        result_lun = self.ssh.get_vdiskhostmapid(volume_name, host_name)
        if result_lun is None:
            result_lun = self.ssh.mkvdiskhostmap(host_name, volume_name, None,
                                                 multihostmap)

        LOG.debug('Leave: map_vol_to_host: LUN %(result_lun)s, volume '
                  '%(volume_name)s, host %(host_name)s.',
                  {'result_lun': result_lun,
                   'volume_name': volume_name,
                   'host_name': host_name})
        return int(result_lun)

    def unmap_vol_from_host(self, volume_name, host_name):
        """Unmap the volume and delete the host if it has no more mappings."""

        LOG.debug('Enter: unmap_vol_from_host: volume %(volume_name)s from '
                  'host %(host_name)s.',
                  {'volume_name': volume_name, 'host_name': host_name})

        # Check if the mapping exists
        resp = self.ssh.lsvdiskhostmap(volume_name)
        if not len(resp):
            LOG.warning('unmap_vol_from_host: No mapping of volume '
                        '%(vol_name)s to any host found.',
                        {'vol_name': volume_name})
            return host_name
        if host_name is None:
            if len(resp) > 1:
                LOG.warning('unmap_vol_from_host: Multiple mappings of '
                            'volume %(vol_name)s found, no host '
                            'specified.', {'vol_name': volume_name})
                return
            else:
                host_name = resp[0]['host_name']
        else:
            found = False
            for h in resp.select('host_name'):
                if h == host_name:
                    found = True
            if not found:
                LOG.warning('unmap_vol_from_host: No mapping of volume '
                            '%(vol_name)s to host %(host)s found.',
                            {'vol_name': volume_name, 'host': host_name})
                return host_name
        # We now know that the mapping exists
        self.ssh.rmvdiskhostmap(host_name, volume_name)

        LOG.debug('Leave: unmap_vol_from_host: volume %(volume_name)s from '
                  'host %(host_name)s.',
                  {'volume_name': volume_name, 'host_name': host_name})
        return host_name

    @staticmethod
    def build_default_opts(config):
        # Ignore capitalization

        opt = {'rsize': config.instorage_mcs_vol_rsize,
               'warning': config.instorage_mcs_vol_warning,
               'autoexpand': config.instorage_mcs_vol_autoexpand,
               'grainsize': config.instorage_mcs_vol_grainsize,
               'compression': config.instorage_mcs_vol_compression,
               'intier': config.instorage_mcs_vol_intier,
               'iogrp': config.instorage_mcs_vol_iogrp,
               'qos': None,
               'replication': False}
        return opt

    @staticmethod
    def check_vdisk_opts(state, opts):
        # Check that grainsize is 32/64/128/256
        if opts['grainsize'] not in [32, 64, 128, 256]:
            raise exception.InvalidInput(
                reason=_('Illegal value specified for '
                         'instorage_mcs_vol_grainsize: set to either '
                         '32, 64, 128, or 256.'))

        # Check that compression is supported
        if opts['compression'] and not state['compression_enabled']:
            raise exception.InvalidInput(
                reason=_('System does not support compression.'))

        # Check that rsize is set if compression is set
        if opts['compression'] and opts['rsize'] == -1:
            raise exception.InvalidInput(
                reason=_('If compression is set to True, rsize must '
                         'also be set (not equal to -1).'))

        iogs = InStorageAssistant._get_valid_requested_io_groups(state, opts)

        if len(iogs) == 0:
            raise exception.InvalidInput(
                reason=_('Given I/O group(s) %(iogrp)s not valid; available '
                         'I/O groups are %(avail)s.')
                % {'iogrp': opts['iogrp'],
                   'avail': state['available_iogrps']})

    @staticmethod
    def _get_valid_requested_io_groups(state, opts):
        given_iogs = str(opts['iogrp'])
        iog_list = given_iogs.split(',')
        # convert to int
        iog_list = list(map(int, iog_list))
        LOG.debug("Requested iogroups %s", iog_list)
        LOG.debug("Available iogroups %s", state['available_iogrps'])
        filtiog = set(iog_list).intersection(state['available_iogrps'])
        iog_list = list(filtiog)
        LOG.debug("Filtered (valid) requested iogroups %s", iog_list)
        return iog_list

    def _get_opts_from_specs(self, opts, specs):
        qos = {}
        for k, value in specs.items():
            # Get the scope, if using scope format
            key_split = k.split(':')
            if len(key_split) == 1:
                scope = None
                key = key_split[0]
            else:
                scope = key_split[0]
                key = key_split[1]

            # We generally do not look at capabilities in the driver, but
            # replication is a special case where the user asks for
            # a volume to be replicated, and we want both the scheduler and
            # the driver to act on the value.
            if ((not scope or scope == 'capabilities') and
                    key == 'replication'):
                scope = None
                key = 'replication'
                words = value.split()
                if not (words and len(words) == 2 and words[0] == '<is>'):
                    LOG.error("Replication must be specified as "
                              "'<is> True' or '<is> False'.")
                del words[0]
                value = words[0]

            # Add the QoS.
            if scope and scope == 'qos':
                if key in self.mcs_qos_keys.keys():
                    try:
                        type_fn = self.mcs_qos_keys[key]['type']
                        value = type_fn(value)
                        qos[key] = value
                    except ValueError:
                        continue

            # Any keys that the driver should look at should have the
            # 'drivers' scope.
            if scope and scope != 'drivers':
                continue
            if key in opts:
                this_type = type(opts[key]).__name__
                if this_type == 'int':
                    value = int(value)
                elif this_type == 'bool':
                    value = strutils.bool_from_string(value)
                opts[key] = value
        if len(qos) != 0:
            opts['qos'] = qos
        return opts

    def _get_qos_from_volume_metadata(self, volume_metadata):
        """Return the QoS information from the volume metadata."""
        qos = {}
        for i in volume_metadata:
            k = i.get('key', None)
            value = i.get('value', None)
            key_split = k.split(':')
            if len(key_split) == 1:
                scope = None
                key = key_split[0]
            else:
                scope = key_split[0]
                key = key_split[1]
            # Add the QoS.
            if scope and scope == 'qos':
                if key in self.mcs_qos_keys.keys():
                    try:
                        type_fn = self.mcs_qos_keys[key]['type']
                        value = type_fn(value)
                        qos[key] = value
                    except ValueError:
                        continue
        return qos

    def _wait_for_a_condition(self, testmethod, timeout=None,
                              interval=INTERVAL_1_SEC,
                              raise_exception=False):
        start_time = time.time()
        if timeout is None:
            timeout = DEFAULT_TIMEOUT

        def _inner():
            try:
                testValue = testmethod()
            except Exception as ex:
                if raise_exception:
                    LOG.exception("_wait_for_a_condition: %s"
                                  " execution failed.",
                                  testmethod.__name__)
                    raise exception.VolumeBackendAPIException(data=ex)
                else:
                    testValue = False
                    LOG.debug('Assistant.'
                              '_wait_for_condition: %(method_name)s '
                              'execution failed for %(exception)s.',
                              {'method_name': testmethod.__name__,
                               'exception': ex.message})
            if testValue:
                raise loopingcall.LoopingCallDone()

            if int(time.time()) - start_time > timeout:
                msg = (
                    _('CommandLineAssistant._wait_for_condition: '
                      '%s timeout.') % testmethod.__name__)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        timer = loopingcall.FixedIntervalLoopingCall(_inner)
        timer.start(interval=interval).wait()

    def get_vdisk_params(self, config, state, type_id,
                         volume_type=None, volume_metadata=None):
        """Return the parameters for creating the vdisk.

        Get volume type and defaults from config options
        and take them into account.
        """
        opts = self.build_default_opts(config)
        ctxt = context.get_admin_context()
        if volume_type is None and type_id is not None:
            volume_type = volume_types.get_volume_type(ctxt, type_id)
        if volume_type:
            qos_specs_id = volume_type.get('qos_specs_id')
            specs = dict(volume_type).get('extra_specs')

            # NOTE: We prefer the qos_specs association
            # and over-ride any existing
            # extra-specs settings if present
            if qos_specs_id is not None:
                kvs = qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs']
                # Merge the qos_specs into extra_specs and qos_specs has higher
                # priority than extra_specs if they have different values for
                # the same key.
                specs.update(kvs)
            opts = self._get_opts_from_specs(opts, specs)
        if (opts['qos'] is None and config.instorage_mcs_allow_tenant_qos and
                volume_metadata):
            qos = self._get_qos_from_volume_metadata(volume_metadata)
            if len(qos) != 0:
                opts['qos'] = qos

        self.check_vdisk_opts(state, opts)
        return opts

    @staticmethod
    def _get_vdisk_create_params(opts):
        intier = 'on' if opts['intier'] else 'off'
        if opts['rsize'] == -1:
            params = []
        else:
            params = ['-rsize', '%s%%' % str(opts['rsize']),
                      '-autoexpand', '-warning',
                      '%s%%' % str(opts['warning'])]
            if not opts['autoexpand']:
                params.remove('-autoexpand')

            if opts['compression']:
                params.append('-compressed')
            else:
                params.extend(['-grainsize', str(opts['grainsize'])])

        params.extend(['-intier', intier])
        return params

    def create_vdisk(self, name, size, units, pool, opts):
        name = '"%s"' % name
        LOG.debug('Enter: create_vdisk: vdisk %s.', name)
        params = self._get_vdisk_create_params(opts)
        self.ssh.mkvdisk(name, size, units, pool, opts, params)
        LOG.debug('Leave: _create_vdisk: volume %s.', name)

    def delete_vdisk(self, vdisk, force):
        """Ensures that vdisk is not part of FC mapping and deletes it."""
        LOG.debug('Enter: delete_vdisk: vdisk %s.', vdisk)
        if not self.is_vdisk_defined(vdisk):
            LOG.info('Tried to delete non-existent vdisk %s.', vdisk)
            return
        self.ensure_vdisk_no_lc_mappings(vdisk, allow_snaps=True,
                                         allow_lctgt=True)
        self.ssh.rmvdisk(vdisk, force=force)
        LOG.debug('Leave: delete_vdisk: vdisk %s.', vdisk)

    def is_vdisk_defined(self, vdisk_name):
        """Check if vdisk is defined."""
        attrs = self.get_vdisk_attributes(vdisk_name)
        return attrs is not None

    def get_vdisk_attributes(self, vdisk):
        attrs = self.ssh.lsvdisk(vdisk)
        return attrs

    def find_vdisk_copy_id(self, vdisk, pool):
        resp = self.ssh.lsvdiskcopy(vdisk)
        for copy_id, mdisk_grp in resp.select('copy_id', 'mdisk_grp_name'):
            if mdisk_grp == pool:
                return copy_id
        msg = _('Failed to find a vdisk copy in the expected pool.')
        LOG.error(msg)
        raise exception.VolumeDriverException(message=msg)

    def get_vdisk_copy_attrs(self, vdisk, copy_id):
        return self.ssh.lsvdiskcopy(vdisk, copy_id=copy_id)[0]

    def get_vdisk_copy_ids(self, vdisk):
        resp = self.ssh.lsvdiskcopy(vdisk)
        if len(resp) == 2:
            if resp[0]['primary'] == 'yes':
                primary = resp[0]['copy_id']
                secondary = resp[1]['copy_id']
            else:
                primary = resp[1]['copy_id']
                secondary = resp[0]['copy_id']

            return primary, secondary
        else:
            msg = (_('list_vdisk_copy failed: No copy of volume %s exists.')
                   % vdisk)
            raise exception.VolumeDriverException(message=msg)

    def get_vdisk_copies(self, vdisk):
        copies = {'primary': None,
                  'secondary': None}

        resp = self.ssh.lsvdiskcopy(vdisk)
        for copy_id, status, sync, primary, mdisk_grp in (
            resp.select('copy_id', 'status', 'sync',
                        'primary', 'mdisk_grp_name')):
            copy = {'copy_id': copy_id,
                    'status': status,
                    'sync': sync,
                    'primary': primary,
                    'mdisk_grp_name': mdisk_grp,
                    'sync_progress': None}
            if copy['sync'] != 'yes':
                progress_info = self.ssh.lsvdisksyncprogress(vdisk, copy_id)
                copy['sync_progress'] = progress_info['progress']
            if copy['primary'] == 'yes':
                copies['primary'] = copy
            else:
                copies['secondary'] = copy
        return copies

    def create_copy(self, src, tgt, src_id, config, opts,
                    full_copy, pool=None):
        """Create a new snapshot using LocalCopy."""
        LOG.debug('Enter: create_copy: snapshot %(src)s to %(tgt)s.',
                  {'tgt': tgt, 'src': src})

        src_attrs = self.get_vdisk_attributes(src)
        if src_attrs is None:
            msg = (_('create_copy: Source vdisk %(src)s (%(src_id)s) '
                     'does not exist.') % {'src': src, 'src_id': src_id})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        src_size = src_attrs['capacity']
        # In case we need to use a specific pool
        if not pool:
            pool = src_attrs['mdisk_grp_name']

        opts['iogrp'] = src_attrs['IO_group_id']
        self.create_vdisk(tgt, src_size, 'b', pool, opts)
        timeout = config.instorage_mcs_localcopy_timeout
        try:
            self.run_localcopy(src, tgt, timeout,
                               config.instorage_mcs_localcopy_rate,
                               full_copy=full_copy)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.delete_vdisk(tgt, True)

        LOG.debug('Leave: _create_copy: snapshot %(tgt)s from '
                  'vdisk %(src)s.',
                  {'tgt': tgt, 'src': src})

    def extend_vdisk(self, vdisk, amount):
        self.ssh.expandvdisksize(vdisk, amount)

    def add_vdisk_copy(self, vdisk, dest_pool, volume_type, state, config):
        """Add a vdisk copy in the given pool."""
        resp = self.ssh.lsvdiskcopy(vdisk)
        if len(resp) > 1:
            msg = (_('add_vdisk_copy failed: A copy of volume %s exists. '
                     'Adding another copy would exceed the limit of '
                     '2 copies.') % vdisk)
            raise exception.VolumeDriverException(message=msg)
        orig_copy_id = resp[0].get("copy_id", None)

        if orig_copy_id is None:
            msg = (_('add_vdisk_copy started without a vdisk copy in the '
                     'expected pool.'))
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        if volume_type is None:
            opts = self.get_vdisk_params(config, state, None)
        else:
            opts = self.get_vdisk_params(config, state, volume_type['id'],
                                         volume_type=volume_type)
        params = self._get_vdisk_create_params(opts)
        new_copy_id = self.ssh.addvdiskcopy(vdisk, dest_pool, params)
        return (orig_copy_id, new_copy_id)

    def check_vdisk_copy_synced(self, vdisk, copy_id):
        sync = self.ssh.lsvdiskcopy(vdisk, copy_id=copy_id)[0]['sync']
        if sync == 'yes':
            return True
        return False

    def rm_vdisk_copy(self, vdisk, copy_id):
        self.ssh.rmvdiskcopy(vdisk, copy_id)

    def _prepare_lc_map(self, lc_map_id, timeout):
        self.ssh.prestartlcmap(lc_map_id)
        mapping_ready = False
        max_retries = (timeout // self.WAIT_TIME) + 1
        for try_number in range(1, max_retries):
            mapping_attrs = self._get_localcopy_mapping_attributes(lc_map_id)
            if (mapping_attrs is None or
                    'status' not in mapping_attrs):
                break
            if mapping_attrs['status'] == 'prepared':
                mapping_ready = True
                break
            elif mapping_attrs['status'] == 'stopped':
                self.ssh.prestartlcmap(lc_map_id)
            elif mapping_attrs['status'] != 'preparing':
                msg = (_('Unexecpted mapping status %(status)s for mapping '
                         '%(id)s. Attributes: %(attr)s.')
                       % {'status': mapping_attrs['status'],
                          'id': lc_map_id,
                          'attr': mapping_attrs})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            greenthread.sleep(self.WAIT_TIME)

        if not mapping_ready:
            msg = (_('Mapping %(id)s prepare failed to complete within the '
                     'allotted %(to)d seconds timeout. Terminating.')
                   % {'id': lc_map_id,
                      'to': timeout})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    # Consistency Group
    def start_lc_consistgrp(self, lc_consistgrp):
        self.ssh.startlcconsistgrp(lc_consistgrp)

    def create_lc_consistgrp(self, lc_consistgrp):
        self.ssh.mklcconsistgrp(lc_consistgrp)

    def delete_lc_consistgrp(self, lc_consistgrp):
        self.ssh.rmlcconsistgrp(lc_consistgrp)

    def stop_lc_consistgrp(self, lc_consistgrp):
        self.ssh.stoplcconsistgrp(lc_consistgrp)

    def run_consistgrp_snapshots(self, lc_consistgrp, snapshots, state,
                                 config, timeout):
        model_update = {'status': fields.ConsistencyGroupStatus.AVAILABLE}
        snapshots_model_update = []
        try:
            for snapshot in snapshots:
                opts = self.get_vdisk_params(config, state,
                                             snapshot.volume_type_id)

                self.create_localcopy_to_consistgrp(snapshot.volume_name,
                                                    snapshot.name,
                                                    lc_consistgrp,
                                                    config, opts)

            self.prepare_lc_consistgrp(lc_consistgrp, timeout)
            self.start_lc_consistgrp(lc_consistgrp)
            # There is CG limitation that could not create more than 128 CGs.
            # After start CG, we delete CG to avoid CG limitation.
            # Cinder general will maintain the CG and snapshots relationship.
            self.delete_lc_consistgrp(lc_consistgrp)
        except exception.VolumeBackendAPIException as err:
            model_update['status'] = fields.ConsistencyGroupStatus.ERROR
            # Release cg
            self.delete_lc_consistgrp(lc_consistgrp)
            LOG.error("Failed to create CGSnapshot. "
                      "Exception: %s.", err)

        for snapshot in snapshots:
            snapshots_model_update.append(
                {'id': snapshot.id,
                 'status': model_update['status']})

        return model_update, snapshots_model_update

    def delete_consistgrp_snapshots(self, lc_consistgrp, snapshots):
        """Delete localcopy maps and consistent group."""
        model_update = {'status': fields.ConsistencyGroupStatus.DELETED}
        snapshots_model_update = []

        try:
            for snapshot in snapshots:
                self.ssh.rmvdisk(snapshot.name, True)
        except exception.VolumeBackendAPIException as err:
            model_update['status'] = (
                fields.ConsistencyGroupStatus.ERROR_DELETING)
            LOG.error("Failed to delete the snapshot %(snap)s of "
                      "CGSnapshot. Exception: %(exception)s.",
                      {'snap': snapshot.name, 'exception': err})

        for snapshot in snapshots:
            snapshots_model_update.append(
                {'id': snapshot.id,
                 'status': model_update['status']})

        return model_update, snapshots_model_update

    def run_group_snapshots(self, lc_group, snapshots, state,
                            config, timeout):
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        snapshots_model_update = []
        try:
            for snapshot in snapshots:
                opts = self.get_vdisk_params(config, state,
                                             snapshot.volume_type_id)

                self.create_localcopy_to_consistgrp(snapshot.volume_name,
                                                    snapshot.name,
                                                    lc_group,
                                                    config, opts)

            self.prepare_lc_consistgrp(lc_group, timeout)
            self.start_lc_consistgrp(lc_group)
            # There is CG limitation that could not create more than 128 CGs.
            # After start CG, we delete CG to avoid CG limitation.
            # Cinder general will maintain the group and snapshots
            # relationship.
            self.delete_lc_consistgrp(lc_group)
        except exception.VolumeBackendAPIException as err:
            model_update['status'] = fields.GroupStatus.ERROR
            # Release cg
            self.delete_lc_consistgrp(lc_group)
            LOG.error("Failed to create Group_Snapshot. "
                      "Exception: %s.", err)

        for snapshot in snapshots:
            snapshots_model_update.append(
                {'id': snapshot.id,
                 'status': model_update['status']})

        return model_update, snapshots_model_update

    def delete_group_snapshots(self, lc_group, snapshots):
        """Delete localcopy maps and group."""
        model_update = {'status': fields.GroupStatus.DELETED}
        snapshots_model_update = []

        try:
            for snapshot in snapshots:
                self.ssh.rmvdisk(snapshot.name, True)
        except exception.VolumeBackendAPIException as err:
            model_update['status'] = (
                fields.GroupStatus.ERROR_DELETING)
            LOG.error("Failed to delete the snapshot %(snap)s of "
                      "Group_Snapshot. Exception: %(exception)s.",
                      {'snap': snapshot.name, 'exception': err})

        for snapshot in snapshots:
            snapshots_model_update.append(
                {'id': snapshot.id,
                 'status': model_update['status']})

        return model_update, snapshots_model_update

    def prepare_lc_consistgrp(self, lc_consistgrp, timeout):
        """Prepare LC Consistency Group."""
        self.ssh.prestartlcconsistgrp(lc_consistgrp)

        def prepare_lc_consistgrp_success():
            mapping_ready = False
            mapping_attrs = self._get_localcopy_consistgrp_attr(lc_consistgrp)
            if (mapping_attrs is None or
                    'status' not in mapping_attrs):
                pass
            if mapping_attrs['status'] == 'prepared':
                mapping_ready = True
            elif mapping_attrs['status'] == 'stopped':
                self.ssh.prestartlcconsistgrp(lc_consistgrp)
            elif mapping_attrs['status'] != 'preparing':
                msg = (_('Unexpected mapping status %(status)s for mapping '
                         '%(id)s. Attributes: %(attr)s.') %
                       {'status': mapping_attrs['status'],
                        'id': lc_consistgrp,
                        'attr': mapping_attrs})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            return mapping_ready
        self._wait_for_a_condition(prepare_lc_consistgrp_success, timeout)

    def create_group_from_source(self, group, lc_group,
                                 sources, targets, state,
                                 config, timeout):
        """Create group from source"""
        LOG.debug('Enter: create_group_from_source: group %(group)s'
                  ' source %(source)s, target %(target)s',
                  {'group': lc_group, 'source': sources, 'target': targets})
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        ctxt = context.get_admin_context()
        try:
            for source, target in zip(sources, targets):
                opts = self.get_vdisk_params(config, state,
                                             source.volume_type_id)
                pool = utils.extract_host(target.host, 'pool')
                self.create_localcopy_to_consistgrp(source.name,
                                                    target.name,
                                                    lc_group,
                                                    config, opts,
                                                    True, pool=pool)
            self.prepare_lc_consistgrp(lc_group, timeout)
            self.start_lc_consistgrp(lc_group)
            self.delete_lc_consistgrp(lc_group)
            volumes_model_update = self._get_volume_model_updates(
                ctxt, targets, group.id, model_update['status'])
        except exception.VolumeBackendAPIException as err:
            model_update['status'] = fields.GroupStatus.ERROR
            volumes_model_update = self._get_volume_model_updates(
                ctxt, targets, group.id, model_update['status'])
            with excutils.save_and_reraise_exception():
                self.delete_lc_consistgrp(lc_group)
                LOG.error("Failed to create group from group_snapshot. "
                          "Exception: %s", err)
            return model_update, volumes_model_update

        LOG.debug('Leave: create_cg_from_source.')
        return model_update, volumes_model_update

    def _get_volume_model_updates(self, ctxt, volumes, cgId,
                                  status='available'):
        """Update the volume model's status and return it."""
        volume_model_updates = []
        LOG.info("Updating status for CG: %(id)s.", {'id': cgId})
        if volumes:
            for volume in volumes:
                volume_model_updates.append({'id': volume.id,
                                             'status': status})
        else:
            LOG.info("No volume found for CG: %(cg)s.", {'cg': cgId})
        return volume_model_updates

    def run_localcopy(self, source, target, timeout, copy_rate,
                      full_copy=True):
        """Create a LocalCopy mapping from the source to the target."""
        LOG.debug('Enter: run_localcopy: execute LocalCopy from source '
                  '%(source)s to target %(target)s.',
                  {'source': source, 'target': target})

        lc_map_id = self.ssh.mklcmap(source, target, full_copy, copy_rate)
        self._prepare_lc_map(lc_map_id, timeout)
        self.ssh.startlcmap(lc_map_id)

        LOG.debug('Leave: run_localcopy: LocalCopy started from '
                  '%(source)s to %(target)s.',
                  {'source': source, 'target': target})

    def create_localcopy_to_consistgrp(self, source, target, consistgrp,
                                       config, opts, full_copy=False,
                                       pool=None):
        """Create a LocalCopy mapping and add to consistent group."""
        LOG.debug('Enter: create_localcopy_to_consistgrp: create LocalCopy '
                  'from source %(source)s to target %(target)s. '
                  'Then add the localcopy to %(cg)s.',
                  {'source': source, 'target': target, 'cg': consistgrp})

        src_attrs = self.get_vdisk_attributes(source)
        if src_attrs is None:
            msg = (_('create_copy: Source vdisk %(src)s '
                     'does not exist.') % {'src': source})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        src_size = src_attrs['capacity']
        # In case we need to use a specific pool
        if not pool:
            pool = src_attrs['mdisk_grp_name']
        opts['iogrp'] = src_attrs['IO_group_id']
        self.create_vdisk(target, src_size, 'b', pool, opts)

        self.ssh.mklcmap(source, target, full_copy,
                         config.instorage_mcs_localcopy_rate,
                         consistgrp=consistgrp)

        LOG.debug('Leave: create_localcopy_to_consistgrp: '
                  'LocalCopy started from  %(source)s to %(target)s.',
                  {'source': source, 'target': target})

    def _get_vdisk_lc_mappings(self, vdisk):
        """Return LocalCopy mappings that this vdisk is associated with."""
        mapping_ids = []
        resp = self.ssh.lsvdisklcmappings(vdisk)
        for id in resp.select('id'):
            mapping_ids.append(id)
        return mapping_ids

    def _get_localcopy_mapping_attributes(self, lc_map_id):
        resp = self.ssh.lslcmap(lc_map_id)
        if not len(resp):
            return None
        return resp[0]

    def _get_localcopy_consistgrp_attr(self, lc_map_id):
        resp = self.ssh.lslcconsistgrp(lc_map_id)
        if not len(resp):
            return None
        return resp[0]

    def _check_vdisk_lc_mappings(self, name,
                                 allow_snaps=True, allow_lctgt=False):
        """LocalCopy mapping check helper."""
        LOG.debug('Loopcall: _check_vdisk_lc_mappings(), vdisk %s.', name)
        mapping_ids = self._get_vdisk_lc_mappings(name)
        wait_for_copy = False
        rmlcmap_failed_e = None
        for map_id in mapping_ids:
            attrs = self._get_localcopy_mapping_attributes(map_id)
            if not attrs:
                continue
            source = attrs['source_vdisk_name']
            target = attrs['target_vdisk_name']
            copy_rate = attrs['copy_rate']
            status = attrs['status']

            if allow_lctgt and target == name and status == 'copying':
                self.ssh.stoplcmap(map_id)
                attrs = self._get_localcopy_mapping_attributes(map_id)
                if attrs:
                    status = attrs['status']

            if copy_rate == '0':
                if source == name:
                    # Vdisk with snapshots. Return False if snapshot
                    # not allowed.
                    if not allow_snaps:
                        raise loopingcall.LoopingCallDone(retvalue=False)
                    self.ssh.chlcmap(map_id, copyrate='50', autodel='on')
                    wait_for_copy = True
                else:
                    # A snapshot
                    if target != name:
                        msg = (_('Vdisk %(name)s not involved in '
                                 'mapping %(src)s -> %(tgt)s.') %
                               {'name': name, 'src': source, 'tgt': target})
                        LOG.error(msg)
                        raise exception.VolumeDriverException(message=msg)
                    if status in ['copying', 'prepared']:
                        self.ssh.stoplcmap(map_id)
                        # Need to wait for the lcmap to change to
                        # stopped state before remove lcmap
                        wait_for_copy = True
                    elif status in ['stopping', 'preparing']:
                        wait_for_copy = True
                    else:
                        try:
                            self.ssh.rmlcmap(map_id)
                        except exception.VolumeBackendAPIException as e:
                            rmlcmap_failed_e = e
            # Case 4: Copy in progress - wait and will autodelete
            else:
                if status == 'prepared':
                    self.ssh.stoplcmap(map_id)
                    self.ssh.rmlcmap(map_id)
                elif status in ['idle_or_copied', 'stopped']:
                    # Prepare failed or stopped
                    self.ssh.rmlcmap(map_id)
                else:
                    wait_for_copy = True

        if not wait_for_copy and rmlcmap_failed_e is not None:
            raise rmlcmap_failed_e

        if not wait_for_copy or not len(mapping_ids):
            raise loopingcall.LoopingCallDone(retvalue=True)

    def ensure_vdisk_no_lc_mappings(self, name, allow_snaps=True,
                                    allow_lctgt=False):
        """Ensure vdisk has no localcopy mappings."""
        timer = loopingcall.FixedIntervalLoopingCall(
            self._check_vdisk_lc_mappings, name,
            allow_snaps, allow_lctgt)
        # Create a timer greenthread. The default volume service heart
        # beat is every 10 seconds. The localcopy usually takes hours
        # before it finishes. Don't set the sleep interval shorter
        # than the heartbeat. Otherwise volume service heartbeat
        # will not be serviced.
        LOG.debug('Calling _ensure_vdisk_no_lc_mappings: vdisk %s.',
                  name)
        ret = timer.start(interval=self.check_lcmapping_interval).wait()
        timer.stop()
        return ret

    def start_relationship(self, volume_name, primary=None):
        vol_attrs = self.get_vdisk_attributes(volume_name)
        if vol_attrs['RC_name']:
            self.ssh.startrcrelationship(vol_attrs['RC_name'], primary)

    def stop_relationship(self, volume_name, access=False):
        vol_attrs = self.get_vdisk_attributes(volume_name)
        if vol_attrs['RC_name']:
            self.ssh.stoprcrelationship(vol_attrs['RC_name'], access=access)

    def create_relationship(self, master, aux, system, asynccopy):
        try:
            rc_id = self.ssh.mkrcrelationship(master, aux, system,
                                              asynccopy)
        except exception.VolumeBackendAPIException as e:
            # CMMVC5959E is the code in InStorage, meaning that
            # there is a relationship that already has this name on the
            # master cluster.
            if 'CMMVC5959E' not in six.text_type(e):
                # If there is no relation between the primary and the
                # secondary back-end storage, the exception is raised.
                raise
        if rc_id:
            self.start_relationship(master)

    def delete_relationship(self, volume_name):
        vol_attrs = self.get_vdisk_attributes(volume_name)
        if vol_attrs['RC_name']:
            self.ssh.rmrcrelationship(vol_attrs['RC_name'], True)

    def get_relationship_info(self, volume_name):
        vol_attrs = self.get_vdisk_attributes(volume_name)
        if not vol_attrs or not vol_attrs['RC_name']:
            LOG.info("Unable to get remote copy information for "
                     "volume %s", volume_name)
            return

        relationship = self.ssh.lsrcrelationship(vol_attrs['RC_name'])
        return relationship[0] if len(relationship) > 0 else None

    def delete_rc_volume(self, volume_name, target_vol=False):
        vol_name = volume_name
        if target_vol:
            vol_name = instorage_const.REPLICA_AUX_VOL_PREFIX + volume_name

        try:
            rel_info = self.get_relationship_info(vol_name)
            if rel_info:
                self.delete_relationship(vol_name)
            self.delete_vdisk(vol_name, False)
        except Exception as e:
            msg = (_('Unable to delete the volume for '
                     'volume %(vol)s. Exception: %(err)s.') %
                   {'vol': vol_name, 'err': e})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def switch_relationship(self, relationship, aux=True):
        self.ssh.switchrelationship(relationship, aux)

    def get_partnership_info(self, system_name):
        partnership = self.ssh.lspartnership(system_name)
        return partnership[0] if len(partnership) > 0 else None

    def get_partnershipcandidate_info(self, system_name):
        candidates = self.ssh.lspartnershipcandidate()
        for candidate in candidates:
            if system_name == candidate['name']:
                return candidate
        return None

    def mkippartnership(self, ip_v4, bandwidth=1000, copyrate=50):
        self.ssh.mkippartnership(ip_v4, bandwidth, copyrate)

    def mkfcpartnership(self, system_name, bandwidth=1000, copyrate=50):
        self.ssh.mkfcpartnership(system_name, bandwidth, copyrate)

    def chpartnership(self, partnership_id):
        self.ssh.chpartnership(partnership_id)

    @staticmethod
    def can_migrate_to_host(host, state):
        if 'location_info' not in host['capabilities']:
            return None
        info = host['capabilities']['location_info']
        try:
            (dest_type, dest_id, dest_pool) = info.split(':')
        except ValueError:
            return None
        if (dest_type != 'InStorageMCSDriver' or dest_id !=
                state['system_id']):
            return None
        return dest_pool

    def add_vdisk_qos(self, vdisk, qos):
        """Add the QoS configuration to the volume."""
        for key, value in qos.items():
            if key in self.mcs_qos_keys.keys():
                param = self.mcs_qos_keys[key]['param']
                self.ssh.chvdisk(vdisk, ['-' + param, str(value)])

    def update_vdisk_qos(self, vdisk, qos):
        """Update all the QoS in terms of a key and value.

        mcs_qos_keys saves all the supported QoS parameters. Going through
        this dict, we set the new values to all the parameters. If QoS is
        available in the QoS configuration, the value is taken from it;
        if not, the value will be set to default.
        """
        for key, value in self.mcs_qos_keys.items():
            param = value['param']
            if key in qos.keys():
                # If the value is set in QoS, take the value from
                # the QoS configuration.
                v = qos[key]
            else:
                # If not, set the value to default.
                v = value['default']
            self.ssh.chvdisk(vdisk, ['-' + param, str(v)])

    def disable_vdisk_qos(self, vdisk, qos):
        """Disable the QoS."""
        for key, value in qos.items():
            if key in self.mcs_qos_keys.keys():
                param = self.mcs_qos_keys[key]['param']
                # Take the default value.
                value = self.mcs_qos_keys[key]['default']
                self.ssh.chvdisk(vdisk, ['-' + param, value])

    def change_vdisk_options(self, vdisk, changes, opts, state):
        if 'warning' in opts:
            opts['warning'] = '%s%%' % str(opts['warning'])
        if 'intier' in opts:
            opts['intier'] = 'on' if opts['intier'] else 'off'
        if 'autoexpand' in opts:
            opts['autoexpand'] = 'on' if opts['autoexpand'] else 'off'

        for key in changes:
            self.ssh.chvdisk(vdisk, ['-' + key, opts[key]])

    def change_vdisk_iogrp(self, vdisk, state, iogrp):
        if state['code_level'] < (3, 0, 0, 0):
            LOG.debug('Ignore change IO group as storage code level is '
                      '%(code_level)s, below the required 3, 0, 0, 0.',
                      {'code_level': state['code_level']})
        else:
            self.ssh.movevdisk(vdisk, str(iogrp[0]))
            self.ssh.addvdiskaccess(vdisk, str(iogrp[0]))
            self.ssh.rmvdiskaccess(vdisk, str(iogrp[1]))

    def vdisk_by_uid(self, vdisk_uid):
        """Returns the properties of the vdisk with the specified UID.

        Returns None if no such disk exists.
        """

        vdisks = self.ssh.lsvdisks_from_filter('vdisk_UID', vdisk_uid)

        if len(vdisks) == 0:
            return None

        if len(vdisks) != 1:
            msg = (_('Expected single vdisk returned from lsvdisk when '
                     'filtering on vdisk_UID.  %(count)s were returned.') %
                   {'count': len(vdisks)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        vdisk = vdisks.result[0]

        return self.ssh.lsvdisk(vdisk['name'])

    def is_vdisk_in_use(self, vdisk):
        """Returns True if the specified vdisk is mapped to at least 1 host."""
        resp = self.ssh.lsvdiskhostmap(vdisk)
        return len(resp) != 0

    def rename_vdisk(self, vdisk, new_name):
        self.ssh.chvdisk(vdisk, ['-name', new_name])

    def change_vdisk_primary_copy(self, vdisk, copy_id):
        self.ssh.chvdisk(vdisk, ['-primary', copy_id])


class InStorageSSH(object):
    """SSH interface to Inspur InStorage systems."""

    def __init__(self, run_ssh):
        self._ssh = run_ssh

    def _run_ssh(self, ssh_cmd):
        try:
            return self._ssh(ssh_cmd)
        except processutils.ProcessExecutionError as e:
            msg = (_('CLI Exception output:\n command: %(cmd)s\n '
                     'stdout: %(out)s\n stderr: %(err)s.') %
                   {'cmd': ssh_cmd,
                    'out': e.stdout,
                    'err': e.stderr})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def run_ssh_inq(self, ssh_cmd, delim='!', with_header=False):
        """Run an SSH command and return parsed output."""
        raw = self._run_ssh(ssh_cmd)
        return CLIParser(raw, ssh_cmd=ssh_cmd, delim=delim,
                         with_header=with_header)

    def run_ssh_assert_no_output(self, ssh_cmd):
        """Run an SSH command and assert no output returned."""
        out, err = self._run_ssh(ssh_cmd)
        if len(out.strip()) != 0:
            msg = (_('Expected no output from CLI command %(cmd)s, '
                     'got %(out)s.') % {'cmd': ' '.join(ssh_cmd), 'out': out})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def run_ssh_check_created(self, ssh_cmd):
        """Run an SSH command and return the ID of the created object."""
        out, err = self._run_ssh(ssh_cmd)
        try:
            match_obj = re.search(r'\[([0-9]+)\],? successfully created', out)
            return match_obj.group(1)
        except (AttributeError, IndexError):
            msg = (_('Failed to parse CLI output:\n command: %(cmd)s\n '
                     'stdout: %(out)s\n stderr: %(err)s.') %
                   {'cmd': ssh_cmd,
                    'out': out,
                    'err': err})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def lsnode(self, node_id=None):
        with_header = True
        ssh_cmd = ['mcsinq', 'lsnode', '-delim', '!']
        if node_id:
            with_header = False
            ssh_cmd.append(node_id)
        return self.run_ssh_inq(ssh_cmd, with_header=with_header)

    def lslicense(self):
        ssh_cmd = ['mcsinq', 'lslicense', '-delim', '!']
        return self.run_ssh_inq(ssh_cmd)[0]

    def lsguicapabilities(self):
        ssh_cmd = ['mcsinq', 'lsguicapabilities', '-delim', '!']
        return self.run_ssh_inq(ssh_cmd)[0]

    def lssystem(self):
        ssh_cmd = ['mcsinq', 'lssystem', '-delim', '!']
        return self.run_ssh_inq(ssh_cmd)[0]

    def lsmdiskgrp(self, pool):
        ssh_cmd = ['mcsinq', 'lsmdiskgrp', '-bytes', '-delim', '!',
                   '"%s"' % pool]
        return self.run_ssh_inq(ssh_cmd)[0]

    def lsiogrp(self):
        ssh_cmd = ['mcsinq', 'lsiogrp', '-delim', '!']
        return self.run_ssh_inq(ssh_cmd, with_header=True)

    def lsportip(self):
        ssh_cmd = ['mcsinq', 'lsportip', '-delim', '!']
        return self.run_ssh_inq(ssh_cmd, with_header=True)

    def lshost(self, host=None):
        with_header = True
        ssh_cmd = ['mcsinq', 'lshost', '-delim', '!']
        if host:
            with_header = False
            ssh_cmd.append('"%s"' % host)
        return self.run_ssh_inq(ssh_cmd, with_header=with_header)

    def lsiscsiauth(self):
        ssh_cmd = ['mcsinq', 'lsiscsiauth', '-delim', '!']
        return self.run_ssh_inq(ssh_cmd, with_header=True)

    def lsfabric(self, wwpn=None, host=None):
        ssh_cmd = ['mcsinq', 'lsfabric', '-delim', '!']
        if wwpn:
            ssh_cmd.extend(['-wwpn', wwpn])
        elif host:
            ssh_cmd.extend(['-host', '"%s"' % host])
        else:
            msg = (_('Must pass wwpn or host to lsfabric.'))
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        return self.run_ssh_inq(ssh_cmd, with_header=True)

    def lsrcrelationship(self, rc_rel):
        key_value = 'name=%s' % rc_rel
        ssh_cmd = ['mcsinq', 'lsrcrelationship', '-filtervalue',
                   key_value, '-delim', '!']
        return self.run_ssh_inq(ssh_cmd, with_header=True)

    def lspartnership(self, system_name):
        key_value = 'name=%s' % system_name
        ssh_cmd = ['mcsinq', 'lspartnership', '-filtervalue',
                   key_value, '-delim', '!']
        return self.run_ssh_inq(ssh_cmd, with_header=True)

    def lspartnershipcandidate(self):
        ssh_cmd = ['mcsinq', 'lspartnershipcandidate', '-delim', '!']
        return self.run_ssh_inq(ssh_cmd, with_header=True)

    def lsvdiskhostmap(self, vdisk):
        ssh_cmd = ['mcsinq', 'lsvdiskhostmap', '-delim', '!', '"%s"' % vdisk]
        return self.run_ssh_inq(ssh_cmd, with_header=True)

    def lshostvdiskmap(self, host):
        ssh_cmd = ['mcsinq', 'lshostvdiskmap', '-delim', '!', '"%s"' % host]
        return self.run_ssh_inq(ssh_cmd, with_header=True)

    def lsvdisk(self, vdisk):
        """Return vdisk attributes or None if it doesn't exist."""
        ssh_cmd = ['mcsinq', 'lsvdisk', '-bytes', '-delim', '!',
                   '"%s"' % vdisk]
        out, err = self._ssh(ssh_cmd, check_exit_code=False)
        if not err:
            return CLIParser((out, err), ssh_cmd=ssh_cmd, delim='!',
                             with_header=False)[0]
        if 'CMMVC5754E' in err:
            return None
        msg = (_('CLI Exception output:\n command: %(cmd)s\n '
                 'stdout: %(out)s\n stderr: %(err)s.') %
               {'cmd': ssh_cmd,
                'out': out,
                'err': err})
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    def lsvdisks_from_filter(self, filter_name, value):
        """Performs an lsvdisk command, filtering the results as specified.

        Returns an iterable for all matching vdisks.
        """
        ssh_cmd = ['mcsinq', 'lsvdisk', '-bytes', '-delim', '!',
                   '-filtervalue', '%s=%s' % (filter_name, value)]
        return self.run_ssh_inq(ssh_cmd, with_header=True)

    def lsvdisklcmappings(self, vdisk):
        ssh_cmd = ['mcsinq', 'lsvdisklcmappings', '-delim', '!',
                   '"%s"' % vdisk]
        return self.run_ssh_inq(ssh_cmd, with_header=True)

    def lslcmap(self, lc_map_id):
        ssh_cmd = ['mcsinq', 'lslcmap', '-filtervalue',
                   'id=%s' % lc_map_id, '-delim', '!']
        return self.run_ssh_inq(ssh_cmd, with_header=True)

    def lslcconsistgrp(self, lc_consistgrp):
        ssh_cmd = ['mcsinq', 'lslcconsistgrp', '-delim', '!', lc_consistgrp]
        out, err = self._ssh(ssh_cmd)
        return CLIParser((out, err), ssh_cmd=ssh_cmd, delim='!',
                         with_header=False)

    def lsvdiskcopy(self, vdisk, copy_id=None):
        ssh_cmd = ['mcsinq', 'lsvdiskcopy', '-delim', '!']
        with_header = True
        if copy_id:
            ssh_cmd += ['-copy', copy_id]
            with_header = False
        ssh_cmd += ['"%s"' % vdisk]
        return self.run_ssh_inq(ssh_cmd, with_header=with_header)

    def lsvdisksyncprogress(self, vdisk, copy_id):
        ssh_cmd = ['mcsinq', 'lsvdisksyncprogress', '-delim', '!',
                   '-copy', copy_id, '"%s"' % vdisk]
        return self.run_ssh_inq(ssh_cmd, with_header=True)[0]

    def lsportfc(self, node_id):
        ssh_cmd = ['mcsinq', 'lsportfc', '-delim', '!',
                   '-filtervalue', 'node_id=%s' % node_id]
        return self.run_ssh_inq(ssh_cmd, with_header=True)

    @staticmethod
    def _create_port_arg(port_type, port_name):
        if port_type == 'initiator':
            port = ['-iscsiname']
        else:
            port = ['-hbawwpn']
        port.append(port_name)
        return port

    def mkhost(self, host_name, port_type, port_name):
        port = self._create_port_arg(port_type, port_name)
        ssh_cmd = ['mcsop', 'mkhost', '-force'] + port
        ssh_cmd += ['-name', '"%s"' % host_name]
        return self.run_ssh_check_created(ssh_cmd)

    def addhostport(self, host, port_type, port_name):
        port = self._create_port_arg(port_type, port_name)
        ssh_cmd = ['mcsop', 'addhostport', '-force'] + port + ['"%s"' % host]
        self.run_ssh_assert_no_output(ssh_cmd)

    def add_chap_secret(self, secret, host):
        ssh_cmd = ['mcsop', 'chhost', '-chapsecret', secret, '"%s"' % host]
        self.run_ssh_assert_no_output(ssh_cmd)

    def mkvdiskhostmap(self, host, vdisk, lun, multihostmap):
        """Map vdisk to host.

        If vdisk already mapped and multihostmap is True, use the force flag.
        """
        ssh_cmd = ['mcsop', 'mkvdiskhostmap', '-host', '"%s"' % host, vdisk]

        if lun:
            ssh_cmd.insert(ssh_cmd.index(vdisk), '-scsi')
            ssh_cmd.insert(ssh_cmd.index(vdisk), lun)

        if multihostmap:
            ssh_cmd.insert(ssh_cmd.index('mkvdiskhostmap') + 1, '-force')
        try:
            self.run_ssh_check_created(ssh_cmd)
            result_lun = self.get_vdiskhostmapid(vdisk, host)
            if result_lun is None or (lun and lun != result_lun):
                msg = (_('mkvdiskhostmap error:\n command: %(cmd)s\n '
                         'lun: %(lun)s\n result_lun: %(result_lun)s') %
                       {'cmd': ssh_cmd,
                        'lun': lun,
                        'result_lun': result_lun})
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
            return result_lun
        except Exception as ex:
            if (not multihostmap and hasattr(ex, 'message') and
                    'CMMVC6071E' in ex.message):
                LOG.error('volume is not allowed to be mapped to multi host')
                raise exception.VolumeDriverException(
                    message=_('CMMVC6071E The VDisk-to-host mapping was not '
                              'created because the VDisk is already mapped '
                              'to a host.\n"'))
            with excutils.save_and_reraise_exception():
                LOG.error('Error mapping VDisk-to-host')

    def mkrcrelationship(self, master, aux, system, asynccopy):
        ssh_cmd = ['mcsop', 'mkrcrelationship', '-master', master,
                   '-aux', aux, '-cluster', system]
        if asynccopy:
            ssh_cmd.append('-async')
        return self.run_ssh_check_created(ssh_cmd)

    def rmrcrelationship(self, relationship, force=False):
        ssh_cmd = ['mcsop', 'rmrcrelationship']
        if force:
            ssh_cmd += ['-force']
        ssh_cmd += [relationship]
        self.run_ssh_assert_no_output(ssh_cmd)

    def switchrelationship(self, relationship, aux=True):
        primary = 'aux' if aux else 'master'
        ssh_cmd = ['mcsop', 'switchrcrelationship', '-primary',
                   primary, relationship]
        self.run_ssh_assert_no_output(ssh_cmd)

    def startrcrelationship(self, rc_rel, primary=None):
        ssh_cmd = ['mcsop', 'startrcrelationship', '-force']
        if primary:
            ssh_cmd.extend(['-primary', primary])
        ssh_cmd.append(rc_rel)
        self.run_ssh_assert_no_output(ssh_cmd)

    def stoprcrelationship(self, relationship, access=False):
        ssh_cmd = ['mcsop', 'stoprcrelationship']
        if access:
            ssh_cmd.append('-access')
        ssh_cmd.append(relationship)
        self.run_ssh_assert_no_output(ssh_cmd)

    def mkippartnership(self, ip_v4, bandwidth=1000, backgroundcopyrate=50):
        ssh_cmd = ['mcsop', 'mkippartnership', '-type', 'ipv4',
                   '-clusterip', ip_v4, '-linkbandwidthmbits',
                   six.text_type(bandwidth),
                   '-backgroundcopyrate', six.text_type(backgroundcopyrate)]
        return self.run_ssh_assert_no_output(ssh_cmd)

    def mkfcpartnership(self, system_name, bandwidth=1000,
                        backgroundcopyrate=50):
        ssh_cmd = ['mcsop', 'mkfcpartnership', '-linkbandwidthmbits',
                   six.text_type(bandwidth),
                   '-backgroundcopyrate', six.text_type(backgroundcopyrate),
                   system_name]
        return self.run_ssh_assert_no_output(ssh_cmd)

    def chpartnership(self, partnership_id, start=True):
        action = '-start' if start else '-stop'
        ssh_cmd = ['mcsop', 'chpartnership', action, partnership_id]
        return self.run_ssh_assert_no_output(ssh_cmd)

    def rmvdiskhostmap(self, host, vdisk):
        ssh_cmd = ['mcsop', 'rmvdiskhostmap', '-host', '"%s"' % host,
                   '"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def get_vdiskhostmapid(self, vdisk, host):
        resp = self.lsvdiskhostmap(vdisk)
        for mapping_info in resp:
            if mapping_info['host_name'] == host:
                lun_id = mapping_info['SCSI_id']
                return lun_id
        return None

    def rmhost(self, host):
        ssh_cmd = ['mcsop', 'rmhost', '"%s"' % host]
        self.run_ssh_assert_no_output(ssh_cmd)

    def mkvdisk(self, name, size, units, pool, opts, params):
        ssh_cmd = ['mcsop', 'mkvdisk', '-name', name, '-mdiskgrp',
                   '"%s"' % pool, '-iogrp', six.text_type(opts['iogrp']),
                   '-size', size, '-unit', units] + params
        try:
            return self.run_ssh_check_created(ssh_cmd)
        except Exception as ex:
            if hasattr(ex, 'msg') and 'CMMVC6372W' in ex.msg:
                vdisk = self.lsvdisk(name)
                if vdisk:
                    LOG.warning('CMMVC6372W The virtualized storage '
                                'capacity that the cluster is using is '
                                'approaching the virtualized storage '
                                'capacity that is licensed.')
                    return vdisk['id']
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to create vdisk %(vol)s.', {'vol': name})

    def rmvdisk(self, vdisk, force=True):
        ssh_cmd = ['mcsop', 'rmvdisk']
        if force:
            ssh_cmd += ['-force']
        ssh_cmd += ['"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def chvdisk(self, vdisk, params):
        ssh_cmd = ['mcsop', 'chvdisk'] + params + ['"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def movevdisk(self, vdisk, iogrp):
        ssh_cmd = ['mcsop', 'movevdisk', '-iogrp', iogrp, '"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def expandvdisksize(self, vdisk, amount):
        ssh_cmd = (
            ['mcsop', 'expandvdisksize', '-size', six.text_type(amount),
             '-unit', 'gb', '"%s"' % vdisk])
        self.run_ssh_assert_no_output(ssh_cmd)

    def mklcmap(self, source, target, full_copy, copy_rate, consistgrp=None):
        ssh_cmd = ['mcsop', 'mklcmap', '-source', '"%s"' % source, '-target',
                   '"%s"' % target, '-autodelete']
        if not full_copy:
            ssh_cmd.extend(['-copyrate', '0'])
        else:
            ssh_cmd.extend(['-copyrate', six.text_type(copy_rate)])
        if consistgrp:
            ssh_cmd.extend(['-consistgrp', consistgrp])
        out, err = self._ssh(ssh_cmd, check_exit_code=False)
        if 'successfully created' not in out:
            msg = (_('CLI Exception output:\n command: %(cmd)s\n '
                     'stdout: %(out)s\n stderr: %(err)s.') %
                   {'cmd': ssh_cmd,
                    'out': out,
                    'err': err})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        try:
            match_obj = re.search(r'LocalCopy Mapping, id \[([0-9]+)\], '
                                  'successfully created', out)
            lc_map_id = match_obj.group(1)
        except (AttributeError, IndexError):
            msg = (_('Failed to parse CLI output:\n command: %(cmd)s\n '
                     'stdout: %(out)s\n stderr: %(err)s.') %
                   {'cmd': ssh_cmd,
                    'out': out,
                    'err': err})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return lc_map_id

    def prestartlcmap(self, lc_map_id):
        ssh_cmd = ['mcsop', 'prestartlcmap', lc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def startlcmap(self, lc_map_id):
        ssh_cmd = ['mcsop', 'startlcmap', lc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def prestartlcconsistgrp(self, lc_consist_group):
        ssh_cmd = ['mcsop', 'prestartlcconsistgrp', lc_consist_group]
        self.run_ssh_assert_no_output(ssh_cmd)

    def startlcconsistgrp(self, lc_consist_group):
        ssh_cmd = ['mcsop', 'startlcconsistgrp', lc_consist_group]
        self.run_ssh_assert_no_output(ssh_cmd)

    def stoplcconsistgrp(self, lc_consist_group):
        ssh_cmd = ['mcsop', 'stoplcconsistgrp', lc_consist_group]
        self.run_ssh_assert_no_output(ssh_cmd)

    def chlcmap(self, lc_map_id, copyrate='50', autodel='on'):
        ssh_cmd = ['mcsop', 'chlcmap', '-copyrate', copyrate,
                   '-autodelete', autodel, lc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def stoplcmap(self, lc_map_id):
        ssh_cmd = ['mcsop', 'stoplcmap', lc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def rmlcmap(self, lc_map_id):
        ssh_cmd = ['mcsop', 'rmlcmap', '-force', lc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def mklcconsistgrp(self, lc_consist_group):
        ssh_cmd = ['mcsop', 'mklcconsistgrp', '-name', lc_consist_group]
        return self.run_ssh_check_created(ssh_cmd)

    def rmlcconsistgrp(self, lc_consist_group):
        ssh_cmd = ['mcsop', 'rmlcconsistgrp', '-force', lc_consist_group]
        return self.run_ssh_assert_no_output(ssh_cmd)

    def addvdiskcopy(self, vdisk, dest_pool, params):
        ssh_cmd = (['mcsop', 'addvdiskcopy'] +
                   params +
                   ['-mdiskgrp', '"%s"' %
                    dest_pool, '"%s"' %
                    vdisk])
        return self.run_ssh_check_created(ssh_cmd)

    def rmvdiskcopy(self, vdisk, copy_id):
        ssh_cmd = ['mcsop', 'rmvdiskcopy', '-copy', copy_id, '"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def addvdiskaccess(self, vdisk, iogrp):
        ssh_cmd = ['mcsop', 'addvdiskaccess', '-iogrp', iogrp,
                   '"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def rmvdiskaccess(self, vdisk, iogrp):
        ssh_cmd = ['mcsop', 'rmvdiskaccess', '-iogrp', iogrp, '"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)


class CLIParser(object):
    """Parse MCS CLI output and generate iterable."""

    def __init__(self, raw, ssh_cmd=None, delim='!', with_header=True):
        super(CLIParser, self).__init__()
        if ssh_cmd:
            self.ssh_cmd = ' '.join(ssh_cmd)
        else:
            self.ssh_cmd = 'None'
        self.raw = raw
        self.delim = delim
        self.with_header = with_header
        self.result = self._parse()

    def select(self, *keys):
        for a in self.result:
            vs = []
            for k in keys:
                v = a.get(k, None)
                if isinstance(v, six.string_types) or v is None:
                    v = [v]
                if isinstance(v, list):
                    vs.append(v)
            for item in zip(*vs):
                if len(item) == 1:
                    yield item[0]
                else:
                    yield item

    def __getitem__(self, key):
        try:
            return self.result[key]
        except KeyError:
            msg = (_('Did not find the expected key %(key)s in %(fun)s: '
                     '%(raw)s.') % {'key': key, 'fun': self.ssh_cmd,
                                    'raw': self.raw})
            raise exception.VolumeBackendAPIException(data=msg)

    def __iter__(self):
        for a in self.result:
            yield a

    def __len__(self):
        return len(self.result)

    def _parse(self):
        def get_reader(content, delim):
            for line in content.lstrip().splitlines():
                line = line.strip()
                if line:
                    yield line.split(delim)
                else:
                    yield []

        if isinstance(self.raw, six.string_types):
            stdout, stderr = self.raw, ''
        else:
            stdout, stderr = self.raw
        reader = get_reader(stdout, self.delim)
        result = []

        if self.with_header:
            hds = tuple()
            for row in reader:
                hds = row
                break
            for row in reader:
                cur = dict()
                if len(hds) != len(row):
                    msg = (_('Unexpected CLI response: header/row mismatch. '
                             'header: %(header)s, row: %(row)s.')
                           % {'header': hds,
                              'row': row})
                    raise exception.VolumeBackendAPIException(data=msg)
                for k, v in zip(hds, row):
                    CLIParser.append_dict(cur, k, v)
                result.append(cur)
        else:
            cur = dict()
            for row in reader:
                if row:
                    CLIParser.append_dict(cur, row[0], ' '.join(row[1:]))
                elif cur:  # start new section
                    result.append(cur)
                    cur = dict()
            if cur:
                result.append(cur)
        return result

    @staticmethod
    def append_dict(dict_, key, value):
        key, value = key.strip(), value.strip()
        obj = dict_.get(key, None)
        if obj is None:
            dict_[key] = value
        elif isinstance(obj, list):
            obj.append(value)
            dict_[key] = obj
        else:
            dict_[key] = [obj, value]
        return dict_
