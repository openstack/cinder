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
team in a weekly meeting or on the ``#openstack-cinder`` IRC
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

CI Job rechecks
---------------

CI job runs may result in false negatives for a considerable number of causes:

- Network failures.
- Not enough resources on the job runner.
- Storage timeouts caused by the array running nightly maintenance jobs.
- External service failure: pypi, package repositories, etc.
- Non cinder components spurious bugs.

And the list goes on and on.

When we detect one of these cases the normal procedure is to run a recheck
writing a comment with ``recheck`` for core Zuul jobs, or the specific third
party CI recheck command, for example ``run-DellEMC PowerStore CI``.

These false negative have periods of time where they spike, for example when
there are spurious failures, and a lot of rechecks are necessary until a valid
result is posted by the CI job.  And it's in these periods of time where people
acquire the tendency to blindly issue rechecks without looking at the errors
reported by the jobs.

When these blind checks happen on real patch failures or with external services
that are going to be out for a while, they lead to wasted resources as well as
longer result times for patches in other projects.

The Cinder community has noticed this tendency and wants to fix it, so now it
is strongly encouraged to avoid issuing naked rechecks and instead issue them
with additional information to indicate that we have looked at the failure and
confirmed it is unrelated to the patch.

Here are some real examples of proper rechecks:

- Spurious issue in other component: ``recheck tempest-integrated-storage :
  intermittent failure nova bug #1836754``

- Deployment issue on the job: ``recheck cinder-plugin-ceph-tempest timed out,
  errors all over the place``

- External service failure: ``Third party recheck grenade : Failed to retrieve
  .deb packages``

Another common case for blindly rechecking a patch is when it is only changing
a specific driver but there are failures on jobs that don't use that driver.
In such cases we still have to look at the failures, because they can be
failures that are going to take a while to fix, and issuing a recheck will be
futile at that time and we should wait for a couple of hours, or maybe even a
day, before issuing a recheck that can yield the desired result.

Efficient Review Guidelines
---------------------------

This section will guide you through the best practices you can follow to do
quality code reviews:

* **Failing Gate**: You can check for jobs like pep8, py36, py38, functional
  etc that are generic to all the patches and look for possible failures in
  linting, unit test, functional test etc and provide feedback on fixing it.
  Usually it's the author's responsibility to do a local run of tox and ensure
  they don't fail upstream but if something is failing on gate and the author
  is not be aware about how to fix it then we can provide valuable guidance on
  it. There are also jobs specific to particular area of code (for example,
  ``cinder-plugin-ceph-tempest`` for the RBD volume driver,
  ``devstack-plugin-nfs-tempest-full`` for the generic NFS driver etc) so look
  for issues in the jobs if they are related to the code changes proposed.
  There is a past example on why we should check these jobs, the
  ``devstack-plugin-nfs-tempest-full`` is a non-voting job and was failing on
  one of the FS drivers related `patch`_ which got merged and started failing
  the ``NetApp CI`` blocking the netapp features during that time.

* **Documentation**: Check whether the patch proposed requires documentation
  or not and ensure the proper documentation is added. If the proper
  documentation is added then the next step is to check the status of docs job
  if it's failing or passing. If it passes, you can check how it looks in HTML
  as follows:
  Go to ``openstack-tox-docs job`` link -> ``View Log`` -> ``docs`` and go to
  the appropriate section for which the documentation is added.
  Rendering: We do have a job for checking failures related to document
  changes proposed (openstack-tox-docs) but we need to be aware that even if
  a document change passes all the syntactical rules, it still might not be
  logically correct i.e. after rendering it could be possible that the bullet
  points are not under the desired section or the spacing and indentation is
  not as desired. It is always good to check the final document after rendering
  in the docs job which might yield possible logical errors.

* **Readability**: In a large codebase (like Cinder), Readability is a big
  factor as remembering the logic of every code path is not feasible and
  contributors change from time to time. We should adapt to writing readable
  code which is easy to follow and can be understood by anyone having
  knowledge about Python constructs and working of Cinder. Sometimes it
  happens that a logic can only be written in a complex way, in that case,
  it's always good practice to add a comment describing the functionality.
  So, if a logic proposed is not readable, do ask/suggest a more readable
  version of it and if that's not feasible then asking for a comment that
  would explain it is also a valid review point.

* **Type Annotations**: There has been an ongoing effort to implement type
  annotations all across Cinder with the help of mypy tooling. Certain areas
  of code already adapt to mypy coding style and it's good practice that new
  code merging into Cinder should also adapt to it. We, as reviewers, should
  ensure that new code proposed should include mypy constructs.

* **Microversions**: Cinder uses the microversion framework for implementing
  new feature that causes a change in the API behavior (request/response)
  while maintaining backward compatibility at the same time. There have been
  examples in the past where a patch adding a new microversion misses file(s)
  where the microversion changes are necessary so it's a good practice for the
  author and reviewer to ensure that all files associated with a microversion
  change should be updated. You can find the list of files and changes
  required in our `Microversion Doc`_.

* **Downvoting reason**: It often happens that the reviewer adds a bunch of
  comments some of which they would like to be addressed (blocking) and some
  of them are good to have but not a hard requirement (non-blocking). It's a
  good practice for the reviewer to mention for which comments is the -1 valid
  so to make sure they are always addressed.

* **Testing**: Always check if the patch adds the associated unit, functional
  and tempest tests depending on the change.

* **Commit Message**: There are few things that we should make sure the commit
  message includes:

  1) Make sure the author clearly explains in the commit message why the
  code changes are necessary and how exactly the code changes fix the
  issue.

  2) It should have the appropriate tags (Eg: Closes-Bug, Related-Bug,
  Blueprint, Depends-On etc). For detailed information refer to
  `external references in commit message`_.

  3) It should follow the guidelines of commit message length i.e.
  50 characters for the summary line and 72 characters for the description.
  More information can be found at `Summary of Git commit message structure`_.

  4) Sometimes it happens that the author updates the code but forgets to
  update the commit message leaving the commit describing the old changes.
  Verify that the commit message is updated as per code changes.

* **Release Notes**: There are different cases where a releasenote is required
  like fixing a bug, adding a feature, changing areas affecting upgrade etc.
  You can refer to the `Release notes`_ section in our contributor docs for
  more information.

* **Ways of reviewing**: There are various ways you can go about reviewing a
  patch, following are some of the standard ways you can follow to provide
  valuable feedback on the patch:

  1) Testing it in local environment: The easiest way to check the correctness
  of a code change proposed is to reproduce the issue (steps should be in
  launchpad bug) and try the same steps after applying the patch to your
  environment and see if the provided code changes fix the issue.
  You can also go a little further to think of possible corner cases where an
  end user might possibly face issues again and provide the same feedback to
  cover those cases in the original change proposed.

  2) Optimization: If you're not aware about the code path the patch is fixing,
  you can still go ahead and provide valuable feedback about the python code
  if that can be optimized to improve maintainability or performance.

  3) Perform Dry Run: Sometimes the code changes are on code paths that we
  don't have or can't create environment for (like vendor driver changes or
  optional service changes like cinder-backup) so we can read through the code
  or use some example values to perform a dry run of the code and see if it
  fails in that scenario.

.. _Review guidelines: https://docs.openstack.org/doc-contrib-guide/docs-review-guidelines.html
.. _Gerrit: https://review.opendev.org/#/q/project:openstack/cinder+status:open
.. _Quick Reference: https://docs.openstack.org/infra/manual/developers.html#quick-reference
.. _Getting Started: https://docs.openstack.org/infra/manual/developers.html#getting-started
.. _Development Workflow: https://docs.openstack.org/infra/manual/developers.html#development-workflow
.. _patch: https://review.opendev.org/c/openstack/cinder/+/761152
.. _Microversion Doc: https://opendev.org/openstack/cinder/src/branch/master/doc/source/contributor/api_microversion_dev.rst#other-necessary-changes
.. _external references in commit message: https://wiki.openstack.org/wiki/GitCommitMessages#Including_external_references
.. _Summary of Git commit message structure: https://wiki.openstack.org/wiki/GitCommitMessages#Summary_of_Git_commit_message_structure
.. _Release notes: https://docs.openstack.org/cinder/latest/contributor/releasenotes.html
