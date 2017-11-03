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

"""Methods for working with eventlet WSGI servers."""

import socket

from oslo_config import cfg
from oslo_service import wsgi
from oslo_utils import netutils


socket_opts = [
    cfg.BoolOpt('tcp_keepalive',
                default=True,
                help="Sets the value of TCP_KEEPALIVE (True/False) for each "
                     "server socket."),
    cfg.IntOpt('tcp_keepalive_interval',
               help="Sets the value of TCP_KEEPINTVL in seconds for each "
                    "server socket. Not supported on OS X."),
    cfg.IntOpt('tcp_keepalive_count',
               help="Sets the value of TCP_KEEPCNT for each "
                    "server socket. Not supported on OS X."),
]


CONF = cfg.CONF
CONF.register_opts(socket_opts)


class Server(wsgi.Server):
    """Server class to manage a WSGI server, serving a WSGI application."""

    def _set_socket_opts(self, _socket):
        _socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # NOTE(praneshp): Call set_tcp_keepalive in oslo to set
        # tcp keepalive parameters. Sockets can hang around forever
        # without keepalive
        netutils.set_tcp_keepalive(_socket,
                                   self.conf.tcp_keepalive,
                                   self.conf.tcp_keepidle,
                                   self.conf.tcp_keepalive_count,
                                   self.conf.tcp_keepalive_interval)

        return _socket
