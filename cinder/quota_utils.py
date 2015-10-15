# Copyright 2013 OpenStack Foundation
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

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _LW
from cinder import quota


LOG = logging.getLogger(__name__)
QUOTAS = quota.QUOTAS


def get_volume_type_reservation(ctxt, volume, type_id):
    # Reserve quotas for the given volume type
    try:
        reserve_opts = {'volumes': 1, 'gigabytes': volume['size']}
        QUOTAS.add_volume_type_opts(ctxt,
                                    reserve_opts,
                                    type_id)
        # Note that usually the project_id on the volume will be the same as
        # the project_id in the context. But, if they are different then the
        # reservations must be recorded against the project_id that owns the
        # volume.
        project_id = volume['project_id']
        reservations = QUOTAS.reserve(ctxt,
                                      project_id=project_id,
                                      **reserve_opts)
    except exception.OverQuota as e:
        overs = e.kwargs['overs']
        usages = e.kwargs['usages']
        quotas = e.kwargs['quotas']

        def _consumed(name):
            return (usages[name]['reserved'] + usages[name]['in_use'])

        for over in overs:
            if 'gigabytes' in over:
                s_size = volume['size']
                d_quota = quotas[over]
                d_consumed = _consumed(over)
                LOG.warning(
                    _LW("Quota exceeded for %(s_pid)s, tried to create "
                        "%(s_size)sG volume - (%(d_consumed)dG of "
                        "%(d_quota)dG already consumed)"),
                    {'s_pid': ctxt.project_id,
                     's_size': s_size,
                     'd_consumed': d_consumed,
                     'd_quota': d_quota})
                raise exception.VolumeSizeExceedsAvailableQuota(
                    requested=s_size, quota=d_quota, consumed=d_consumed)
            elif 'volumes' in over:
                LOG.warning(
                    _LW("Quota exceeded for %(s_pid)s, tried to create "
                        "volume (%(d_consumed)d volumes "
                        "already consumed)"),
                    {'s_pid': ctxt.project_id,
                     'd_consumed': _consumed(over)})
                raise exception.VolumeLimitExceeded(
                    allowed=quotas[over])
    return reservations
