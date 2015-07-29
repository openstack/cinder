# Copyright (c) 2014 OpenStack Foundation
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
"""Weighers that weigh hosts by volume number in backends:

1. Volume Number Weigher.  Weigh hosts by their volume number.

The default is to spread volumes across all hosts evenly.  If you prefer
stacking, you can set the 'volume_number_multiplier' option to a positive
number and the weighing has the opposite effect of the default.
"""


from oslo_config import cfg
from oslo_log import log as logging

from cinder import db
from cinder.openstack.common.scheduler import weights


LOG = logging.getLogger(__name__)


volume_number_weight_opts = [
    cfg.FloatOpt('volume_number_multiplier',
                 default=-1.0,
                 help='Multiplier used for weighing volume number. '
                      'Negative numbers mean to spread vs stack.'),
]

CONF = cfg.CONF
CONF.register_opts(volume_number_weight_opts)


class VolumeNumberWeigher(weights.BaseHostWeigher):
    def weight_multiplier(self):
        """Override the weight multiplier."""
        return CONF.volume_number_multiplier

    def _weigh_object(self, host_state, weight_properties):
        """Less volume number weights win.

        We want spreading to be the default.
        """
        context = weight_properties['context']
        volume_number = db.volume_data_get_for_host(context=context,
                                                    host=host_state.host,
                                                    count_only=True)
        return volume_number
