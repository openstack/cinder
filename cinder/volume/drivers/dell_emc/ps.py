#    Copyright (c) 2013-2017 Dell Inc, or its subsidiaries.
#    Copyright 2013 OpenStack Foundation
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

"""Volume driver for Dell EMC PS Series Storage."""

import functools
import math
import random

import eventlet
from eventlet import greenthread
import greenlet
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from six.moves import range

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import ssh_utils
from cinder import utils
from cinder.volume import configuration
from cinder.volume.drivers import san

LOG = logging.getLogger(__name__)

eqlx_opts = [
    cfg.StrOpt('eqlx_group_name',
               default='group-0',
               help='Group name to use for creating volumes. Defaults to '
                    '"group-0".'),
    cfg.IntOpt('eqlx_cli_max_retries',
               min=0,
               default=5,
               help='Maximum retry count for reconnection. Default is 5.'),
    cfg.StrOpt('eqlx_pool',
               default='default',
               help='Pool in which volumes will be created. Defaults '
                    'to "default".')
]


CONF = cfg.CONF
CONF.register_opts(eqlx_opts, group=configuration.SHARED_CONF_GROUP)


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


@interface.volumedriver
class PSSeriesISCSIDriver(san.SanISCSIDriver):
    """Implements commands for Dell EMC PS Series ISCSI management.

    To enable the driver add the following line to the cinder configuration:
        volume_driver=cinder.volume.drivers.dell_emc.ps.PSSeriesISCSIDriver

    Driver's prerequisites are:
        - a separate volume group set up and running on the SAN
        - SSH access to the SAN
        - a special user must be created which must be able to
            - create/delete volumes and snapshots;
            - clone snapshots into volumes;
            - modify volume access records;

    The access credentials to the SAN are provided by means of the following
    flags:

    .. code-block:: ini

        san_ip=<ip_address>
        san_login=<user name>
        san_password=<user password>
        san_private_key=<file containing SSH private key>

    Thin provision of volumes is enabled by default, to disable it use:

    .. code-block:: ini

        san_thin_provision=false

    In order to use target CHAP authentication (which is disabled by default)
    SAN administrator must create a local CHAP user and specify the following
    flags for the driver:

    .. code-block:: ini

        use_chap_auth=True
        chap_login=<chap_login>
        chap_password=<chap_password>

    eqlx_group_name parameter actually represents the CLI prompt message
    without '>' ending. E.g. if prompt looks like 'group-0>', then the
    parameter must be set to 'group-0'

    Version history:

    .. code-block:: none

        1.0   - Initial driver
        1.1.0 - Misc fixes
        1.2.0 - Deprecated eqlx_cli_timeout infavor of ssh_conn_timeout
        1.3.0 - Added support for manage/unmanage volume
        1.4.0 - Removed deprecated options eqlx_cli_timeout, eqlx_use_chap,
                eqlx_chap_login, and eqlx_chap_password.
        1.4.1 - Rebranded driver to Dell EMC.
        1.4.2 - Enable report discard support.
        1.4.4 - Fixed over-subscription ratio calculation
        1.4.5 - Optimize volume stats information parsing
        1.4.6 - Extend volume with no-snap option

    """

    VERSION = "1.4.6"

    # ThirdPartySytems wiki page
    CI_WIKI_NAME = "Dell_Storage_CI"

    def __init__(self, *args, **kwargs):
        super(PSSeriesISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(eqlx_opts)
        self._group_ip = None
        self.sshpool = None

    def _get_output(self, chan):
        out = ''
        ending = '%s> ' % self.configuration.eqlx_group_name
        while out.find(ending) == -1:
            ret = chan.recv(102400)
            if len(ret) == 0:
                # According to paramiko.channel.Channel documentation, which
                # says "If a string of length zero is returned, the channel
                # stream has closed". So we can confirm that the PS server
                # has closed the connection.
                msg = _("The PS array has closed the connection.")
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
                desc = _("Error executing PS command")
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
                        LOG.info('PS-driver: executing "%s".', command)
                        return self._ssh_execute(
                            ssh, command,
                            timeout=self.configuration.ssh_conn_timeout)
                    except Exception:
                        LOG.exception('Error running command.')
                        greenthread.sleep(random.randint(20, 500) / 100.0)
                msg = (_("SSH Command failed after '%(total_attempts)r' "
                         "attempts : '%(command)s'") %
                       {'total_attempts': total_attempts - attempts,
                        'command': command})
                raise exception.VolumeBackendAPIException(data=msg)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Error running SSH command: "%s".', command)

    def check_for_setup_error(self):
        super(PSSeriesISCSIDriver, self).check_for_setup_error()

    def _eql_execute(self, *args, **kwargs):
        return self._run_ssh(
            args, attempts=self.configuration.eqlx_cli_max_retries + 1)

    def _get_volume_data(self, lines):
        prefix = 'iSCSI target name is '
        target_name = self._get_prefixed_value(lines, prefix)[:-1]
        return self._get_model_update(target_name)

    def _get_model_update(self, target_name):
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
        return math.ceil(scale * float(val.partition(part)[0]))

    def _update_volume_stats(self):
        """Retrieve stats info from eqlx group."""

        LOG.debug('Updating volume stats.')
        data = {}
        backend_name = "eqlx"
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or 'eqlx'
        data["vendor_name"] = 'Dell EMC'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = 'iSCSI'

        data['reserved_percentage'] = 0
        data['QoS_support'] = False

        data['total_capacity_gb'] = None
        data['free_capacity_gb'] = None
        data['multiattach'] = False

        data['total_volumes'] = None

        provisioned_capacity = None
        for line in self._eql_execute('pool', 'select',
                                      self.configuration.eqlx_pool, 'show'):
            if line.startswith('TotalCapacity:'):
                out_tup = line.rstrip().partition(' ')
                data['total_capacity_gb'] = self._get_space_in_gb(out_tup[-1])
            if line.startswith('FreeSpace:'):
                out_tup = line.rstrip().partition(' ')
                data['free_capacity_gb'] = self._get_space_in_gb(out_tup[-1])
            if line.startswith('VolumeReportedSpace:'):
                out_tup = line.rstrip().partition(' ')
                provisioned_capacity = self._get_space_in_gb(out_tup[-1])
            if line.startswith('TotalVolumes:'):
                out_tup = line.rstrip().partition(' ')
                data['total_volumes'] = int(out_tup[-1])
            # Terminate parsing once this data is found to improve performance
            if (data['total_capacity_gb'] and data['free_capacity_gb'] and
               provisioned_capacity and data['total_volumes']):
                break

        global_capacity = data['total_capacity_gb']
        global_free = data['free_capacity_gb']

        thin_enabled = self.configuration.san_thin_provision
        if not thin_enabled:
            provisioned_capacity = round(global_capacity - global_free, 2)

        data['provisioned_capacity_gb'] = provisioned_capacity
        data['max_over_subscription_ratio'] = (
            self.configuration.max_over_subscription_ratio)
        data['thin_provisioning_support'] = thin_enabled
        data['thick_provisioning_support'] = not thin_enabled

        self._stats = data

    def _get_volume_info(self, volume_name):
        """Get the volume details on the array"""
        command = ['volume', 'select', volume_name, 'show']
        try:
            data = {}
            for line in self._eql_execute(*command):
                if line.startswith('Size:'):
                    out_tup = line.rstrip().partition(' ')
                    data['size'] = self._get_space_in_gb(out_tup[-1])
                elif line.startswith('iSCSI Name:'):
                    out_tup = line.rstrip().partition(': ')
                    data['iSCSI_Name'] = out_tup[-1]
            return data
        except processutils.ProcessExecutionError:
            msg = (_("Volume does not exists %s.") % volume_name)
            LOG.error(msg)
            raise exception.ManageExistingInvalidReference(
                existing_ref=volume_name, reason=msg)

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

    def _get_access_record(self, volume, connector):
        """Returns access record id for the initiator"""
        try:
            out = self._eql_execute('volume', 'select', volume['name'],
                                    'access', 'show')
            return self._parse_connection(connector, out)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to get access records '
                          'to volume "%s".', volume['name'])

    def _parse_connection(self, connector, out):
        """Returns the correct connection id for the initiator.

        This parses the cli output from the command
        'volume select <volumename> access show'
        and returns the correct connection id.
        """
        lines = [line for line in out if line != '']
        # Every record has 2 lines
        for i in range(0, len(lines), 2):
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

            LOG.info('PS-driver: Setup is complete, group IP is "%s".',
                     self._group_ip)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to setup the Dell EMC PS driver.')

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
                LOG.error('Failed to create volume "%s".', volume['name'])

    def add_multihost_access(self, volume):
        """Add multihost-access to a volume. Needed for live migration."""
        try:
            cmd = ['volume', 'select',
                   volume['name'], 'multihost-access', 'enable']
            self._eql_execute(*cmd)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to add multihost-access '
                          'for volume "%s".',
                          volume['name'])

    def _set_volume_description(self, volume, description):
        """Set the description of the volume"""
        try:
            cmd = ['volume', 'select',
                   volume['name'], 'description', description]
            self._eql_execute(*cmd)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to set description '
                          'for volume "%s".',
                          volume['name'])

    def delete_volume(self, volume):
        """Delete a volume."""
        try:
            self._check_volume(volume)
            self._eql_execute('volume', 'select', volume['name'], 'offline')
            self._eql_execute('volume', 'delete', volume['name'])
        except exception.VolumeNotFound:
            LOG.warning('Volume %s was not found while trying to delete it.',
                        volume['name'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to delete volume "%s".', volume['name'])

    def create_snapshot(self, snapshot):
        """Create snapshot of existing volume on appliance."""
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
                LOG.error('Failed to create snapshot of volume "%s".',
                          snapshot['volume_name'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other volume's snapshot on appliance."""
        try:
            out = self._eql_execute('volume', 'select',
                                    snapshot['volume_name'], 'snapshot',
                                    'select', snapshot['name'],
                                    'clone', volume['name'])
            # Extend Volume if needed
            if out and volume['size'] > snapshot['volume_size']:
                self.extend_volume(volume, volume['size'])
                LOG.debug('Volume from snapshot %(name)s resized from '
                          '%(current_size)sGB to %(new_size)sGB.',
                          {'name': volume['name'],
                           'current_size': snapshot['volume_size'],
                           'new_size': volume['size']})

            self.add_multihost_access(volume)
            return self._get_volume_data(out)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to create volume from snapshot "%s".',
                          snapshot['name'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        try:
            src_volume_name = src_vref['name']
            out = self._eql_execute('volume', 'select', src_volume_name,
                                    'clone', volume['name'])

            # Extend Volume if needed
            if out and volume['size'] > src_vref['size']:
                self.extend_volume(volume, volume['size'])

            self.add_multihost_access(volume)
            return self._get_volume_data(out)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to create clone of volume "%s".',
                          volume['name'])

    def delete_snapshot(self, snapshot):
        """Delete volume's snapshot."""
        try:
            self._eql_execute('volume', 'select', snapshot['volume_name'],
                              'snapshot', 'delete', snapshot['name'])
        except processutils.ProcessExecutionError as err:
            if err.stdout.find('does not exist') > -1:
                LOG.debug('Snapshot %s could not be found.', snapshot['name'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to delete snapshot %(snap)s of '
                          'volume %(vol)s.',
                          {'snap': snapshot['name'],
                           'vol': snapshot['volume_name']})

    def initialize_connection(self, volume, connector):
        """Restrict access to a volume."""
        try:
            connection_id = self._get_access_record(volume, connector)
            if connection_id is None:
                cmd = ['volume', 'select', volume['name'], 'access', 'create',
                       'initiator', connector['initiator']]
                if self.configuration.use_chap_auth:
                    cmd.extend(['authmethod', 'chap', 'username',
                                self.configuration.chap_username])
                self._eql_execute(*cmd)

            iscsi_properties = self._get_iscsi_properties(volume)
            iscsi_properties['discard'] = True
            return {
                'driver_volume_type': 'iscsi',
                'data': iscsi_properties
            }
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to initialize connection to volume "%s".',
                          volume['name'])

    def terminate_connection(self, volume, connector, force=False, **kwargs):
        """Remove access restrictions from a volume."""
        try:
            connection_id = self._get_access_record(volume, connector)
            if connection_id is not None:
                self._eql_execute('volume', 'select', volume['name'],
                                  'access', 'delete', connection_id)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to terminate connection to volume "%s".',
                          volume['name'])

    def create_export(self, context, volume, connector):
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
            LOG.warning('Volume %s is not found!, it may have been deleted.',
                        volume['name'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to ensure export of volume "%s".',
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
                              'size', "%sG" % new_size, 'no-snap')
            LOG.info('Volume %(name)s resized from '
                     '%(current_size)sGB to %(new_size)sGB.',
                     {'name': volume['name'],
                      'current_size': volume['size'],
                      'new_size': new_size})
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to extend_volume %(name)s from '
                          '%(current_size)sGB to %(new_size)sGB.',
                          {'name': volume['name'],
                           'current_size': volume['size'],
                           'new_size': new_size})

    def _get_existing_volume_ref_name(self, ref):
        existing_volume_name = None
        if 'source-name' in ref:
            existing_volume_name = ref['source-name']
        elif 'source-id' in ref:
            existing_volume_name = ref['source-id']
        else:
            msg = _('Reference must contain source-id or source-name.')
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        return existing_volume_name

    def manage_existing(self, volume, existing_ref):
        """Manage an existing volume on the backend storage."""
        existing_volume_name = self._get_existing_volume_ref_name(existing_ref)
        try:
            cmd = ['volume', 'rename',
                   existing_volume_name, volume['name']]
            self._eql_execute(*cmd)
            self._set_volume_description(volume, '"OpenStack Managed"')
            self.add_multihost_access(volume)
            data = self._get_volume_info(volume['name'])
            updates = self._get_model_update(data['iSCSI_Name'])
            LOG.info("Backend volume %(back_vol)s renamed to "
                     "%(vol)s and is now managed by cinder.",
                     {'back_vol': existing_volume_name,
                      'vol': volume['name']})
            return updates
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to manage volume "%s".', volume['name'])

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume
        """
        existing_volume_name = self._get_existing_volume_ref_name(existing_ref)
        data = self._get_volume_info(existing_volume_name)
        return data['size']

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        :param volume: Cinder volume to unmanage
        """
        try:
            self._set_volume_description(volume, '"OpenStack UnManaged"')
            LOG.info("Virtual volume %(disp)s '%(vol)s' is no "
                     "longer managed.",
                     {'disp': volume['display_name'],
                      'vol': volume['name']})
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to unmanage volume "%s".',
                          volume['name'])

    def local_path(self, volume):
        raise NotImplementedError()
