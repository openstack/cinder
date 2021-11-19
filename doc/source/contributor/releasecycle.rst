===================
Release Cycle Tasks
===================

This document describes the relative ordering and rough timeline for
all of the steps related to tasks that need to be completed during a
release cycle for Cinder.

Before PTG (after closing previous release)
===========================================

#. Collect topics and prepare notes for PTG discussions in an etherpad.
   The PTGbot will generate a list of etherpads at some point that will
   be named according to the convention::

     https://etherpad.openstack.org/p/<release-name>-ptg-cinder

   (You can use a different name, but following the convention makes it
   easy to locate the etherpad for any project for any release.  Something
   we've done in the past is to do the planning on an etherpad named::

     https://etherpad.openstack.org/p/<release-name>-ptg-cinder-planning

   and then move the topics over to the "real" etherpad when the team has
   decided on what to include and the ordering.  Do whatever works for
   you.  Just make sure the team knows where the planning etherpad is and
   give everyone plenty of reminders to add topics.

#. Add any Cinder-specific schedule information to the release calendar
   as soon as it's available.  Example patch:
   https://review.opendev.org/c/openstack/releases/+/754484

   * We used to wait to do this until after proposed deadlines were discussed
     at the PTG, but recently people have been getting antsy about what the
     deadlines are as soon as the stable branch for the previous release is cut
     (which is roughly a month before the PTG).  So you may want to go ahead
     and post the patch early and announce the dates at a Cinder meeting so
     that people can point out conflicts.  Or do it the old-fashioned way
     and work it out at the PTG.  Either way, the point is to make sure you
     don't forget to add Cinder-specific dates to the main release schedule.

#. Review the :ref:`cinder-groups`.

Between Summit and Milestone-1
==============================

#. Review output from the PTG and set Review-Priority on any high
   priority items identified from those discussions. Send out recap to
   the mailing list.

#. Focus on spec reviews to get them approved and updated early in
   the cycle to allow enough time for implementation.

#. Review new driver submissions and give early feedback so there isn't
   a rush at the new driver deadline. Check for status of third party CI
   and any missing steps they need to know about.

#. Review community-wide goals and decide a plan or response to
   them.

Milestone-1
===========

#. Propose library releases for os-brick or python-cinderclient if there
   are merged commits ready to be released. Watch for any releases
   proposed by the release team.

#. Check progress on new drivers and specs and warn contributors if
   it looks like they are at risk for making it in this cycle.

Between Milestone-1 and Milestone-2
===================================

#. cinderlib is a "trailing" deliverable type on a "cycle-with-intermediary"
   release model.  That means that its release for the *previous* cycle hasn't
   happened yet.  The release must happen no later than 3 months after the
   main release, which will put it roughly one week before Milestone-2 (check
   the current release schedule for the exact deadline).  Example patch:
   https://review.opendev.org/c/openstack/releases/+/742503

#. Review stable backports and release status.

#. The Cinder Spec Freeze usually occurs sometime within this window.
   After all the approved specs have merged, propose a patch that adds
   a directory for the next release.  (You may have to wait until the release
   name has been determined by the TC.)  Example patch:
   https://review.opendev.org/c/openstack/cinder-specs/+/778436

#. Watch for and respond to updates to new driver patches.

Milestone-2
===========

#. Propose library releases for os-brick or python-cinderclient if there
   are merged commits ready to be released. Watch for any releases
   proposed by the release team.

Between Milestone-2 and Milestone-3
===================================

#. Review stable backports and release status.

#. Set Review-Priority for any os-brick changes that are needed for
   feature work to make sure they are ready by the library freeze prior
   to Milestone-3.

#. Make sure any new feature work that needs client changes are proposed
   and on track to land before the client library freeze at Milestone-3. Ensure
   microversion bumps are reflected in cinderclient/api_versions.py
   MAX_VERSION.

#. The week before Milestone-3, propose releases for unreleased changes
   in os-brick. (The release team may have already proposed an auto-
   generated patch 1-2 weeks earlier; make sure you -1 it if there are
   still changes that need to land in os-brick before release.)  Include
   branch request for stable/$series creation.  Example patch:
   https://review.opendev.org/c/openstack/releases/+/804670

Milestone-3
===========

#. Propose releases for unreleased changes in python-cinderclient and
   python-brick-cinderclient-ext. These will be the official cycle
   releases for these deliverables.  Watch for a release patch proposed
   by the release team; it may need to be updated to include all the
   appropriate changes. Include branch request for stable/$series creation.
   Example patches:
   | https://review.opendev.org/c/openstack/releases/+/806583
   | https://review.opendev.org/c/openstack/releases/+/807167

#. Set Review-Priority -1 for any feature work not complete in time for
   inclusion in this cycle. Remind contributors that FFE will need to be
   requested to still allow it in this cycle.

#. Complete the responses to community-wide goals if not already done.

#. Add cycle-highlights in the releases deliverable file.  The deadline for
   this has been moved up (since wallaby) to the Friday of M-3 week.  (There
   should be an entry on the cycle release schedule, and a reminder email with
   subject "[PTLs][release] xxx Cycle Highlights" to the ML.)

   The Foundation people use the info to start preparing press releases for the
   cycle coordinated release, so it's good to have key features mentioned.  (If
   something has an FFE and you're not sure if it will land, you can always
   update the cycle-highlights later and shoot an email to whoever sent out the
   reminder so they know to look for it.)

   Example patch:
   https://review.opendev.org/c/openstack/releases/+/807398

Between Milestone-3 and RC1
===========================

#. Make sure the maximum microversion is up-to-date in the version history
   file ``cinder/api/openstack/rest_api_version_history.rst``

   * Any patch that bumped the microversion should have already
     included an entry in this file; you need to add "(Maximum in
     <release-name>)" to the last (highest) entry.
   * This file is pulled into the api-ref by the documentation build
     process.

#. Prepare "prelude" release notes as
   summaries of the content of the release so that those are merged
   before their first release candidate.

#. Check the "Driver Removal History" section (bottom) of
   ``doc/source/reference/support-matrix.rst`` to make sure any drivers
   removed during the cycle are mentioned there.

#. Check the upgrade check tool ``cmd/status.py`` to make sure the
   removed drivers list is up to date.

RC1 week
========

#. Propose RC1 release for cinder or watch for proposal from the release team.
   Include ``stable/$series`` branching request with the release.

#. Update any cycle-highlights for the release cycle if there was something
   you weren't sure about at M-3.

#. Remind contributors that ``master`` is now the next cycle but focus should
   be on wrapping up the current cycle.

#. Watch for translation and new stable branch patches and merge them quickly.

Between RC1 and Final
=====================

#. The release team has started adding a 'release-notes' field to the
   deliverables' yaml files.  You can watch for the patch and vote on it if you
   see it.  Example patch:
   https://review.opendev.org/c/openstack/releases/+/810236

#. Related to the previous point: at this time in the cycle, the release
   notes for all the cinder cycle deliverables (cinder, os-brick,
   python-cinderclient, and python-brick-cinderclient-ext) should
   have been published automatically at
   https://docs.openstack.org/releasenotes/.  Sometimes the promotion job
   fails, though, so it's good to check that the release notes for the
   current cycle are actually there.

#. Propose additional RC releases as needed.

   .. note::

     Try to avoid creating more than 3 release candidates so we are not
     creating candidates that consumers are then trained to ignore. Each
     release candidate should be kept for at least 1 day, so if there is a
     proposal to create RCx but clearly a reason to create another one,
     delay RCX to include the additional patches.

#. Watch for translation patches and merge them quickly.

#. Make sure final RC request is done one week before the final release date.

#. | Watch for the final release proposal from the release team to review and
     +1 so team approval is included in the metadata that goes onto the signed
     tag.
     Example patch: https://review.opendev.org/c/openstack/releases/+/785754
   | Here's what it looks like when people forget to check for this patch:
     https://review.opendev.org/c/openstack/releases/+/812251

Final Release
=============

#. Start planning for next release cycle.

#. Check for bugfixes that would be good to backport to older stable branches.

#. Propose any bugfix releases for things that did not make the freeze for
   final library or service releases.

Post-Final Release
==================

#. Make sure at least three SQLAlchemy-Migrate migrations are reserved
   for potential backports.  Example patch:
   https://review.opendev.org/c/openstack/cinder/+/649436

#. Unblock any new driver submission patches that missed the previous
   release cycle's deadline.

#. Review approved cinder-specs that were merged to the previous cycle
   folder that did not get implemented. Revert or move those specs to the
   next cycles's folder.

#. The oldest active stable branch (that is, the oldest one you can still
   release from) will go to Extended Maintenance mode shortly after the
   coordinated release.  Watch for an email notification from the release
   team about the projected date, which you can also find in the "Next
   Phase" column for that release series on https://releases.openstack.org

   * Prioritize any open reviews that should get into the final stable
     release from this branch for all relevant cinder deliverables and
     motivate the cinder-stable-maint cores to review them.

   * Propose a final release for any deliverable that needs one.  Example
     patch: https://review.opendev.org/c/openstack/releases/+/761929

   * The release team will probably propose a placeholder patch to tag
     the stable branch for each deliverable as <release>-em (or if they
     haven't gotten around to it yet, you can propose it yourself).
     Verify that the hash is at the current HEAD for each deliverable
     (it may have changed if some last-minute stuff was merged).
     Example patch: https://review.opendev.org/c/openstack/releases/+/762372

   * After the "transition to EM" patch has merged, update the zuul jobs
     for the cinder-tempest-plugin.  We always have 3 jobs for the active
     stable branches plus jobs for master.  Add a new job for the most
     recent release and remove the job for the stable branch that just
     went to EM.  Example patch:
     https://review.opendev.org/c/openstack/cinder-tempest-plugin/+/756330
