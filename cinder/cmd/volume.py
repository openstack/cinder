#!/usr/bin/env python
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

"""Starter script for Cinder Volume."""

import os

import eventlet

from cinder import objects

if os.name == 'nt':
    # eventlet monkey patching the os module causes subprocess.Popen to fail
    # on Windows when using pipes due to missing non-blocking IO support.
    eventlet.monkey_patch(os=False)
else:
    eventlet.monkey_patch()

import sys
import warnings

warnings.simplefilter('once', DeprecationWarning)

from oslo_config import cfg
from oslo_log import log as logging

from cinder import i18n
i18n.enable_lazy()

# Need to register global_opts
from cinder.common import config  # noqa
from cinder.db import api as session
from cinder import service
from cinder import utils
from cinder import version


deprecated_host_opt = cfg.DeprecatedOpt('host')
host_opt = cfg.StrOpt('backend_host', help='Backend override of host value.',
                      deprecated_opts=[deprecated_host_opt])
cfg.CONF.register_cli_opt(host_opt)
CONF = cfg.CONF


def main():
    objects.register_all()
    CONF(sys.argv[1:], project='cinder',
         version=version.version_string())
    logging.setup(CONF, "cinder")
    utils.monkey_patch()
    launcher = service.get_launcher()
    if CONF.enabled_backends:
        for backend in CONF.enabled_backends:
            CONF.register_opt(host_opt, group=backend)
            backend_host = getattr(CONF, backend).backend_host
            host = "%s@%s" % (backend_host or CONF.host, backend)
            server = service.Service.create(host=host,
                                            service_name=backend,
                                            binary='cinder-volume')
            # Dispose of the whole DB connection pool here before
            # starting another process.  Otherwise we run into cases where
            # child processes share DB connections which results in errors.
            session.dispose_engine()
            launcher.launch_service(server)
    else:
        server = service.Service.create(binary='cinder-volume')
        launcher.launch_service(server)
    launcher.wait()
