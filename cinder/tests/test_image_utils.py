# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import textwrap

from cinder.image import image_utils
from cinder import test
from cinder import utils


class TestUtils(test.TestCase):
    def setUp(self):
        super(TestUtils, self).setUp()
        self._mox = mox.Mox()
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

        self.assertEquals(1024, result)


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
                raise Exception()

        self.assertRaises(Exception, sut)


class TestCoalesceChain(test.TestCase):
    def test_single_vhd(self):
        mox = self.mox
        mox.StubOutWithMock(image_utils, 'get_vhd_size')
        mox.StubOutWithMock(image_utils, 'resize_vhd')
        mox.StubOutWithMock(image_utils, 'coalesce_vhd')

        mox.ReplayAll()

        result = image_utils.coalesce_chain(['0.vhd'])
        mox.VerifyAll()

        self.assertEquals('0.vhd', result)

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
        self.assertEquals('1.vhd', result)


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

        self.assertEquals(
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
