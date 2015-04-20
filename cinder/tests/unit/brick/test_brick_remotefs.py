# (c) Copyright 2013 OpenStack Foundation
# All Rights Reserved
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

import mock
import mox
from oslo_log import log as logging

from cinder.brick import exception
from cinder.brick.remotefs import remotefs
from cinder.i18n import _
from cinder import test

LOG = logging.getLogger(__name__)


class BrickRemoteFsTestCase(test.TestCase):
    TEST_EXPORT = '1.2.3.4/export1'
    TEST_MNT_BASE = '/mnt/test'
    TEST_HASH = '4d664fd43b6ff86d80a4ea969c07b3b9'
    TEST_MNT_POINT = TEST_MNT_BASE + '/' + TEST_HASH

    def setUp(self):
        super(BrickRemoteFsTestCase, self).setUp()
        self._mox = mox.Mox()
        self._nfsclient = remotefs.RemoteFsClient(
            'nfs', 'sudo', nfs_mount_point_base=self.TEST_MNT_BASE)
        self.addCleanup(self._mox.UnsetStubs)

    def test_get_hash_str(self):
        """_get_hash_str should calculation correct value."""

        self.assertEqual(self.TEST_HASH,
                         self._nfsclient._get_hash_str(self.TEST_EXPORT))

    def test_get_mount_point(self):
        mnt_point = self._nfsclient.get_mount_point(self.TEST_EXPORT)
        self.assertEqual(mnt_point, self.TEST_MNT_POINT)

    def test_mount_nfs_should_mount_correctly(self):
        mox = self._mox
        client = self._nfsclient

        mox.StubOutWithMock(client, '_execute')
        client._execute('mount', check_exit_code=0).AndReturn(("", ""))
        client._execute('mkdir', '-p', self.TEST_MNT_POINT,
                        check_exit_code=0).AndReturn(("", ""))
        client._execute('mount', '-t', 'nfs', '-o', 'vers=4,minorversion=1',
                        self.TEST_EXPORT,
                        self.TEST_MNT_POINT,
                        root_helper='sudo', run_as_root=True,
                        check_exit_code=0).AndReturn(("", ""))
        mox.ReplayAll()

        client.mount(self.TEST_EXPORT)

        mox.VerifyAll()

    def test_mount_nfs_with_specific_vers(self):
        opts = ['vers=2,nointr', 'nfsvers=3,lock', 'nolock,v2', 'v4.0']
        for opt in opts:
            client = remotefs.RemoteFsClient(
                'nfs', 'sudo', nfs_mount_point_base=self.TEST_MNT_BASE,
                nfs_mount_options=opt)

            client._read_mounts = mock.Mock(return_value=[])
            client._execute = mock.Mock(return_value=True)

            client.mount(self.TEST_EXPORT)
            client._execute.assert_any_call('mkdir', '-p', self.TEST_MNT_POINT,
                                            check_exit_code=0)
            client._execute.assert_any_call('mount', '-t', 'nfs', '-o',
                                            opt, self.TEST_EXPORT,
                                            self.TEST_MNT_POINT,
                                            root_helper='sudo',
                                            run_as_root=True,
                                            check_exit_code=0)

    def test_mount_nfs_with_fallback_no_vers(self):
        def execute(*args, **kwargs):
            if 'mkdir' in args:
                return True
            elif 'mount' in args:
                if 'lock,nointr,vers=4,minorversion=1' in args:
                    raise Exception()
                else:
                    return True
            else:
                self.fail(_("Unexpected call to _execute."))

        opts = 'lock,nointr'
        client = remotefs.RemoteFsClient(
            'nfs', 'sudo', nfs_mount_point_base=self.TEST_MNT_BASE,
            nfs_mount_options=opts)

        client._read_mounts = mock.Mock(return_value=[])
        client._execute = mock.Mock(wraps=execute)

        client.mount(self.TEST_EXPORT)
        client._execute.assert_any_call('mkdir', '-p', self.TEST_MNT_POINT,
                                        check_exit_code=0)
        client._execute.assert_any_call('mount', '-t', 'nfs', '-o',
                                        'lock,nointr,vers=4,minorversion=1',
                                        self.TEST_EXPORT,
                                        self.TEST_MNT_POINT,
                                        root_helper='sudo',
                                        run_as_root=True,
                                        check_exit_code=0)
        client._execute.assert_any_call('mount', '-t', 'nfs', '-o',
                                        'lock,nointr',
                                        self.TEST_EXPORT,
                                        self.TEST_MNT_POINT,
                                        root_helper='sudo',
                                        run_as_root=True,
                                        check_exit_code=0)

    def test_mount_nfs_with_fallback_all_fail(self):
        def execute(*args, **kwargs):
            if 'mkdir' in args:
                return True
            else:
                raise Exception(_("mount failed."))

        opts = 'lock,nointr'
        client = remotefs.RemoteFsClient(
            'nfs', 'sudo', nfs_mount_point_base=self.TEST_MNT_BASE,
            nfs_mount_options=opts)

        client._read_mounts = mock.Mock(return_value=[])
        client._execute = mock.Mock(wraps=execute)
        self.assertRaises(exception.BrickException, client.mount,
                          self.TEST_EXPORT)

    def test_mount_nfs_should_not_remount(self):
        mox = self._mox
        client = self._nfsclient

        line = "%s on %s type nfs (rw)\n" % (self.TEST_EXPORT,
                                             self.TEST_MNT_POINT)
        mox.StubOutWithMock(client, '_execute')
        client._execute('mount', check_exit_code=0).AndReturn((line, ""))
        mox.ReplayAll()

        client.mount(self.TEST_EXPORT)

        mox.VerifyAll()

    def test_nfs_mount_options(self):
        opts = 'test_nfs_mount_options'
        client = remotefs.RemoteFsClient(
            'nfs', 'sudo', nfs_mount_point_base=self.TEST_MNT_BASE,
            nfs_mount_options=opts)
        self.assertEqual(opts, client._mount_options)

    def test_nfs_mount_point_base(self):
        base = '/mnt/test/nfs/mount/point/base'
        client = remotefs.RemoteFsClient('nfs', 'sudo',
                                         nfs_mount_point_base=base)
        self.assertEqual(base, client._mount_base)

    def test_glusterfs_mount_point_base(self):
        base = '/mnt/test/glusterfs/mount/point/base'
        client = remotefs.RemoteFsClient('glusterfs', 'sudo',
                                         glusterfs_mount_point_base=base)
        self.assertEqual(base, client._mount_base)
