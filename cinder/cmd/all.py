#!/usr/bin/env python
# Copyright 2011 OpenStack Foundation
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""Starter script for All cinder services.

This script attempts to start all the cinder services in one process.  Each
service is started in its own greenthread.  Please note that exceptions and
sys.exit() on the starting of a service are logged and the script will
continue attempting to launch the rest of the services.

"""

import eventlet
eventlet.monkey_patch()

import sys

from oslo_config import cfg
from oslo_log import log as logging
from oslo_log import versionutils
from oslo_reports import guru_meditation_report as gmr
from oslo_reports import opts as gmr_opts

from cinder import i18n
i18n.enable_lazy()

# Need to register global_opts
from cinder.cmd import volume as volume_cmd
from cinder.common import config   # noqa
from cinder.db import api as session
from cinder.i18n import _LE, _, _LW
from cinder import objects
from cinder import rpc
from cinder import service
from cinder import utils
from cinder import version


CONF = cfg.CONF


# TODO(e0ne): get a rid of code duplication in cinder.cmd module in Mitaka
def main():
    objects.register_all()
    gmr_opts.set_defaults(CONF)
    CONF(sys.argv[1:], project='cinder',
         version=version.version_string())
    config.set_middleware_defaults()
    logging.setup(CONF, "cinder")
    LOG = logging.getLogger('cinder.all')
    versionutils.report_deprecated_feature(LOG, _(
        'cinder-all is deprecated in Newton and will be removed in Ocata.'))

    utils.monkey_patch()

    gmr.TextGuruMeditation.setup_autorun(version, conf=CONF)

    rpc.init(CONF)

    launcher = service.process_launcher()
    # cinder-api
    try:
        server = service.WSGIService('osapi_volume')
        launcher.launch_service(server, workers=server.workers or 1)
    except (Exception, SystemExit):
        LOG.exception(_LE('Failed to load osapi_volume'))

    for binary in ['cinder-scheduler', 'cinder-backup']:
        try:
            launcher.launch_service(service.Service.create(binary=binary))
        except (Exception, SystemExit):
            LOG.exception(_LE('Failed to load %s'), binary)

    # cinder-volume
    try:
        if CONF.enabled_backends:
            for backend in filter(None, CONF.enabled_backends):
                CONF.register_opt(volume_cmd.host_opt, group=backend)
                backend_host = getattr(CONF, backend).backend_host
                host = "%s@%s" % (backend_host or CONF.host, backend)
                server = service.Service.create(host=host,
                                                service_name=backend,
                                                binary='cinder-volume',
                                                coordination=True)
                # Dispose of the whole DB connection pool here before
                # starting another process.  Otherwise we run into cases
                # where child processes share DB connections which results
                # in errors.
                session.dispose_engine()
                launcher.launch_service(server)
        else:
            LOG.warning(_LW('Configuration for cinder-volume does not specify '
                            '"enabled_backends", using DEFAULT as backend. '
                            'Support for DEFAULT section to configure drivers '
                            'will be removed in the next release.'))
            server = service.Service.create(binary='cinder-volume',
                                            coordination=True)
            launcher.launch_service(server)
    except (Exception, SystemExit):
        LOG.exception(_LE('Failed to load cinder-volume'))

    launcher.wait()
