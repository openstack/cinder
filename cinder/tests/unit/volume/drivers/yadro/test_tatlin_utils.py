#  Copyright (C) 2021-2022 YADRO.
#  All rights reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import os
from unittest.mock import mock_open
from unittest.mock import patch
from unittest import TestCase

from cinder.volume.drivers.yadro.tatlin_utils import TatlinVolumeConnections

VOL_ID = 'cinder-volume-id'


class TatlinVolumeConnectionsTest(TestCase):

    @patch('oslo_concurrency.lockutils.lock', autospec=True)
    @patch('os.mkdir')
    @patch('os.path.isdir')
    def setUp(self, isdir, mkdir, lock):
        self.path = 'fake_path'
        isdir.return_value = False
        self.connections = TatlinVolumeConnections(self.path)
        isdir.assert_called_once_with(self.path)
        mkdir.assert_called_once_with(self.path)
        isdir.reset_mock()
        mkdir.reset_mock()
        isdir.return_value = True
        self.connections = TatlinVolumeConnections(self.path)
        isdir.assert_called_once_with(self.path)
        mkdir.assert_not_called()

    @patch('oslo_concurrency.lockutils.lock', autospec=True)
    @patch('builtins.open', mock_open(read_data='1'))
    @patch('os.path.exists')
    def test_get(self, exists, lock):
        exists.side_effect = [False, True]
        self.assertEqual(self.connections.get(VOL_ID), 0)
        self.assertEqual(self.connections.get(VOL_ID), 1)

    @patch('oslo_concurrency.lockutils.lock', autospec=True)
    @patch('builtins.open', callable=mock_open(read_data='1'))
    @patch('os.path.exists')
    def test_increment(self, exists, open, lock):
        exists.side_effect = [False, True]
        self.assertEqual(self.connections.increment(VOL_ID), 1)
        open.assert_called_once_with(os.path.join(self.path, VOL_ID), 'w')
        with open() as f:
            f.write.assert_called_once_with('1')
        self.assertEqual(self.connections.increment(VOL_ID), 2)
        open.assert_called_with(os.path.join(self.path, VOL_ID), 'w')
        with open() as f:
            f.write.assert_called_with('2')

    @patch('oslo_concurrency.lockutils.lock', autospec=True)
    @patch('builtins.open', callable=mock_open())
    @patch('os.remove')
    @patch('os.path.exists')
    def test_decrement(self, exists, remove, open, lock):
        exists.side_effect = [False, True, True]
        with open() as f:
            f.read.side_effect = [2, 1]

            self.assertEqual(self.connections.decrement(VOL_ID), 0)
            remove.assert_not_called()

            self.assertEqual(self.connections.decrement(VOL_ID), 1)
            open.assert_called_with(os.path.join(self.path, VOL_ID), 'w')
            f.write.assert_called_with('1')

            self.assertEqual(self.connections.decrement(VOL_ID), 0)
            remove.assert_called_with(os.path.join(self.path, VOL_ID))
