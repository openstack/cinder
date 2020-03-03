.. _reviewing-cinder:

Code Reviews
============

Cinder follows the same `Review guidelines`_ outlined by the OpenStack
community. This page provides additional information that is helpful for
reviewers of patches to Cinder.

Gerrit
------

Cinder uses the `Gerrit`_ tool to review proposed code changes. The review
site is https://review.opendev.org

Gerrit is a complete replacement for Github pull requests. `All Github pull
requests to the Cinder repository will be ignored`.

See `Quick Reference`_ for information on quick reference for developers.
See `Getting Started`_ for information on how to get started using Gerrit.
See `Development Workflow`_ for more detailed information on how to work with
Gerrit.

The Great Change
----------------

With the demise of Python 2.7 in January 2020, beginning with the Ussuri
development cycle, Cinder only needs to support Python 3 runtimes (in
particular, 3.6 and 3.7).  Thus we can begin to incorporate Python 3
language features and remove Python 2 compatibility code.  At the same
time, however, we are still supporting stable branches that must support
Python 2.  Our biggest interaction with the stable branches is backporting
bugfixes, where in the ideal case, we're just doing a simple cherry-pick of
a commit from master to the stable branches.  You can see that there's some
tension here.

With that in mind, here are some guidelines for reviewers and developers
that the Cinder community has agreed on during this phase where we want to
write pure Python 3 but still must support Python 2 code.

.. _transition-guidelines:

Python 2 to Python 3 transition guidelines
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* We need to be checking the code coverage of test cases very carefully so
  that new code has excellent coverage.  The idea is that we want these
  tests to fail when a backport is proposed to a stable branch and the
  tests are run under Python 2 (if the code is using any Python-3-only
  language features).
* New features can use Python-3-only language constructs, but bugfixes
  likely to be backported should be more conservative and write for
  Python 2 compatibilty.
* The code for drivers may continue to use the six compatibility library at
  their discretion.
* We will not remove six from mainline Cinder code that impacts the drivers
  (for example, classes they inherit from).
* We can remove six from code that doesn't impact drivers, keeping in mind
  that backports may be more problematic, and hence making sure that we have
  really good test coverage.

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
.. _Gerrit: https://review.opendev.org/#/q/project:openstack/cinder+status:open
.. _Quick Reference: https://docs.openstack.org/infra/manual/developers.html#quick-reference
.. _Getting Started: https://docs.openstack.org/infra/manual/developers.html#getting-started
.. _Development Workflow: https://docs.openstack.org/infra/manual/developers.html#development-workflow
