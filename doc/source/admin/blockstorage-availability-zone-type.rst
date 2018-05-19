=======================
Availability-zone types
=======================

Background
----------

In a newly deployed region environment, the volume types (SSD, HDD or others)
may only exist on part of the AZs, but end users have no idea which AZ is
allowed for one specific volume type and they can't realize that only when
the volume failed to be scheduled to backend. In this case, we have supported
availability zone volume type in Rocky cycle which administrators can take
advantage of to fix that.

How to config availability zone types?
--------------------------------------

We decided to use type's extra-specs to store this additional info,
administrators can turn it on by updating volume type's key
``RESKEY:availability_zones`` as below::

    "RESKEY:availability_zones": "az1,az2,az3"

It's an array list whose items are separated by comma and stored in string.
Once the availability zone type is configured, any UI component or client
can filter out invalid volume types based on their choice of availability
zone::

    Request example:
    /v3/{project_id}/types?extra_specs={'RESKEY:availability_zones':'az1'}

Remember, Cinder will always try inexact match for this spec value, for
instance, when extra spec ``RESKEY:availability_zones`` is configured
with value ``az1,az2``, both ``az1`` and ``az2`` are valid inputs for query,
also this spec will not be used during performing capability filter, instead
it will be only used for choosing suitable availability zones in these two
cases below.

1. Create volume, within this feature, now we can specify availability zone
via parameter ``availability_zone``, volume source (volume, snapshot, group),
configuration option ``default_availability_zone`` and
``storage_availability_zone``. When creating new volume, Cinder will try to
read the AZ(s) in the priority of::

    source group > parameter availability_zone > source snapshot (or volume) > volume type > configuration default_availability_zone > storage_availability_zone

If there is a conflict between any of them, 400 BadRequest will be raised,
also now a AZ list instead of single AZ will be delivered to
``AvailabilityZoneFilter``.

2. Retype volume, this flow also has been updated, if new type has configured
``RESKEY:availability_zones`` Cinder scheduler will validate this as well.
