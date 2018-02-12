# Copyright (c) 2012 Intel
# Copyright (c) 2012 OpenStack Foundation
# Copyright (c) 2015 EMC Corporation
#
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


import math

from oslo_log import log as logging

from cinder.scheduler import filters


LOG = logging.getLogger(__name__)


class CapacityFilter(filters.BaseBackendFilter):
    """Capacity filters based on volume backend's capacity utilization."""

    def backend_passes(self, backend_state, filter_properties):
        """Return True if host has sufficient capacity."""

        volid = None
        # If the volume already exists on this host, don't fail it for
        # insufficient capacity (e.g., if we are retyping)
        if backend_state.backend_id == filter_properties.get('vol_exists_on'):
            return True

        spec = filter_properties.get('request_spec')
        if spec:
            volid = spec.get('volume_id')

        grouping = 'cluster' if backend_state.cluster_name else 'host'
        if filter_properties.get('new_size'):
            # If new_size is passed, we are allocating space to extend a volume
            requested_size = (int(filter_properties.get('new_size')) -
                              int(filter_properties.get('size')))
            LOG.debug('Checking if %(grouping)s %(grouping_name)s can extend '
                      'the volume %(id)s in %(size)s GB',
                      {'grouping': grouping,
                       'grouping_name': backend_state.backend_id, 'id': volid,
                       'size': requested_size})
        else:
            requested_size = filter_properties.get('size')
            LOG.debug('Checking if %(grouping)s %(grouping_name)s can create '
                      'a %(size)s GB volume (%(id)s)',
                      {'grouping': grouping,
                       'grouping_name': backend_state.backend_id, 'id': volid,
                       'size': requested_size})

        # requested_size is 0 means that it's a manage request.
        if requested_size == 0:
            return True

        if backend_state.free_capacity_gb is None:
            # Fail Safe
            LOG.error("Free capacity not set: "
                      "volume node info collection broken.")
            return False

        free_space = backend_state.free_capacity_gb
        total_space = backend_state.total_capacity_gb
        reserved = float(backend_state.reserved_percentage) / 100
        if free_space in ['infinite', 'unknown']:
            # NOTE(zhiteng) for those back-ends cannot report actual
            # available capacity, we assume it is able to serve the
            # request.  Even if it was not, the retry mechanism is
            # able to handle the failure by rescheduling
            return True
        elif total_space in ['infinite', 'unknown']:
            # If total_space is 'infinite' or 'unknown' and reserved
            # is 0, we assume the back-ends can serve the request.
            # If total_space is 'infinite' or 'unknown' and reserved
            # is not 0, we cannot calculate the reserved space.
            # float(total_space) will throw an exception. total*reserved
            # also won't work. So the back-ends cannot serve the request.
            if reserved == 0:
                return True
            LOG.debug("Cannot calculate GB of reserved space (%s%%) with "
                      "backend's reported total capacity '%s'",
                      backend_state.reserved_percentage, total_space)
            return False
        total = float(total_space)
        if total <= 0:
            LOG.warning("Insufficient free space for volume creation. "
                        "Total capacity is %(total).2f on %(grouping)s "
                        "%(grouping_name)s.",
                        {"total": total,
                         "grouping": grouping,
                         "grouping_name": backend_state.backend_id})
            return False

        # Calculate how much free space is left after taking into account
        # the reserved space.
        free = free_space - math.floor(total * reserved)

        # NOTE(xyang): If 'provisioning:type' is 'thick' in extra_specs,
        # we will not use max_over_subscription_ratio and
        # provisioned_capacity_gb to determine whether a volume can be
        # provisioned. Instead free capacity will be used to evaluate.
        thin = True
        vol_type = filter_properties.get('volume_type', {}) or {}
        provision_type = vol_type.get('extra_specs', {}).get(
            'provisioning:type')
        if provision_type == 'thick':
            thin = False

        msg_args = {"grouping_name": backend_state.backend_id,
                    "grouping": grouping,
                    "requested": requested_size,
                    "available": free}
        # Only evaluate using max_over_subscription_ratio if
        # thin_provisioning_support is True. Check if the ratio of
        # provisioned capacity over total capacity has exceeded over
        # subscription ratio.
        if (thin and backend_state.thin_provisioning_support and
                backend_state.max_over_subscription_ratio >= 1):
            provisioned_ratio = ((backend_state.provisioned_capacity_gb +
                                  requested_size) / total)
            LOG.debug("Checking provisioning for request of %s GB. "
                      "Backend: %s", requested_size, backend_state)
            if provisioned_ratio > backend_state.max_over_subscription_ratio:
                msg_args = {
                    "provisioned_ratio": provisioned_ratio,
                    "oversub_ratio": backend_state.max_over_subscription_ratio,
                    "grouping": grouping,
                    "grouping_name": backend_state.backend_id,
                }
                LOG.warning(
                    "Insufficient free space for thin provisioning. "
                    "The ratio of provisioned capacity over total capacity "
                    "%(provisioned_ratio).2f has exceeded the maximum over "
                    "subscription ratio %(oversub_ratio).2f on %(grouping)s "
                    "%(grouping_name)s.", msg_args)
                return False
            else:
                # Thin provisioning is enabled and projected over-subscription
                # ratio does not exceed max_over_subscription_ratio. The host
                # passes if "adjusted" free virtual capacity is enough to
                # accommodate the volume. Adjusted free virtual capacity is
                # the currently available free capacity (taking into account
                # of reserved space) which we can over-subscribe.
                adjusted_free_virtual = (
                    free * backend_state.max_over_subscription_ratio)
                res = adjusted_free_virtual >= requested_size
                if not res:
                    msg_args = {"available": adjusted_free_virtual,
                                "size": requested_size,
                                "grouping": grouping,
                                "grouping_name": backend_state.backend_id}
                    LOG.warning("Insufficient free virtual space "
                                "(%(available)sGB) to accommodate thin "
                                "provisioned %(size)sGB volume on %(grouping)s"
                                " %(grouping_name)s.", msg_args)
                else:
                    LOG.debug("Space information for volume creation "
                              "on %(grouping)s %(grouping_name)s "
                              "(requested / avail): "
                              "%(requested)s/%(available)s", msg_args)
                return res
        elif thin and backend_state.thin_provisioning_support:
            LOG.warning("Filtering out %(grouping)s %(grouping_name)s "
                        "with an invalid maximum over subscription ratio "
                        "of %(oversub_ratio).2f. The ratio should be a "
                        "minimum of 1.0.",
                        {"oversub_ratio":
                            backend_state.max_over_subscription_ratio,
                         "grouping": grouping,
                         "grouping_name": backend_state.backend_id})
            return False

        if free < requested_size:
            LOG.warning("Insufficient free space for volume creation "
                        "on %(grouping)s %(grouping_name)s (requested / "
                        "avail): %(requested)s/%(available)s",
                        msg_args)
            return False

        LOG.debug("Space information for volume creation "
                  "on %(grouping)s %(grouping_name)s (requested / avail): "
                  "%(requested)s/%(available)s", msg_args)

        return True
