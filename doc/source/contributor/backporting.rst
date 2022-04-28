=================
Backporting a Fix
=================

  **tl;dr:** Only propose a cherry pick from a *merged* commit, even if you
  want to backport the patch to multiple stable branches.  Doing them all at
  once doesn't speed anything up, because the cinder-stable-maint team will
  **not** approve a backport to branch *n*-1 until the patch has been merged
  into branch *n*.

From time to time, you may find a bug that's been fixed in master, and you'd
like to have that fix in the release you're currently using (for example,
Wallaby).  What you want to do is propose a **backport** of the fix.

.. note::
   The Cinder project observes the OpenStack `Stable Branch Policy
   <https://docs.openstack.org/project-team-guide/stable-branches.html>`_.
   Thus, not every change in master is backportable to the stable branches.
   In particular, features are *never* backportable.  A really complicated
   bugfix may not be backportable if what it fixes is low-occurrence and
   there's a high risk that it may cause a regression elsewhere in the
   software.

   How can you tell?  Ask in the ``#openstack-cinder`` channel on IRC
   or during the open discussion part of the weekly Cinder team meeting.

Since we use git for source code version control, backporting is done by
*cherry-picking* a change that has already been merged into one branch into
another branch.  The gerrit web interface makes it really easy to do this.
In fact, maybe *too* easy.  Here are some guidelines:

* Before you cherry-pick a change, make sure it has already **merged**
  to master.  If the change hasn't merged yet, it may require further
  revision, and the commit you've cherry-picked won't be the correct
  commit to backport.

* Backports must be done in *reverse chronological order*.  Since
  OpenStack releases are named alphabetically, this means reverse
  alphabetical order: ``stable/yoga``, ``stable/xena``, ``stable/wallaby``,
  etc.

* The cherry-pick must have **merged** into the closest most recent branch
  before it will be considered for a branch, that is, a cherry-pick to
  ``stable/xena`` will **not** be considered until it has merged into
  ``stable/yoga`` first.

  * This is because sometimes a backport requires revision along the
    way.  For example, different OpenStack releases support different
    versions of Python.  So if a fix uses a language feature introduced
    in Python 3.8, it will merge just fine into current master (during zed
    development), but it will not pass unit tests in ``stable/yoga``
    (which supports Python 3.6).  Likewise, if you already cherry-picked
    the patch from master directly to ``stable/xena``, it won't pass tests
    there either (because xena also supports Python 3.6).

    So it's better to follow the policy and wait until the patch is merged
    into ``stable/yoga`` *before* you propose a backport to ``stable/xena``.

* You can propose backports directly from git instead of using the gerrit
  web interface, but if you do, you must include the fact that it's a
  cherry-pick in the commit message.  Gerrit does this automatically for
  you *if you cherry-pick from a merged commit* (which is the only kind of
  commit you should cherry-pick from in Gerrit); git will do it for you if
  you use the ``-x`` flag when you do a manual cherry-pick.

  This will keep the history of this backport intact as it goes from
  branch to branch.  We want this information to be in the commit message
  and to be accurate, because if the fix causes a regression (which is
  always possible), it will be helpful to the poor sucker who has to fix
  it to know where this code came from without digging through a bunch of
  git history.

If you have questions about any of this, or if you have a bug to fix that
is only present in one of the stable branches, ask for advice in
``#openstack-cinder`` on IRC.

Backport CI Testing
-------------------

Like all code changes, backports should undergo continuous integration
testing.  This is done automatically by Zuul for changes that affect the
main cinder code.

  When a vendor driver patch backport is proposed, we would like to
  see a clear statement on the gerrit review that the patch has been
  tested in an appropriate environment.

This shouldn't be a big deal because presumably you've done local
testing with your backend to ensure that the code works as expected in a
stable branch; we're simply asking that this be documented on the backport.

A good example of how to document this can be found on
`https://review.opendev.org/c/openstack/cinder/+/821893/
<https://review.opendev.org/c/openstack/cinder/+/821893/3#message-ade9aa6ad8bd99fefab908c777fe106e907c7636>`_.
