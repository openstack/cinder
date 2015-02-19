#    Copyright (c) 2013 Dell Inc.
#    Copyright 2013 OpenStack LLC
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

"""Volume driver for Dell EqualLogic Storage."""

import functools
import random

import eventlet
from eventlet import greenthread
import greenlet
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from cinder import exception
from cinder.i18n import _, _LE, _LW, _LI
from cinder import ssh_utils
from cinder import utils
from cinder.volume.drivers import san

LOG = logging.getLogger(__name__)

eqlx_opts = [
    cfg.StrOpt('eqlx_group_name',
               default='group-0',
               help='Group name to use for creating volumes. Defaults to '
                    '"group-0".'),
    cfg.IntOpt('eqlx_cli_timeout',
               default=30,
               help='Timeout for the Group Manager cli command execution. '
                    'Default is 30.'),
    cfg.IntOpt('eqlx_cli_max_retries',
               default=5,
               help='Maximum retry count for reconnection. Default is 5.'),
    cfg.BoolOpt('eqlx_use_chap',
                default=False,
                help='Use CHAP authentication for targets. Note that this '
                     'option is deprecated in favour of "use_chap_auth" as '
                     'specified in cinder/volume/driver.py and will be '
                     'removed in next release.'),
    cfg.StrOpt('eqlx_chap_login',
               default='admin',
               help='Existing CHAP account name. Note that this '
                    'option is deprecated in favour of "chap_username" as '
                    'specified in cinder/volume/driver.py and will be '
                    'removed in next release.'),
    cfg.StrOpt('eqlx_chap_password',
               default='password',
               help='Password for specified CHAP account name. Note that this '
                    'option is deprecated in favour of "chap_password" as '
                    'specified in cinder/volume/driver.py and will be '
                    'removed in the next release',
               secret=True),
    cfg.StrOpt('eqlx_pool',
               default='default',
               help='Pool in which volumes will be created. Defaults '
                    'to "default".')
]


CONF = cfg.CONF
CONF.register_opts(eqlx_opts)


def with_timeout(f):
    @functools.wraps(f)
    def __inner(self, *args, **kwargs):
        timeout = kwargs.pop('timeout', None)
        gt = eventlet.spawn(f, self, *args, **kwargs)
        if timeout is None:
            return gt.wait()
        else:
            kill_thread = eventlet.spawn_after(timeout, gt.kill)
            try:
                res = gt.wait()
            except greenlet.GreenletExit:
                raise exception.VolumeBackendAPIException(
                    data="Command timed out")
            else:
                kill_thread.cancel()
                return res

    return __inner


class DellEQLSanISCSIDriver(san.SanISCSIDriver):
    """Implements commands for Dell EqualLogic SAN ISCSI management.

    To enable the driver add the following line to the cinder configuration:
        volume_driver=cinder.volume.drivers.eqlx.DellEQLSanISCSIDriver

    Driver's prerequisites are:
        - a separate volume group set up and running on the SAN
        - SSH access to the SAN
        - a special user must be created which must be able to
            - create/delete volumes and snapshots;
            - clone snapshots into volumes;
            - modify volume access records;

    The access credentials to the SAN are provided by means of the following
    flags
        san_ip=<ip_address>
        san_login=<user name>
        san_password=<user password>
        san_private_key=<file containing SSH private key>

    Thin provision of volumes is enabled by default, to disable it use:
        san_thin_provision=false

    In order to use target CHAP authentication (which is disabled by default)
    SAN administrator must create a local CHAP user and specify the following
    flags for the driver:
        use_chap_auth=True
        chap_login=<chap_login>
        chap_password=<chap_password>

    eqlx_group_name parameter actually represents the CLI prompt message
    without '>' ending. E.g. if prompt looks like 'group-0>', then the
    parameter must be set to 'group-0'

    Also, the default CLI command execution timeout is 30 secs. Adjustable by
        eqlx_cli_timeout=<seconds>
    """

    VERSION = "1.1.0"

    def __init__(self, *args, **kwargs):
        super(DellEQLSanISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(eqlx_opts)
        self._group_ip = None
        self.sshpool = None

        if self.configuration.eqlx_use_chap is True:
            LOG.warning(_LW(
                'Configuration options eqlx_use_chap, '
                'eqlx_chap_login and eqlx_chap_password are deprecated. Use '
                'use_chap_auth, chap_username and chap_password '
                'respectively for the same.'))

            self.configuration.use_chap_auth = \
                self.configuration.eqlx_use_chap
            self.configuration.chap_username = \
                self.configuration.eqlx_chap_login
            self.configuration.chap_password = \
                self.configuration.eqlx_chap_password

    def _get_output(self, chan):
        out = ''
        ending = '%s> ' % self.configuration.eqlx_group_name
        while out.find(ending) == -1:
            ret = chan.recv(102400)
            if len(ret) == 0:
                # According to paramiko.channel.Channel documentation, which
                # says "If a string of length zero is returned, the channel
                # stream has closed". So we can confirm that the EQL server
                # has closed the connection.
                msg = _("The EQL array has closed the connection.")
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            out += ret

        LOG.debug("CLI output\n%s", out)
        return out.splitlines()

    def _get_prefixed_value(self, lines, prefix):
        for line in lines:
            if line.startswith(prefix):
                return line[len(prefix):]
        return

    @with_timeout
    def _ssh_execute(self, ssh, command, *arg, **kwargs):
        transport = ssh.get_transport()
        chan = transport.open_session()
        completed = False

        try:
            chan.invoke_shell()

            LOG.debug("Reading CLI MOTD")
            self._get_output(chan)

            cmd = 'stty columns 255'
            LOG.debug("Setting CLI terminal width: '%s'", cmd)
            chan.send(cmd + '\r')
            out = self._get_output(chan)

            LOG.debug("Sending CLI command: '%s'", command)
            chan.send(command + '\r')
            out = self._get_output(chan)

            completed = True

            if any(ln.startswith(('% Error', 'Error:')) for ln in out):
                desc = _("Error executing EQL command")
                cmdout = '\n'.join(out)
                LOG.error(cmdout)
                raise processutils.ProcessExecutionError(
                    stdout=cmdout, cmd=command, description=desc)
            return out
        finally:
            if not completed:
                LOG.debug("Timed out executing command: '%s'", command)
            chan.close()

    def _run_ssh(self, cmd_list, attempts=1):
        utils.check_ssh_injection(cmd_list)
        command = ' '. join(cmd_list)

        if not self.sshpool:
            password = self.configuration.san_password
            privatekey = self.configuration.san_private_key
            min_size = self.configuration.ssh_min_pool_conn
            max_size = self.configuration.ssh_max_pool_conn
            self.sshpool = ssh_utils.SSHPool(
                self.configuration.san_ip,
                self.configuration.san_ssh_port,
                self.configuration.ssh_conn_timeout,
                self.configuration.san_login,
                password=password,
                privatekey=privatekey,
                min_size=min_size,
                max_size=max_size)
        try:
            total_attempts = attempts
            with self.sshpool.item() as ssh:
                while attempts > 0:
                    attempts -= 1
                    try:
                        LOG.info(_LI('EQL-driver: executing "%s".'), command)
                        return self._ssh_execute(
                            ssh, command,
                            timeout=self.configuration.eqlx_cli_timeout)
                    except processutils.ProcessExecutionError:
                        raise
                    except Exception as e:
                        LOG.exception(e)
                        greenthread.sleep(random.randint(20, 500) / 100.0)
                msg = (_("SSH Command failed after '%(total_attempts)r' "
                         "attempts : '%(command)s'") %
                       {'total_attempts': total_attempts - attempts,
                        'command': command})
                raise exception.VolumeBackendAPIException(data=msg)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error running SSH command: "%s".'), command)

    def check_for_setup_error(self):
        super(DellEQLSanISCSIDriver, self).check_for_setup_error()
        if self.configuration.eqlx_cli_max_retries < 0:
            raise exception.InvalidInput(
                reason=_("eqlx_cli_max_retries must be greater than or "
                         "equal to 0"))

    def _eql_execute(self, *args, **kwargs):
        return self._run_ssh(
            args, attempts=self.configuration.eqlx_cli_max_retries + 1)

    def _get_volume_data(self, lines):
        prefix = 'iSCSI target name is '
        target_name = self._get_prefixed_value(lines, prefix)[:-1]
        lun_id = "%s:%s,1 %s 0" % (self._group_ip, '3260', target_name)
        model_update = {}
        model_update['provider_location'] = lun_id
        if self.configuration.use_chap_auth:
            model_update['provider_auth'] = 'CHAP %s %s' % \
                (self.configuration.chap_username,
                 self.configuration.chap_password)
        return model_update

    def _get_space_in_gb(self, val):
        scale = 1.0
        part = 'GB'
        if val.endswith('MB'):
            scale = 1.0 / 1024
            part = 'MB'
        elif val.endswith('TB'):
            scale = 1.0 * 1024
            part = 'TB'
        return scale * float(val.partition(part)[0])

    def _update_volume_stats(self):
        """Retrieve stats info from eqlx group."""

        LOG.debug('Updating volume stats.')
        data = {}
        backend_name = "eqlx"
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or 'eqlx'
        data["vendor_name"] = 'Dell'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = 'iSCSI'

        data['reserved_percentage'] = 0
        data['QoS_support'] = False

        data['total_capacity_gb'] = 0
        data['free_capacity_gb'] = 0

        for line in self._eql_execute('pool', 'select',
                                      self.configuration.eqlx_pool, 'show'):
            if line.startswith('TotalCapacity:'):
                out_tup = line.rstrip().partition(' ')
                data['total_capacity_gb'] = self._get_space_in_gb(out_tup[-1])
            if line.startswith('FreeSpace:'):
                out_tup = line.rstrip().partition(' ')
                data['free_capacity_gb'] = self._get_space_in_gb(out_tup[-1])

        self._stats = data

    def _check_volume(self, volume):
        """Check if the volume exists on the Array."""
        command = ['volume', 'select', volume['name'], 'show']
        try:
            self._eql_execute(*command)
        except processutils.ProcessExecutionError as err:
            with excutils.save_and_reraise_exception():
                if err.stdout.find('does not exist.\n') > -1:
                    LOG.debug('Volume %s does not exist, '
                              'it may have already been deleted',
                              volume['name'])
                    raise exception.VolumeNotFound(volume_id=volume['id'])

    def _parse_connection(self, connector, out):
        """Returns the correct connection id for the initiator.

        This parses the cli output from the command
        'volume select <volumename> access show'
        and returns the correct connection id.
        """
        lines = [line for line in out if line != '']
        # Every record has 2 lines
        for i in xrange(0, len(lines), 2):
            try:
                int(lines[i][0])
                # sanity check
                if len(lines[i + 1].split()) == 1:
                    check = lines[i].split()[1] + lines[i + 1].strip()
                    if connector['initiator'] == check:
                        return lines[i].split()[0]
            except (IndexError, ValueError):
                pass  # skip the line that is not a valid access record

        return None

    def do_setup(self, context):
        """Disable cli confirmation and tune output format."""
        try:
            disabled_cli_features = ('confirmation', 'paging', 'events',
                                     'formatoutput')
            for feature in disabled_cli_features:
                self._eql_execute('cli-settings', feature, 'off')

            for line in self._eql_execute('grpparams', 'show'):
                if line.startswith('Group-Ipaddress:'):
                    out_tup = line.rstrip().partition(' ')
                    self._group_ip = out_tup[-1]

            LOG.info(_LI('EQL-driver: Setup is complete, group IP is "%s".'),
                     self._group_ip)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to setup the Dell EqualLogic driver.'))

    def create_volume(self, volume):
        """Create a volume."""
        try:
            cmd = ['volume', 'create',
                   volume['name'], "%sG" % (volume['size'])]
            if self.configuration.eqlx_pool != 'default':
                cmd.append('pool')
                cmd.append(self.configuration.eqlx_pool)
            if self.configuration.san_thin_provision:
                cmd.append('thin-provision')
            out = self._eql_execute(*cmd)
            self.add_multihost_access(volume)
            return self._get_volume_data(out)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to create volume "%s".'), volume['name'])

    def add_multihost_access(self, volume):
        """Add multihost-access to a volume. Needed for live migration."""
        try:
            cmd = ['volume', 'select',
                   volume['name'], 'multihost-access', 'enable']
            self._eql_execute(*cmd)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to add multihost-access '
                              'for volume "%s".'),
                          volume['name'])

    def delete_volume(self, volume):
        """Delete a volume."""
        try:
            self._check_volume(volume)
            self._eql_execute('volume', 'select', volume['name'], 'offline')
            self._eql_execute('volume', 'delete', volume['name'])
        except exception.VolumeNotFound:
            LOG.warn(_LW('Volume %s was not found while trying to delete it.'),
                     volume['name'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to delete '
                              'volume "%s".'), volume['name'])

    def create_snapshot(self, snapshot):
        """"Create snapshot of existing volume on appliance."""
        try:
            out = self._eql_execute('volume', 'select',
                                    snapshot['volume_name'],
                                    'snapshot', 'create-now')
            prefix = 'Snapshot name is '
            snap_name = self._get_prefixed_value(out, prefix)
            self._eql_execute('volume', 'select', snapshot['volume_name'],
                              'snapshot', 'rename', snap_name,
                              snapshot['name'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to create snapshot of volume "%s".'),
                          snapshot['volume_name'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other volume's snapshot on appliance."""
        try:
            out = self._eql_execute('volume', 'select',
                                    snapshot['volume_name'], 'snapshot',
                                    'select', snapshot['name'],
                                    'clone', volume['name'])
            self.add_multihost_access(volume)
            return self._get_volume_data(out)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to create volume from snapshot "%s".'),
                          snapshot['name'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        try:
            src_volume_name = src_vref['name']
            out = self._eql_execute('volume', 'select', src_volume_name,
                                    'clone', volume['name'])
            self.add_multihost_access(volume)
            return self._get_volume_data(out)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to create clone of volume "%s".'),
                          volume['name'])

    def delete_snapshot(self, snapshot):
        """Delete volume's snapshot."""
        try:
            self._eql_execute('volume', 'select', snapshot['volume_name'],
                              'snapshot', 'delete', snapshot['name'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to delete snapshot %(snap)s of '
                              'volume %(vol)s.'),
                          {'snap': snapshot['name'],
                           'vol': snapshot['volume_name']})

    def initialize_connection(self, volume, connector):
        """Restrict access to a volume."""
        try:
            cmd = ['volume', 'select', volume['name'], 'access', 'create',
                   'initiator', connector['initiator']]
            if self.configuration.use_chap_auth:
                cmd.extend(['authmethod', 'chap', 'username',
                            self.configuration.chap_username])
            self._eql_execute(*cmd)
            iscsi_properties = self._get_iscsi_properties(volume)
            return {
                'driver_volume_type': 'iscsi',
                'data': iscsi_properties
            }
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to initialize connection '
                              'to volume "%s".'),
                          volume['name'])

    def terminate_connection(self, volume, connector, force=False, **kwargs):
        """Remove access restrictions from a volume."""
        try:
            out = self._eql_execute('volume', 'select', volume['name'],
                                    'access', 'show')
            connection_id = self._parse_connection(connector, out)
            if connection_id is not None:
                self._eql_execute('volume', 'select', volume['name'],
                                  'access', 'delete', connection_id)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to terminate connection '
                              'to volume "%s".'),
                          volume['name'])

    def create_export(self, context, volume):
        """Create an export of a volume.

        Driver has nothing to do here for the volume has been exported
        already by the SAN, right after it's creation.
        """
        pass

    def ensure_export(self, context, volume):
        """Ensure an export of a volume.

        Driver has nothing to do here for the volume has been exported
        already by the SAN, right after it's creation. We will just make
        sure that the volume exists on the array and issue a warning.
        """
        try:
            self._check_volume(volume)
        except exception.VolumeNotFound:
            LOG.warn(_LW('Volume %s is not found!, it may have been deleted.'),
                     volume['name'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to ensure export of volume "%s".'),
                          volume['name'])

    def remove_export(self, context, volume):
        """Remove an export of a volume.

        Driver has nothing to do here for the volume has been exported
        already by the SAN, right after it's creation.
        Nothing to remove since there's nothing exported.
        """
        pass

    def extend_volume(self, volume, new_size):
        """Extend the size of the volume."""
        try:
            self._eql_execute('volume', 'select', volume['name'],
                              'size', "%sG" % new_size)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to extend_volume %(name)s from '
                              '%(current_size)sGB to %(new_size)sGB.'),
                          {'name': volume['name'],
                           'current_size': volume['size'],
                           'new_size': new_size})

    def local_path(self, volume):
        raise NotImplementedError()
