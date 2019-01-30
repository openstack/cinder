==========================
CINDER - Driver Fixes Only
==========================

This is a driverfixes branch of the OpenStack Cinder repo.

**This branch is for driver fixes only!!!**

This should not be treated like a normal stable branch. Changes allowed here
are only for fixes to drivers so that vendors and downstream consumers don't
need to maintain their own forked repos in multiple places to get driver fixes
to their users.

There is no expectation that the code in this repo is in a runnable state.
Tempest tests are not run against patches to this repo, only very basic unit
tests.

It might be best to think of this as a convenient file share for driver vendors
to keep their driver fixes - nothing more.
