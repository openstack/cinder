# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from cinder.scheduler import driver
from cinder import utils


simple_scheduler_opts = [
    cfg.IntOpt("max_gigabytes",
               default=10000,
               help="maximum number of volume gigabytes to allow per host"), ]

CONF = cfg.CONF
CONF.register_opts(simple_scheduler_opts)


class SimpleScheduler(chance.ChanceScheduler):
    """Implements Naive Scheduler that tries to find least loaded host."""

    def schedule_create_volume(self, context, request_spec, filter_properties):
        """Picks a host that is up and has the fewest volumes."""
        elevated = context.elevated()

        volume_id = request_spec.get('volume_id')
        snapshot_id = request_spec.get('snapshot_id')
        image_id = request_spec.get('image_id')
        volume_properties = request_spec.get('volume_properties')
        volume_size = volume_properties.get('size')
        availability_zone = volume_properties.get('availability_zone')

        zone, host = None, None
        if availability_zone:
            zone, _x, host = availability_zone.partition(':')
        if host and context.is_admin:
            topic = CONF.volume_topic
            service = db.service_get_by_args(elevated, host, topic)
            if not utils.service_is_up(service):
                raise exception.WillNotSchedule(host=host)
            updated_volume = driver.volume_update_db(context, volume_id, host)
            self.volume_rpcapi.create_volume(context, updated_volume, host,
                                             request_spec, filter_properties,
                                             snapshot_id=snapshot_id,
                                             image_id=image_id)
            return None

        results = db.service_get_all_volume_sorted(elevated)
        if zone:
            results = [(s, gigs) for (s, gigs) in results
                       if s['availability_zone'] == zone]
        for result in results:
            (service, volume_gigabytes) = result
            if volume_gigabytes + volume_size > CONF.max_gigabytes:
                msg = _("Not enough allocatable volume gigabytes remaining")
                raise exception.NoValidHost(reason=msg)
            if utils.service_is_up(service) and not service['disabled']:
                updated_volume = driver.volume_update_db(context, volume_id,
                                                         service['host'])
                self.volume_rpcapi.create_volume(context, updated_volume,
                                                 service['host'], request_spec,
                                                 filter_properties,
                                                 snapshot_id=snapshot_id,
                                                 image_id=image_id)
                return None
        msg = _("Is the appropriate service running?")
        raise exception.NoValidHost(reason=msg)
