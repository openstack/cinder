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

LOG = logging.getLogger(__name__)

INITIAL_AUTO_MOSR = 20
INFINITE_UNKNOWN_VALUES = ('infinite', 'unknown')


def calculate_capacity_factors(total_capacity: float,
                               free_capacity: float,
                               provisioned_capacity: float,
                               thin_provisioning_support: bool,
                               max_over_subscription_ratio: float,
                               reserved_percentage: int,
                               thin: bool) -> dict:
    """Create the various capacity factors of the a particular backend.

    Based off of definition of terms
    cinder-specs/specs/queens/provisioning-improvements.html
    Description of factors calculated where units of gb are Gibibytes.
    reserved_capacity - The amount of space reserved from the total_capacity
    as reported by the backend.
    total_reserved_available_capacity - The total capacity minus reserved
    capacity
    total_available_capacity - The total capacity available to cinder
    calculated from total_reserved_available_capacity (for thick) OR
    for thin total_reserved_available_capacity max_over_subscription_ratio
    calculated_free_capacity - total_available_capacity - provisioned_capacity
    virtual_free_capacity - The calculated free capacity available to cinder
    to allocate new storage.
    For thin: calculated_free_capacity
    For thick: the reported free_capacity can be less than the calculated
    capacity, so we use free_capacity - reserved_capacity.

    free_percent - the percentage of the virtual_free_capacity and
    total_available_capacity is left over
    provisioned_ratio - The ratio of provisioned storage to
    total_available_capacity

    :param total_capacity: The reported total capacity in the backend.
    :type total_capacity: float
    :param free_capacity: The free space/capacity as reported by the backend.
    :type free_capacity: float
    :param provisioned_capacity: as reported by backend or volume manager from
        allocated_capacity_gb
    :type provisioned_capacity: float
    :param thin_provisioning_support: Is thin provisioning supported?
    :type thin_provisioning_support: bool
    :param max_over_subscription_ratio: as reported by the backend
    :type max_over_subscription_ratio: float
    :param reserved_percentage: the % amount to reserve as unavailable. 0-100
    :type reserved_percentage: int, 0-100
    :param thin: calculate based on thin provisioning if enabled by
        thin_provisioning_support
    :type thin: bool
    :return: A dictionary of all of the capacity factors.
    :rtype: dict

    """

    total = float(total_capacity)
    reserved = float(reserved_percentage) / 100
    reserved_capacity = math.floor(total * reserved)
    total_reserved_available = total - reserved_capacity

    if thin and thin_provisioning_support:
        total_available_capacity = (
            total_reserved_available * max_over_subscription_ratio
        )
        calculated_free = total_available_capacity - provisioned_capacity
        virtual_free = calculated_free
        provisioned_type = 'thin'
    else:
        # Calculate how much free space is left after taking into
        # account the reserved space.
        total_available_capacity = total_reserved_available
        calculated_free = total_available_capacity - provisioned_capacity
        virtual_free = calculated_free
        if free_capacity < calculated_free:
            virtual_free = free_capacity

        provisioned_type = 'thick'

    if total_available_capacity:
        provisioned_ratio = provisioned_capacity / total_available_capacity
        free_percent = (virtual_free / total_available_capacity) * 100
    else:
        provisioned_ratio = 0
        free_percent = 0

    def _limit(x):
        """Limit our floating points to 2 decimal places."""
        return round(x, 2)

    return {
        "total_capacity": total,
        "free_capacity": free_capacity,
        "reserved_capacity": reserved_capacity,
        "total_reserved_available_capacity": _limit(total_reserved_available),
        "max_over_subscription_ratio": (
            max_over_subscription_ratio if provisioned_type == 'thin' else None
        ),
        "total_available_capacity": _limit(total_available_capacity),
        "provisioned_capacity": provisioned_capacity,
        "calculated_free_capacity": _limit(calculated_free),
        "virtual_free_capacity": _limit(virtual_free),
        "free_percent": _limit(free_percent),
        "provisioned_ratio": _limit(provisioned_ratio),
        "provisioned_type": provisioned_type
    }


def calculate_virtual_free_capacity(total_capacity: float,
                                    free_capacity: float,
                                    provisioned_capacity: float,
                                    thin_provisioning_support: bool,
                                    max_over_subscription_ratio: float,
                                    reserved_percentage: int,
                                    thin: bool) -> float:
    """Calculate the virtual free capacity based on multiple factors.

    :param total_capacity:  total_capacity_gb of a host_state or pool.
    :param free_capacity:   free_capacity_gb of a host_state or pool.
    :param provisioned_capacity:    provisioned_capacity_gb of a host_state
                                    or pool.
    :param thin_provisioning_support:   thin_provisioning_support of
                                        a host_state or a pool.
    :param max_over_subscription_ratio: max_over_subscription_ratio of
                                        a host_state or a pool
    :param reserved_percentage: reserved_percentage of a host_state or
                                a pool.
    :param thin: whether volume to be provisioned is thin
    :returns: the calculated virtual free capacity.
    """

    factors = calculate_capacity_factors(
        total_capacity,
        free_capacity,
        provisioned_capacity,
        thin_provisioning_support,
        max_over_subscription_ratio,
        reserved_percentage,
        thin
    )
    return factors["virtual_free_capacity"]


def calculate_max_over_subscription_ratio(
        capability: dict,
        global_max_over_subscription_ratio: float) -> float:
    # provisioned_capacity_gb is the apparent total capacity of
    # all the volumes created on a backend, which is greater than
    # or equal to allocated_capacity_gb, which is the apparent
    # total capacity of all the volumes created on a backend
    # in Cinder. Using allocated_capacity_gb as the default of
    # provisioned_capacity_gb if it is not set.
    allocated_capacity_gb = capability.get('allocated_capacity_gb', 0)
    provisioned_capacity_gb = capability.get('provisioned_capacity_gb',
                                             allocated_capacity_gb)
    thin_provisioning_support = capability.get('thin_provisioning_support',
                                               False)
    total_capacity_gb = capability.get('total_capacity_gb', 0)
    free_capacity_gb = capability.get('free_capacity_gb', 0)
    pool_name = capability.get('pool_name',
                               capability.get('volume_backend_name'))

    # If thin provisioning is not supported the capacity filter will not use
    # the value we return, no matter what it is.
    if not thin_provisioning_support:
        LOG.debug("Trying to retrieve max_over_subscription_ratio from a "
                  "service that does not support thin provisioning")
        return 1.0

    # Again, if total or free capacity is infinite or unknown, the capacity
    # filter will not use the max_over_subscription_ratio at all. So, does
    # not matter what we return here.
    if ((total_capacity_gb in INFINITE_UNKNOWN_VALUES) or
            (free_capacity_gb in INFINITE_UNKNOWN_VALUES)):
        return 1.0

    max_over_subscription_ratio = (capability.get(
        'max_over_subscription_ratio') or global_max_over_subscription_ratio)

    # We only calculate the automatic max_over_subscription_ratio (mosr)
    # when the global or driver conf is set auto and while
    # provisioned_capacity_gb is not 0. When auto is set and
    # provisioned_capacity_gb is 0, we use the default value 20.0.
    if max_over_subscription_ratio == 'auto':
        if provisioned_capacity_gb != 0:
            used_capacity = total_capacity_gb - free_capacity_gb
            LOG.debug("Calculating max_over_subscription_ratio for "
                      "pool %s: provisioned_capacity_gb=%s, "
                      "used_capacity=%s",
                      pool_name, provisioned_capacity_gb, used_capacity)
            max_over_subscription_ratio = 1 + (
                float(provisioned_capacity_gb) / (used_capacity + 1))
        else:
            max_over_subscription_ratio = INITIAL_AUTO_MOSR

        LOG.info("Auto max_over_subscription_ratio for pool %s is "
                 "%s", pool_name, max_over_subscription_ratio)
    else:
        max_over_subscription_ratio = float(max_over_subscription_ratio)

    return max_over_subscription_ratio
