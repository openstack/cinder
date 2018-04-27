Cinder Thin provisioning and Oversubscription
==============================================

Background
~~~~~~~~~~
After the support on Cinder for Thin provisioning, driver maintainers have
been struggling to understand what is the expected behavior of their drivers
and what exactly each value reported means. This document summarizes the
concepts, definitions and terminology from all specs related to the subject
and should be used as reference for new drivers implementing support for thin
provisioning.


Core concepts and terminology
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
In order to maintain the same behavior among all drivers, we first need to
define some concepts used throughout drivers. This terminology is discussed
and defined in this spec[1] and should be used as reference in further
implementations.

Stats to be reported
~~~~~~~~~~~~~~~~~~~~
The following fields should be reported by drivers supporting thin
provisioning on the get_volume_stats() function:

Mandatory Fields
----------------
.. code-block:: ini

   thin_provisioning_support = True (or False)

Optional Fields
---------------
.. code-block:: ini

   thick_provisioning_support = True (or False)
   provisioned_capacity_gb = PROVISIONED_CAPACITY
   max_over_subscription_ratio = MAX_RATIO

.. note::

   If provisioned_capacity_gb is not reported, the value used in the scheduler
   calculations and filtering is allocated_capacity_gb.

.. note::

   If max_over_subscription_ratio is not reported, the scheduler will use the
   value defined on the [DEFAULT] section. This falls back to the default
   value (20.0) if not set by the user.

[1] https://specs.openstack.org/openstack/cinder-specs/specs/queens/provisioning-improvements.html
