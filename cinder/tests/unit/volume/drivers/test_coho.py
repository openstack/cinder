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
#

import binascii
import errno
import mock
import os
import six
import socket
import xdrlib

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_volume
from cinder.volume import configuration as conf
from cinder.volume.drivers import coho
from cinder.volume.drivers import nfs
from cinder.volume.drivers import remotefs
from cinder.volume import qos_specs
from cinder.volume import volume_types

ADDR = 'coho-datastream-addr'
PATH = '/test/path'
RPC_PORT = 2049
LOCAL_PATH = '/opt/cinder/mnt/test/path'

VOLUME = {
    'name': 'volume-bcc48c61-9691-4e5f-897c-793686093190',
    'volume_id': 'bcc48c61-9691-4e5f-897c-793686093190',
    'size': 128,
    'volume_type': 'silver',
    'volume_type_id': 'deadbeef-aaaa-bbbb-cccc-deadbeefbeef',
    'metadata': [{'key': 'type',
                  'service_label': 'silver'}],
    'provider_location': 'coho-datastream-addr:/test/path',
    'id': 'bcc48c61-9691-4e5f-897c-793686093190',
    'status': 'available',
}

CLONE_VOL = VOLUME.copy()
CLONE_VOL['size'] = 256

SNAPSHOT = {
    'name': 'snapshot-51dd4-8d8a-4aa9-9176-086c9d89e7fc',
    'id': '51dd4-8d8a-4aa9-9176-086c9d89e7fc',
    'size': 128,
    'volume_type': None,
    'provider_location': None,
    'volume_size': 128,
    'volume_name': 'volume-bcc48c61-9691-4e5f-897c-793686093190',
    'volume_id': 'bcc48c61-9691-4e5f-897c-793686093191',
}

VOLUME_TYPE = {
    'name': 'sf-1',
    'qos_specs_id': 'qos-spec-id',
    'deleted': False,
    'created_at': '2016-06-06 04:58:11',
    'updated_at': None,
    'extra_specs': {},
    'deleted_at': None,
    'id': 'deadbeef-aaaa-bbbb-cccc-deadbeefbeef'
}

QOS_SPEC = {
    'id': 'qos-spec-id',
    'specs': {
        'maxIOPS': '2000',
        'maxMBS': '500'
    }
}

QOS = {
    'uuid': 'qos-spec-id',
    'maxIOPS': 2000,
    'maxMBS': 500
}

INVALID_SNAPSHOT = SNAPSHOT.copy()
INVALID_SNAPSHOT['name'] = ''

INVALID_HEADER_BIN = binascii.unhexlify('800000')
NO_REPLY_BIN = binascii.unhexlify(
    'aaaaa01000000010000000000000000000000003')
MSG_DENIED_BIN = binascii.unhexlify(
    '00000a010000000110000000000000000000000000000003')
PROC_UNAVAIL_BIN = binascii.unhexlify(
    '00000a010000000100000000000000000000000000000003')
PROG_UNAVAIL_BIN = binascii.unhexlify(
    '000003c70000000100000000000000000000000000000001')
PROG_MISMATCH_BIN = binascii.unhexlify(
    '00000f7700000001000000000000000000000000000000020000000100000001')
GARBAGE_ARGS_BIN = binascii.unhexlify(
    '00000d6e0000000100000000000000000000000000000004')


class CohoDriverTest(test.TestCase):
    """Test Coho Data's NFS volume driver."""

    def __init__(self, *args, **kwargs):
        super(CohoDriverTest, self).__init__(*args, **kwargs)

    def setUp(self):
        super(CohoDriverTest, self).setUp()

        self.context = mock.Mock()
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.max_over_subscription_ratio = 20.0
        self.configuration.reserved_percentage = 0
        self.configuration.volume_backend_name = 'coho-1'
        self.configuration.coho_rpc_port = 2049
        self.configuration.nfs_shares_config = '/etc/cinder/coho_shares'
        self.configuration.nfs_sparsed_volumes = True
        self.configuration.nfs_mount_point_base = '/opt/stack/cinder/mnt'
        self.configuration.nfs_mount_options = None
        self.configuration.nas_host = None
        self.configuration.nas_share_path = None
        self.configuration.nas_mount_options = None

    def test_setup_failure_when_rpc_port_unconfigured(self):
        self.configuration.coho_rpc_port = None
        drv = coho.CohoDriver(configuration=self.configuration)

        self.mock_object(coho, 'LOG')
        self.mock_object(nfs.NfsDriver, 'do_setup')

        with self.assertRaisesRegex(exception.CohoException,
                                    ".*Coho rpc port is not configured.*"):
            drv.do_setup(self.context)

        self.assertTrue(coho.LOG.warning.called)
        self.assertTrue(nfs.NfsDriver.do_setup.called)

    def test_setup_failure_when_coho_rpc_port_is_invalid(self):
        self.configuration.coho_rpc_port = 99999
        drv = coho.CohoDriver(configuration=self.configuration)

        self.mock_object(coho, 'LOG')
        self.mock_object(nfs.NfsDriver, 'do_setup')

        with self.assertRaisesRegex(exception.CohoException,
                                    "Invalid port number.*"):
            drv.do_setup(self.context)

        self.assertTrue(coho.LOG.warning.called)
        self.assertTrue(nfs.NfsDriver.do_setup.called)

    def test_create_volume_with_qos(self):
        drv = coho.CohoDriver(configuration=self.configuration)

        volume = fake_volume.fake_volume_obj(self.context,
                                             **{'volume_type_id':
                                                VOLUME['volume_type_id'],
                                                'provider_location':
                                                VOLUME['provider_location']})
        mock_remotefs_create = self.mock_object(remotefs.RemoteFSDriver,
                                                'create_volume')
        mock_rpc_client = self.mock_object(coho, 'CohoRPCClient')
        mock_get_volume_type = self.mock_object(volume_types,
                                                'get_volume_type')
        mock_get_volume_type.return_value = VOLUME_TYPE
        mock_get_qos_specs = self.mock_object(qos_specs, 'get_qos_specs')
        mock_get_qos_specs.return_value = QOS_SPEC
        mock_get_admin_context = self.mock_object(context, 'get_admin_context')
        mock_get_admin_context.return_value = 'test'

        drv.create_volume(volume)

        self.assertTrue(mock_remotefs_create.called)
        self.assertTrue(mock_get_admin_context.called)
        mock_remotefs_create.assert_has_calls([mock.call(volume)])
        mock_get_volume_type.assert_has_calls(
            [mock.call('test', volume.volume_type_id)])
        mock_get_qos_specs.assert_has_calls(
            [mock.call('test', QOS_SPEC['id'])])
        mock_rpc_client.assert_has_calls(
            [mock.call(ADDR, self.configuration.coho_rpc_port),
             mock.call().set_qos_policy(os.path.join(PATH, volume.name),
                                        QOS)])

    def test_create_snapshot(self):
        drv = coho.CohoDriver(configuration=self.configuration)

        mock_rpc_client = self.mock_object(coho, 'CohoRPCClient')
        mock_get_volume_location = self.mock_object(coho.CohoDriver,
                                                    '_get_volume_location')
        mock_get_volume_location.return_value = ADDR, PATH

        drv.create_snapshot(SNAPSHOT)

        mock_get_volume_location.assert_has_calls(
            [mock.call(SNAPSHOT['volume_id'])])
        mock_rpc_client.assert_has_calls(
            [mock.call(ADDR, self.configuration.coho_rpc_port),
             mock.call().create_snapshot(
                os.path.join(PATH, SNAPSHOT['volume_name']),
                SNAPSHOT['name'], 0)])

    def test_delete_snapshot(self):
        drv = coho.CohoDriver(configuration=self.configuration)

        mock_rpc_client = self.mock_object(coho, 'CohoRPCClient')
        mock_get_volume_location = self.mock_object(coho.CohoDriver,
                                                    '_get_volume_location')
        mock_get_volume_location.return_value = ADDR, PATH

        drv.delete_snapshot(SNAPSHOT)

        mock_get_volume_location.assert_has_calls(
            [mock.call(SNAPSHOT['volume_id'])])
        mock_rpc_client.assert_has_calls(
            [mock.call(ADDR, self.configuration.coho_rpc_port),
             mock.call().delete_snapshot(SNAPSHOT['name'])])

    def test_create_volume_from_snapshot(self):
        drv = coho.CohoDriver(configuration=self.configuration)

        mock_rpc_client = self.mock_object(coho, 'CohoRPCClient')
        mock_find_share = self.mock_object(drv, '_find_share')
        mock_find_share.return_value = ADDR + ':' + PATH
        mock_get_volume_type = self.mock_object(volume_types,
                                                'get_volume_type')
        mock_get_volume_type.return_value = VOLUME_TYPE
        mock_get_qos_specs = self.mock_object(qos_specs, 'get_qos_specs')
        mock_get_qos_specs.return_value = QOS_SPEC
        mock_get_admin_context = self.mock_object(context, 'get_admin_context')
        mock_get_admin_context.return_value = 'test'

        drv.create_volume_from_snapshot(VOLUME, SNAPSHOT)

        mock_find_share.assert_has_calls(
            [mock.call(VOLUME)])
        self.assertTrue(mock_get_admin_context.called)
        mock_get_volume_type.assert_has_calls(
            [mock.call('test', VOLUME_TYPE['id'])])
        mock_get_qos_specs.assert_has_calls(
            [mock.call('test', QOS_SPEC['id'])])
        mock_rpc_client.assert_has_calls(
            [mock.call(ADDR, self.configuration.coho_rpc_port),
             mock.call().create_volume_from_snapshot(
                SNAPSHOT['name'], os.path.join(PATH, VOLUME['name'])),
             mock.call(ADDR, self.configuration.coho_rpc_port),
             mock.call().set_qos_policy(os.path.join(PATH, VOLUME['name']),
                                        QOS)])

    def test_create_cloned_volume(self):
        drv = coho.CohoDriver(configuration=self.configuration)

        mock_rpc_client = self.mock_object(coho, 'CohoRPCClient')
        mock_find_share = self.mock_object(drv, '_find_share')
        mock_find_share.return_value = ADDR + ':' + PATH
        mock_execute = self.mock_object(drv, '_execute')
        mock_local_path = self.mock_object(drv, 'local_path')
        mock_local_path.return_value = LOCAL_PATH
        mock_get_volume_type = self.mock_object(volume_types,
                                                'get_volume_type')
        mock_get_volume_type.return_value = VOLUME_TYPE
        mock_get_qos_specs = self.mock_object(qos_specs, 'get_qos_specs')
        mock_get_qos_specs.return_value = QOS_SPEC
        mock_get_admin_context = self.mock_object(context, 'get_admin_context')
        mock_get_admin_context.return_value = 'test'

        drv.create_cloned_volume(VOLUME, CLONE_VOL)

        mock_find_share.assert_has_calls(
            [mock.call(VOLUME)])
        mock_local_path.assert_has_calls(
            [mock.call(VOLUME), mock.call(CLONE_VOL)])
        mock_execute.assert_has_calls(
            [mock.call('cp', LOCAL_PATH, LOCAL_PATH, run_as_root=True)])
        self.assertTrue(mock_get_admin_context.called)
        mock_get_volume_type.assert_has_calls(
            [mock.call('test', VOLUME_TYPE['id'])])
        mock_get_qos_specs.assert_has_calls(
            [mock.call('test', QOS_SPEC['id'])])
        mock_rpc_client.assert_has_calls(
            [mock.call(ADDR, self.configuration.coho_rpc_port),
             mock.call().set_qos_policy(os.path.join(PATH, VOLUME['name']),
                                        QOS)])

    def test_retype(self):
        drv = coho.CohoDriver(configuration=self.configuration)

        mock_rpc_client = self.mock_object(coho, 'CohoRPCClient')
        mock_get_volume_type = self.mock_object(volume_types,
                                                'get_volume_type')
        mock_get_volume_type.return_value = VOLUME_TYPE
        mock_get_qos_specs = self.mock_object(qos_specs, 'get_qos_specs')
        mock_get_qos_specs.return_value = QOS_SPEC

        drv.retype('test', VOLUME, VOLUME_TYPE, None, None)

        mock_get_volume_type.assert_has_calls(
            [mock.call('test', VOLUME_TYPE['id'])])
        mock_get_qos_specs.assert_has_calls(
            [mock.call('test', QOS_SPEC['id'])])
        mock_rpc_client.assert_has_calls(
            [mock.call(ADDR, self.configuration.coho_rpc_port),
             mock.call().set_qos_policy(os.path.join(PATH, VOLUME['name']),
                                        QOS)])

    def test_create_cloned_volume_larger(self):
        drv = coho.CohoDriver(configuration=self.configuration)

        mock_rpc_client = self.mock_object(coho, 'CohoRPCClient')
        mock_find_share = self.mock_object(drv, '_find_share')
        mock_find_share.return_value = ADDR + ':' + PATH
        mock_execute = self.mock_object(drv, '_execute')
        mock_local_path = self.mock_object(drv, 'local_path')
        mock_local_path.return_value = LOCAL_PATH
        mock_get_volume_type = self.mock_object(volume_types,
                                                'get_volume_type')
        mock_get_volume_type.return_value = VOLUME_TYPE
        mock_get_qos_specs = self.mock_object(qos_specs, 'get_qos_specs')
        mock_get_qos_specs.return_value = QOS_SPEC
        mock_get_admin_context = self.mock_object(context, 'get_admin_context')
        mock_get_admin_context.return_value = 'test'

        drv.create_cloned_volume(CLONE_VOL, VOLUME)

        mock_find_share.assert_has_calls(
            [mock.call(CLONE_VOL)])
        mock_local_path.assert_has_calls(
            [mock.call(CLONE_VOL), mock.call(VOLUME)])
        mock_execute.assert_has_calls(
            [mock.call('cp', LOCAL_PATH, LOCAL_PATH, run_as_root=True)])
        self.assertTrue(mock_get_admin_context.called)
        mock_get_volume_type.assert_has_calls(
            [mock.call('test', VOLUME_TYPE['id'])])
        mock_get_qos_specs.assert_has_calls(
            [mock.call('test', QOS_SPEC['id'])])
        mock_rpc_client.assert_has_calls(
            [mock.call(ADDR, self.configuration.coho_rpc_port),
             mock.call().set_qos_policy(os.path.join(PATH, VOLUME['name']),
                                        QOS)])
        mock_local_path.assert_has_calls(
            [mock.call(CLONE_VOL)])
        mock_execute.assert_has_calls(
            [mock.call('truncate', '-s', '256G',
                       LOCAL_PATH, run_as_root=True)])

    def test_extend_volume(self):
        drv = coho.CohoDriver(configuration=self.configuration)

        mock_execute = self.mock_object(drv, '_execute')
        mock_local_path = self.mock_object(drv, 'local_path')
        mock_local_path.return_value = LOCAL_PATH

        drv.extend_volume(VOLUME, 512)

        mock_local_path.assert_has_calls(
            [mock.call(VOLUME)])
        mock_execute.assert_has_calls(
            [mock.call('truncate', '-s', '512G',
                       LOCAL_PATH, run_as_root=True)])

    def test_snapshot_failure_when_source_does_not_exist(self):
        drv = coho.CohoDriver(configuration=self.configuration)

        self.mock_object(coho.Client, '_make_call')
        mock_init_socket = self.mock_object(coho.Client, 'init_socket')
        mock_unpack_uint = self.mock_object(xdrlib.Unpacker, 'unpack_uint')
        mock_unpack_uint.return_value = errno.ENOENT
        mock_get_volume_location = self.mock_object(coho.CohoDriver,
                                                    '_get_volume_location')
        mock_get_volume_location.return_value = ADDR, PATH

        with self.assertRaisesRegex(exception.CohoException,
                                    "No such file or directory.*"):
            drv.create_snapshot(SNAPSHOT)

        self.assertTrue(mock_init_socket.called)
        self.assertTrue(mock_unpack_uint.called)
        mock_get_volume_location.assert_has_calls(
            [mock.call(SNAPSHOT['volume_id'])])

    def test_snapshot_failure_with_invalid_input(self):
        drv = coho.CohoDriver(configuration=self.configuration)

        self.mock_object(coho.Client, '_make_call')
        mock_init_socket = self.mock_object(coho.Client, 'init_socket')
        mock_unpack_uint = self.mock_object(xdrlib.Unpacker, 'unpack_uint')
        mock_unpack_uint.return_value = errno.EINVAL
        mock_get_volume_location = self.mock_object(coho.CohoDriver,
                                                    '_get_volume_location')
        mock_get_volume_location.return_value = ADDR, PATH

        with self.assertRaisesRegex(exception.CohoException,
                                    "Invalid argument"):
            drv.delete_snapshot(INVALID_SNAPSHOT)

        self.assertTrue(mock_init_socket.called)
        self.assertTrue(mock_unpack_uint.called)
        mock_get_volume_location.assert_has_calls(
            [mock.call(INVALID_SNAPSHOT['volume_id'])])

    @mock.patch('cinder.volume.drivers.coho.Client.init_socket',
                side_effect=exception.CohoException(
                    "Failed to establish connection."))
    def test_snapshot_failure_when_remote_is_unreachable(self,
                                                         mock_init_socket):
        drv = coho.CohoDriver(configuration=self.configuration)

        mock_get_volume_location = self.mock_object(coho.CohoDriver,
                                                    '_get_volume_location')
        mock_get_volume_location.return_value = 'uknown-address', PATH

        with self.assertRaisesRegex(exception.CohoException,
                                    "Failed to establish connection.*"):
            drv.create_snapshot(SNAPSHOT)

        mock_get_volume_location.assert_has_calls(
            [mock.call(INVALID_SNAPSHOT['volume_id'])])

    def test_rpc_client_make_call_proper_order(self):
        """This test ensures that the RPC client logic is correct.

        When the RPC client's make_call function is called it creates
        a packet and sends it to the Coho cluster RPC server. This test
        ensures that the functions needed to complete the process are
        called in the proper order with valid arguments.
        """

        mock_packer = self.mock_object(xdrlib, 'Packer')
        mock_unpacker = self.mock_object(xdrlib, 'Unpacker')
        mock_unpacker.return_value.unpack_uint.return_value = 0
        mock_socket = self.mock_object(socket, 'socket')
        mock_init_call = self.mock_object(coho.Client, 'init_call')
        mock_init_call.return_value = (1, 2)
        mock_sendrecord = self.mock_object(coho.Client, '_sendrecord')
        mock_recvrecord = self.mock_object(coho.Client, '_recvrecord')
        mock_recvrecord.return_value = 'test_reply'
        mock_unpack_replyheader = self.mock_object(coho.Client,
                                                   'unpack_replyheader')
        mock_unpack_replyheader.return_value = (123, 1)

        rpc_client = coho.CohoRPCClient(ADDR, RPC_PORT)
        rpc_client.create_volume_from_snapshot('src', 'dest')

        self.assertTrue(mock_sendrecord.called)
        self.assertTrue(mock_unpack_replyheader.called)
        mock_packer.assert_has_calls([mock.call().reset()])
        mock_unpacker.assert_has_calls(
            [mock.call().reset('test_reply'),
             mock.call().unpack_uint()])
        mock_socket.assert_has_calls(
            [mock.call(socket.AF_INET, socket.SOCK_STREAM),
             mock.call().connect((ADDR, RPC_PORT))])
        mock_init_call.assert_has_calls(
            [mock.call(coho.COHO1_CREATE_VOLUME_FROM_SNAPSHOT,
                       [(six.b('src'), mock_packer().pack_string),
                        (six.b('dest'), mock_packer().pack_string)])])

    def test_rpc_client_error_in_reply_header(self):
        """Ensure excpetions in reply header are raised by the RPC client.

        Coho cluster's RPC server packs errors into the reply header.
        This test ensures that the RPC client parses the reply header
        correctly and raises exceptions on various errors that can be
        included in the reply header.
        """
        mock_socket = self.mock_object(socket, 'socket')
        mock_recvrecord = self.mock_object(coho.Client, '_recvrecord')
        rpc_client = coho.CohoRPCClient(ADDR, RPC_PORT)

        mock_recvrecord.return_value = NO_REPLY_BIN
        with self.assertRaisesRegex(exception.CohoException,
                                    "no REPLY.*"):
            rpc_client.create_snapshot('src', 'dest', 0)

        mock_recvrecord.return_value = MSG_DENIED_BIN
        with self.assertRaisesRegex(exception.CohoException,
                                    ".*MSG_DENIED.*"):
            rpc_client.delete_snapshot('snapshot')

        mock_recvrecord.return_value = PROG_UNAVAIL_BIN
        with self.assertRaisesRegex(exception.CohoException,
                                    ".*PROG_UNAVAIL"):
            rpc_client.delete_snapshot('snapshot')

        mock_recvrecord.return_value = PROG_MISMATCH_BIN
        with self.assertRaisesRegex(exception.CohoException,
                                    ".*PROG_MISMATCH.*"):
            rpc_client.delete_snapshot('snapshot')

        mock_recvrecord.return_value = GARBAGE_ARGS_BIN
        with self.assertRaisesRegex(exception.CohoException,
                                    ".*GARBAGE_ARGS"):
            rpc_client.delete_snapshot('snapshot')

        mock_recvrecord.return_value = PROC_UNAVAIL_BIN
        with self.assertRaisesRegex(exception.CohoException,
                                    ".*PROC_UNAVAIL"):
            rpc_client.delete_snapshot('snapshot')

        self.assertTrue(mock_recvrecord.called)
        mock_socket.assert_has_calls(
            [mock.call(socket.AF_INET, socket.SOCK_STREAM),
             mock.call().connect((ADDR, RPC_PORT))])

    def test_rpc_client_error_in_receive_fragment(self):
        """Ensure exception is raised when malformed packet is received."""
        mock_sendrcd = self.mock_object(coho.Client, '_sendrecord')
        mock_socket = self.mock_object(socket, 'socket')
        mock_socket.return_value.recv.return_value = INVALID_HEADER_BIN
        rpc_client = coho.CohoRPCClient(ADDR, RPC_PORT)

        with self.assertRaisesRegex(exception.CohoException,
                                    "Invalid response header.*"):
            rpc_client.create_snapshot('src', 'dest', 0)

        self.assertTrue(mock_sendrcd.called)
        mock_socket.assert_has_calls(
            [mock.call(socket.AF_INET, socket.SOCK_STREAM),
             mock.call().connect((ADDR, RPC_PORT)),
             mock.call().recv(4)])

    def test_rpc_client_recovery_on_broken_pipe(self):
        """Ensure RPC retry on broken pipe error.

        When the cluster closes the TCP socket, try reconnecting
        and retrying the command before returing error for the operation.
        """
        mock_socket = self.mock_object(socket, 'socket')
        mock_make_call = self.mock_object(coho.Client, '_make_call')
        socket_error = socket.error('[Errno 32] Broken pipe')
        socket_error.errno = errno.EPIPE
        mock_make_call.side_effect = socket_error
        rpc_client = coho.CohoRPCClient(ADDR, RPC_PORT)

        with self.assertRaisesRegex(exception.CohoException,
                                    "Failed to establish.*"):
            rpc_client.create_snapshot('src', 'dest', 0)

        self.assertEqual(coho.COHO_MAX_RETRIES, mock_make_call.call_count)
        self.assertEqual(coho.COHO_MAX_RETRIES + 1, mock_socket.call_count)

        # assert that on a none EPIPE error it only tries once
        socket_error.errno = errno.EINVAL
        mock_make_call.side_effect = socket_error
        with self.assertRaisesRegex(exception.CohoException,
                                    "Unable to send request.*"):
            rpc_client.delete_snapshot('src')

        self.assertEqual(coho.COHO_MAX_RETRIES + 1, mock_make_call.call_count)
        self.assertEqual(coho.COHO_MAX_RETRIES + 1, mock_socket.call_count)
