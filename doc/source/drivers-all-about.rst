========================
All About Cinder Drivers
========================

.. toctree::
   :hidden:

   reference/support-matrix
   drivers


General Considerations
~~~~~~~~~~~~~~~~~~~~~~

Cinder allows you to integrate various storage solutions into your
OpenStack cloud.  It does this by providing a stable interface for
hardware providers to write *drivers* that allow you to take advantage
of the various features that their solutions offer.

"Supported" drivers
-------------------

In order to make it easier for you to assess the stability and quality
of a particular vendor's driver, The Cinder team has introduced the concept
of a **supported** driver.  These are drivers that:

* have an identifiable *driver maintainer*
* are included in the Cinder source code repository
* use the upstream Cinder bug tracking mechanism
* support the Cinder :ref:`required_driver_functions`
* maintain a third-party Continuous Integration system that runs the
  OpenStack Tempest test suite against their storage devices

  * this must be done for every Cinder commit, and the results must be
    reported to the OpenStack Gerrit code review interface
  * for details, see `Driver Testing <https://wiki.openstack.org/wiki/Cinder/tested-3rdParty-drivers>`_

In summary, there are two important aspects to a driver being considered
as **supported**:

* the code meets the Cinder driver specifications (so you know it
  should integrate properly with Cinder)
* the driver code is continually tested against changes to Cinder (so
  you know that the code actually does integrate properly with Cinder)

The second point is particularly important because changes to Cinder
can impact the drivers in two ways:

* A Cinder change may introduce a bug that only affects a particular
  driver or drivers (this could be because many drivers implement
  functionality well beyond the Required Driver Functions).  With a
  properly running and reporting third-party CI system, such a bug can
  be detected at the code review stage.

* A Cinder change may exercise a new code path that exposes a driver
  bug that had previously gone undetected.  A properly running third-party
  CI system will detect this and alert the driver maintainer that there
  is a problem.

Driver Compliance
-----------------

The current policy for CI compliance is:

* CIs must report on every patch, whether the code change is in their own
  driver code or not

* The CI comments must be properly formatted to show up in the CI summary in
  Gerrit

Non-compliant drivers will be tagged as unsupported if:

* No CI success reporting occurs within a two week span
* The CI is found to not be testing the expected driver (CI runs using the
  default LVM driver, etc.)
* Other issues are found but failed to be addressed in a timely manner

CI results are reviewed on a regular basis and if found non-compliant, a
driver patch is submitted flagging it as 'unsupported'.  This can occur
at any time during the development cycle.  A driver can be returned to
'supported' status as soon as the CI problem is corrected.

We do a final compliance check around the third milestone of each release.
If a driver is marked as 'unsupported', vendors have until the time of
the first Release Candidate tag (two weeks after the third milestone)
to become compliant, in which case the patch flagging the driver as
'unsupported' can be reverted.  Otherwise, the driver will be considered
'unsupported' in the release.

The CI results are currently posted here:
http://cinderstats.ivehearditbothways.com/cireport.txt

"Unsupported" drivers
---------------------

A driver is marked as 'unsupported' when it is out of compliance.

Such a driver will log a warning message to be logged in the cinder-volume
log stating that it is unsupported and deprecated for removal.

In order to use an unsupported driver, an operator must set the configuration
option ``enable_unsupported_driver=True`` in the driver's configuration
section of ``cinder.conf`` or the Cinder service will fail to load.

If the issue is not corrected before the next release, the driver will be
eligible for removal from the Cinder code repository per the standard
OpenStack deprecation policy.

Driver Removal
--------------
**(Added January 2020**)

As stated above, an unsupported driver is eligible for removal during the
development cycle following the release in which it was marked 'unsupported'.
(For example, a driver marked 'unsupported' in the Ussuri release is eligible
for removal during the development cycle leading up to the Victoria release.)

During the Ussuri development cycle, the Cinder team decided that drivers
eligible for removal, at the discretion of the team, may remain in the code
repository *as long as they continue to pass OpenStack CI testing*. When such a
driver blocks the CI check or gate, it will be removed immediately.  (This does
not violate the OpenStack deprecation policy because such a driver's
deprecation period began when it was marked as 'unsupported'.)

.. note::
   Why the "at the discretion of the team" qualification?  Some vendors may
   announce that they have no intention of continuing to support a driver.
   In that case, the Cinder team reserves the right to remove the driver as
   soon as the deprecation period has passed.

Thus, unsupported drivers *may* remain in the code repository for multiple
releases following their declaration as 'unsupported'.  Operators should
therefore take into account the length of time a driver has been marked
'unsupported' when deciding to deploy an unsupported driver.  This is because
as an unmaintained driver ages, updates and bugfixes to libraries and other
software it depends on may cause the driver to fail unit and functional tests,
making it subject to immediate removal.

The intent of this policy revision is twofold.  First, it gives vendors a
longer grace period in which to make the necessary changes to have their
drivers reinstated as 'supported'.  Second, keeping these drivers in-tree
longer should make life easier for operators who have deployed storage backends
with drivers that have been marked as 'unsupported'.  Operators should keep the
above points in mind, however, when deploying such a driver.

Current Cinder Drivers
~~~~~~~~~~~~~~~~~~~~~~

The Cinder team maintains a page of the current drivers and what exactly
they support in the :ref:`Driver Support Matrix <driver_support_matrix>`.

You may find more details about the current drivers on the
:doc:`Available Drivers <drivers>` page.

Additionally, the configuration reference for each driver provides
even more information.  See :doc:`Volume drivers
<configuration/block-storage/volume-drivers>`.
