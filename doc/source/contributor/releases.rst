Cinder Project Releases
=======================

The Cinder project follows the OpenStack 6 month development cycle, at the
end of which a new stable branch is created from master, and master becomes
the development branch for the next development cycle.

Because many OpenStack consumers don't move as quickly as OpenStack
development, we backport appropriate bugfixes from master into the stable
branches and create new releases for consumers to use ... for a while.
See the `Stable Branches
<https://docs.openstack.org/project-team-guide/stable-branches.html>`_
section of the
`OpenStack Project Team Guide
<https://docs.openstack.org/project-team-guide/index.html>`_
for details about the timelines.

What follows is information about the Cinder project and its releases.

Where Stuff Is
~~~~~~~~~~~~~~

The Cinder Project Deliverables
-------------------------------

https://governance.openstack.org/tc/reference/projects/cinder.html#deliverables

The Code Repositories
---------------------

* https://opendev.org/openstack/cinder
* https://opendev.org/openstack/cinderlib
* https://opendev.org/openstack/os-brick
* https://opendev.org/openstack/python-cinderclient
* https://opendev.org/openstack/python-brick-cinderclient-ext
* https://opendev.org/openstack/rbd-iscsi-client
* https://opendev.org/openstack/cinder-tempest-plugin
* https://opendev.org/openstack/cinder-specs   (no releases)

Review Dashboards for Releases
------------------------------

* Patches for releasable stable branches:
  http://tiny.cc/cinder-releasable-stable
* Patches for nonreleasable stable branches:
  http://tiny.cc/cinder-em-branches
* Cinder project release patches:
  http://tiny.cc/cinder-release-patches

All Cinder Project Releases
---------------------------
https://releases.openstack.org/teams/cinder.html

How Stuff Works
~~~~~~~~~~~~~~~

Releases from Master
--------------------

Releases from **master** for *cinder* follow the 'cycle-with-rc' release model.

* The 'cycle-with-rc' model describes projects that produce a single release
  at the end of the cycle, with one or more release candidates (RC) close to
  the end of the cycle and optional development milestone betas published on
  a per-project need.

Releases from **master** for *os-brick, cinderlib, and the clients* follow
the 'cycle-with-intermediary' release model.

* The 'cycle-with-intermediary' model describes projects that produce multiple
  full releases during the development cycle, with a final release to match
  the end of the cycle.
* os-brick has a deliverable type of 'library'
* python-cinderclient and python-brick-cinderclient-ext have a deliverable
  type of 'client-library'
* cinderlib has a deliverable type of 'trailing'

  * The final cinderlib release for a cycle must occur no later than 3 months
    after the coordinated OpenStack release of cinder.

Releases from **master** for *cinder-tempest-plugin* follow the
'cycle-automatic' scheme.

* No stable branches are created.
* Released automatically at the end of each cycle, or on-demand.

Releases from **master** for *rbd-iscsi-client* follow the 'independent'
scheme.

* No stable branches are created.
* Released on demand whenever necessary because it has to track ceph
  development more than openstack development.

For more information about the release models and deliverable types:
https://releases.openstack.org/reference/release_models.html

Branching
---------

All Cinder project deliverables (except cinder-tempest-plugin and
rbd-iscsi-client) follow the `OpenStack stable branch policy
<https://docs.openstack.org/project-team-guide/stable-branches.html>`_. Briefly,

* The stable branches are intended to be a safe source of fixes for high
  impact bugs and security issues which have been fixed on master since a
  given release.
* Stable branches are cut from the last release of a given deliverable, at
  the end of the common 6-month development cycle.

Only members of the `cinder-stable-maint
<https://review.opendev.org/admin/groups/534,members>`_
gerrit group have +2 powers on patches proposed to stable branches.  This
is a subset of `cinder-core
<https://review.opendev.org/#/admin/groups/83,members>`_
plus the OpenStack-wide `stable-maint-core
<https://review.opendev.org/admin/groups/2267a5998d4224dd0acf1081eb2ee7b11573b7ea,members>`_
team.

While anyone may propose a release, releases must be approved by
the `OpenStack Release Managers
<https://review.opendev.org/admin/groups/5c75219bf2ace95cdea009c82df26ca199e04d59,members>`_.
