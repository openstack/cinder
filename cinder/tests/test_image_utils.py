
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

import math

import mock
from oslo_concurrency import processutils
from oslo_utils import units

from cinder import exception
from cinder.image import image_utils
from cinder import test
<<<<<<< HEAD
from cinder import utils
from cinder.volume import utils as volume_utils

CONF = cfg.CONF


class FakeImageService:
    def __init__(self):
        self._imagedata = {}

    def download(self, context, image_id, data):
        self.show(context, image_id)
        data.write(self._imagedata.get(image_id, ''))

    def show(self, context, image_id):
        return {'size': 2 * units.Gi,
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

    @mock.patch('os.stat')
    def test_convert_image(self, mock_stat):

        mox = self._mox
        mox.StubOutWithMock(utils, 'execute')
        mox.StubOutWithMock(utils, 'is_blk_device')

        TEST_OUT_FORMAT = 'vmdk'
        TEST_SOURCE = 'img/qemu.img'
        TEST_DEST = '/img/vmware.vmdk'

        utils.is_blk_device(TEST_DEST).AndReturn(True)
        utils.execute('dd', 'count=0', 'if=img/qemu.img',
                      'of=/img/vmware.vmdk', 'oflag=direct',
                      run_as_root=True)
        utils.execute(
            'qemu-img', 'convert', '-t', 'none', '-O', TEST_OUT_FORMAT,
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

    def _test_fetch_to_raw(self, has_qemu=True, src_inf=None, dest_inf=None,
                           bps_limit=0):
        mox = self._mox
        mox.StubOutWithMock(image_utils, 'create_temporary_file')
        mox.StubOutWithMock(utils, 'execute')
        mox.StubOutWithMock(image_utils, 'fetch')
        mox.StubOutWithMock(volume_utils, 'setup_blkio_cgroup')
        mox.StubOutWithMock(utils, 'is_blk_device')

        TEST_INFO = ("image: qemu.qcow2\n"
                     "file format: raw\n"
                     "virtual size: 0 (0 bytes)\n"
                     "disk size: 0")

        utils.is_blk_device(self.TEST_DEV_PATH).AndReturn(True)
        CONF.set_override('volume_copy_bps_limit', bps_limit)

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
                    (src_inf, 'ignored'))

        if has_qemu and dest_inf:
            if bps_limit:
                prefix = ('cgexec', '-g', 'blkio:test')
            else:
                prefix = ()

            utils.execute('dd', 'count=0', 'if=/dev/ether/fake_dev',
                          'of=/dev/ether/fake_dev', 'oflag=direct',
                          run_as_root=True)

            cmd = prefix + ('qemu-img', 'convert', '-t', 'none', '-O', 'raw',
                            self.TEST_DEV_PATH, self.TEST_DEV_PATH)

            volume_utils.setup_blkio_cgroup(
                self.TEST_DEV_PATH, self.TEST_DEV_PATH,
                bps_limit).AndReturn(prefix)

            utils.execute(*cmd, run_as_root=True)

            utils.execute(
                'env', 'LC_ALL=C', 'qemu-img', 'info',
                self.TEST_DEV_PATH, run_as_root=True).AndReturn(
                    (dest_inf, 'ignored'))

        self._mox.ReplayAll()

    @mock.patch('os.stat')
    def test_fetch_to_raw(self, mock_stat):

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

    @mock.patch('os.stat')
    def test_fetch_to_raw_with_bps_limit(self, mock_stat):
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

        self._test_fetch_to_raw(src_inf=SRC_INFO, dest_inf=DST_INFO,
                                bps_limit=1048576)

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

    @mock.patch('os.stat')
    def test_fetch_to_raw_on_error_not_convert_to_raw(self, mock_stat):

        IMG_INFO = ("image: qemu.qcow2\n"
                    "file_format: qcow2 \n"
                    "virtual_size: 50M (52428800 bytes)\n"
                    "cluster_size: 65536\n"
                    "disk_size: 196K (200704 bytes)")

        self._test_fetch_to_raw(src_inf=IMG_INFO, dest_inf=IMG_INFO)
=======
from cinder.volume import throttling


class TestQemuImgInfo(test.TestCase):
    @mock.patch('cinder.openstack.common.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info(self, mock_exec, mock_info):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)

        output = image_utils.qemu_img_info(test_path)
        mock_exec.assert_called_once_with('env', 'LC_ALL=C', 'qemu-img',
                                          'info', test_path, run_as_root=True)
        self.assertEqual(mock_info.return_value, output)

    @mock.patch('cinder.openstack.common.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info_not_root(self, mock_exec, mock_info):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)

        output = image_utils.qemu_img_info(test_path, run_as_root=False)
        mock_exec.assert_called_once_with('env', 'LC_ALL=C', 'qemu-img',
                                          'info', test_path, run_as_root=False)
        self.assertEqual(mock_info.return_value, output)

    @mock.patch('cinder.image.image_utils.os')
    @mock.patch('cinder.openstack.common.imageutils.QemuImgInfo')
    @mock.patch('cinder.utils.execute')
    def test_qemu_img_info_on_nt(self, mock_exec, mock_info, mock_os):
        mock_out = mock.sentinel.out
        mock_err = mock.sentinel.err
        test_path = mock.sentinel.path
        mock_exec.return_value = (mock_out, mock_err)
        mock_os.name = 'nt'

        output = image_utils.qemu_img_info(test_path)
        mock_exec.assert_called_once_with('qemu-img', 'info', test_path,
                                          run_as_root=True)
        self.assertEqual(mock_info.return_value, output)


class TestConvertImage(test.TestCase):
    @mock.patch('cinder.image.image_utils.os.stat')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.utils.is_blk_device', return_value=True)
    def test_defaults_block_dev(self, mock_isblk, mock_exec,
                                mock_stat):
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        out_format = mock.sentinel.out_format
        mock_stat.return_value.st_size = 1048576
        throttle = throttling.Throttle(prefix=['cgcmd'])

        with mock.patch('cinder.volume.utils.check_for_odirect_support',
                        return_value=True):
            output = image_utils.convert_image(source, dest, out_format,
                                               throttle=throttle)

            self.assertIsNone(output)
            mock_exec.assert_called_once_with('cgcmd', 'qemu-img', 'convert',
                                              '-t', 'none', '-O', out_format,
                                              source, dest, run_as_root=True)

        mock_exec.reset_mock()

        with mock.patch('cinder.volume.utils.check_for_odirect_support',
                        return_value=False):
            output = image_utils.convert_image(source, dest, out_format)

            self.assertIsNone(output)
            mock_exec.assert_called_once_with('qemu-img', 'convert',
                                              '-O', out_format, source, dest,
                                              run_as_root=True)

    @mock.patch('cinder.volume.utils.check_for_odirect_support',
                return_value=True)
    @mock.patch('cinder.image.image_utils.os.stat')
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.utils.is_blk_device', return_value=False)
    def test_defaults_not_block_dev(self, mock_isblk, mock_exec,
                                    mock_stat, mock_odirect):
        source = mock.sentinel.source
        dest = mock.sentinel.dest
        out_format = mock.sentinel.out_format
        mock_stat.return_value.st_size = 1048576

        output = image_utils.convert_image(source, dest, out_format)

        self.assertIsNone(output)
        mock_exec.assert_called_once_with('qemu-img', 'convert', '-O',
                                          out_format, source, dest,
                                          run_as_root=True)


class TestResizeImage(test.TestCase):
    @mock.patch('cinder.utils.execute')
    def test_defaults(self, mock_exec):
        source = mock.sentinel.source
        size = mock.sentinel.size
        output = image_utils.resize_image(source, size)
        self.assertIsNone(output)
        mock_exec.assert_called_once_with('qemu-img', 'resize', source,
                                          'sentinel.sizeG', run_as_root=False)

    @mock.patch('cinder.utils.execute')
    def test_run_as_root(self, mock_exec):
        source = mock.sentinel.source
        size = mock.sentinel.size
        output = image_utils.resize_image(source, size, run_as_root=True)
        self.assertIsNone(output)
        mock_exec.assert_called_once_with('qemu-img', 'resize', source,
                                          'sentinel.sizeG', run_as_root=True)


class TestFetch(test.TestCase):
    @mock.patch('os.stat')
    @mock.patch('cinder.image.image_utils.fileutils')
    def test_defaults(self, mock_fileutils, mock_stat):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        path = 'test_path'
        _user_id = mock.sentinel._user_id
        _project_id = mock.sentinel._project_id
        mock_open = mock.mock_open()
        mock_stat.return_value.st_size = 1048576

        with mock.patch('cinder.image.image_utils.open',
                        new=mock_open, create=True):
            output = image_utils.fetch(ctxt, image_service, image_id, path,
                                       _user_id, _project_id)
        self.assertIsNone(output)
        image_service.download.assert_called_once_with(ctxt, image_id,
                                                       mock_open.return_value)
        mock_open.assert_called_once_with(path, 'wb')
        mock_fileutils.remove_path_on_error.assert_called_once_with(path)
        (mock_fileutils.remove_path_on_error.return_value.__enter__
            .assert_called_once_with())
        (mock_fileutils.remove_path_on_error.return_value.__exit__
            .assert_called_once_with(None, None, None))


class TestVerifyImage(test.TestCase):
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.fileutils')
    @mock.patch('cinder.image.image_utils.fetch')
    def test_defaults(self, mock_fetch, mock_fileutils, mock_info):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        mock_data = mock_info.return_value
        mock_data.file_format = 'test_format'
        mock_data.backing_file = None

        output = image_utils.fetch_verify_image(ctxt, image_service,
                                                image_id, dest)
        self.assertIsNone(output)
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           dest, None, None)
        mock_info.assert_called_once_with(dest, run_as_root=True)
        mock_fileutils.remove_path_on_error.assert_called_once_with(dest)
        (mock_fileutils.remove_path_on_error.return_value.__enter__
            .assert_called_once_with())
        (mock_fileutils.remove_path_on_error.return_value.__exit__
            .assert_called_once_with(None, None, None))

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.fileutils')
    @mock.patch('cinder.image.image_utils.fetch')
    def test_kwargs(self, mock_fetch, mock_fileutils, mock_info):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 2
        run_as_root = mock.sentinel.run_as_root
        mock_data = mock_info.return_value
        mock_data.file_format = 'test_format'
        mock_data.backing_file = None
        mock_data.virtual_size = 1

        output = image_utils.fetch_verify_image(
            ctxt, image_service, image_id, dest, user_id=user_id,
            project_id=project_id, size=size, run_as_root=run_as_root)
        self.assertIsNone(output)
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           dest, None, None)
        mock_info.assert_called_once_with(dest, run_as_root=run_as_root)
        mock_fileutils.remove_path_on_error.assert_called_once_with(dest)
        (mock_fileutils.remove_path_on_error.return_value.__enter__
            .assert_called_once_with())
        (mock_fileutils.remove_path_on_error.return_value.__exit__
            .assert_called_once_with(None, None, None))

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.fileutils')
    @mock.patch('cinder.image.image_utils.fetch')
    def test_format_error(self, mock_fetch, mock_fileutils, mock_info):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        mock_data = mock_info.return_value
        mock_data.file_format = None
        mock_data.backing_file = None

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.fetch_verify_image,
                          ctxt, image_service, image_id, dest)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.fileutils')
    @mock.patch('cinder.image.image_utils.fetch')
    def test_backing_file_error(self, mock_fetch, mock_fileutils, mock_info):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        mock_data = mock_info.return_value
        mock_data.file_format = 'test_format'
        mock_data.backing_file = 'test_backing_file'
>>>>>>> 8bb5554537b34faead2b5eaf6d29600ff8243e85

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.fetch_verify_image,
                          ctxt, image_service, image_id, dest)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.fileutils')
    @mock.patch('cinder.image.image_utils.fetch')
    def test_size_error(self, mock_fetch, mock_fileutils, mock_info):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        size = 1
        mock_data = mock_info.return_value
        mock_data.file_format = 'test_format'
        mock_data.backing_file = None
        mock_data.virtual_size = 2

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.fetch_verify_image,
<<<<<<< HEAD
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

    @mock.patch('os.stat')
    def test_upload_volume(self, mock_stat, bps_limit=0):
        image_meta = {'id': 1, 'disk_format': 'qcow2'}
        TEST_RET = "image: qemu.qcow2\n"\
                   "file_format: qcow2 \n"\
                   "virtual_size: 50M (52428800 bytes)\n"\
                   "cluster_size: 65536\n"\
                   "disk_size: 196K (200704 bytes)"

        if bps_limit:
            CONF.set_override('volume_copy_bps_limit', bps_limit)
            prefix = ('cgexec', '-g', 'blkio:test')
        else:
            prefix = ()

        cmd = prefix + ('qemu-img', 'convert', '-O', 'qcow2',
                        mox.IgnoreArg(), mox.IgnoreArg())

        m = self._mox
        m.StubOutWithMock(utils, 'execute')
        m.StubOutWithMock(volume_utils, 'setup_blkio_cgroup')

        volume_utils.setup_blkio_cgroup(mox.IgnoreArg(), mox.IgnoreArg(),
                                        bps_limit).AndReturn(prefix)

        utils.execute(*cmd, run_as_root=True)
        utils.execute(
            'env', 'LC_ALL=C', 'qemu-img', 'info',
            mox.IgnoreArg(), run_as_root=True).AndReturn(
                (TEST_RET, 'ignored'))

        m.ReplayAll()

        image_utils.upload_volume(context, FakeImageService(),
                                  image_meta, '/dev/loop1')
        m.VerifyAll()

    @mock.patch('os.stat')
    def test_upload_volume_with_bps_limit(self, mock_stat):
        bps_limit = 1048576
        image_meta = {'id': 1, 'disk_format': 'qcow2'}
        TEST_RET = "image: qemu.qcow2\n"\
                   "file_format: qcow2 \n"\
                   "virtual_size: 50M (52428800 bytes)\n"\
                   "cluster_size: 65536\n"\
                   "disk_size: 196K (200704 bytes)"

        CONF.set_override('volume_copy_bps_limit', bps_limit)
        prefix = ('cgexec', '-g', 'blkio:test')

        cmd = prefix + ('qemu-img', 'convert', '-O', 'qcow2',
                        mox.IgnoreArg(), mox.IgnoreArg())

        m = self._mox
        m.StubOutWithMock(utils, 'execute')
        m.StubOutWithMock(volume_utils, 'setup_blkio_cgroup')
        m.StubOutWithMock(volume_utils, 'check_for_odirect_support')

        volume_utils.setup_blkio_cgroup(mox.IgnoreArg(), mox.IgnoreArg(),
                                        bps_limit).AndReturn(prefix)
        utils.execute(*cmd, run_as_root=True)
        utils.execute(
            'env', 'LC_ALL=C', 'qemu-img', 'info',
            mox.IgnoreArg(), run_as_root=True).AndReturn(
                (TEST_RET, 'ignored'))

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

    @mock.patch('os.stat')
    def test_upload_volume_on_error(self, mock_stat):
        image_meta = {'id': 1, 'disk_format': 'qcow2'}
        TEST_RET = "image: qemu.vhd\n"\
                   "file_format: vhd \n"\
                   "virtual_size: 50M (52428800 bytes)\n"\
                   "cluster_size: 65536\n"\
                   "disk_size: 196K (200704 bytes)"

        m = self._mox
        m.StubOutWithMock(utils, 'execute')
        m.StubOutWithMock(volume_utils, 'check_for_odirect_support')

        utils.execute('qemu-img', 'convert', '-O', 'qcow2',
                      mox.IgnoreArg(), mox.IgnoreArg(), run_as_root=True)
        utils.execute(
            'env', 'LC_ALL=C', 'qemu-img', 'info',
            mox.IgnoreArg(), run_as_root=True).AndReturn(
                (TEST_RET, 'ignored'))

        m.ReplayAll()
=======
                          ctxt, image_service, image_id, dest, size=size)


class TestTemporaryDir(test.TestCase):
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('os.makedirs')
    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('cinder.image.image_utils.utils.tempdir')
    def test_conv_dir_exists(self, mock_tempdir, mock_exists, mock_make,
                             mock_conf):
        mock_conf.image_conversion_dir = mock.sentinel.conv_dir

        output = image_utils.temporary_dir()

        self.assertFalse(mock_make.called)
        mock_tempdir.assert_called_once_with(dir=mock.sentinel.conv_dir)
        self.assertEqual(output, mock_tempdir.return_value)

    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('os.makedirs')
    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('cinder.image.image_utils.utils.tempdir')
    def test_create_conv_dir(self, mock_tempdir, mock_exists, mock_make,
                             mock_conf):
        mock_conf.image_conversion_dir = mock.sentinel.conv_dir

        output = image_utils.temporary_dir()

        mock_make.assert_called_once_with(mock.sentinel.conv_dir)
        mock_tempdir.assert_called_once_with(dir=mock.sentinel.conv_dir)
        self.assertEqual(output, mock_tempdir.return_value)

    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('os.makedirs')
    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('cinder.image.image_utils.utils.tempdir')
    def test_no_conv_dir(self, mock_tempdir, mock_exists, mock_make,
                         mock_conf):
        mock_conf.image_conversion_dir = None

        output = image_utils.temporary_dir()

        self.assertFalse(mock_make.called)
        mock_tempdir.assert_called_once_with(dir=None)
        self.assertEqual(output, mock_tempdir.return_value)


class TestUploadVolume(test.TestCase):
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.fileutils.file_open')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_diff_format(self, mock_os, mock_temp, mock_convert, mock_info,
                         mock_open, mock_conf):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': mock.sentinel.disk_format}
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'posix'
        data = mock_info.return_value
        data.file_format = mock.sentinel.disk_format
        temp_file = mock_temp.return_value.__enter__.return_value

        output = image_utils.upload_volume(ctxt, image_service, image_meta,
                                           volume_path)

        self.assertIsNone(output)
        mock_convert.assert_called_once_with(volume_path,
                                             temp_file,
                                             mock.sentinel.disk_format,
                                             run_as_root=True)
        mock_info.assert_called_once_with(temp_file, run_as_root=True)
        mock_open.assert_called_once_with(temp_file, 'rb')
        image_service.update.assert_called_once_with(
            ctxt, image_meta['id'], {},
            mock_open.return_value.__enter__.return_value)

    @mock.patch('cinder.image.image_utils.utils.temporary_chown')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.fileutils.file_open')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_same_format(self, mock_os, mock_temp, mock_convert, mock_info,
                         mock_open, mock_conf, mock_chown):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': 'raw'}
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'posix'
        mock_os.access.return_value = False

        output = image_utils.upload_volume(ctxt, image_service, image_meta,
                                           volume_path)

        self.assertIsNone(output)
        self.assertFalse(mock_convert.called)
        self.assertFalse(mock_info.called)
        mock_chown.assert_called_once_with(volume_path)
        mock_open.assert_called_once_with(volume_path)
        image_service.update.assert_called_once_with(
            ctxt, image_meta['id'], {},
            mock_open.return_value.__enter__.return_value)

    @mock.patch('cinder.image.image_utils.utils.temporary_chown')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.fileutils.file_open')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_same_format_on_nt(self, mock_os, mock_temp, mock_convert,
                               mock_info, mock_open, mock_conf, mock_chown):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': 'raw'}
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'nt'
        mock_os.access.return_value = False

        output = image_utils.upload_volume(ctxt, image_service, image_meta,
                                           volume_path)

        self.assertIsNone(output)
        self.assertFalse(mock_convert.called)
        self.assertFalse(mock_info.called)
        mock_open.assert_called_once_with(volume_path, 'rb')
        image_service.update.assert_called_once_with(
            ctxt, image_meta['id'], {},
            mock_open.return_value.__enter__.return_value)

    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.fileutils.file_open')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.os')
    def test_convert_error(self, mock_os, mock_temp, mock_convert, mock_info,
                           mock_open, mock_conf):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_meta = {'id': 'test_id',
                      'disk_format': mock.sentinel.disk_format}
        volume_path = mock.sentinel.volume_path
        mock_os.name = 'posix'
        data = mock_info.return_value
        data.file_format = mock.sentinel.other_disk_format
        temp_file = mock_temp.return_value.__enter__.return_value
>>>>>>> 8bb5554537b34faead2b5eaf6d29600ff8243e85

        self.assertRaises(exception.ImageUnacceptable,
                          image_utils.upload_volume,
                          ctxt, image_service, image_meta, volume_path)
        mock_convert.assert_called_once_with(volume_path,
                                             temp_file,
                                             mock.sentinel.disk_format,
                                             run_as_root=True)
        mock_info.assert_called_once_with(temp_file, run_as_root=True)
        self.assertFalse(image_service.update.called)


class TestFetchToVhd(test.TestCase):
    @mock.patch('cinder.image.image_utils.fetch_to_volume_format')
    def test_defaults(self, mock_fetch_to):
        ctxt = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        blocksize = mock.sentinel.blocksize

        output = image_utils.fetch_to_vhd(ctxt, image_service, image_id,
                                          dest, blocksize)
        self.assertIsNone(output)
        mock_fetch_to.assert_called_once_with(ctxt, image_service, image_id,
                                              dest, 'vpc', blocksize, None,
                                              None, run_as_root=True)

    @mock.patch('cinder.image.image_utils.fetch_to_volume_format')
    def test_kwargs(self, mock_fetch_to):
        ctxt = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        run_as_root = mock.sentinel.run_as_root

        output = image_utils.fetch_to_vhd(ctxt, image_service, image_id,
                                          dest, blocksize, user_id=user_id,
                                          project_id=project_id,
                                          run_as_root=run_as_root)
        self.assertIsNone(output)
        mock_fetch_to.assert_called_once_with(ctxt, image_service, image_id,
                                              dest, 'vpc', blocksize, user_id,
                                              project_id,
                                              run_as_root=run_as_root)


class TestFetchToRaw(test.TestCase):
    @mock.patch('cinder.image.image_utils.fetch_to_volume_format')
    def test_defaults(self, mock_fetch_to):
        ctxt = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        blocksize = mock.sentinel.blocksize

        output = image_utils.fetch_to_raw(ctxt, image_service, image_id,
                                          dest, blocksize)
        self.assertIsNone(output)
        mock_fetch_to.assert_called_once_with(ctxt, image_service, image_id,
                                              dest, 'raw', blocksize, None,
                                              None, None, run_as_root=True)

    @mock.patch('cinder.image.image_utils.fetch_to_volume_format')
    def test_kwargs(self, mock_fetch_to):
        ctxt = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = mock.sentinel.size
        run_as_root = mock.sentinel.run_as_root

        output = image_utils.fetch_to_raw(ctxt, image_service, image_id,
                                          dest, blocksize, user_id=user_id,
                                          project_id=project_id, size=size,
                                          run_as_root=run_as_root)
        self.assertIsNone(output)
        mock_fetch_to.assert_called_once_with(ctxt, image_service, image_id,
                                              dest, 'raw', blocksize, user_id,
                                              project_id, size,
                                              run_as_root=run_as_root)


class TestFetchToVolumeFormat(test.TestCase):
    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_defaults(self, mock_conf, mock_temp, mock_info, mock_fetch,
                      mock_is_xen, mock_repl_xen, mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize

        data = mock_info.return_value
        data.file_format = volume_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        output = image_utils.fetch_to_volume_format(ctxt, image_service,
                                                    image_id, dest,
                                                    volume_format, blocksize)

        self.assertIsNone(output)
        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=True),
            mock.call(tmp, run_as_root=True),
            mock.call(dest, run_as_root=True)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, None, None)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             run_as_root=True)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_kwargs(self, mock_conf, mock_temp, mock_info, mock_fetch,
                    mock_is_xen, mock_repl_xen, mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = volume_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        output = image_utils.fetch_to_volume_format(
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        self.assertIsNone(output)
        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(dest, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             run_as_root=run_as_root)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info',
                side_effect=processutils.ProcessExecutionError)
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_no_qemu_img_and_is_raw(self, mock_conf, mock_temp, mock_info,
                                    mock_fetch, mock_is_xen, mock_repl_xen,
                                    mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        tmp = mock_temp.return_value.__enter__.return_value
        image_service.show.return_value = {'disk_format': 'raw',
                                           'size': 41126400}
        image_size_m = math.ceil(41126400 / units.Mi)

        output = image_utils.fetch_to_volume_format(
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        self.assertIsNone(output)
        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_called_once_with(tmp, run_as_root=run_as_root)
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        mock_copy.assert_called_once_with(tmp, dest, image_size_m,
                                          blocksize)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info',
                side_effect=processutils.ProcessExecutionError)
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_no_qemu_img_not_raw(self, mock_conf, mock_temp, mock_info,
                                 mock_fetch, mock_is_xen, mock_repl_xen,
                                 mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        tmp = mock_temp.return_value.__enter__.return_value
        image_service.show.return_value = {'disk_format': 'not_raw'}

        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.fetch_to_volume_format,
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_called_once_with(tmp, run_as_root=run_as_root)
        self.assertFalse(mock_fetch.called)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info',
                side_effect=processutils.ProcessExecutionError)
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_no_qemu_img_no_metadata(self, mock_conf, mock_temp, mock_info,
                                     mock_fetch, mock_is_xen, mock_repl_xen,
                                     mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        tmp = mock_temp.return_value.__enter__.return_value
        image_service.show.return_value = None

        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.fetch_to_volume_format,
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_called_once_with(tmp, run_as_root=run_as_root)
        self.assertFalse(mock_fetch.called)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_size_error(self, mock_conf, mock_temp, mock_info, mock_fetch,
                        mock_is_xen, mock_repl_xen, mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 1234
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = volume_format
        data.backing_file = None
        data.virtual_size = 4321 * 1024 ** 3
        tmp = mock_temp.return_value.__enter__.return_value

        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.fetch_to_volume_format,
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_qemu_img_parse_error(self, mock_conf, mock_temp, mock_info,
                                  mock_fetch, mock_is_xen, mock_repl_xen,
                                  mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = None
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.fetch_to_volume_format,
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_backing_file_error(self, mock_conf, mock_temp, mock_info,
                                mock_fetch, mock_is_xen, mock_repl_xen,
                                mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = volume_format
        data.backing_file = mock.sentinel.backing_file
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.fetch_to_volume_format,
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_convert.called)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=False)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_format_mismatch(self, mock_conf, mock_temp, mock_info, mock_fetch,
                             mock_is_xen, mock_repl_xen, mock_copy,
                             mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = mock.sentinel.file_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        self.assertRaises(
            exception.ImageUnacceptable,
            image_utils.fetch_to_volume_format,
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(dest, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        self.assertFalse(mock_repl_xen.called)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             run_as_root=run_as_root)

    @mock.patch('cinder.image.image_utils.convert_image')
    @mock.patch('cinder.image.image_utils.volume_utils.copy_volume')
    @mock.patch(
        'cinder.image.image_utils.replace_xenserver_image_with_coalesced_vhd')
    @mock.patch('cinder.image.image_utils.is_xenserver_image',
                return_value=True)
    @mock.patch('cinder.image.image_utils.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.temporary_file')
    @mock.patch('cinder.image.image_utils.CONF')
    def test_xenserver_to_vhd(self, mock_conf, mock_temp, mock_info,
                              mock_fetch, mock_is_xen, mock_repl_xen,
                              mock_copy, mock_convert):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id
        dest = mock.sentinel.dest
        volume_format = mock.sentinel.volume_format
        blocksize = mock.sentinel.blocksize
        user_id = mock.sentinel.user_id
        project_id = mock.sentinel.project_id
        size = 4321
        run_as_root = mock.sentinel.run_as_root

        data = mock_info.return_value
        data.file_format = volume_format
        data.backing_file = None
        data.virtual_size = 1234
        tmp = mock_temp.return_value.__enter__.return_value

        output = image_utils.fetch_to_volume_format(
            ctxt, image_service, image_id, dest, volume_format, blocksize,
            user_id=user_id, project_id=project_id, size=size,
            run_as_root=run_as_root)

        self.assertIsNone(output)
        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_temp.assert_called_once_with()
        mock_info.assert_has_calls([
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(tmp, run_as_root=run_as_root),
            mock.call(dest, run_as_root=run_as_root)])
        mock_fetch.assert_called_once_with(ctxt, image_service, image_id,
                                           tmp, user_id, project_id)
        mock_repl_xen.assert_called_once_with(tmp)
        self.assertFalse(mock_copy.called)
        mock_convert.assert_called_once_with(tmp, dest, volume_format,
                                             run_as_root=run_as_root)


class TestXenserverUtils(test.TestCase):
    @mock.patch('cinder.image.image_utils.is_xenserver_format')
    def test_is_xenserver_image(self, mock_format):
        ctxt = mock.sentinel.context
        image_service = mock.Mock()
        image_id = mock.sentinel.image_id

        output = image_utils.is_xenserver_image(ctxt, image_service, image_id)

        image_service.show.assert_called_once_with(ctxt, image_id)
        mock_format.assert_called_once_with(image_service.show.return_value)
        self.assertEqual(mock_format.return_value, output)

    def test_is_xenserver_format(self):
        image_meta1 = {'disk_format': 'vhd', 'container_format': 'ovf'}
        self.assertTrue(image_utils.is_xenserver_format(image_meta1))

        image_meta2 = {'disk_format': 'test_disk_format',
                       'container_format': 'test_cont_format'}
        self.assertFalse(image_utils.is_xenserver_format(image_meta2))

    @mock.patch('cinder.image.image_utils.utils.execute')
    def test_extract_targz(self, mock_exec):
        name = mock.sentinel.archive_name
        target = mock.sentinel.target

        output = image_utils.extract_targz(name, target)

        mock_exec.assert_called_once_with('tar', '-xzf', name, '-C', target)
        self.assertIsNone(output)


class TestVhdUtils(test.TestCase):
    @mock.patch('cinder.image.image_utils.utils.execute')
    def test_set_vhd_parent(self, mock_exec):
        vhd_path = mock.sentinel.vhd_path
        parentpath = mock.sentinel.parentpath

        output = image_utils.set_vhd_parent(vhd_path, parentpath)

        mock_exec.assert_called_once_with('vhd-util', 'modify', '-n', vhd_path,
                                          '-p', parentpath)
        self.assertIsNone(output)

    @mock.patch('cinder.image.image_utils.set_vhd_parent')
    def test_fix_vhd_chain(self, mock_set_parent):
        vhd_chain = (mock.sentinel.first,
                     mock.sentinel.second,
                     mock.sentinel.third,
                     mock.sentinel.fourth,
                     mock.sentinel.fifth)

        output = image_utils.fix_vhd_chain(vhd_chain)

        self.assertIsNone(output)
        mock_set_parent.assert_has_calls([
            mock.call(mock.sentinel.first, mock.sentinel.second),
            mock.call(mock.sentinel.second, mock.sentinel.third),
            mock.call(mock.sentinel.third, mock.sentinel.fourth),
            mock.call(mock.sentinel.fourth, mock.sentinel.fifth)])

    @mock.patch('cinder.image.image_utils.utils.execute',
                return_value=(98765.43210, mock.sentinel.error))
    def test_get_vhd_size(self, mock_exec):
        vhd_path = mock.sentinel.vhd_path

        output = image_utils.get_vhd_size(vhd_path)

        mock_exec.assert_called_once_with('vhd-util', 'query', '-n', vhd_path,
                                          '-v')
        self.assertEqual(98765, output)

    @mock.patch('cinder.image.image_utils.utils.execute')
    def test_resize_vhd(self, mock_exec):
        vhd_path = mock.sentinel.vhd_path
        size = 387549349
        journal = mock.sentinel.journal

        output = image_utils.resize_vhd(vhd_path, size, journal)

        self.assertIsNone(output)
        mock_exec.assert_called_once_with('vhd-util', 'resize', '-n', vhd_path,
                                          '-s', str(size), '-j', journal)

    @mock.patch('cinder.image.image_utils.utils.execute')
    def test_coalesce_vhd(self, mock_exec):
        vhd_path = mock.sentinel.vhd_path

        output = image_utils.coalesce_vhd(vhd_path)

        self.assertIsNone(output)
        mock_exec.assert_called_once_with('vhd-util', 'coalesce', '-n',
                                          vhd_path)

    @mock.patch('cinder.image.image_utils.coalesce_vhd')
    @mock.patch('cinder.image.image_utils.resize_vhd')
    @mock.patch('cinder.image.image_utils.get_vhd_size')
    @mock.patch('cinder.image.image_utils.utils.execute')
    def test_coalesce_chain(self, mock_exec, mock_size, mock_resize,
                            mock_coal):
        vhd_chain = (mock.sentinel.first,
                     mock.sentinel.second,
                     mock.sentinel.third,
                     mock.sentinel.fourth,
                     mock.sentinel.fifth)

        output = image_utils.coalesce_chain(vhd_chain)

        self.assertEqual(mock.sentinel.fifth, output)
        mock_size.assert_has_calls([
            mock.call(mock.sentinel.first),
            mock.call(mock.sentinel.second),
            mock.call(mock.sentinel.third),
            mock.call(mock.sentinel.fourth)])
        mock_resize.assert_has_calls([
            mock.call(mock.sentinel.second, mock_size.return_value, mock.ANY),
            mock.call(mock.sentinel.third, mock_size.return_value, mock.ANY),
            mock.call(mock.sentinel.fourth, mock_size.return_value, mock.ANY),
            mock.call(mock.sentinel.fifth, mock_size.return_value, mock.ANY)])
        mock_coal.assert_has_calls([
            mock.call(mock.sentinel.first),
            mock.call(mock.sentinel.second),
            mock.call(mock.sentinel.third),
            mock.call(mock.sentinel.fourth)])

    @mock.patch('cinder.image.image_utils.os.path')
    def test_discover_vhd_chain(self, mock_path):
        directory = '/some/test/directory'
        mock_path.join.side_effect = lambda x, y: '/'.join((x, y))
        mock_path.exists.side_effect = (True, True, True, False)

        output = image_utils.discover_vhd_chain(directory)

        expected_output = ['/some/test/directory/0.vhd',
                           '/some/test/directory/1.vhd',
                           '/some/test/directory/2.vhd']
        self.assertEqual(expected_output, output)

    @mock.patch('cinder.image.image_utils.temporary_dir')
    @mock.patch('cinder.image.image_utils.os.rename')
    @mock.patch('cinder.image.image_utils.fileutils.delete_if_exists')
    @mock.patch('cinder.image.image_utils.coalesce_chain')
    @mock.patch('cinder.image.image_utils.fix_vhd_chain')
    @mock.patch('cinder.image.image_utils.discover_vhd_chain')
    @mock.patch('cinder.image.image_utils.extract_targz')
    def test_replace_xenserver_image_with_coalesced_vhd(
            self, mock_targz, mock_discover, mock_fix, mock_coal, mock_delete,
            mock_rename, mock_temp):
        image_file = mock.sentinel.image_file
        tmp = mock_temp.return_value.__enter__.return_value

        output = image_utils.replace_xenserver_image_with_coalesced_vhd(
            image_file)

        self.assertIsNone(output)
        mock_targz.assert_called_once_with(image_file, tmp)
        mock_discover.assert_called_once_with(tmp)
        mock_fix.assert_called_once_with(mock_discover.return_value)
        mock_coal.assert_called_once_with(mock_discover.return_value)
        mock_delete.assert_called_once_with(image_file)
        mock_rename.assert_called_once_with(mock_coal.return_value, image_file)


class TestCreateTemporaryFile(test.TestCase):
    @mock.patch('cinder.image.image_utils.os.close')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.os.path.exists')
    @mock.patch('cinder.image.image_utils.os.makedirs')
    @mock.patch('cinder.image.image_utils.tempfile.mkstemp')
    def test_create_temporary_file_no_dir(self, mock_mkstemp, mock_dirs,
                                          mock_path, mock_conf, mock_close):
        mock_conf.image_conversion_dir = None
        fd = mock.sentinel.file_descriptor
        path = mock.sentinel.absolute_pathname
        mock_mkstemp.return_value = (fd, path)

        output = image_utils.create_temporary_file()

        self.assertEqual(path, output)
        mock_mkstemp.assert_called_once_with(dir=None)
        mock_close.assert_called_once_with(fd)

    @mock.patch('cinder.image.image_utils.os.close')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.os.path.exists', return_value=True)
    @mock.patch('cinder.image.image_utils.os.makedirs')
    @mock.patch('cinder.image.image_utils.tempfile.mkstemp')
    def test_create_temporary_file_with_dir(self, mock_mkstemp, mock_dirs,
                                            mock_path, mock_conf, mock_close):
        conv_dir = mock.sentinel.image_conversion_dir
        mock_conf.image_conversion_dir = conv_dir
        fd = mock.sentinel.file_descriptor
        path = mock.sentinel.absolute_pathname
        mock_mkstemp.return_value = (fd, path)

        output = image_utils.create_temporary_file()

        self.assertEqual(path, output)
        self.assertFalse(mock_dirs.called)
        mock_mkstemp.assert_called_once_with(dir=conv_dir)
        mock_close.assert_called_once_with(fd)

    @mock.patch('cinder.image.image_utils.os.close')
    @mock.patch('cinder.image.image_utils.CONF')
    @mock.patch('cinder.image.image_utils.os.path.exists', return_value=False)
    @mock.patch('cinder.image.image_utils.os.makedirs')
    @mock.patch('cinder.image.image_utils.tempfile.mkstemp')
    def test_create_temporary_file_and_dir(self, mock_mkstemp, mock_dirs,
                                           mock_path, mock_conf, mock_close):
        conv_dir = mock.sentinel.image_conversion_dir
        mock_conf.image_conversion_dir = conv_dir
        fd = mock.sentinel.file_descriptor
        path = mock.sentinel.absolute_pathname
        mock_mkstemp.return_value = (fd, path)

        output = image_utils.create_temporary_file()

        self.assertEqual(path, output)
        mock_dirs.assert_called_once_with(conv_dir)
        mock_mkstemp.assert_called_once_with(dir=conv_dir)
        mock_close.assert_called_once_with(fd)


class TestTemporaryFileContextManager(test.TestCase):
    @mock.patch('cinder.image.image_utils.create_temporary_file',
                return_value=mock.sentinel.temporary_file)
    @mock.patch('cinder.image.image_utils.fileutils.delete_if_exists')
    def test_temporary_file(self, mock_delete, mock_create):
        with image_utils.temporary_file() as tmp_file:
            self.assertEqual(mock.sentinel.temporary_file, tmp_file)
            self.assertFalse(mock_delete.called)
        mock_delete.assert_called_once_with(mock.sentinel.temporary_file)
