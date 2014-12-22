# (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Generic exec utility that allows us to set the
   execute and root_helper attributes for putils.
   Some projects need their own execute wrapper
   and root_helper settings, so this provides that hook.
"""

from oslo_concurrency import processutils as putils


class Executor(object):
    def __init__(self, root_helper, execute=putils.execute,
                 *args, **kwargs):
        self.set_execute(execute)
        self.set_root_helper(root_helper)

    def set_execute(self, execute):
        self._execute = execute

    def set_root_helper(self, helper):
        self._root_helper = helper
