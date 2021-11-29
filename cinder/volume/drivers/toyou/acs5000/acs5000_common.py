# Copyright 2020 toyou Corp.
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
acs5000 san for common driver
It will be called by iSCSI driver
"""

import json
import math
import random

from eventlet import greenthread
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units
import paramiko

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import ssh_utils
from cinder import utils as cinder_utils
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume import volume_utils

VOLUME_PREFIX = 'cinder-'

LOG = logging.getLogger(__name__)
acs5000c_opts = [
    cfg.ListOpt(
        'acs5000_volpool_name',
        default=['pool01'],
        help='Comma separated list of storage system storage '
             'pools for volumes.'),
    cfg.IntOpt(
        'acs5000_copy_interval',
        default=5,
        min=3,
        max=100,
        help='When volume copy task is going on,refresh volume '
             'status interval'),
    cfg.BoolOpt(
        'acs5000_multiattach',
        default=False,
        help='Enable to allow volumes attaching to multiple '
             'hosts with no limit.'),
]
CONF = cfg.CONF
CONF.register_opts(acs5000c_opts)


class Command(object):

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

    def run_ssh_info(self, ssh_cmd, key=False):
        """Run an SSH command and return parsed output."""
        ssh_cmd.insert(0, 'cinder')
        out, err = self._run_ssh(ssh_cmd)
        if len(err):
            msg = (_('Execute command %(cmd)s failed, '
                     'out: %(out)s, err: %(err)s.') %
                   {'cmd': ' '.join(ssh_cmd),
                    'out': str(out),
                    'err': str(err)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        try:
            info = json.loads(out)
        except json.JSONDecodeError as e:
            msg = (_('Parse response error from CLI command %(cmd)s, '
                     'out: %(out)s, err: %(err)s') %
                   {'cmd': ' '.join(ssh_cmd),
                    'out': str(out),
                    'err': e})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if not isinstance(info, dict):
            msg = (_('Unexpected format from CLI command %(cmd)s, '
                     'result: %(info)s.') %
                   {'cmd': ' '.join(ssh_cmd),
                    'info': str(info)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        require = ('key', 'msg', 'arr')
        require_valid = True
        for r in require:
            if r not in info.keys():
                require_valid = False
                break
        if not require_valid:
            msg = (_('Unexpected response from CLI command %(cmd)s, '
                     'require \'key\' \'msg\' \'arr\'. out: %(info)s.') %
                   {'cmd': ' '.join(ssh_cmd),
                    'info': str(info)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        elif int(info['key']) != 0:
            msg = (_('Unexpected error output from CLI command %(cmd)s, '
                     'key: %(key)s, msg: %(msg)s.') %
                   {'cmd': ' '.join(ssh_cmd),
                    'msg': info['msg'],
                    'key': info['key']})
            LOG.error(msg)
            if not key:
                raise exception.VolumeBackendAPIException(data=msg)
        if key:
            info['key'] = int(info['key'])
            return info
        else:
            return info['arr']

    def get_system(self):
        ssh_cmd = ['get_system']
        return self.run_ssh_info(ssh_cmd)

    def ls_iscsi(self):
        ssh_cmd = ['ls_iscsi']
        ports = self.run_ssh_info(ssh_cmd)
        up_ports = []
        for port in ports:
            if 'link' in port and port['link'] != 'Down':
                up_ports.append(up_ports)
        return up_ports

    def ls_fc(self):
        ssh_cmd = ['ls_fc']
        ports = self.run_ssh_info(ssh_cmd)
        up_ports = []
        for port in ports:
            if 'link' in port and port['link'] == 'Up':
                up_ports.append(port)
        return up_ports

    def get_pool(self, pool):
        ssh_cmd = ['get_pool',
                   '--pool',
                   pool]
        return self.run_ssh_info(ssh_cmd)

    def get_volume(self, volume):
        ssh_cmd = ['get_volume']
        if not volume:
            return []
        elif isinstance(volume, str):
            ssh_cmd.append('--volume')
            ssh_cmd.append(volume)
        elif isinstance(volume, list):
            for vol in volume:
                ssh_cmd.append('--volume')
                ssh_cmd.append(vol)
        result = self.run_ssh_info(ssh_cmd)
        if not result:
            return []
        else:
            return result

    def ls_controller(self):
        ssh_cmd = ['ls_controller']
        ctrs = self.run_ssh_info(ssh_cmd)
        nodes = {}
        for node_data in ctrs:
            nodes[node_data['id']] = {
                'id': int(node_data['id']),
                'name': node_data['name'],
                'status': node_data['status']
            }
        return nodes

    def create_volume(self, name, size, pool_name, type='0'):
        ssh_cmd = ['create_volume',
                   '--size',
                   size,
                   '--volume',
                   name,
                   '--pool',
                   pool_name,
                   '--type',
                   type]
        return self.run_ssh_info(ssh_cmd, key=True)

    def delete_volume(self, volume):
        ssh_cmd = ['delete_volume',
                   '--volume',
                   volume]
        return self.run_ssh_info(ssh_cmd)

    def extend_volume(self, volume, size):
        ssh_cmd = ['extend_volume',
                   '--volume',
                   volume,
                   '--size',
                   str(size)]
        return self.run_ssh_info(ssh_cmd, key=True)

    def create_clone(self, volume_name, clone_name):
        ssh_cmd = ['create_clone',
                   '--volume',
                   volume_name,
                   '--clone',
                   clone_name]
        return self.run_ssh_info(ssh_cmd, key=True)

    def start_clone(self, volume_name, snapshot=''):
        ssh_cmd = ['start_clone',
                   '--volume',
                   volume_name,
                   '--snapshot',
                   snapshot]
        return self.run_ssh_info(ssh_cmd, key=True)

    def delete_clone(self, volume_name, snapshot=''):
        ssh_cmd = ['delete_clone',
                   '--volume',
                   volume_name,
                   '--snapshot',
                   snapshot]
        return self.run_ssh_info(ssh_cmd, key=True)

    def create_lun_map(self, volume_name, protocol, host):
        """Map volume to host."""
        LOG.debug('enter: create_lun_map volume %s.', volume_name)
        ssh_cmd = ['create_lun_map',
                   '--volume',
                   volume_name,
                   '--protocol',
                   protocol]
        if isinstance(host, list):
            for ht in host:
                ssh_cmd.append('--host')
                ssh_cmd.append(ht)
        else:
            ssh_cmd.append('--host')
            ssh_cmd.append(str(host))
        return self.run_ssh_info(ssh_cmd, key=True)

    def delete_lun_map(self, volume_name, protocol, host):
        ssh_cmd = ['delete_lun_map',
                   '--volume',
                   volume_name,
                   '--protocol',
                   protocol]
        if isinstance(host, list):
            for ht in host:
                ssh_cmd.append('--host')
                ssh_cmd.append(ht)
        else:
            ssh_cmd.append('--host')
            ssh_cmd.append(str(host))
        return self.run_ssh_info(ssh_cmd, key=True)

    def create_snapshot(self, volume_name, snapshot_name):
        ssh_cmd = ['create_snapshot',
                   '--volume',
                   volume_name,
                   '--snapshot',
                   snapshot_name]
        return self.run_ssh_info(ssh_cmd, key=True)

    def delete_snapshot(self, volume_name, snapshot_name):
        ssh_cmd = ['delete_snapshot',
                   '--volume',
                   volume_name,
                   '--snapshot',
                   snapshot_name]
        return self.run_ssh_info(ssh_cmd, key=True)

    def rollback_snapshot(self, snapshot_name, volume_name=''):
        ssh_cmd = ['rollback_snapshot',
                   '--snapshot',
                   snapshot_name,
                   '--volume',
                   volume_name]
        return self.run_ssh_info(ssh_cmd, key=True)

    def set_volume_property(self, name, setting):
        ssh_cmd = ['set_volume',
                   '--volume',
                   name]
        for key, value in setting.items():
            ssh_cmd.extend(['--' + key, value])
        return self.run_ssh_info(ssh_cmd, key=True)


class Acs5000CommonDriver(san.SanDriver,
                          driver.MigrateVD,
                          driver.CloneableImageVD):
    """TOYOU ACS5000 storage abstract common class.

    .. code-block:: none

      Version history:
          1.0.0 - Initial driver

    """
    VENDOR = 'TOYOU'
    VERSION = '1.0.0'

    def __init__(self, *args, **kwargs):
        super(Acs5000CommonDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(acs5000c_opts)
        self._backend_name = self.configuration.safe_get('volume_backend_name')
        self.pools = self.configuration.acs5000_volpool_name
        self._cmd = Command(self._run_ssh)
        self.protocol = None
        self._state = {'controller': {},
                       'enabled_protocols': set(),
                       'system_name': None,
                       'system_id': None,
                       'code_level': None,
                       'version': None}

    @staticmethod
    def get_driver_options():
        additional_opts = driver.BaseVD._get_oslo_driver_opts(
            'san_ip', 'san_ssh_port', 'san_login', 'san_password',
            'ssh_conn_timeout', 'ssh_min_pool_conn', 'ssh_max_pool_conn')
        return acs5000c_opts + additional_opts

    @volume_utils.trace_method
    def do_setup(self, ctxt):
        """Check that we have all configuration details from the storage."""
        self._validate_pools_exist()

        self._state.update(self._cmd.get_system())

        self._state['controller'] = self._cmd.ls_controller()
        if self.protocol == 'FC':
            ports = self._cmd.ls_fc()
        else:
            ports = self._cmd.ls_iscsi()
        if len(ports) > 0:
            self._state['enabled_protocols'].add(self.protocol)

    def _validate_pools_exist(self):
        LOG.debug('_validate_pools_exist. '
                  'pools: %s', ' '.join(self.pools))
        for pool in self.pools:
            pool_data = self._cmd.get_pool(pool)
            if not pool_data:
                msg = _('Failed getting details for pool %s.') % pool
                raise exception.InvalidInput(reason=msg)
        return True

    @staticmethod
    def _convert_name(name):
        if len(name) >= 12:
            suffix = name[-12:]
        elif len(name) > 0:
            suffix = str(name).zfill(12)
        else:
            suffix = str(random.randint(0, 999999)).zfill(12)
        return VOLUME_PREFIX + suffix

    @staticmethod
    def _check_multi_attached(volume, connector):
        # In the case of multi-attach, these VMs belong to the same host.
        # The mapping action only happens once.
        # If the only mapping relationship is cancelled,
        # volume on other VMs cannot be read or written.
        if not connector or 'uuid' not in connector:
            return 0
        attached_count = 0
        uuid = connector['uuid']
        for ref in volume.volume_attachment:
            ref_connector = {}
            if 'connector' in ref and ref.connector:
                # ref.connector may be None
                ref_connector = ref.connector
            if 'uuid' in ref_connector and uuid == ref_connector['uuid']:
                attached_count += 1
        return attached_count

    @volume_utils.trace_method
    def check_for_setup_error(self):
        """Ensure that the params are set properly."""
        if self._state['system_name'] is None:
            exception_msg = _('Unable to determine system name.')
            raise exception.VolumeBackendAPIException(data=exception_msg)
        if self._state['system_id'] is None:
            exception_msg = _('Unable to determine system id.')
            raise exception.VolumeBackendAPIException(data=exception_msg)
        if len(self._state['controller']) != 2:
            msg = _('do_setup: The dual controller status is incorrect.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        if self.protocol not in self._state['enabled_protocols']:
            raise exception.InvalidInput(
                reason=(_('The storage device does not support %(prot)s. '
                          'Please configure the device to support %(prot)s '
                          'or switch to a driver using a different '
                          'protocol.') % {'prot': self.protocol}))
        required = ['san_ip',
                    'san_ssh_port',
                    'san_login',
                    'acs5000_volpool_name']
        for param in required:
            if not self.configuration.safe_get(param):
                raise exception.InvalidInput(
                    reason=_('%s is not set.') % param)

        if not self.configuration.san_password:
            raise exception.InvalidInput(
                reason='Password is required for authentication')

        return

    def _run_ssh(self, cmd_list, check_exit_code=True):
        cinder_utils.check_ssh_injection(cmd_list)
        command = ' '.join(cmd_list)
        if not self.sshpool:
            try:
                self.sshpool = self._set_up_sshpool(self.configuration.san_ip)
            except paramiko.SSHException as e:
                raise exception.VolumeDriverException(message=e)
        ssh_execute = self._ssh_execute(
            self.sshpool, command, check_exit_code)
        return ssh_execute

    def _set_up_sshpool(self, ip):
        port = self.configuration.get('san_ssh_port', 22)
        login = self.configuration.get('san_login')
        password = self.configuration.get('san_password')
        timeout = self.configuration.get('ssh_conn_timeout', 30)
        min_size = self.configuration.get('ssh_min_pool_conn', 1)
        max_size = self.configuration.get('ssh_max_pool_conn', 5)
        sshpool = ssh_utils.SSHPool(ip,
                                    port,
                                    timeout,
                                    login,
                                    password=password,
                                    min_size=min_size,
                                    max_size=max_size)
        return sshpool

    def _ssh_execute(
            self,
            sshpool,
            command,
            check_exit_code=True):
        # noinspection PyBroadException
        try:
            with sshpool.item() as ssh:
                try:
                    return processutils.ssh_execute(
                        ssh, command, check_exit_code=check_exit_code)
                except Exception as e:
                    LOG.error('Error has occurred: %s', e)
                    raise processutils.ProcessExecutionError(
                        exit_code=e.exit_code,
                        stdout=e.stdout,
                        stderr=e.stderr,
                        cmd=e.cmd)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Error running SSH command: %s', command)

    def create_volume(self, volume):
        LOG.debug('create_volume, volume %s.', volume['id'])
        volume_name = self._convert_name(volume.name)
        pool_name = volume_utils.extract_host(volume['host'], 'pool')
        ret = self._cmd.create_volume(
            volume_name,
            str(volume['size']),
            pool_name)
        if ret['key'] == 310:
            msg = _('Volume: %s with same name '
                    'already exists on the system.') % volume_name
            raise exception.VolumeBackendAPIException(data=msg)
        elif ret['key'] == 102:
            allow_size = 0
            for p in self._stats['pools']:
                if p['pool_name'] == pool_name:
                    allow_size = p['free_capacity_gb']
                    break
            raise exception.VolumeSizeExceedsLimit(size=int(volume['size']),
                                                   limit=allow_size)
        elif ret['key'] == 307:
            raise exception.VolumeLimitExceeded(allowed=96,
                                                name=volume_name)
        elif ret['key'] == 308:
            raise exception.VolumeLimitExceeded(allowed=4096,
                                                name=volume_name)
        elif ret['key'] != 0:
            msg = (_('Failed to create_volume %(vol)s on pool %(pool)s, '
                     'code=%(ret)s, error=%(msg)s.') % {'vol': volume_name,
                                                        'pool': pool_name,
                                                        'ret': ret['key'],
                                                        'msg': ret['msg']})
            raise exception.VolumeBackendAPIException(data=msg)
        return None

    def delete_volume(self, volume):
        volume_name = self._convert_name(volume.name)
        self._cmd.delete_volume(volume_name)

    def create_snapshot(self, snapshot):
        volume_name = self._convert_name(snapshot.volume_name)
        snapshot_name = self._convert_name(snapshot.name)
        ret = self._cmd.create_snapshot(volume_name, snapshot_name)
        if ret['key'] == 303:
            raise exception.VolumeNotFound(volume_id=volume_name)
        elif ret['key'] == 503:
            raise exception.SnapshotLimitExceeded(allowed=4096)
        elif ret['key'] == 504:
            raise exception.SnapshotLimitExceeded(allowed=64)
        elif ret['key'] != 0:
            msg = (_('Failed to create_snapshot %(snap)s on volume %(vol)s '
                     'code=%(ret)s, error=%(msg)s.') % {'vol': volume_name,
                                                        'snap': snapshot_name,
                                                        'ret': ret['key'],
                                                        'msg': ret['msg']})
            raise exception.VolumeBackendAPIException(data=msg)

    def delete_snapshot(self, snapshot):
        volume_name = self._convert_name(snapshot.volume_name)
        snapshot_name = self._convert_name(snapshot.name)
        ret = self._cmd.delete_snapshot(volume_name, snapshot_name)
        if ret['key'] == 505:
            raise exception.SnapshotNotFound(snapshot_id=snapshot['id'])
        elif ret['key'] != 0:
            msg = (_('Failed to delete_snapshot %(snap)s on volume %(vol)s '
                     'code=%(ret)s, error=%(msg)s.') % {'vol': volume_name,
                                                        'snap': snapshot_name,
                                                        'ret': ret['key'],
                                                        'msg': ret['msg']})
            raise exception.VolumeBackendAPIException(data=msg)

    def create_volume_from_snapshot(self, volume, snapshot):
        snapshot_name = self._convert_name(snapshot.name)
        volume_name = self._convert_name(volume.name)
        source_volume = self._convert_name(snapshot.volume_name)
        pool = volume_utils.extract_host(volume['host'], 'pool')
        self._cmd.create_volume(volume_name,
                                str(volume['size']),
                                pool, '10')
        self._local_clone_copy(source_volume,
                               volume_name,
                               'create_volume_from_snapshot',
                               snapshot_name)

    def snapshot_revert_use_temp_snapshot(self):
        return False

    @volume_utils.trace
    def revert_to_snapshot(self, context, volume, snapshot):
        volume_name = self._convert_name(volume.name)
        snapshot_name = self._convert_name(snapshot.name)
        ret = self._cmd.rollback_snapshot(snapshot_name, volume_name)
        if ret['key'] == 303:
            raise exception.VolumeNotFound(volume_id=volume_name)
        elif ret['key'] == 505:
            raise exception.SnapshotNotFound(snapshot_id=snapshot_name)
        elif ret['key'] == 506:
            msg = (_('Snapshot %s is not the latest one.') % snapshot_name)
            raise exception.InvalidSnapshot(reason=msg)
        elif ret['key'] != 0:
            msg = (_('Failed to revert volume %(vol)s to snapshot %(snap)s, '
                     'code=%(ret)s, error=%(msg)s.') % {'vol': volume_name,
                                                        'snap': snapshot_name,
                                                        'ret': ret['key'],
                                                        'msg': ret['msg']})
            raise exception.VolumeBackendAPIException(data=msg)

    def create_cloned_volume(self, tgt_volume, src_volume):
        clone_name = self._convert_name(tgt_volume.name)
        volume_name = self._convert_name(src_volume.name)
        tgt_pool = volume_utils.extract_host(tgt_volume['host'], 'pool')
        try:
            self._cmd.create_volume(clone_name, str(
                tgt_volume['size']), tgt_pool, '10')
            self._local_clone_copy(
                volume_name, clone_name, 'create_cloned_volume')
        except exception.VolumeBackendAPIException:
            self._cmd.delete_volume(clone_name)
            raise exception.VolumeBackendAPIException(
                data='create_cloned_volume failed.')

    def extend_volume(self, volume, new_size):
        volume_name = self._convert_name(volume.name)
        ret = self._cmd.extend_volume(volume_name, int(new_size))
        if ret['key'] == 303:
            raise exception.VolumeNotFound(volume_id=volume_name)
        elif ret['key'] == 321:
            msg = _('Volume capacity shall not be '
                    'less than the current size %sG.') % volume['size']
            raise exception.VolumeBackendAPIException(data=msg)
        elif ret['key'] == 102:
            pool_name = volume_utils.extract_host(volume['host'], 'pool')
            allow_size = 0
            for p in self._stats['pools']:
                if p['pool_name'] == pool_name:
                    allow_size = p['free_capacity_gb']
                    break
            raise exception.VolumeSizeExceedsLimit(size=int(new_size),
                                                   limit=allow_size)
        elif ret['key'] != 0:
            msg = (_('Failed to extend_volume %(vol)s to size %(size)s, '
                     'code=%(ret)s, error=%(msg)s.') % {'vol': volume_name,
                                                        'size': new_size,
                                                        'ret': ret['key'],
                                                        'msg': ret['msg']})
            raise exception.VolumeBackendAPIException(data=msg)

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Only for host copy."""
        existing_name = self._convert_name(new_volume.name)
        wanted_name = self._convert_name(volume.name)
        LOG.debug('enter: update_migrated_volume: rename of %(new)s '
                  'to original name %(wanted)s.', {'new': existing_name,
                                                   'wanted': wanted_name})
        is_existed = self._cmd.get_volume(wanted_name)
        if len(is_existed) == 1:
            LOG.warning('volume name %(wanted)s is existed, The two volumes '
                        '%(wanted)s and %(new)s may be on the same system.',
                        {'new': existing_name,
                         'wanted': wanted_name})
            return {'_name_id': new_volume['_name_id'] or new_volume['id']}
        else:
            self._cmd.set_volume_property(existing_name,
                                          {'new_name': wanted_name})
            return {'_name_id': None}

    def migrate_volume(self, ctxt, volume, host):
        LOG.debug('enter: migrate_volume id %(id)s, host %(host)s',
                  {'id': volume['id'], 'host': host['host']})
        pool = volume_utils.extract_host(volume['host'], 'pool')
        if 'system_id' not in host['capabilities']:
            LOG.error('Target host has no system_id')
            return (False, None)
        if host['capabilities']['system_id'] != self._state['system_id']:
            LOG.info('The target host does not belong to the same '
                     'storage system as the current volume')
            return (False, None)
        if host['capabilities']['pool_name'] == pool:
            LOG.info('The target host belongs to the same storage system '
                     'and pool as the current volume.')
            return (True, None)
        LOG.info('The target host belongs to the same storage system '
                 'as the current but to a different pool. '
                 'The same storage system will clone volume into the new pool')
        volume_name = self._convert_name(volume.name)
        tmp_name = VOLUME_PREFIX + 'tmp'
        tmp_name += str(random.randint(0, 999999)).zfill(8)
        self._cmd.create_volume(tmp_name,
                                str(volume['size']),
                                host['capabilities']['pool_name'],
                                '10')
        self._local_clone_copy(
            volume_name, tmp_name, 'migrate_volume')
        self._cmd.delete_volume(volume_name)
        self._cmd.set_volume_property(tmp_name,
                                      {'type': '"RAID Volume"',
                                       'new_name': volume_name})
        return (True, None)

    def _manage_get_volume(self, ref, pool_name=None):
        if 'source-name' in ref:
            manage_source = ref['source-name']
            volumes = self._cmd.get_volume(manage_source)
        else:
            reason = _('Reference must contain source-name element '
                       'and only support source-name.')
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)

        if not volumes:
            reason = (_('No volume by ref %s.')
                      % manage_source)
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)
        volume = volumes[0]
        if pool_name and pool_name != volume['poolname']:
            reason = (_('Volume %(volume)s does not belong to pool name '
                        '%(pool)s.') % {'volume': manage_source,
                                        'pool': pool_name})
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)
        return volume

    @volume_utils.trace_method
    def manage_existing(self, volume, ref):
        """Manages an existing volume."""
        volume_name = ref.get('source-name')
        if not volume_name:
            reason = _('Reference must contain source-name element '
                       'and only support source-name.')
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)
        new_name = self._convert_name(volume.name)
        self._cmd.set_volume_property(volume_name, {'type': '2',
                                                    'new_name': new_name})

    @volume_utils.trace_method
    def manage_existing_get_size(self, volume, ref):
        """Return size of an existing volume for manage_existing."""
        pool_name = volume_utils.extract_host(volume['host'], 'pool')
        vol_backend = self._manage_get_volume(ref, pool_name)
        size = int(vol_backend.get('size_mb', 0))
        size_gb = int(math.ceil(size / 1024))
        if (size_gb * 1024) > size:
            LOG.warning('Volume %(vol)s capacity is %(mb)s MB, '
                        'extend to %(gb)s GB.', {'vol': ref['source-name'],
                                                 'mb': size,
                                                 'gb': size_gb})
            self._cmd.extend_volume(ref['source-name'], size_gb)
        return size_gb

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If we haven't gotten stats yet or 'refresh' is True,
        run update the stats first.
        """
        if not self._stats or refresh:
            self._update_volume_stats()
        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""
        LOG.debug('Updating volume stats, '
                  'pools: \'%(host)s#%(pool)s\'.',
                  {'host': self.host,
                   'pool': ','.join(self.pools)})
        data = {}
        data['vendor_name'] = self.VENDOR
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = self.protocol
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = (backend_name or
                                       self._state['system_name'])
        data['pools'] = [self._build_pool_stats(pool)
                         for pool in self.pools]

        self._stats = data

    def _build_pool_stats(self, pool):
        """Build pool status"""
        pool_stats = {}
        try:
            pool_data = self._cmd.get_pool(pool)
            if pool_data:
                total_capacity_gb = float(
                    pool_data['capacity']) / units.Gi
                free_capacity_gb = float(
                    pool_data['free_capacity']) / units.Gi
                allocated_capacity_gb = float(
                    pool_data['used_capacity']) / units.Gi
                total_volumes = None
                if 'total_volumes' in pool_data.keys():
                    total_volumes = int(pool_data['total_volumes'])
                thin_provisioning = False
                if 'thin' in pool_data and pool_data['thin'] == 'Enabled':
                    thin_provisioning = True
                pool_stats = {
                    'pool_name': pool_data['name'],
                    'total_capacity_gb': total_capacity_gb,
                    'free_capacity_gb': free_capacity_gb,
                    'allocated_capacity_gb': allocated_capacity_gb,
                    'compression_support': True,
                    'reserved_percentage':
                        self.configuration.reserved_percentage,
                    'QoS_support': False,
                    'consistencygroup_support': False,
                    'multiattach': self.configuration.acs5000_multiattach,
                    'thin_provisioning_support': thin_provisioning,
                    'total_volumes': total_volumes,
                    'system_id': self._state['system_id']}
            else:
                msg = _('Backend storage pool "%s" not found.') % pool
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        except exception.VolumeBackendAPIException:
            msg = _('Failed getting details for pool %s.') % pool
            raise exception.VolumeBackendAPIException(data=msg)

        return pool_stats

    def _local_clone_copy(self, volume, clone, action=None, snapshot=''):
        LOG.debug('enter: copy volume %(vol)s to %(clone)s by %(action)s.',
                  {'vol': volume,
                   'clone': clone,
                   'action': action})
        if self._wait_volume_copy(volume, clone, action, 'wait'):
            LOG.info('start copy task.')
            ret = self._cmd.create_clone(volume, clone)
            if ret['key'] != 0:
                self._cmd.delete_volume(clone)
            if ret['key'] == 306:
                raise exception.VolumeBackendAPIException(
                    data='The source volume must not be larger '
                         'than the target volume in a clone relation. ')
            elif ret['key'] == 0:
                ret = self._cmd.start_clone(volume, snapshot)
                if ret['key'] == 505:
                    raise exception.SnapshotNotFound(snapshot_id=snapshot)
        else:
            LOG.error('%(action)s failed.', {'action': action})
            raise exception.VolumeBackendAPIException(data='clone failed!')

        if self._wait_volume_copy(volume, clone, action, 'copy'):
            self._cmd.delete_clone(volume, snapshot)
            LOG.info('%s successfully.', action)
        else:
            LOG.error('%(action)s failed.', {'action': action})
            raise exception.VolumeBackendAPIException(data='clone failed!')
        LOG.debug('leave: copy volume %(vol)s to %(clone)s by %(action)s. ',
                  {'vol': volume,
                   'clone': clone,
                   'action': action})

    @coordination.synchronized('acs5000-copy-{volume}-task')
    def _wait_volume_copy(self, volume, clone, function=None, action=None):
        LOG.debug('_wait_volume_copy, volume %s.', volume)
        if volume is None or clone is None:
            LOG.error('volume parameter error.')
            return False
        ret = False
        while_exit = False
        rescan = 0
        interval = self.configuration.acs5000_copy_interval
        wait_status = (
            'Initiating',
            'Rebuilding',
            'Erasing',
            'Delayed rebuilding')
        # All status
        # {"Offline", "Online", "Initiating",
        # ###"Rebuilding", "Migrating", "Parity chking",
        # ###"Cloning", "Rolling back", "Parity chking",
        # ###"Replicating", "Erasing", "Moving", "Replacing",
        # "Reclaiming", "Delayed rebuilding", "Relocation", "N/A"};
        # All health
        # {"Optimal", "Degraded", "Deleted", "Missing", "Failed",
        #  "Partially optimal", "N/A"}
        while True:
            rescan += 1
            volume_info = self._cmd.get_volume([volume, clone])
            if len(volume_info) == 2:
                for vol in volume_info:
                    if vol['type'] == 'BACKUP':
                        if vol['health'] == 'Optimal' and (
                                vol['status'] in wait_status):
                            LOG.info('%(function)s %(action)s task: '
                                     'rescan %(scan)s times, clone %(clone)s '
                                     'need wait,status is %(status)s, '
                                     'health is %(health)s, '
                                     'process is %(process)s%%. ',
                                     {'function': function,
                                      'action': action,
                                      'scan': rescan,
                                      'clone': vol['name'],
                                      'status': vol['status'],
                                      'health': vol['health'],
                                      'process': vol['r']})
                    elif vol['status'] == 'Cloning':
                        LOG.info('%(function)s %(action)s task: '
                                 'rescan %(scan)s times,volume %(volume)s '
                                 'copy process %(process)s%%. ',
                                 {'function': function,
                                  'action': action,
                                  'scan': rescan,
                                  'volume': vol['name'],
                                  'process': vol['r']})
                    elif vol['status'] == 'Queued':
                        LOG.info('%(function)s %(action)s task: '
                                 'rescan %(scan)s times, '
                                 'volume %(volume)s is in the queue. ',
                                 {'function': function,
                                  'action': action, 'scan': rescan,
                                  'volume': vol['name']})
                    elif (vol['type'] == 'RAID Volume'
                          and vol['status'] == 'Online'):
                        ret = True
                        while_exit = True
                        LOG.info('%(function)s %(action)s task: '
                                 'rescan %(scan)s times,volume %(volume)s '
                                 'copy task completed,status is Online. ',
                                 {'function': function,
                                  'action': action,
                                  'scan': rescan,
                                  'volume': vol['name']})
                    elif (vol['health'] == 'Optimal'
                          and (vol['status'] in wait_status)):
                        LOG.info('%(function)s %(action)s task: '
                                 'rescan %(scan)s times,volume %(volume)s '
                                 'need wait, '
                                 'status is %(status)s,health is %(health)s, '
                                 'process is %(process)s%%. ',
                                 {'function': function,
                                  'action': action,
                                  'scan': rescan,
                                  'volume': vol['name'],
                                  'status': vol['status'],
                                  'health': vol['health'],
                                  'process': vol['r']})
                    else:
                        LOG.info('%(function)s %(action)s task: '
                                 'rescan %(scan)s times,volume %(volume)s '
                                 'is not normal, '
                                 'status %(status)s,health is %(health)s. ',
                                 {'function': function,
                                  'action': action,
                                  'scan': rescan,
                                  'volume': vol['name'],
                                  'status': vol['status'],
                                  'health': vol['health']})
                        while_exit = True
                        break
            elif len(volume_info) == 1:
                while_exit = True
                if volume_info[0]['name'] == volume:
                    LOG.info('%(function)s %(action)s task: '
                             'rescan %(scan)s times,clone %(clone)s '
                             'does not exist! ',
                             {'function': function,
                              'action': action,
                              'scan': rescan,
                              'clone': clone})
                else:
                    LOG.info('%(function)s %(action)s task: '
                             'rescan %(scan)s times,volume %(volume)s '
                             'does not exist! ',
                             {'function': function,
                              'action': action,
                              'scan': rescan,
                              'volume': volume})
            else:
                while_exit = True
                LOG.info('%(function)s %(action)s task: '
                         'rescan %(scan)s times,volume %(volume)s '
                         'clone %(clone)s does not exist! ',
                         {'function': function,
                          'action': action,
                          'scan': rescan,
                          'volume': volume,
                          'clone': clone})

            if while_exit:
                break
            greenthread.sleep(interval)
        return ret
