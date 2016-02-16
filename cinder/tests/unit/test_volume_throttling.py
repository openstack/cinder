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

import mock

from cinder import test
from cinder import utils
from cinder.volume import throttling


class ThrottleTestCase(test.TestCase):

    def test_NoThrottle(self):
        with throttling.Throttle().subcommand('volume1', 'volume2') as cmd:
            self.assertEqual([], cmd['prefix'])

    @mock.patch.object(utils, 'get_blkdev_major_minor')
    def test_BlkioCgroup(self, mock_major_minor):

        def fake_get_blkdev_major_minor(path):
            return {'src_volume1': "253:0", 'dst_volume1': "253:1",
                    'src_volume2': "253:2", 'dst_volume2': "253:3"}[path]

        mock_major_minor.side_effect = fake_get_blkdev_major_minor

        self.exec_cnt = 0

        def fake_execute(*cmd, **kwargs):
            cmd_set = ['cgset', '-r',
                       'blkio.throttle.%s_bps_device=%s %d', 'fake_group']
            set_order = [None,
                         ('read', '253:0', 1024),
                         ('write', '253:1', 1024),
                         # a nested job starts; bps limit are set to the half
                         ('read', '253:0', 512),
                         ('read', '253:2', 512),
                         ('write', '253:1', 512),
                         ('write', '253:3', 512),
                         # a nested job ends; bps limit is resumed
                         ('read', '253:0', 1024),
                         ('write', '253:1', 1024)]

            if set_order[self.exec_cnt] is None:
                self.assertEqual(('cgcreate', '-g', 'blkio:fake_group'), cmd)
            else:
                cmd_set[2] %= set_order[self.exec_cnt]
                self.assertEqual(tuple(cmd_set), cmd)

            self.exec_cnt += 1

        with mock.patch.object(utils, 'execute', side_effect=fake_execute):
            throttle = throttling.BlkioCgroup(1024, 'fake_group')
            with throttle.subcommand('src_volume1', 'dst_volume1') as cmd:
                self.assertEqual(['cgexec', '-g', 'blkio:fake_group'],
                                 cmd['prefix'])

                # a nested job
                with throttle.subcommand('src_volume2', 'dst_volume2') as cmd:
                    self.assertEqual(['cgexec', '-g', 'blkio:fake_group'],
                                     cmd['prefix'])
