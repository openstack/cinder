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

from cinder import objects

warnings.simplefilter('once', DeprecationWarning)

from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import wsgi

from cinder import i18n
i18n.enable_lazy()

# Need to register global_opts
from cinder.common import config
from cinder import rpc
from cinder import version

CONF = cfg.CONF


def initialize_application():
    objects.register_all()
    CONF(sys.argv[1:], project='cinder',
         version=version.version_string())
    logging.setup(CONF, "cinder")
    config.set_middleware_defaults()

    rpc.init(CONF)
    return wsgi.Loader(CONF).load_app(name='osapi_volume')
