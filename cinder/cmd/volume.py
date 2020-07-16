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
import logging as python_logging
import os
import re
import shlex
import sys

import eventlet
import eventlet.tpool
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
import __original_module_threading as orig_threading
import threading # noqa
orig_threading.current_thread.__globals__['_active'] = threading._active

from oslo_config import cfg
from oslo_log import log as logging
from oslo_privsep import priv_context
from oslo_reports import guru_meditation_report as gmr
from oslo_reports import opts as gmr_opts

# Need to register global_opts
from cinder.common import config  # noqa
from cinder.common import constants
from cinder.db import api as session
from cinder import exception
from cinder import i18n
i18n.enable_lazy()
from cinder.i18n import _
from cinder import objects
from cinder import service
from cinder import utils
from cinder import version

CONF = cfg.CONF

host_opt = cfg.StrOpt('backend_host', help='Backend override of host value.')
CONF.register_cli_opt(host_opt)

backend_name_opt = cfg.StrOpt(
    'backend_name',
    help='NOTE: For Windows internal use only. The name of the backend to be '
         'managed by this process. It must be one of the backends defined '
         'using the "enabled_backends" option. Note that normally, this '
         'should not be used directly. Cinder uses it internally in order to '
         'spawn subprocesses on Windows.')
CONF.register_cli_opt(backend_name_opt)


cluster_opt = cfg.StrOpt('cluster',
                         default=None,
                         help='Name of this cluster. Used to group volume '
                              'hosts that share the same backend '
                              'configurations to work in HA Active-Active '
                              'mode.')
CONF.register_opt(cluster_opt)

LOG = None

service_started = False


def _launch_service(launcher, backend):
    CONF.register_opt(host_opt, group=backend)
    backend_host = getattr(CONF, backend).backend_host
    host = "%s@%s" % (backend_host or CONF.host, backend)
    # We also want to set cluster to None on empty strings, and we
    # ignore leading and trailing spaces.
    cluster = CONF.cluster and CONF.cluster.strip()
    cluster = (cluster or None) and '%s@%s' % (cluster, backend)
    try:
        server = service.Service.create(host=host,
                                        service_name=backend,
                                        binary=constants.VOLUME_BINARY,
                                        coordination=True,
                                        cluster=cluster)
    except Exception:
        LOG.exception('Volume service %s failed to start.', host)
    else:
        # Dispose of the whole DB connection pool here before
        # starting another process.  Otherwise we run into cases where
        # child processes share DB connections which results in errors.
        session.dispose_engine()
        launcher.launch_service(server)
        _notify_service_started()


def _ensure_service_started():
    if not service_started:
        LOG.error('No volume service(s) started successfully, terminating.')
        sys.exit(1)


def _notify_service_started():
    global service_started
    service_started = True


def _launch_services_win32():
    if CONF.backend_name and CONF.backend_name not in CONF.enabled_backends:
        msg = _('The explicitly passed backend name "%(backend_name)s" is not '
                'among the enabled backends: %(enabled_backends)s.')
        raise exception.InvalidInput(
            reason=msg % dict(backend_name=CONF.backend_name,
                              enabled_backends=CONF.enabled_backends))

    # We'll avoid spawning a subprocess if a single backend is requested.
    single_backend_name = (CONF.enabled_backends[0]
                           if len(CONF.enabled_backends) == 1
                           else CONF.backend_name)
    if single_backend_name:
        launcher = service.get_launcher()
        _launch_service(launcher, single_backend_name)
    elif CONF.enabled_backends:
        # We're using the 'backend_name' argument, requesting a certain backend
        # and constructing the service object within the child process.
        launcher = service.WindowsProcessLauncher()
        py_script_re = re.compile(r'.*\.py\w?$')
        for backend in filter(None, CONF.enabled_backends):
            cmd = sys.argv + ['--backend_name=%s' % backend]
            # Recent setuptools versions will trim '-script.py' and '.exe'
            # extensions from sys.argv[0].
            if py_script_re.match(sys.argv[0]):
                cmd = [sys.executable] + cmd
            launcher.add_process(cmd)
            _notify_service_started()

    _ensure_service_started()

    launcher.wait()


def _launch_services_posix():
    launcher = service.get_launcher()

    for backend in filter(None, CONF.enabled_backends):
        _launch_service(launcher, backend)

    _ensure_service_started()

    launcher.wait()


def main():
    objects.register_all()
    gmr_opts.set_defaults(CONF)
    CONF(sys.argv[1:], project='cinder',
         version=version.version_string())
    logging.setup(CONF, "cinder")
    python_logging.captureWarnings(True)
    priv_context.init(root_helper=shlex.split(utils.get_root_helper()))
    utils.monkey_patch()
    gmr.TextGuruMeditation.setup_autorun(version, conf=CONF)
    global LOG
    LOG = logging.getLogger(__name__)

    if not CONF.enabled_backends:
        LOG.error('Configuration for cinder-volume does not specify '
                  '"enabled_backends". Using DEFAULT section to configure '
                  'drivers is not supported since Ocata.')
        sys.exit(1)

    if os.name == 'nt':
        # We cannot use oslo.service to spawn multiple services on Windows.
        # It relies on forking, which is not available on Windows.
        # Furthermore, service objects are unmarshallable objects that are
        # passed to subprocesses.
        _launch_services_win32()
    else:
        _launch_services_posix()
