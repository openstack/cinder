# Copyright 2018 Red Hat, Inc
# Copyright 2017 Rackspace Australia
# Copyright 2018 Michael Still and Aptira
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

"""
Helpers for path related routines.
"""

import os

from cinder import exception
import cinder.privsep


@cinder.privsep.sys_admin_pctxt.entrypoint
def readfile(path):
    if not os.path.exists(path):
        raise exception.FileNotFound(file_path=path)
    with open(path, 'r') as f:
        return f.read()


@cinder.privsep.sys_admin_pctxt.entrypoint
def removefile(path):
    if not os.path.exists(path):
        raise exception.FileNotFound(file_path=path)
    os.unlink(path)


@cinder.privsep.sys_admin_pctxt.entrypoint
def touch(path):
    if os.path.exists(path):
        os.utime(path, None)
    else:
        open(path, 'a').close()


@cinder.privsep.sys_admin_pctxt.entrypoint
def symlink(src, dest):
    if not os.path.exists(src):
        raise exception.FileNotFound(file_path=src)
    os.symlink(src, dest)
