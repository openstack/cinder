# Copyright 2018 Red Hat, Inc
# Copyright (c) 2017 Veritas Technologies LLC.  All rights reserved.
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
Helpers for hscli related routines
"""
from oslo_concurrency import processutils as putils
from oslo_log import log as logging

from cinder import exception
import cinder.privsep

LOG = logging.getLogger(__name__)


@cinder.privsep.sys_admin_pctxt.entrypoint
def hsexecute(cmdarg_json):

    cmd_out = None
    cmd_err = None
    try:
        # call hyperscale cli
        (cmd_out, cmd_err) = putils.execute("hscli", cmdarg_json)
    except (putils.UnknownArgumentError, putils.ProcessExecutionError,
            OSError):
        LOG.exception("Exception in running the command for %s",
                      cmdarg_json)
        raise exception.UnableToExecuteHyperScaleCmd(command=cmdarg_json)

    return (cmd_out, cmd_err)
