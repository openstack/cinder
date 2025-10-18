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

"""Cinder OS API WSGI application."""

import sys
import warnings
warnings.simplefilter('once', DeprecationWarning)

from oslo_config import cfg
from oslo_log import log as logging
from oslo_reports import guru_meditation_report as gmr
from oslo_reports import opts as gmr_opts
from oslo_service import wsgi

from cinder import objects  # noqa
from cinder import i18n  # noqa
i18n.enable_lazy()
# Need to register global_opts
from cinder.common import config
from cinder.common import constants
from cinder import coordination
from cinder import rpc
from cinder import service
from cinder import version

CONF = cfg.CONF


def initialize_application():
    objects.register_all()
    gmr_opts.set_defaults(CONF)
    CONF(sys.argv[1:], project='cinder',
         version=version.version_string())
    logging.setup(CONF, "cinder")
    config.set_middleware_defaults()

    # NOTE(amorin): Do not register signal handers because it does not work
    # in wsgi applications
    gmr.TextGuruMeditation.setup_autorun(
        version, conf=CONF, setup_signal=False)

    coordination.COORDINATOR.start()

    rpc.init(CONF)
    service.setup_profiler(constants.API_BINARY, CONF.host)

    return wsgi.Loader(CONF).load_app(name='osapi_volume')
