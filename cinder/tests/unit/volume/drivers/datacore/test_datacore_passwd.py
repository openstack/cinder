# Copyright (c) 2017 DataCore Software Corp. All Rights Reserved.
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

"""Unit tests for the password storage."""

import collections
import json
import os
import stat

import mock
import six

from cinder import test
from cinder.volume.drivers.datacore import passwd


class FakeFileStorage(object):
    """Mock FileStorage class."""
    def __init__(self):
        self._storage = {
            'resource1': {
                'user1': 'resource1-user1',
                'user2': 'resource1-user2',
            },
            'resource2': {
                'user1': 'resource2-user1',
            }
        }

    def open(self):
        return self

    def load(self):
        return self._storage

    def save(self, storage):
        self._storage = storage

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()


class PasswordFileStorageTestCase(test.TestCase):
    """Tests for the password storage."""

    def test_get_password(self):
        fake_file_storage = FakeFileStorage()
        passwords = fake_file_storage.load()
        resource = six.next(six.iterkeys(passwords))
        user, expected = six.next(six.iteritems(passwords[resource]))

        self._mock_file_storage(fake_file_storage)
        password_storage = passwd.PasswordFileStorage('fake_file_path')

        result = password_storage.get_password(resource, user)
        self.assertEqual(expected, result)

        result = password_storage.get_password(resource.upper(), user)
        self.assertIsNone(result)

    def test_set_password(self):
        fake_file_storage = FakeFileStorage()
        user = 'user3'
        resource1 = 'resource2'
        password1 = 'resource2-user3'
        resource2 = 'resource3'
        password2 = 'resource3-user3'

        self._mock_file_storage(fake_file_storage)
        password_storage = passwd.PasswordFileStorage('fake_file_path')

        password_storage.set_password(resource1, user, password1)
        passwords = fake_file_storage.load()
        self.assertIn(resource1, passwords)
        self.assertIn(user, passwords[resource1])
        self.assertEqual(password1, passwords[resource1][user])

        password_storage.set_password(resource2, user, password2)
        passwords = fake_file_storage.load()
        self.assertIn(resource2, passwords)
        self.assertIn(user, passwords[resource2])
        self.assertEqual(password2, passwords[resource2][user])

    def test_delete_password(self):
        fake_file_storage = FakeFileStorage()
        passwords = fake_file_storage.load()
        resource1, resource2 = 'resource1', 'resource2'
        user1 = six.next(six.iterkeys(passwords[resource1]))
        user2 = six.next(six.iterkeys(passwords[resource2]))

        self._mock_file_storage(fake_file_storage)
        password_storage = passwd.PasswordFileStorage('fake_file_path')

        password_storage.delete_password(resource1, user1)
        passwords = fake_file_storage.load()
        self.assertIn(resource1, passwords)
        self.assertNotIn(user1, passwords[resource1])

        password_storage.delete_password(resource2, user2)
        passwords = fake_file_storage.load()
        self.assertNotIn(resource2, passwords)

    def _mock_file_storage(self, fake_file_storage):
        self.mock_object(passwd, 'FileStorage', return_value=fake_file_storage)


class FileStorageTestCase(test.TestCase):
    """Test for the file storage."""

    def test_open(self):
        fake_file_path = 'file_storage.data'
        self.mock_object(passwd.os.path, 'isfile', return_value=True)
        self.mock_object(passwd.os.path, 'isdir', return_value=True)
        mock_open = self.mock_object(passwd, 'open', mock.mock_open())

        file_storage = passwd.FileStorage(fake_file_path)
        file_storage.open()
        mock_open.assert_called_once_with(fake_file_path, 'r+')

    def test_open_not_existing(self):
        fake_file_path = '/fake_path/file_storage.data'
        fake_dir_name = os.path.dirname(fake_file_path)
        mock_chmod_calls = [
            mock.call(fake_dir_name,
                      stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP),
            mock.call(fake_file_path, stat.S_IRUSR | stat.S_IWUSR)
        ]
        mock_open_calls = [
            mock.call(fake_file_path, 'w'),
            mock.call(fake_file_path, 'r+'),
        ]

        self.mock_object(passwd.os.path, 'isfile', return_value=False)
        self.mock_object(passwd.os.path, 'isdir', return_value=False)
        mock_makedirs = self.mock_object(passwd.os, 'makedirs')
        mock_chmod = self.mock_object(passwd.os, 'chmod')
        mock_open = self.mock_object(
            passwd, 'open', return_value=mock.MagicMock())

        file_storage = passwd.FileStorage(fake_file_path)
        file_storage.open()
        mock_makedirs.assert_called_with(fake_dir_name)
        mock_chmod.assert_has_calls(mock_chmod_calls, any_order=True)
        mock_open.assert_has_calls(mock_open_calls, any_order=True)

    def test_open_not_closed(self):
        fake_file_path = 'file_storage.data'
        fake_file = mock.MagicMock()
        mock_open_calls = [
            mock.call(fake_file_path, 'r+'),
            mock.call(fake_file_path, 'r+'),
        ]
        self.mock_object(passwd.os.path, 'isfile', return_value=True)
        self.mock_object(passwd.os.path, 'isdir', return_value=True)
        mock_open = self.mock_object(passwd, 'open', return_value=fake_file)

        file_storage = passwd.FileStorage(fake_file_path)
        file_storage.open()
        file_storage.open()
        mock_open.assert_has_calls(mock_open_calls)
        fake_file.close.assert_called_once_with()

    def test_load(self):
        passwords = {
            'resource1': {
                'user1': 'resource1-user1',
                'user2': 'resource1-user2',
            },
            'resource2': {
                'user1': 'resource2-user1',
                'user2': 'resource2-user2'
            }
        }
        fake_file_name = 'file_storage.data'
        fake_file_content = json.dumps(passwords)
        fake_file = self._get_fake_file(fake_file_content)
        fake_os_stat = self._get_fake_os_stat(1)

        self._mock_file_open(fake_file, fake_os_stat)

        file_storage = passwd.FileStorage(fake_file_name)
        file_storage.open()
        result = file_storage.load()
        self.assertEqual(passwords, result)

    def test_load_empty_file(self):
        fake_file_name = 'file_storage.data'
        fake_file = self._get_fake_file()
        fake_os_stat = self._get_fake_os_stat(0)

        self._mock_file_open(fake_file, fake_os_stat)

        file_storage = passwd.FileStorage(fake_file_name)
        file_storage.open()
        result = file_storage.load()
        expected = {}
        self.assertEqual(expected, result)

    def test_load_malformed_file(self):
        fake_file_name = 'file_storage.data'
        fake_file = self._get_fake_file('[1, 2, 3]')
        fake_os_stat = self._get_fake_os_stat(1)

        self._mock_file_open(fake_file, fake_os_stat)

        file_storage = passwd.FileStorage(fake_file_name)
        file_storage.open()
        self.assertRaises(ValueError, file_storage.load)

    def test_save(self):
        fake_file_name = 'file_storage.data'
        fake_file = self._get_fake_file('')
        fake_os_stat = self._get_fake_os_stat(0)

        self._mock_file_open(fake_file, fake_os_stat)

        passwords = {
            'resource1': {
                'user1': 'resource1-user1',
                'user2': 'resource1-user2',
            },
            'resource2': {
                'user1': 'resource2-user1',
                'user2': 'resource2-user2'
            }
        }
        fake_file_content = json.dumps(passwords)
        file_storage = passwd.FileStorage(fake_file_name)
        file_storage.open()
        file_storage.save(passwords)
        self.assertEqual(fake_file_content, fake_file.getvalue())

    def test_save_not_dictionary(self):
        fake_file_name = 'file_storage.data'
        fake_file = self._get_fake_file('')
        fake_os_stat = self._get_fake_os_stat(0)

        self._mock_file_open(fake_file, fake_os_stat)

        file_storage = passwd.FileStorage(fake_file_name)
        file_storage.open()
        self.assertRaises(TypeError, file_storage.save, [])

    def test_close(self):
        fake_file_name = 'file_storage.data'
        fake_file = mock.MagicMock()

        self.mock_object(passwd.os.path, 'isfile', return_value=True)
        self.mock_object(passwd.os.path, 'isdir', return_value=True)
        self.mock_object(passwd, 'open', return_value=fake_file)

        file_storage = passwd.FileStorage(fake_file_name)
        file_storage.open()
        file_storage.close()
        fake_file.close.assert_called_once_with()

    def _mock_file_open(self, fake_file, fake_os_stat):
        self.mock_object(passwd.os.path, 'isfile', return_value=True)
        self.mock_object(passwd.os.path, 'isdir', return_value=True)
        self.mock_object(passwd.os, 'stat', return_value=fake_os_stat)
        self.mock_object(passwd, 'open', return_value=fake_file)

    @staticmethod
    def _get_fake_file(content=None):
        return six.StringIO(content)

    @staticmethod
    def _get_fake_os_stat(st_size):
        os_stat = collections.namedtuple('fake_os_stat', ['st_size'])
        os_stat.st_size = st_size
        return os_stat
