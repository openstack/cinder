# Copyright (c) 2010 OpenStack Foundation
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

"""
Simple Scheduler
"""

from oslo.config import cfg

from cinder import db
from cinder import exception
from cinder.scheduler import chance
from cinder import utils


simple_scheduler_opts = [
    cfg.IntOpt("max_gigabytes",
               default=10000,
               help="maximum number of volume gigabytes to allow per host"), ]

CONF = cfg.CONF
CONF.register_opts(simple_scheduler_opts)


class SimpleScheduler(chance.ChanceScheduler):
    """Implements Naive Scheduler that tries to find least loaded host."""

    def _get_weighted_candidates(self, context, topic, request_spec, **kwargs):
        """Picks a host that is up and has the fewest volumes."""
        elevated = context.elevated()

        volume_id = request_spec.get('volume_id')
        snapshot_id = request_spec.get('snapshot_id')
        image_id = request_spec.get('image_id')
        volume_properties = request_spec.get('volume_properties')
        volume_size = volume_properties.get('size')
        availability_zone = volume_properties.get('availability_zone')
        filter_properties = kwargs.get('filter_properties', {})

        zone, host = None, None
        if availability_zone:
            zone, _x, host = availability_zone.partition(':')
        if host and context.is_admin:
            service = db.service_get_by_args(elevated, host, topic)
            if not utils.service_is_up(service):
                raise exception.WillNotSchedule(host=host)
            return [host]

        candidates = []
        results = db.service_get_all_volume_sorted(elevated)
        if zone:
            results = [(s, gigs) for (s, gigs) in results
                       if s['availability_zone'] == zone]
        for result in results:
            (service, volume_gigabytes) = result
            no_skip = service['host'] != filter_properties.get('vol_exists_on')
            if no_skip and volume_gigabytes + volume_size > CONF.max_gigabytes:
                continue
            if utils.service_is_up(service) and not service['disabled']:
                candidates.append(service['host'])

        if candidates:
            return candidates
        else:
            msg = _("No service with adequate space or no service running")
            raise exception.NoValidHost(reason=msg)

    def _choose_host_from_list(self, hosts):
        return hosts[0]
