# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
# Copyright 2014 Red Hat, Inc.
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

"""Utilities related to SSH connection management."""

import os.path

from eventlet import pools
import paramiko

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class SSHPool(pools.Pool):
    """A simple eventlet pool to hold ssh connections."""

    def __init__(self, ip, port, conn_timeout, login, password=None,
                 privatekey=None, *args, **kwargs):
        self.ip = ip
        self.port = port
        self.login = login
        self.password = password
        self.conn_timeout = conn_timeout if conn_timeout else None
        self.privatekey = privatekey
        if 'missing_key_policy' in kwargs.keys():
            self.missing_key_policy = kwargs.pop('missing_key_policy')
        else:
            self.missing_key_policy = paramiko.AutoAddPolicy()
        if 'hosts_key_file' in kwargs.keys():
            self.hosts_key_file = kwargs.pop('hosts_key_file')
        else:
            self.hosts_key_file = None
        super(SSHPool, self).__init__(*args, **kwargs)

    def create(self):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(self.missing_key_policy)
            if not self.hosts_key_file:
                ssh.load_system_host_keys()
            else:
                ssh.load_host_keys(self.hosts_key_file)
            if self.password:
                ssh.connect(self.ip,
                            port=self.port,
                            username=self.login,
                            password=self.password,
                            timeout=self.conn_timeout)
            elif self.privatekey:
                pkfile = os.path.expanduser(self.privatekey)
                privatekey = paramiko.RSAKey.from_private_key_file(pkfile)
                ssh.connect(self.ip,
                            port=self.port,
                            username=self.login,
                            pkey=privatekey,
                            timeout=self.conn_timeout)
            else:
                msg = _("Specify a password or private_key")
                raise exception.CinderException(msg)

            # Paramiko by default sets the socket timeout to 0.1 seconds,
            # ignoring what we set through the sshclient. This doesn't help for
            # keeping long lived connections. Hence we have to bypass it, by
            # overriding it after the transport is initialized. We are setting
            # the sockettimeout to None and setting a keepalive packet so that,
            # the server will keep the connection open. All that does is send
            # a keepalive packet every ssh_conn_timeout seconds.
            if self.conn_timeout:
                transport = ssh.get_transport()
                transport.sock.settimeout(None)
                transport.set_keepalive(self.conn_timeout)
            return ssh
        except Exception as e:
            msg = _("Error connecting via ssh: %s") % e
            LOG.error(msg)
            raise paramiko.SSHException(msg)

    def get(self):
        """Return an item from the pool, when one is available.

        This may cause the calling greenthread to block. Check if a
        connection is active before returning it.

        For dead connections create and return a new connection.
        """
        conn = super(SSHPool, self).get()
        if conn:
            if conn.get_transport().is_active():
                return conn
            else:
                conn.close()
        return self.create()

    def remove(self, ssh):
        """Close an ssh client and remove it from free_items."""
        ssh.close()
        ssh = None
        if ssh in self.free_items:
            self.free_items.pop(ssh)
        if self.current_size > 0:
            self.current_size -= 1
