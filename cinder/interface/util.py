# Copyright 2016 Dell Inc.
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
#
import fnmatch
import inspect
import os

from cinder import interface


def _ensure_loaded(start_path):
    """Loads everything in a given path.

    This will make sure all classes have been loaded and therefore all
    decorators have registered class.

    :param start_path: The starting path to load.
    """
    for root, folder, files in os.walk(start_path):
        for phile in fnmatch.filter(files, '*.py'):
            path = os.path.join(root, phile)
            try:
                __import__(
                    path.replace('/', '.')[:-3], globals(), locals())
            except Exception:
                # Really don't care here
                pass


def get_volume_drivers():
    """Get a list of all volume drivers."""
    _ensure_loaded('cinder/volume/drivers')
    return [DriverInfo(x) for x in interface._volume_register]


def get_backup_drivers():
    """Get a list of all backup drivers."""
    _ensure_loaded('cinder/backup/drivers')
    return [DriverInfo(x) for x in interface._backup_register]


def get_fczm_drivers():
    """Get a list of all fczm drivers."""
    _ensure_loaded('cinder/zonemanager/drivers')
    return [DriverInfo(x) for x in interface._fczm_register]


class DriverInfo(object):
    """Information about driver implementations."""

    def __init__(self, cls):
        self.cls = cls
        self.desc = cls.__doc__
        self.class_name = cls.__name__
        self.class_fqn = '{}.{}'.format(inspect.getmodule(cls).__name__,
                                        self.class_name)
        self.version = getattr(cls, 'VERSION', None)
        self.ci_wiki_name = getattr(cls, 'CI_WIKI_NAME', None)
        self.supported = getattr(cls, 'SUPPORTED', True)

    def __str__(self):
        return self.class_name

    def __repr__(self):
        return self.class_fqn

    def __hash__(self):
        return hash(self.class_fqn)
