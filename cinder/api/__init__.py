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


from oslo_config import cfg
from oslo_log import log as logging
import paste.urlmap


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def root_app_factory(loader, global_conf, **local_conf):
    # To support upgrades from previous api-paste config files, we need
    # to check for and remove any legacy references to the v1 or v2 API
    if '/v1' in local_conf:
        LOG.warning('The v1 API has been removed and is no longer '
                    'available. Client applications should be '
                    'using v3, which is currently the only supported '
                    'version of the Block Storage API.')
        del local_conf['/v1']

    if '/v2' in local_conf:
        LOG.warning('The v2 API has been removed and is no longer available. '
                    'Client applications must now use the v3 API only. '
                    'The \'enable_v2_api\' option has been removed and is '
                    'ignored in the cinder.conf file.')
        del local_conf['/v2']

    return paste.urlmap.urlmap_factory(loader, global_conf, **local_conf)
