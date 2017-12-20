# Copyright 2011 Justin Santa Barbara
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
Default Driver for san-stored volumes.

The unique thing about a SAN is that we don't expect that we can run the volume
controller on the SAN hardware. We expect to access it over SSH or some API.
"""

import random

from eventlet import greenthread
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from cinder import exception
from cinder.i18n import _
from cinder import ssh_utils
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver

LOG = logging.getLogger(__name__)

san_opts = [
    cfg.BoolOpt('san_thin_provision',
                default=True,
                help='Use thin provisioning for SAN volumes?'),
    cfg.StrOpt('san_ip',
               default='',
               help='IP address of SAN controller'),
    cfg.StrOpt('san_login',
               default='admin',
               help='Username for SAN controller'),
    cfg.StrOpt('san_password',
               default='',
               help='Password for SAN controller',
               secret=True),
    cfg.StrOpt('san_private_key',
               default='',
               help='Filename of private key to use for SSH authentication'),
    cfg.StrOpt('san_clustername',
               default='',
               help='Cluster name to use for creating volumes'),
    cfg.PortOpt('san_ssh_port',
                default=22,
                help='SSH port to use with SAN'),
    cfg.PortOpt('san_api_port',
                help='Port to use to access the SAN API'),
    cfg.BoolOpt('san_is_local',
                default=False,
                help='Execute commands locally instead of over SSH; '
                     'use if the volume service is running on the SAN device'),
    cfg.IntOpt('ssh_conn_timeout',
               default=30,
               help="SSH connection timeout in seconds"),
    cfg.IntOpt('ssh_min_pool_conn',
               default=1,
               help='Minimum ssh connections in the pool'),
    cfg.IntOpt('ssh_max_pool_conn',
               default=5,
               help='Maximum ssh connections in the pool'),
]

CONF = cfg.CONF
CONF.register_opts(san_opts, group=configuration.SHARED_CONF_GROUP)


class SanDriver(driver.BaseVD):
    """Base class for SAN-style storage volumes

    A SAN-style storage value is 'different' because the volume controller
    probably won't run on it, so we need to access is over SSH or another
    remote protocol.
    """

    def __init__(self, *args, **kwargs):
        execute = kwargs.pop('execute', self.san_execute)
        super(SanDriver, self).__init__(execute=execute,
                                        *args, **kwargs)
        self.configuration.append_config_values(san_opts)
        self.run_local = self.configuration.san_is_local
        self.sshpool = None

    def san_execute(self, *cmd, **kwargs):
        if self.run_local:
            return utils.execute(*cmd, **kwargs)
        else:
            check_exit_code = kwargs.pop('check_exit_code', None)
            return self._run_ssh(cmd, check_exit_code)

    def _run_ssh(self, cmd_list, check_exit_code=True, attempts=1):
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
        last_exception = None
        try:
            with self.sshpool.item() as ssh:
                while attempts > 0:
                    attempts -= 1
                    try:
                        return processutils.ssh_execute(
                            ssh,
                            command,
                            check_exit_code=check_exit_code)
                    except Exception as e:
                        LOG.error(e)
                        last_exception = e
                        greenthread.sleep(random.randint(20, 500) / 100.0)
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

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, context, volume, connector):
        """Exports the volume."""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        if not self.run_local:
            if not (self.configuration.san_password or
                    self.configuration.san_private_key):
                raise exception.InvalidInput(
                    reason=_('Specify san_password or san_private_key'))

        # The san_ip must always be set, because we use it for the target
        if not self.configuration.san_ip:
            raise exception.InvalidInput(reason=_("san_ip must be set"))


class SanISCSIDriver(SanDriver, driver.ISCSIDriver):
    def __init__(self, *args, **kwargs):
        super(SanISCSIDriver, self).__init__(*args, **kwargs)

    def _build_iscsi_target_name(self, volume):
        return "%s%s" % (self.configuration.target_prefix,
                         volume['name'])
