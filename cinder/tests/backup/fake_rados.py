# Copyright 2013 Canonical Ltd.
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


class mock_rados(object):

    class ioctx(object):
        def __init__(self, *args, **kwargs):
            pass

        def close(self, *args, **kwargs):
            pass

    class Rados(object):

        def __init__(self, *args, **kwargs):
            pass

        def connect(self, *args, **kwargs):
            pass

        def open_ioctx(self, *args, **kwargs):
            return mock_rados.ioctx()

        def shutdown(self, *args, **kwargs):
            pass

    class Error():
        def __init__(self, *args, **kwargs):
            pass


class mock_rbd(object):

    class ImageBusy(Exception):
        def __init__(self, *args, **kwargs):
            pass

    class ImageNotFound(Exception):
        def __init__(self, *args, **kwargs):
            pass

    class Image(object):

        def __init__(self, *args, **kwargs):
            pass

        def create_snap(self, *args, **kwargs):
            pass

        def remove_snap(self, *args, **kwargs):
            pass

        def read(self, *args, **kwargs):
            raise NotImplementedError()

        def write(self, *args, **kwargs):
            raise NotImplementedError()

        def resize(self, *args, **kwargs):
            raise NotImplementedError()

        def close(self):
            pass

        def list_snaps(self):
            raise NotImplementedError()

        def size(self):
            raise NotImplementedError()

    class RBD(object):

        def __init__(self, *args, **kwargs):
            pass

        def create(self, *args, **kwargs):
            pass

        def remove(self, *args, **kwargs):
            pass

        def list(self, *args, **kwargs):
            raise NotImplementedError()
