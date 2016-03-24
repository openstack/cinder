# Copyright 2013 Red Hat, Inc.
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

import mock


def mock_cast_as_call(obj=None):
    """Use this to mock `cast` as calls.

    :param obj: Either an instance of RPCClient
    or an instance of _Context.
    """
    orig_prepare = obj.prepare

    def prepare(*args, **kwargs):
        cctxt = orig_prepare(*args, **kwargs)
        mock_cast_as_call(obj=cctxt)  # woo, recurse!
        return cctxt

    prepare_patch = mock.patch.object(obj, 'prepare').start()
    prepare_patch.side_effect = prepare

    cast_patch = mock.patch.object(obj, 'cast').start()
    cast_patch.side_effect = obj.call
