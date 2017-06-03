# Copyright (c) 2016 Red Hat Inc.
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

from oslo_utils import timeutils


class ViewBuilder(object):
    """Map Cluster into dicts for API responses."""

    @staticmethod
    def _normalize(date):
        if date:
            return timeutils.normalize_time(date)
        return ''

    @classmethod
    def detail(cls, cluster, replication_data=False, flat=False):
        """Detailed view of a cluster."""
        result = cls.summary(cluster, flat=True)
        result.update(
            num_hosts=cluster.num_hosts,
            num_down_hosts=cluster.num_down_hosts,
            last_heartbeat=cls._normalize(cluster.last_heartbeat),
            created_at=cls._normalize(cluster.created_at),
            updated_at=cls._normalize(cluster.updated_at),
            disabled_reason=cluster.disabled_reason,
            replication_status=cluster.replication_status,
            frozen=cluster.frozen,
            active_backend_id=cluster.active_backend_id,
        )
        if not replication_data:
            for field in ('replication_status', 'frozen', 'active_backend_id'):
                del result[field]
        if flat:
            return result
        return {'cluster': result}

    @staticmethod
    def summary(cluster, replication_data=False, flat=False):
        """Generic, non-detailed view of a cluster."""
        result = {
            'name': cluster.name,
            'binary': cluster.binary,
            'state': 'up' if cluster.is_up else 'down',
            'status': 'disabled' if cluster.disabled else 'enabled',
            'replication_status': cluster.replication_status,
        }
        if not replication_data:
            del result['replication_status']
        if flat:
            return result
        return {'cluster': result}

    @classmethod
    def list(cls, clusters, detail=False, replication_data=False):
        func = cls.detail if detail else cls.summary
        return {'clusters': [func(n, replication_data, flat=True)
                             for n in clusters]}
