.. _cinder-groups:

=====================================
Cinder Groups in Gerrit and Launchpad
=====================================

Cinder-related groups in Launchpad
==================================

.. list-table::
   :header-rows: 1

   * - group
     - what
     - who
     - where
   * - "Cinder" team
     - not sure, exactly
     - an "open" team, anyone with a Launchpad account can join
     - https://launchpad.net/~cinder
   * - "Cinder Bug Team" team
     - can triage (change status fields) on bugs
     - an "open" team, people self-nominate
     - https://launchpad.net/~cinder-bugs
   * - "Cinder Drivers" team
     - Maintains the Launchpad space for Cinder, os-brick, cinderlib,
       python-cinderclient, and cinder-tempest-plugin
     - Anyone who is interested in doing some work, has a Launchpad
       account, and is approved by the current members
     - https://launchpad.net/~cinder-drivers
   * - "Cinder Core security contacts" team
     - can see and work on private security bugs while they are under embargo
     - subset of cinder-core (the OpenStack Vulnerablity Management Team
       likes to keep this team small), so even though the PTL can add people,
       you should propose them on the mailing list first
     - https://launchpad.net/~cinder-coresec

Cinder-related groups in Gerrit
===============================

The Cinder project has total control over the membership of these groups.

.. list-table::
   :header-rows: 1

   * - group
     - what
     - who
     - where
   * - cinder-core
     - +2 powers in Cinder project code repositories
     - cinder core reviewers
     - https://review.opendev.org/#/admin/groups/83,members
   * - cinder-specs-core
     - +2 powers in cinder-specs repository
     - cinder-core plus other appropriate people
     - https://review.opendev.org/#/admin/groups/344,members
   * - cinder-tempest-plugin-core
     - +2 powers on the cinder-tempest-plugin repository
     - cinder-core plus other appropriate people
     - https://review.opendev.org/#/admin/groups/2088,members
   * - rbd-iscsi-client-core
     - +2 powers on the rbd-iscsi-client repository
     - cinder-core (plus others if appropriate; currently only cinder-core)
     - https://review.opendev.org/admin/groups/b25813f5baef62b9449371c91f7dbacbcf7bc6d6,members

The Cinder project shares control over the membership of these groups.  If you
want to add someone to one of these groups who doesn't already have membership
by being in an included group, be sure to include the other groups or
individual members in your proposal email.

.. list-table::
   :header-rows: 1

   * - group
     - what
     - who
     - where
   * - cinder-stable-maint
     - +2 powers on backports to stable branches
     - subset of cinder-core (selected in consultation with stable-maint-core)
       plus the stable-maint-core team
     - https://review.opendev.org/#/admin/groups/534,members
   * - devstack-plugin-ceph-core
     - +2 powers on the code repo for the Ceph devstack plugin
     - cinder-core, devstack-core, manila-core, qa-release, other appropriate
       people
     - https://review.opendev.org/#/admin/groups/1196,members
   * - devstack-plugin-nfs-core
     - +2 powers on the code repo for the NFS devstack plugin
     - cinder-core, devstack-core, other appropriate people
     - https://review.opendev.org/#/admin/groups/1330,members
   * - devstack-plugin-open-cas-core
     - +2 powers on the code repo for the Open CAS devstack plugin
     - cinder-core, devstack-core, other appropriate people
     - https://review.opendev.org/#/admin/groups/2082,members

NOTE: The following groups exist, but I don't think they are used for anything
anymore.

.. list-table::
   :header-rows: 1

   * - group
     - where
   * - cinder-ci
     - https://review.opendev.org/#/admin/groups/508,members
   * - cinder-milestone
     - https://review.opendev.org/#/admin/groups/82,members
   * - cinder-release
     - https://review.opendev.org/#/admin/groups/144,members
   * - cinder-release-branch
     - https://review.opendev.org/#/admin/groups/1507,members

How Gerrit groups are connected to project repositories
-------------------------------------------------------

The connection between the groups defined in gerrit and what they
can do is defined in the project-config repository:
https://opendev.org/openstack/project-config

* ``gerrit/projects.yaml`` sets the config file for a project
* ``gerrit/acls/openstack`` contains the config files

The Special Relationship with OpenStack Command Line Client and SDK
-------------------------------------------------------------------

The OpenStack Command Line Client (aka OSC) and the OpenStack SDK provide
unified interfaces across most of the OpenStack APIs.  To facilitate this,
they make use of two kinds of core teams:

- "service cores": people very familiar with the particular API that's
  being given an interface in the OSC or SDK.  For example, cinder cores
  can be service cores for implementations in OSC or SDK that provide
  an interface to the Block Storage API.
- additionally, the OSC and SDK projects have their own core teams whose
  members have a broader vision over the OSC and SDK, and therefore can
  enforce consistency across all the service code.  This way, end users
  will be provided with a consistent and predictable interface to
  OpenStack as a whole.

The cinder-core gerrit group acts as "service cores" for the OSC and SDK.
This means that the cinder-core members have +2 powers on OSC or SDK reviews
but do not have permission to approve patches.  The connection between
cinder-core and the python-openstackclient and openstacksdk code repositories
is made directly in their ACL files in the ``project-config`` repository:

- ``gerrit/acls/openstack/openstacksdk.config``
- ``gerrit/acls/openstack/python-openstackclient.config``
