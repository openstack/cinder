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

"""Password storage."""

import json
import os
import stat

from oslo_log import log as logging

from cinder.i18n import _
from cinder import utils as cinder_utils


LOG = logging.getLogger(__name__)


class FileStorage(object):
    """Represents a file as a dictionary."""

    def __init__(self, file_path):
        self._file_path = file_path
        self._file = None
        self._is_open = False

    def open(self):
        """Open a file for simultaneous reading and writing.

        If the specified file does not exist, it will be created
        with the 0600 access permissions for the current user, if needed
        the appropriate directories will be created with the 0750 access
        permissions for the current user.
        """

        file_dir = os.path.dirname(self._file_path)
        if file_dir and not os.path.isdir(file_dir):
            os.makedirs(file_dir)
            os.chmod(file_dir, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
        if not os.path.isfile(self._file_path):
            open(self._file_path, 'w').close()
            os.chmod(self._file_path, stat.S_IRUSR | stat.S_IWUSR)

        if self._file:
            self.close()
        self._file = open(self._file_path, 'r+')
        return self

    def load(self):
        """Reads the file and returns corresponded dictionary object.

        :return: The dictionary that represents the file content.
        """

        storage = {}
        if os.stat(self._file_path).st_size != 0:
            storage = json.load(self._file)
            if not isinstance(storage, dict):
                msg = _('File %s has a malformed format.') % self._file_path
                raise ValueError(msg)
        return storage

    def save(self, storage):
        """Writes the specified dictionary to the file.

        :param storage: Dictionary that should be written to the file.
        """

        if not isinstance(storage, dict):
            msg = _('%s is not a dict.') % repr(storage)
            raise TypeError(msg)

        self._file.seek(0)
        self._file.truncate()
        json.dump(storage, self._file)

    def close(self):
        """Close the file."""

        if self._file:
            self._file.close()
        self._file = None

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()


class PasswordFileStorage(object):
    """Password storage implementation.

    It stores passwords in a file in a clear text. The password file must be
    secured by setting up file permissions.
    """

    def __init__(self, file_path):
        self._file_path = file_path
        self._file_storage = FileStorage(file_path)

    def set_password(self, resource, username, password):
        """Store the credential for the resource.

        :param resource: Resource name for which credential will be stored
        :param username: User name
        :param password: Password
        """

        @cinder_utils.synchronized(
            'datacore-password_storage-' + self._file_path, external=True)
        def _set_password():
            with self._file_storage.open() as storage:
                passwords = storage.load()
                if resource not in passwords:
                    passwords[resource] = {}
                passwords[resource][username] = password
                storage.save(passwords)

        _set_password()

    def get_password(self, resource, username):
        """Returns the stored password for the resource.

        If the password does not exist, it will return None

        :param resource: Resource name for which credential was stored
        :param username: User name
        :return password: Password
        """

        @cinder_utils.synchronized(
            'datacore-password_storage-' + self._file_path, external=True)
        def _get_password():
            with self._file_storage.open() as storage:
                passwords = storage.load()
            if resource in passwords:
                return passwords[resource].get(username)

        return _get_password()

    def delete_password(self, resource, username):
        """Delete the stored credential for the resource.

        :param resource: Resource name for which credential was stored
        :param username: User name
        """

        @cinder_utils.synchronized(
            'datacore-password_storage-' + self._file_path, external=True)
        def _delete_password():
            with self._file_storage.open() as storage:
                passwords = storage.load()
                if resource in passwords and username in passwords[resource]:
                    del passwords[resource][username]
                    if not passwords[resource].keys():
                        del passwords[resource]
                    storage.save(passwords)

        _delete_password()
