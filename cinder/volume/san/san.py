# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
controller on the SAN hardware.  We expect to access it over SSH or some API.
"""

import os
import paramiko

from cinder import exception
from cinder import flags
from cinder.openstack.common import log as logging
from cinder.openstack.common import cfg
from cinder import utils
from cinder.volume.driver import ISCSIDriver


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
               help='Password for SAN controller'),
    cfg.StrOpt('san_private_key',
               default='',
               help='Filename of private key to use for SSH authentication'),
    cfg.StrOpt('san_clustername',
               default='',
               help='Cluster name to use for creating volumes'),
    cfg.IntOpt('san_ssh_port',
               default=22,
               help='SSH port to use with SAN'),
    cfg.BoolOpt('san_is_local',
                default=False,
                help='Execute commands locally instead of over SSH; '
                     'use if the volume service is running on the SAN device'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(san_opts)


class SanISCSIDriver(ISCSIDriver):
    """Base class for SAN-style storage volumes

    A SAN-style storage value is 'different' because the volume controller
    probably won't run on it, so we need to access is over SSH or another
    remote protocol.
    """

    def __init__(self, *args, **kwargs):
        super(SanISCSIDriver, self).__init__(*args, **kwargs)
        self.run_local = FLAGS.san_is_local

    def _build_iscsi_target_name(self, volume):
        return "%s%s" % (FLAGS.iscsi_target_prefix, volume['name'])

    def _connect_to_ssh(self):
        ssh = paramiko.SSHClient()
        #TODO(justinsb): We need a better SSH key policy
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if FLAGS.san_password:
            ssh.connect(FLAGS.san_ip,
                        port=FLAGS.san_ssh_port,
                        username=FLAGS.san_login,
                        password=FLAGS.san_password)
        elif FLAGS.san_private_key:
            privatekeyfile = os.path.expanduser(FLAGS.san_private_key)
            # It sucks that paramiko doesn't support DSA keys
            privatekey = paramiko.RSAKey.from_private_key_file(privatekeyfile)
            ssh.connect(FLAGS.san_ip,
                        port=FLAGS.san_ssh_port,
                        username=FLAGS.san_login,
                        pkey=privatekey)
        else:
            msg = _("Specify san_password or san_private_key")
            raise exception.InvalidInput(reason=msg)
        return ssh

    def _execute(self, *cmd, **kwargs):
        if self.run_local:
            return utils.execute(*cmd, **kwargs)
        else:
            check_exit_code = kwargs.pop('check_exit_code', None)
            command = ' '.join(cmd)
            return self._run_ssh(command, check_exit_code)

    def _run_ssh(self, command, check_exit_code=True):
        #TODO(justinsb): SSH connection caching (?)
        ssh = self._connect_to_ssh()

        #TODO(justinsb): Reintroduce the retry hack
        ret = utils.ssh_execute(ssh, command, check_exit_code=check_exit_code)

        ssh.close()

        return ret

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, context, volume):
        """Exports the volume."""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        if not self.run_local:
            if not (FLAGS.san_password or FLAGS.san_private_key):
                raise exception.InvalidInput(
                    reason=_('Specify san_password or san_private_key'))

        # The san_ip must always be set, because we use it for the target
        if not FLAGS.san_ip:
            raise exception.InvalidInput(reason=_("san_ip must be set"))
