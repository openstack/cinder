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
removed from the Cinder code repository per the standard OpenStack
deprecation policy.

Current Cinder Drivers
~~~~~~~~~~~~~~~~~~~~~~

The Cinder team maintains a page of the current drivers and what exactly
they support in the :ref:`Driver Support Matrix <driver_support_matrix>`.

You may find more details about the current drivers on the
:doc:`Available Drivers <drivers>` page.

Additionally, the configuration reference for each driver provides
even more information.  See :doc:`Volume drivers
<configuration/block-storage/volume-drivers>`.
