# Copyright (c) 2015 Hitachi Data Systems, Inc.
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

"""Tests for volume copy throttling helpers."""

from unittest import mock

from cinder.tests.unit import test
from cinder import utils
from cinder.volume import throttling


class ThrottleTestCase(test.TestCase):

    def test_NoThrottle(self):
        with throttling.Throttle().subcommand('volume1', 'volume2') as cmd:
            self.assertEqual([], cmd['prefix'])

    @mock.patch.object(utils, 'get_blkdev_major_minor')
    @mock.patch('cinder.privsep.cgroup.cgroup_create')
    @mock.patch('cinder.privsep.cgroup.cgroup_limit')
    def test_BlkioCgroup(self, mock_limit, mock_create, mock_major_minor):

        def fake_get_blkdev_major_minor(path):
            return {'src_volume1': "253:0", 'dst_volume1': "253:1",
                    'src_volume2': "253:2", 'dst_volume2': "253:3"}[path]

        mock_major_minor.side_effect = fake_get_blkdev_major_minor

        throttle = throttling.BlkioCgroup(1024, 'fake_group')
        with throttle.subcommand('src_volume1', 'dst_volume1') as cmd:
            self.assertEqual(['cgexec', '-g', 'blkio:fake_group'],
                             cmd['prefix'])

            # a nested job
            with throttle.subcommand('src_volume2', 'dst_volume2') as cmd:
                self.assertEqual(['cgexec', '-g', 'blkio:fake_group'],
                                 cmd['prefix'])

        mock_create.assert_has_calls([mock.call('fake_group')])
        mock_limit.assert_has_calls([
            mock.call('fake_group', 'read', '253:0', 1024),
            mock.call('fake_group', 'write', '253:1', 1024),
            # a nested job starts; bps limit are set to the half
            mock.call('fake_group', 'read', '253:0', 512),
            mock.call('fake_group', 'read', '253:2', 512),
            mock.call('fake_group', 'write', '253:1', 512),
            mock.call('fake_group', 'write', '253:3', 512),
            # a nested job ends; bps limit is resumed
            mock.call('fake_group', 'read', '253:0', 1024),
            mock.call('fake_group', 'write', '253:1', 1024)])
