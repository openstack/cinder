#!/usr/bin/env python

# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
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

"""Starter script for Cinder Volume Backup."""

import logging as python_logging
import shlex
import sys

# NOTE(geguileo): Monkey patching must go before OSLO.log import, otherwise
# OSLO.context will not use greenthread thread local and all greenthreads will
# share the same context.
import eventlet
eventlet.monkey_patch()

from oslo_config import cfg
from oslo_log import log as logging
from oslo_privsep import priv_context
from oslo_reports import guru_meditation_report as gmr
from oslo_reports import opts as gmr_opts


from cinder import i18n
i18n.enable_lazy()

# Need to register global_opts
from cinder.common import config  # noqa
from cinder import objects
from cinder import service
from cinder import utils
from cinder import version


CONF = cfg.CONF

# NOTE(mriedem): The default backup driver uses swift and performs read/write
# operations in a thread. swiftclient will log requests and responses at DEBUG
# level, which can cause a thread switch and break the backup operation. So we
# set a default log level of WARN for swiftclient to try and avoid this issue.
_EXTRA_DEFAULT_LOG_LEVELS = ['swiftclient=WARN']


def main():
    objects.register_all()
    gmr_opts.set_defaults(CONF)
    CONF(sys.argv[1:], project='cinder',
         version=version.version_string())
    logging.set_defaults(
        default_log_levels=logging.get_default_log_levels() +
        _EXTRA_DEFAULT_LOG_LEVELS)
    logging.setup(CONF, "cinder")
    python_logging.captureWarnings(True)
    priv_context.init(root_helper=shlex.split(utils.get_root_helper()))
    utils.monkey_patch()
    gmr.TextGuruMeditation.setup_autorun(version, conf=CONF)
    server = service.Service.create(binary='cinder-backup',
                                    coordination=True)
    service.serve(server)
    service.wait()
