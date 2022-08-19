# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
:mod:`cinder.tests.unit` -- Cinder Unittests
=====================================================

.. automodule:: cinder.tests.unit
   :platform: Unix
"""

import os

import eventlet
# Monkey patching must go before the oslo.log import, otherwise
# oslo.context will not use greenthread thread local and all greenthreads
# will share the same context.
if os.name == 'nt':
    # eventlet monkey patching the os module causes subprocess.Popen to fail
    # on Windows when using pipes due to missing non-blocking IO support.
    eventlet.monkey_patch(os=False)
else:
    eventlet.monkey_patch()
# Monkey patch the original current_thread to use the up-to-date _active
# global variable. See https://bugs.launchpad.net/bugs/1863021 and
# https://github.com/eventlet/eventlet/issues/592
import __original_module_threading as orig_threading  # pylint: disable=E0401
import threading # noqa
orig_threading.current_thread.__globals__['_active'] = threading._active

from cinder import objects

# NOTE(alaski): Make sure this is done after eventlet monkey patching otherwise
# the threading.local() store used in oslo_messaging will be initialized to
# threadlocal storage rather than greenthread local.  This will cause context
# sets and deletes in that storage to clobber each other.
# NOTE(comstud): Make sure we have all of the objects loaded. We do this
# at module import time, because we may be using mock decorators in our
# tests that run at import time.
objects.register_all()
