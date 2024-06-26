# Copyright 2024 Red Hat, Inc
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


from unittest import mock

from cinder.privsep import format_inspector as pfi
from cinder.tests.unit import test


class TestFormatInspectorHelper(test.TestCase):
    @mock.patch('cinder.image.format_inspector.detect_file_format')
    def test_get_format_if_safe__happy_path(self, mock_detect):
        mock_inspector = mock.MagicMock()
        mock_inspector.__str__.return_value = 'mock_fmt'
        mock_safety = mock_inspector.safety_check
        mock_safety.return_value = True
        mock_backing = mock_inspector.safety_check_allow_backing_file
        mock_detect.return_value = mock_inspector

        test_path = mock.sentinel.path

        fmt_name = pfi._get_format_if_safe(path=test_path,
                                           allow_qcow2_backing_file=False)
        self.assertEqual(fmt_name, 'mock_fmt')
        mock_safety.assert_called_once_with()
        mock_backing.assert_not_called()

    @mock.patch('cinder.image.format_inspector.detect_file_format')
    def test_get_format_if_safe__allow_backing(self, mock_detect):
        mock_inspector = mock.MagicMock()
        mock_inspector.__str__.return_value = 'qcow2'
        mock_safety = mock_inspector.safety_check
        mock_safety.return_value = False
        mock_backing = mock_inspector.safety_check_allow_backing_file
        mock_backing.return_value = True
        mock_detect.return_value = mock_inspector

        test_path = mock.sentinel.path

        fmt_name = pfi._get_format_if_safe(path=test_path,
                                           allow_qcow2_backing_file=True)
        self.assertEqual(fmt_name, 'qcow2')
        mock_safety.assert_called_once_with()
        mock_backing.assert_called_once_with()

    @mock.patch('cinder.image.format_inspector.detect_file_format')
    def test_get_format_if_safe__backing_fail(self, mock_detect):
        """backing flag should only work for qcow2"""
        mock_inspector = mock.MagicMock()
        mock_inspector.__str__.return_value = 'mock_fmt'
        mock_safety = mock_inspector.safety_check
        mock_safety.return_value = False
        mock_backing = mock_inspector.safety_check_allow_backing_file
        mock_detect.return_value = mock_inspector

        test_path = mock.sentinel.path

        fmt_name = pfi._get_format_if_safe(path=test_path,
                                           allow_qcow2_backing_file=True)
        self.assertIsNone(fmt_name)
        mock_safety.assert_called_once_with()
        mock_backing.assert_not_called()

    @mock.patch('cinder.image.format_inspector.detect_file_format')
    def test_get_format_if_safe__allow_backing_but_other_problem(
            self, mock_detect):
        mock_inspector = mock.MagicMock()
        mock_inspector.__str__.return_value = 'qcow2'
        mock_safety = mock_inspector.safety_check
        mock_safety.return_value = False
        mock_backing = mock_inspector.safety_check_allow_backing_file
        mock_backing.return_value = False
        mock_detect.return_value = mock_inspector

        test_path = mock.sentinel.path

        fmt_name = pfi._get_format_if_safe(path=test_path,
                                           allow_qcow2_backing_file=True)
        self.assertIsNone(fmt_name)
        mock_safety.assert_called_once_with()
        mock_backing.assert_called_once_with()

    @mock.patch('cinder.image.format_inspector.detect_file_format')
    def test_get_format_if_safe__unsafe(self, mock_detect):
        mock_inspector = mock.MagicMock()
        mock_inspector.__str__.return_value = 'mock_fmt'
        mock_safety = mock_inspector.safety_check
        mock_safety.return_value = False
        mock_backing = mock_inspector.safety_check_allow_backing_file
        mock_detect.return_value = mock_inspector

        test_path = mock.sentinel.path

        fmt_name = pfi._get_format_if_safe(path=test_path,
                                           allow_qcow2_backing_file=False)
        self.assertIsNone(fmt_name)
        mock_safety.assert_called_once_with()
        mock_backing.assert_not_called()
