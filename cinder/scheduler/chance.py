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
Chance (Random) Scheduler implementation
"""

import random

from oslo.config import cfg

from cinder import exception
from cinder.scheduler import driver


CONF = cfg.CONF


class ChanceScheduler(driver.Scheduler):
    """Implements Scheduler as a random node selector."""

    def _filter_hosts(self, request_spec, hosts, **kwargs):
        """Filter a list of hosts based on request_spec."""

        filter_properties = kwargs.get('filter_properties', {})
        if not filter_properties:
            filter_properties = {}
        ignore_hosts = filter_properties.get('ignore_hosts', [])
        hosts = [host for host in hosts if host not in ignore_hosts]
        return hosts

    def _get_weighted_candidates(self, context, topic, request_spec, **kwargs):
        """Returns a list of the available hosts."""

        elevated = context.elevated()
        hosts = self.hosts_up(elevated, topic)
        if not hosts:
            msg = _("Is the appropriate service running?")
            raise exception.NoValidHost(reason=msg)

        return self._filter_hosts(request_spec, hosts, **kwargs)

    def _schedule(self, context, topic, request_spec, **kwargs):
        """Picks a host that is up at random."""
        hosts = self._get_weighted_candidates(context, topic,
                                              request_spec, **kwargs)
        if not hosts:
            msg = _("Could not find another host")
            raise exception.NoValidHost(reason=msg)
        return hosts[int(random.random() * len(hosts))]

    def schedule_create_volume(self, context, request_spec, filter_properties):
        """Picks a host that is up at random."""
        topic = CONF.volume_topic
        host = self._schedule(context, topic, request_spec,
                              filter_properties=filter_properties)
        volume_id = request_spec['volume_id']
        snapshot_id = request_spec['snapshot_id']
        image_id = request_spec['image_id']

        updated_volume = driver.volume_update_db(context, volume_id, host)
        self.volume_rpcapi.create_volume(context, updated_volume, host,
                                         request_spec, filter_properties,
                                         snapshot_id=snapshot_id,
                                         image_id=image_id)

    def host_passes_filters(self, context, host, request_spec,
                            filter_properties):
        """Check if the specified host passes the filters."""
        weighed_hosts = self._get_weighted_candidates(
            context,
            CONF.volume_topic,
            request_spec,
            filter_properties=filter_properties)

        for weighed_host in weighed_hosts:
            if weighed_host == host:
                elevated = context.elevated()
                host_states = self.host_manager.get_all_host_states(elevated)
                for host_state in host_states:
                    if host_state.host == host:
                        return host_state

        msg = (_('cannot place volume %(id)s on %(host)s')
               % {'id': request_spec['volume_id'], 'host': host})
        raise exception.NoValidHost(reason=msg)
