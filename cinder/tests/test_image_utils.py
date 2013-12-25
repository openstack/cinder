
# Copyright (c) 2013 eNovance , Inc.
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
"""Unit tests for image utils."""

import contextlib
import mox
import tempfile

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import processutils
from cinder import test
from cinder import units
from cinder import utils


class FakeImageService:
    def __init__(self):
        self._imagedata = {}

    def download(self, context, image_id, data):
        self.show(context, image_id)
        data.write(self._imagedata.get(image_id, ''))

    def show(self, context, image_id):
        return {'size': 2 * units.GiB,
                'disk_format': 'qcow2',
                'container_format': 'bare'}

    def update(self, context, image_id, metadata, path):
        pass


class TestUtils(test.TestCase):
    TEST_IMAGE_ID = 321
    TEST_DEV_PATH = "/dev/ether/fake_dev"

    def setUp(self):
        super(TestUtils, self).setUp()
        self._mox = mox.Mox()
        self._image_service = FakeImageService()

        self.addCleanup(self._mox.UnsetStubs)

    def test_resize_image(self):
        mox = self._mox
        mox.StubOutWithMock(utils, 'execute')

        TEST_IMG_SOURCE = 'boobar.img'
        TEST_IMG_SIZE_IN_GB = 1

        utils.execute('qemu-img', 'resize', TEST_IMG_SOURCE,
                      '%sG' % TEST_IMG_SIZE_IN_GB, run_as_root=False)

        mox.ReplayAll()

        image_utils.resize_image(TEST_IMG_SOURCE, TEST_IMG_SIZE_IN_GB)

        mox.VerifyAll()

    def test_convert_image(self):
        mox = self._mox
        mox.StubOutWithMock(utils, 'execute')

        TEST_OUT_FORMAT = 'vmdk'
        TEST_SOURCE = 'img/qemu.img'
        TEST_DEST = '/img/vmware.vmdk'

        utils.execute('qemu-img', 'convert', '-O', TEST_OUT_FORMAT,
                      TEST_SOURCE, TEST_DEST, run_as_root=True)

        mox.ReplayAll()

        image_utils.convert_image(TEST_SOURCE, TEST_DEST, TEST_OUT_FORMAT)

        mox.VerifyAll()

    def test_qemu_img_info(self):
        TEST_PATH = "img/qemu.qcow2"
        TEST_RETURN = "image: qemu.qcow2\n"\
                      "backing_file: qemu.qcow2 (actual path: qemu.qcow2)\n"\
                      "file_format: qcow2\n"\
                      "virtual_size: 50M (52428800 bytes)\n"\
                      "cluster_size: 65536\n"\
                      "disk_size: 196K (200704 bytes)\n"\
                      "Snapshot list:\n"\
                      "ID TAG  VM SIZE DATE VM CLOCK\n"\
                      "1  snap1 1.7G 2011-10-04 19:04:00 32:06:34.974"
        TEST_STR = "image: qemu.qcow2\n"\
                   "file_format: qcow2\n"\
                   "virtual_size: 52428800\n"\
                   "disk_size: 200704\n"\
                   "cluster_size: 65536\n"\
                   "backing_file: qemu.qcow2\n"\
                   "snapshots: [{'date': '2011-10-04', "\
                   "'vm_clock': '19:04:00 32:06:34.974', "\
                   "'vm_size': '1.7G', 'tag': 'snap1', 'id': '1'}]"

        mox = self._mox
        mox.StubOutWithMock(utils, 'execute')

        utils.execute(
            'env', 'LC_ALL=C', 'qemu-img', 'info',
            TEST_PATH, run_as_root=True).AndReturn(
                (TEST_RETURN, 'ignored')
            )

        mox.ReplayAll()

        inf = image_utils.qemu_img_info(TEST_PATH)

        self.assertEqual(inf.image, 'qemu.qcow2')
        self.assertEqual(inf.backing_file, 'qemu.qcow2')
        self.assertEqual(inf.file_format, 'qcow2')
        self.assertEqual(inf.virtual_size, 52428800)
        self.assertEqual(inf.cluster_size, 65536)
        self.assertEqual(inf.disk_size, 200704)

        self.assertEqual(inf.snapshots[0]['id'], '1')
        self.assertEqual(inf.snapshots[0]['tag'], 'snap1')
        self.assertEqual(inf.snapshots[0]['vm_size'], '1.7G')
        self.assertEqual(inf.snapshots[0]['date'], '2011-10-04')
        self.assertEqual(inf.snapshots[0]['vm_clock'], '19:04:00 32:06:34.974')

        self.assertEqual(str(inf), TEST_STR)

    def test_qemu_img_info_alt(self):
        """Test a slightly different variation of qemu-img output.

           (Based on Fedora 19's qemu-img 1.4.2.)
        """

        TEST_PATH = "img/qemu.qcow2"
        TEST_RETURN = "image: qemu.qcow2\n"\
                      "backing file: qemu.qcow2 (actual path: qemu.qcow2)\n"\
                      "file format: qcow2\n"\
                      "virtual size: 50M (52428800 bytes)\n"\
                      "cluster_size: 65536\n"\
                      "disk size: 196K (200704 bytes)\n"\
                      "Snapshot list:\n"\
                      "ID TAG  VM SIZE DATE VM CLOCK\n"\
                      "1  snap1 1.7G 2011-10-04 19:04:00 32:06:34.974"
        TEST_STR = "image: qemu.qcow2\n"\
                   "file_format: qcow2\n"\
                   "virtual_size: 52428800\n"\
                   "disk_size: 200704\n"\
                   "cluster_size: 65536\n"\
                   "backing_file: qemu.qcow2\n"\
                   "snapshots: [{'date': '2011-10-04', "\
                   "'vm_clock': '19:04:00 32:06:34.974', "\
                   "'vm_size': '1.7G', 'tag': 'snap1', 'id': '1'}]"

        mox = self._mox
        mox.StubOutWithMock(utils, 'execute')

        cmd = ['env', 'LC_ALL=C', 'qemu-img', 'info', TEST_PATH]
        utils.execute(*cmd, run_as_root=True).AndReturn(
            (TEST_RETURN, 'ignored'))

        mox.ReplayAll()

        inf = image_utils.qemu_img_info(TEST_PATH)

        self.assertEqual(inf.image, 'qemu.qcow2')
        self.assertEqual(inf.backing_file, 'qemu.qcow2')
        self.assertEqual(inf.file_format, 'qcow2')
        self.assertEqual(inf.virtual_size, 52428800)
        self.assertEqual(inf.cluster_size, 65536)
        self.assertEqual(inf.disk_size, 200704)

        self.assertEqual(inf.snapshots[0]['id'], '1')
        self.assertEqual(inf.snapshots[0]['tag'], 'snap1')
        self.assertEqual(inf.snapshots[0]['vm_size'], '1.7G')
        self.assertEqual(inf.snapshots[0]['date'], '2011-10-04')
        self.assertEqual(inf.snapshots[0]['vm_clock'],
                         '19:04:00 32:06:34.974')

        self.assertEqual(str(inf), TEST_STR)

    def _test_fetch_to_raw(self, has_qemu=True, src_inf=None, dest_inf=None):
        mox = self._mox
        mox.StubOutWithMock(image_utils, 'create_temporary_file')
        mox.StubOutWithMock(utils, 'execute')
        mox.StubOutWithMock(image_utils, 'fetch')

        TEST_INFO = ("image: qemu.qcow2\n"
                     "file format: raw\n"
                     "virtual size: 0 (0 bytes)\n"
                     "disk size: 0")

        image_utils.create_temporary_file().AndReturn(self.TEST_DEV_PATH)

        test_qemu_img = utils.execute(
            'env', 'LC_ALL=C', 'qemu-img', 'info', self.TEST_DEV_PATH,
            run_as_root=True)

        if has_qemu:
            test_qemu_img.AndReturn((TEST_INFO, 'ignored'))
            image_utils.fetch(context, self._image_service, self.TEST_IMAGE_ID,
                              self.TEST_DEV_PATH, None, None)
        else:
            test_qemu_img.AndRaise(processutils.ProcessExecutionError())

        if has_qemu and src_inf:
            utils.execute(
                'env', 'LC_ALL=C', 'qemu-img', 'info',
                self.TEST_DEV_PATH, run_as_root=True).AndReturn(
                    (src_inf, 'ignored')
                )

        if has_qemu and dest_inf:
            utils.execute(
                'qemu-img', 'convert', '-O', 'raw',
                self.TEST_DEV_PATH, self.TEST_DEV_PATH, run_as_root=True)

            utils.execute(
                'env', 'LC_ALL=C', 'qemu-img', 'info',
                self.TEST_DEV_PATH, run_as_root=True).AndReturn(
                    (dest_inf, 'ignored')
                )

        self._mox.ReplayAll()

    def test_fetch_to_raw(self):
        SRC_INFO = ("image: qemu.qcow2\n"
                    "file_format: qcow2 \n"
                    "virtual_size: 50M (52428800 bytes)\n"
                    "cluster_size: 65536\n"
                    "disk_size: 196K (200704 bytes)")
        DST_INFO = ("image: qemu.raw\n"
                    "file_format: raw\n"
                    "virtual_size: 50M (52428800 bytes)\n"
                    "cluster_size: 65536\n"
                    "disk_size: 196K (200704 bytes)\n")

        self._test_fetch_to_raw(src_inf=SRC_INFO, dest_inf=DST_INFO)

        image_utils.fetch_to_raw(context, self._image_service,
                                 self.TEST_IMAGE_ID, self.TEST_DEV_PATH,
                                 mox.IgnoreArg())
        self._mox.VerifyAll()

    def test_fetch_to_raw_no_qemu_img(self):
        self._test_fetch_to_raw(has_qemu=False)

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.fetch_to_raw,
                          context, self._image_service,
                          self.TEST_IMAGE_ID, self.TEST_DEV_PATH,
                          mox.IgnoreArg())

        self._mox.VerifyAll()

    def test_fetch_to_raw_on_error_parsing_failed(self):
        SRC_INFO_NO_FORMAT = ("image: qemu.qcow2\n"
                              "virtual_size: 50M (52428800 bytes)\n"
                              "cluster_size: 65536\n"
                              "disk_size: 196K (200704 bytes)")

        self._test_fetch_to_raw(src_inf=SRC_INFO_NO_FORMAT)

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.fetch_to_raw,
                          context, self._image_service,
                          self.TEST_IMAGE_ID, self.TEST_DEV_PATH,
                          mox.IgnoreArg())
        self._mox.VerifyAll()

    def test_fetch_to_raw_on_error_backing_file(self):
        SRC_INFO_BACKING_FILE = ("image: qemu.qcow2\n"
                                 "backing_file: qemu.qcow2\n"
                                 "file_format: qcow2 \n"
                                 "virtual_size: 50M (52428800 bytes)\n"
                                 "cluster_size: 65536\n"
                                 "disk_size: 196K (200704 bytes)")

        self._test_fetch_to_raw(src_inf=SRC_INFO_BACKING_FILE)

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.fetch_to_raw,
                          context, self._image_service,
                          self.TEST_IMAGE_ID, self.TEST_DEV_PATH,
                          mox.IgnoreArg())
        self._mox.VerifyAll()

    def test_fetch_to_raw_on_error_not_convert_to_raw(self):
        IMG_INFO = ("image: qemu.qcow2\n"
                    "file_format: qcow2 \n"
                    "virtual_size: 50M (52428800 bytes)\n"
                    "cluster_size: 65536\n"
                    "disk_size: 196K (200704 bytes)")

        self._test_fetch_to_raw(src_inf=IMG_INFO, dest_inf=IMG_INFO)

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.fetch_to_raw,
                          context, self._image_service,
                          self.TEST_IMAGE_ID, self.TEST_DEV_PATH,
                          mox.IgnoreArg())

    def test_fetch_to_raw_on_error_image_size(self):
        TEST_VOLUME_SIZE = 1
        SRC_INFO = ("image: qemu.qcow2\n"
                    "file_format: qcow2 \n"
                    "virtual_size: 2G (2147483648 bytes)\n"
                    "cluster_size: 65536\n"
                    "disk_size: 196K (200704 bytes)")

        self._test_fetch_to_raw(src_inf=SRC_INFO)

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.fetch_to_raw,
                          context, self._image_service,
                          self.TEST_IMAGE_ID, self.TEST_DEV_PATH,
                          mox.IgnoreArg(), size=TEST_VOLUME_SIZE)

    def _test_fetch_verify_image(self, qemu_info, volume_size=1):
        fake_image_service = FakeImageService()
        mox = self._mox
        mox.StubOutWithMock(image_utils, 'fetch')
        mox.StubOutWithMock(utils, 'execute')
        image_utils.fetch(context, fake_image_service,
                          self.TEST_IMAGE_ID, self.TEST_DEV_PATH, None, None)

        utils.execute(
            'env', 'LC_ALL=C', 'qemu-img', 'info',
            self.TEST_DEV_PATH, run_as_root=True).AndReturn(
                (qemu_info, 'ignored')
            )

        self._mox.ReplayAll()
        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.fetch_verify_image,
                          context, fake_image_service,
                          self.TEST_IMAGE_ID, self.TEST_DEV_PATH,
                          size=volume_size)

    def test_fetch_verify_image_with_backing_file(self):
        TEST_RETURN = "image: qemu.qcow2\n"\
                      "backing_file: qemu.qcow2 (actual path: qemu.qcow2)\n"\
                      "file_format: qcow2\n"\
                      "virtual_size: 50M (52428800 bytes)\n"\
                      "cluster_size: 65536\n"\
                      "disk_size: 196K (200704 bytes)\n"\
                      "Snapshot list:\n"\
                      "ID TAG  VM SIZE DATE VM CLOCK\n"\
                      "1  snap1 1.7G 2011-10-04 19:04:00 32:06:34.974"

        self._test_fetch_verify_image(TEST_RETURN)

    def test_fetch_verify_image_without_file_format(self):
        TEST_RETURN = "image: qemu.qcow2\n"\
                      "virtual_size: 50M (52428800 bytes)\n"\
                      "cluster_size: 65536\n"\
                      "disk_size: 196K (200704 bytes)\n"\
                      "Snapshot list:\n"\
                      "ID TAG  VM SIZE DATE VM CLOCK\n"\
                      "1  snap1 1.7G 2011-10-04 19:04:00 32:06:34.974"

        self._test_fetch_verify_image(TEST_RETURN)

    def test_fetch_verify_image_image_size(self):
        TEST_RETURN = "image: qemu.qcow2\n"\
                      "file_format: qcow2\n"\
                      "virtual_size: 2G (2147483648 bytes)\n"\
                      "cluster_size: 65536\n"\
                      "disk_size: 196K (200704 bytes)\n"\
                      "Snapshot list:\n"\
                      "ID TAG  VM SIZE DATE VM CLOCK\n"\
                      "1  snap1 1.7G 2011-10-04 19:04:00 32:06:34.974"

        self._test_fetch_verify_image(TEST_RETURN)

    def test_upload_volume(self):
        image_meta = {'id': 1, 'disk_format': 'qcow2'}
        TEST_RET = "image: qemu.qcow2\n"\
                   "file_format: qcow2 \n"\
                   "virtual_size: 50M (52428800 bytes)\n"\
                   "cluster_size: 65536\n"\
                   "disk_size: 196K (200704 bytes)"

        m = self._mox
        m.StubOutWithMock(utils, 'execute')

        utils.execute('qemu-img', 'convert', '-O', 'qcow2',
                      mox.IgnoreArg(), mox.IgnoreArg(), run_as_root=True)
        utils.execute(
            'env', 'LC_ALL=C', 'qemu-img', 'info',
            mox.IgnoreArg(), run_as_root=True).AndReturn(
                (TEST_RET, 'ignored')
            )

        m.ReplayAll()

        image_utils.upload_volume(context, FakeImageService(),
                                  image_meta, '/dev/loop1')
        m.VerifyAll()

    def test_upload_volume_with_raw_image(self):
        image_meta = {'id': 1, 'disk_format': 'raw'}
        mox = self._mox

        mox.StubOutWithMock(image_utils, 'convert_image')

        mox.ReplayAll()

        with tempfile.NamedTemporaryFile() as f:
            image_utils.upload_volume(context, FakeImageService(),
                                      image_meta, f.name)
        mox.VerifyAll()

    def test_upload_volume_on_error(self):
        image_meta = {'id': 1, 'disk_format': 'qcow2'}
        TEST_RET = "image: qemu.vhd\n"\
                   "file_format: vhd \n"\
                   "virtual_size: 50M (52428800 bytes)\n"\
                   "cluster_size: 65536\n"\
                   "disk_size: 196K (200704 bytes)"

        m = self._mox
        m.StubOutWithMock(utils, 'execute')

        utils.execute('qemu-img', 'convert', '-O', 'qcow2',
                      mox.IgnoreArg(), mox.IgnoreArg(), run_as_root=True)
        utils.execute(
            'env', 'LC_ALL=C', 'qemu-img', 'info',
            mox.IgnoreArg(), run_as_root=True).AndReturn(
                (TEST_RET, 'ignored')
            )

        m.ReplayAll()

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.upload_volume,
                          context, FakeImageService(),
                          image_meta, '/dev/loop1')
        m.VerifyAll()


class TestExtractTo(test.TestCase):
    def test_extract_to_calls_tar(self):
        mox = self.mox
        mox.StubOutWithMock(utils, 'execute')

        utils.execute(
            'tar', '-xzf', 'archive.tgz', '-C', 'targetpath').AndReturn(
                ('ignored', 'ignored')
            )

        mox.ReplayAll()

        image_utils.extract_targz('archive.tgz', 'targetpath')
        mox.VerifyAll()


class TestSetVhdParent(test.TestCase):
    def test_vhd_util_call(self):
        mox = self.mox
        mox.StubOutWithMock(utils, 'execute')

        utils.execute(
            'vhd-util', 'modify', '-n', 'child', '-p', 'parent').AndReturn(
                ('ignored', 'ignored')
            )

        mox.ReplayAll()

        image_utils.set_vhd_parent('child', 'parent')
        mox.VerifyAll()


class TestFixVhdChain(test.TestCase):
    def test_empty_chain(self):
        mox = self.mox
        mox.StubOutWithMock(image_utils, 'set_vhd_parent')

        mox.ReplayAll()
        image_utils.fix_vhd_chain([])

    def test_single_vhd_file_chain(self):
        mox = self.mox
        mox.StubOutWithMock(image_utils, 'set_vhd_parent')

        mox.ReplayAll()
        image_utils.fix_vhd_chain(['0.vhd'])

    def test_chain_with_two_elements(self):
        mox = self.mox
        mox.StubOutWithMock(image_utils, 'set_vhd_parent')

        image_utils.set_vhd_parent('0.vhd', '1.vhd')

        mox.ReplayAll()
        image_utils.fix_vhd_chain(['0.vhd', '1.vhd'])


class TestGetSize(test.TestCase):
    def test_vhd_util_call(self):
        mox = self.mox
        mox.StubOutWithMock(utils, 'execute')

        utils.execute(
            'vhd-util', 'query', '-n', 'vhdfile', '-v').AndReturn(
                ('1024', 'ignored')
            )

        mox.ReplayAll()

        result = image_utils.get_vhd_size('vhdfile')
        mox.VerifyAll()

        self.assertEqual(1024, result)


class TestResize(test.TestCase):
    def test_vhd_util_call(self):
        mox = self.mox
        mox.StubOutWithMock(utils, 'execute')

        utils.execute(
            'vhd-util', 'resize', '-n', 'vhdfile', '-s', '1024',
            '-j', 'journal').AndReturn(('ignored', 'ignored'))

        mox.ReplayAll()

        image_utils.resize_vhd('vhdfile', 1024, 'journal')
        mox.VerifyAll()


class TestCoalesce(test.TestCase):
    def test_vhd_util_call(self):
        mox = self.mox
        mox.StubOutWithMock(utils, 'execute')

        utils.execute(
            'vhd-util', 'coalesce', '-n', 'vhdfile'
        ).AndReturn(('ignored', 'ignored'))

        mox.ReplayAll()

        image_utils.coalesce_vhd('vhdfile')
        mox.VerifyAll()


@contextlib.contextmanager
def fake_context(return_value):
    yield return_value


class TestTemporaryFile(test.TestCase):
    def test_file_unlinked(self):
        mox = self.mox
        mox.StubOutWithMock(image_utils, 'create_temporary_file')
        mox.StubOutWithMock(image_utils.os, 'unlink')

        image_utils.create_temporary_file().AndReturn('somefile')
        image_utils.os.unlink('somefile')

        mox.ReplayAll()

        with image_utils.temporary_file():
            pass

    def test_file_unlinked_on_error(self):
        mox = self.mox
        mox.StubOutWithMock(image_utils, 'create_temporary_file')
        mox.StubOutWithMock(image_utils.os, 'unlink')

        image_utils.create_temporary_file().AndReturn('somefile')
        image_utils.os.unlink('somefile')

        mox.ReplayAll()

        def sut():
            with image_utils.temporary_file():
                raise test.TestingException()

        self.assertRaises(test.TestingException, sut)


class TestCoalesceChain(test.TestCase):
    def test_single_vhd(self):
        mox = self.mox
        mox.StubOutWithMock(image_utils, 'get_vhd_size')
        mox.StubOutWithMock(image_utils, 'resize_vhd')
        mox.StubOutWithMock(image_utils, 'coalesce_vhd')

        mox.ReplayAll()

        result = image_utils.coalesce_chain(['0.vhd'])
        mox.VerifyAll()

        self.assertEqual('0.vhd', result)

    def test_chain_of_two_vhds(self):
        self.mox.StubOutWithMock(image_utils, 'get_vhd_size')
        self.mox.StubOutWithMock(image_utils, 'temporary_dir')
        self.mox.StubOutWithMock(image_utils, 'resize_vhd')
        self.mox.StubOutWithMock(image_utils, 'coalesce_vhd')
        self.mox.StubOutWithMock(image_utils, 'temporary_file')

        image_utils.get_vhd_size('0.vhd').AndReturn(1024)
        image_utils.temporary_dir().AndReturn(fake_context('tdir'))
        image_utils.resize_vhd('1.vhd', 1024, 'tdir/vhd-util-resize-journal')
        image_utils.coalesce_vhd('0.vhd')
        self.mox.ReplayAll()

        result = image_utils.coalesce_chain(['0.vhd', '1.vhd'])
        self.mox.VerifyAll()
        self.assertEqual('1.vhd', result)


class TestDiscoverChain(test.TestCase):
    def test_discovery_calls(self):
        mox = self.mox
        mox.StubOutWithMock(image_utils, 'file_exist')

        image_utils.file_exist('some/path/0.vhd').AndReturn(True)
        image_utils.file_exist('some/path/1.vhd').AndReturn(True)
        image_utils.file_exist('some/path/2.vhd').AndReturn(False)

        mox.ReplayAll()
        result = image_utils.discover_vhd_chain('some/path')
        mox.VerifyAll()

        self.assertEqual(
            ['some/path/0.vhd', 'some/path/1.vhd'], result)


class TestXenServerImageToCoalescedVhd(test.TestCase):
    def test_calls(self):
        mox = self.mox
        mox.StubOutWithMock(image_utils, 'temporary_dir')
        mox.StubOutWithMock(image_utils, 'extract_targz')
        mox.StubOutWithMock(image_utils, 'discover_vhd_chain')
        mox.StubOutWithMock(image_utils, 'fix_vhd_chain')
        mox.StubOutWithMock(image_utils, 'coalesce_chain')
        mox.StubOutWithMock(image_utils.os, 'unlink')
        mox.StubOutWithMock(image_utils, 'rename_file')

        image_utils.temporary_dir().AndReturn(fake_context('somedir'))
        image_utils.extract_targz('image', 'somedir')
        image_utils.discover_vhd_chain('somedir').AndReturn(
            ['somedir/0.vhd', 'somedir/1.vhd'])
        image_utils.fix_vhd_chain(['somedir/0.vhd', 'somedir/1.vhd'])
        image_utils.coalesce_chain(
            ['somedir/0.vhd', 'somedir/1.vhd']).AndReturn('somedir/1.vhd')
        image_utils.os.unlink('image')
        image_utils.rename_file('somedir/1.vhd', 'image')

        mox.ReplayAll()
        image_utils.replace_xenserver_image_with_coalesced_vhd('image')
        mox.VerifyAll()
