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

import sys
import warnings

warnings.simplefilter('once', DeprecationWarning)

import eventlet
from oslo_config import cfg
from oslo_log import log as logging

eventlet.monkey_patch()

from cinder import i18n
i18n.enable_lazy()

# Need to register global_opts
from cinder.common import config  # noqa
from cinder import service
from cinder import utils
from cinder import version


CONF = cfg.CONF


def main():
    CONF(sys.argv[1:], project='cinder',
         version=version.version_string())
    logging.setup(CONF, "cinder")
    utils.monkey_patch()
    server = service.Service.create(binary='cinder-backup')
    service.serve(server)
    service.wait()
