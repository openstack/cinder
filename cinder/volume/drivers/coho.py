# Copyright (c) 2015 Coho Data, Inc.
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

import errno
import os
import six
import socket
import xdrlib

from oslo_config import cfg
from oslo_log import log as logging
from random import randint

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume import configuration
from cinder.volume.drivers import nfs
from cinder.volume import qos_specs
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

#
# RPC Definition
#

RPCVERSION = 2

CALL = 0
REPLY = 1

AUTH_NULL = 0

MSG_ACCEPTED = 0
MSG_DENIED = 1

SUCCESS = 0
PROG_UNAVAIL = 1
PROG_MISMATCH = 2
PROC_UNAVAIL = 3
GARBAGE_ARGS = 4

RPC_MISMATCH = 0
AUTH_ERROR = 1

COHO_PROGRAM = 400115
COHO_V1 = 1
COHO1_CREATE_SNAPSHOT = 1
COHO1_DELETE_SNAPSHOT = 2
COHO1_CREATE_VOLUME_FROM_SNAPSHOT = 3
COHO1_SET_QOS_POLICY = 4

COHO_MAX_RETRIES = 5

COHO_NO_QOS = {'maxIOPS': 0, 'maxMBS': 0}

#
# Simple RPC Client
#


class Client(object):

    def __init__(self, address, prog, vers, port):
        self.packer = xdrlib.Packer()
        self.unpacker = xdrlib.Unpacker('')
        self.address = address
        self.prog = prog
        self.vers = vers
        self.port = port
        self.cred = None
        self.verf = None

        self.init_socket()
        self.init_xid()

    def init_socket(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.address, self.port))
        except socket.error:
            msg = _('Failed to establish connection with Coho cluster')
            raise exception.CohoException(msg)

    def init_xid(self):
        self.xid = randint(0, 4096)

    def make_xid(self):
        self.xid += 1

    def make_cred(self):
        if self.cred is None:
            self.cred = (AUTH_NULL, six.b(''))
        return self.cred

    def make_verf(self):
        if self.verf is None:
            self.verf = (AUTH_NULL, six.b(''))
        return self.verf

    def pack_auth(self, auth):
        flavor, stuff = auth
        self.packer.pack_enum(flavor)
        self.packer.pack_opaque(stuff)

    def pack_callheader(self, xid, prog, vers, proc, cred, verf):
        self.packer.pack_uint(xid)
        self.packer.pack_enum(CALL)
        self.packer.pack_uint(RPCVERSION)
        self.packer.pack_uint(prog)
        self.packer.pack_uint(vers)
        self.packer.pack_uint(proc)
        self.pack_auth(cred)
        self.pack_auth(verf)

    def unpack_auth(self):
        flavor = self.unpacker.unpack_enum()
        stuff = self.unpacker.unpack_opaque()
        return (flavor, stuff)

    def unpack_replyheader(self):
        xid = self.unpacker.unpack_uint()
        mtype = self.unpacker.unpack_enum()
        if mtype != REPLY:
            raise exception.CohoException(
                _('no REPLY but %r') % (mtype,))
        stat = self.unpacker.unpack_enum()
        if stat == MSG_DENIED:
            stat = self.unpacker.unpack_enum()
            if stat == RPC_MISMATCH:
                low = self.unpacker.unpack_uint()
                high = self.unpacker.unpack_uint()
                raise exception.CohoException(
                    _('MSG_DENIED: RPC_MISMATCH: %r') % ((low, high),))
            if stat == AUTH_ERROR:
                stat = self.unpacker.unpack_uint()
                raise exception.CohoException(
                    _('MSG_DENIED: AUTH_ERROR: %r') % (stat,))
            raise exception.CohoException(_('MSG_DENIED: %r') % (stat,))
        if stat != MSG_ACCEPTED:
            raise exception.CohoException(
                _('Neither MSG_DENIED nor MSG_ACCEPTED: %r') % (stat,))
        verf = self.unpack_auth()
        stat = self.unpacker.unpack_enum()
        if stat == PROG_UNAVAIL:
            raise exception.CohoException(_('call failed: PROG_UNAVAIL'))
        if stat == PROG_MISMATCH:
            low = self.unpacker.unpack_uint()
            high = self.unpacker.unpack_uint()
            raise exception.CohoException(
                _('call failed: PROG_MISMATCH: %r') % ((low, high),))
        if stat == PROC_UNAVAIL:
            raise exception.CohoException(_('call failed: PROC_UNAVAIL'))
        if stat == GARBAGE_ARGS:
            raise exception.CohoException(_('call failed: GARBAGE_ARGS'))
        if stat != SUCCESS:
            raise exception.CohoException(_('call failed: %r') % (stat,))
        return xid, verf

    def init_call(self, proc, args):
        self.make_xid()
        self.packer.reset()
        cred = self.make_cred()
        verf = self.make_verf()
        self.pack_callheader(self.xid, self.prog, self.vers, proc, cred, verf)

        for arg, func in args:
            func(arg)

        return self.xid, self.packer.get_buf()

    def _sendfrag(self, last, frag):
        x = len(frag)
        if last:
            x = x | 0x80000000
        header = (six.int2byte(int(x >> 24 & 0xff)) +
                  six.int2byte(int(x >> 16 & 0xff)) +
                  six.int2byte(int(x >> 8 & 0xff)) +
                  six.int2byte(int(x & 0xff)))
        self.sock.send(header + frag)

    def _sendrecord(self, record):
        self._sendfrag(1, record)

    def _recvfrag(self):
        header = self.sock.recv(4)
        if len(header) < 4:
            raise exception.CohoException(
                _('Invalid response header from RPC server'))
        x = (six.indexbytes(header, 0) << 24 |
             six.indexbytes(header, 1) << 16 |
             six.indexbytes(header, 2) << 8 |
             six.indexbytes(header, 3))
        last = ((x & 0x80000000) != 0)
        n = int(x & 0x7fffffff)
        frag = six.b('')
        while n > 0:
            buf = self.sock.recv(n)
            if not buf:
                raise exception.CohoException(
                    _('RPC server response is incomplete'))
            n = n - len(buf)
            frag = frag + buf
        return last, frag

    def _recvrecord(self):
        record = six.b('')
        last = 0
        while not last:
            last, frag = self._recvfrag()
            record = record + frag
        return record

    def _make_call(self, proc, args):
        self.packer.reset()
        xid, call = self.init_call(proc, args)
        self._sendrecord(call)
        reply = self._recvrecord()
        self.unpacker.reset(reply)
        xid, verf = self.unpack_replyheader()

    @utils.synchronized('coho-rpc', external=True)
    def _call(self, proc, args):
        for retry in range(COHO_MAX_RETRIES):
            try:
                self._make_call(proc, args)
                break
            except socket.error as e:
                if e.errno == errno.EPIPE:
                    # Reopen connection to cluster and retry
                    LOG.debug('Re-establishing socket, retry number %d', retry)
                    self.init_socket()
                else:
                    msg = (_('Unable to send requests: %s') %
                           six.text_type(e))
                    raise exception.CohoException(msg)
        else:
            msg = _('Failed to establish a stable connection')
            raise exception.CohoException(msg)

        res = self.unpacker.unpack_uint()
        if res != SUCCESS:
            raise exception.CohoException(os.strerror(res))


class CohoRPCClient(Client):

    def __init__(self, address, port):
        Client.__init__(self, address, COHO_PROGRAM, 1, port)

    def create_snapshot(self, src, dst, flags):
        LOG.debug('COHO1_CREATE_SNAPSHOT src %s to dst %s', src, dst)
        self._call(COHO1_CREATE_SNAPSHOT,
                   [(six.b(src), self.packer.pack_string),
                    (six.b(dst), self.packer.pack_string),
                    (flags, self.packer.pack_uint)])

    def delete_snapshot(self, name):
        LOG.debug('COHO1_DELETE_SNAPSHOT name %s', name)
        self._call(COHO1_DELETE_SNAPSHOT,
                   [(six.b(name), self.packer.pack_string)])

    def create_volume_from_snapshot(self, src, dst):
        LOG.debug('COHO1_CREATE_VOLUME_FROM_SNAPSHOT src %s to dst %s',
                  src, dst)
        self._call(COHO1_CREATE_VOLUME_FROM_SNAPSHOT,
                   [(six.b(src), self.packer.pack_string),
                    (six.b(dst), self.packer.pack_string)])

    def set_qos_policy(self, src, qos):
        LOG.debug('COHO1_SET_QOS_POLICY volume %s, uuid %s, %d:%d',
                  src, qos.get('uuid', ''), qos.get('maxIOPS', 0),
                  qos.get('maxMBS', ''))
        self._call(COHO1_SET_QOS_POLICY,
                   [(six.b(src), self.packer.pack_string),
                    (six.b(qos.get('uuid', '')), self.packer.pack_string),
                    (0, self.packer.pack_uhyper),
                    (qos.get('maxIOPS', 0), self.packer.pack_uhyper),
                    (0, self.packer.pack_uhyper),
                    (qos.get('maxMBS', 0), self.packer.pack_uhyper)])


#
# Coho Data Volume Driver
#

VERSION = '1.1.1'

coho_opts = [
    cfg.IntOpt('coho_rpc_port',
               default=2049,
               help='RPC port to connect to Coho Data MicroArray')
]

CONF = cfg.CONF
CONF.register_opts(coho_opts, group=configuration.SHARED_CONF_GROUP)


@interface.volumedriver
class CohoDriver(nfs.NfsDriver):
    """Coho Data NFS based cinder driver.

    Creates file on NFS share for using it as block device on hypervisor.
    Version history:
    1.0.0 - Initial driver
    1.1.0 - Added QoS support
    1.1.1 - Stability fixes in the RPC client
    """

    # We have to overload this attribute of RemoteFSDriver because
    # unfortunately the base method doesn't accept exports of the form:
    # <address>:/
    # It expects a non blank export name following the /.
    # We are more permissive.
    SHARE_FORMAT_REGEX = r'.+:/.*'

    COHO_QOS_KEYS = ['maxIOPS', 'maxMBS']

    # ThirdPartySystems wiki page name
    CI_WIKI_NAME = "Coho_Data_CI"

    # TODO(smcginnis) Remove driver in Queens if CI issues not fixed
    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        super(CohoDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(coho_opts)
        self._backend_name = (self.configuration.volume_backend_name or
                              self.__class__.__name__)

    def _get_rpcclient(self, addr, port):
        return CohoRPCClient(addr, port)

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(CohoDriver, self).do_setup(context)
        self._execute_as_root = True
        self._context = context

        config = self.configuration.coho_rpc_port
        if not config:
            msg = _("Coho rpc port is not configured")
            LOG.warning(msg)
            raise exception.CohoException(msg)
        if config < 1 or config > 65535:
            msg = (_("Invalid port number %(config)s for Coho rpc port") %
                   {'config': config})
            LOG.warning(msg)
            raise exception.CohoException(msg)

    def _do_clone_volume(self, volume, src):
        """Clone volume to source.

        Create a volume on given remote share with the same contents
        as the specified source.
        """
        volume_path = self.local_path(volume)
        source_path = self.local_path(src)

        self._execute('cp', source_path, volume_path,
                      run_as_root=self._execute_as_root)

        qos = self._retrieve_qos_setting(volume)
        self._do_set_qos_policy(volume, qos)

    def _get_volume_location(self, volume_id):
        """Returns provider location for given volume."""

        # The driver should not directly access db, but since volume is not
        # passed in create_snapshot and delete_snapshot we are forced to read
        # the volume info from the database
        volume = self.db.volume_get(self._context, volume_id)
        addr, path = volume.provider_location.split(":")
        return addr, path

    def _do_set_qos_policy(self, volume, qos):
        if qos:
            addr, path = volume['provider_location'].split(':')
            volume_path = os.path.join(path, volume['name'])

            client = self._get_rpcclient(addr,
                                         self.configuration.coho_rpc_port)
            client.set_qos_policy(volume_path, qos)

    def _get_qos_by_volume_type(self, ctxt, type_id):
        qos = {}

        # NOTE(bardia): we only honor qos_specs
        if type_id:
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            qos_specs_id = volume_type.get('qos_specs_id')

            if qos_specs_id is not None:
                kvs = qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs']
                qos['uuid'] = qos_specs_id
            else:
                kvs = {}

            for key, value in kvs.items():
                if key in self.COHO_QOS_KEYS:
                    qos[key] = int(value)
        return qos

    def _retrieve_qos_setting(self, volume):
        ctxt = context.get_admin_context()
        type_id = volume['volume_type_id']

        return self._get_qos_by_volume_type(ctxt, type_id)

    def create_volume(self, volume):
        resp = super(CohoDriver, self).create_volume(volume)
        qos = self._retrieve_qos_setting(volume)
        self._do_set_qos_policy(volume, qos)

        return resp

    def create_snapshot(self, snapshot):
        """Create a volume snapshot."""
        addr, path = self._get_volume_location(snapshot['volume_id'])
        volume_path = os.path.join(path, snapshot['volume_name'])
        snapshot_name = snapshot['name']
        flags = 0  # unused at this time
        client = self._get_rpcclient(addr, self.configuration.coho_rpc_port)
        client.create_snapshot(volume_path, snapshot_name, flags)

    def delete_snapshot(self, snapshot):
        """Delete a volume snapshot."""
        addr, unused = self._get_volume_location(snapshot['volume_id'])
        snapshot_name = snapshot['name']
        client = self._get_rpcclient(addr, self.configuration.coho_rpc_port)
        client.delete_snapshot(snapshot_name)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""
        volume['provider_location'] = self._find_share(volume)
        addr, path = volume['provider_location'].split(":")
        volume_path = os.path.join(path, volume['name'])
        snapshot_name = snapshot['name']

        client = self._get_rpcclient(addr, self.configuration.coho_rpc_port)
        client.create_volume_from_snapshot(snapshot_name, volume_path)

        qos = self._retrieve_qos_setting(volume)
        self._do_set_qos_policy(volume, qos)

        return {'provider_location': volume['provider_location']}

    def _extend_file_sparse(self, path, size):
        """Extend the size of a file (with no additional disk usage)."""
        self._execute('truncate', '-s', '%sG' % size,
                      path, run_as_root=self._execute_as_root)

    def create_cloned_volume(self, volume, src_vref):
        volume['provider_location'] = self._find_share(volume)

        self._do_clone_volume(volume, src_vref)

        if volume['size'] > src_vref['size']:
            self.extend_volume(volume, volume['size'])

    def extend_volume(self, volume, new_size):
        """Extend the specified file to the new_size (sparsely)."""
        volume_path = self.local_path(volume)

        self._extend_file_sparse(volume_path, new_size)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        Changes the volume's QoS policy if needed.
        """
        qos = self._get_qos_by_volume_type(ctxt, new_type['id'])

        # Reset the QoS policy on the volume in case the previous
        # type had a QoS policy
        if not qos:
            qos = COHO_NO_QOS

        self._do_set_qos_policy(volume, qos)

        return True, None

    def get_volume_stats(self, refresh=False):
        """Pass in Coho Data information in volume stats."""
        _stats = super(CohoDriver, self).get_volume_stats(refresh)
        _stats["vendor_name"] = 'Coho Data'
        _stats["driver_version"] = VERSION
        _stats["storage_protocol"] = 'NFS'
        _stats["volume_backend_name"] = self._backend_name
        _stats["total_capacity_gb"] = 'unknown'
        _stats["free_capacity_gb"] = 'unknown'
        _stats["export_paths"] = self._mounted_shares
        _stats["QoS_support"] = True

        return _stats
