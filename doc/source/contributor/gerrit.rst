Code Reviews
============

Cinder follows the same `Review guidelines`_ outlined by the OpenStack
community. This page provides additional information that is helpful for
reviewers of patches to Cinder.

Gerrit
------

Cinder uses the `Gerrit`_ tool to review proposed code changes. The review
site is https://review.openstack.org

Gerrit is a complete replacement for Github pull requests. `All Github pull
requests to the Cinder repository will be ignored`.

See `Quick Reference`_ for information on quick reference for developers.
See `Getting Started`_ for information on how to get started using Gerrit.
See `Development Workflow`_ for more detailed information on how to work with
Gerrit.

Targeting Milestones
--------------------

In an effort to guide team review priorities the Cinder team has
adopted the process of adding comments to reviews to target a
milestone for a particular patch.  This process is not required
for all patches but is beneficial for patches that may be time sensitive.
For example patches that need to land earlier in the release cycle so as to
get additional test time or because later development activities are dependent
upon that functionality merging.

To target a patch to a milestone a reviewer should add a comment using the
following format:

  ``target-<release>-<milestone>``

Release should be used to indicate the release to which the patch should be
targeted, all lower case.  The milestone is a single number, 1 to 3,
indicating the milestone number. So, to target a patch to land in
Milestone 2 of the Rocky release a comment like the following
would be added:

  ``target-rocky-2``

Adding this tag allows reviewers to search for these tags and use them as a
guide in review priorities.

Targeting patches should be done by Cinder Core Review Team members.
If a patch developer feels that a patch should be targeted to a
milestone the developer should bring the request up to the Cinder
team in a weekly meeting or on the #openstack-cinder Freenode IRC
channel.

Reviewing Vendor Patches
------------------------

It is important to consider, when reviewing patches to a vendor's Cinder
driver, whether the patch passes the vendor's CI process.  CI reports
are the only tool we have to ensure that a patch works with the Vendor's
driver.  A patch to a vendor's driver that does not pass that
vendor's CI should not be merged.  If a patch is submitted by a person
that does not work with the vendor that owns the driver, a +1 review
from someone at that vendor is also required.  Finally, a patch should
not be merged before the Vendor's CI has run against the patch.

.. note::

    Patches which have passed vendor CI and have merged in master
    are exempt from this requirement upon backport to stable and/or
    driverfixes branches as vendors are not required to run CI on those
    branches.  If the vendor, however, is running CI on stable and/or
    driverfix branches failures should not be ignored unless otherwise
    verified by a developer from the vendor.

Unit Tests
----------

Cinder requires unit tests with all patches that introduce a new
branch or function in the code.  Changes that do not come with a
unit test change should be considered closely and usually returned
to the submitter with a request for the addition of unit test.

.. note::

   Unit test changes are not validated in any way by vendor's CI.
   Vendor CI's run the tempest volume tests against a change which
   does not include a unit test execution.

.. _Review guidelines: https://docs.openstack.org/doc-contrib-guide/docs-review-guidelines.html
.. _Gerrit: https://review.openstack.org/#/q/project:openstack/cinder+status:open
.. _Quick Reference: https://docs.openstack.org/infra/manual/developers.html#quick-reference
.. _Getting Started: https://docs.openstack.org/infra/manual/developers.html#getting-started
.. _Development Workflow: https://docs.openstack.org/infra/manual/developers.html#development-workflow
