===================
Release Cycle Tasks
===================

This document describes the relative ordering and rough timeline for
all of the steps related to tasks that need to be completed during a
release cycle for Cinder.

Before PTG (after closing previous release)
===========================================

#. Collect topics and prepare notes for PTG discussions in an etherpad.
   Add a link to the etherpad to the list of PTG etherpads (for example:
   https://wiki.openstack.org/wiki/PTG/Train/Etherpads)


Between Summit and Milestone-1
==============================

#. Review output from the PTG and set Review-Priority on any high
   priority items identified from those discussions. Send out recap to
   the mailing list.

#. Add any Cinder-specific schedule information to the release calendar
   (https://review.openstack.org/#/c/509019/)

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

#. Review stable backports and release status.

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
   in os-brick. Include branch request for stable/$series creation.

Milestone-3
===========

#. Propose releases for unreleased changes in python-cinderclient and
   python-brick-cinderclient-ext. Watch for releases proposed by the
   release team. Include branch request for stable/$series creation.

#. Set Review-Priority -1 for any feature work not complete in time for
   inclusion in this cycle. Remind contributors that FFE will need to be
   requested to still allow it in this cycle.

#. Prepare "prelude" release notes as
   summaries of the content of the release so that those are merged
   before their first release candidate.

#. Complete the responses to community-wide goals if not already done.

#. Start assembling cycle-highlights for the team.

Between Milestone-3 and RC1
===========================

#. Add cycle-highlights in the releases deliverable file.

RC1 week
========

#. Propose RC1 release for cinder or watch for proposal from the release team.
   Include stable/$series branching request with the release.

#. Finalize any cycle-highlights for the release cycle.

#. Remind contributors that ``master`` is now the next cycle but focus should
   be on wrapping up the current cycle.

#. Watch for translation and new stable branch patches and merge them quickly.

Between RC1 and Final
=====================

#. Propose additional RC releases as needed.

   .. note::

     Try to avoid creating more than 3 release candidates so we are not
     creating candidates that consumers are then trained to ignore. Each
     release candidate should be kept for at least 1 day, so if there is a
     proposal to create RCx but clearly a reason to create another one,
     delay RCX to include the additional patches.

#. Watch for translation patches and merge them quickly.

#. Make sure final RC request is done one week before the final release date.

#. Watch for the final release proposal from the release team to review and +1
   so team approval is included in the metadata that goes onto the signed tag.

Final Release
=============

#. Start planning for next release cycle.

#. Check for bugfixes that would be good to backport to older stable branches.

#. Propose any bugfix releases for things that did not make the freeze for
   final library or service releases.

Post-Final Release
==================

#. Make sure at least three SQLAlchemy-Migrate migrations are reserved
   for potential backports (https://review.openstack.org/#/c/649436/).

#. Unblock any new driver submission patches that missed the previous
   release cycle's deadline.

#. Review approved cinder-specs that were merged to the previous cycle
   folder that did not get implemented. Revert or move those specs to the
   next cycles's folder.
