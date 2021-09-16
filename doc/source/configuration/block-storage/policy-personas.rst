===============================
Policy Personas and Permissions
===============================

Beginning with the Xena release, the Block Storage service API v3 takes
advantage of the default authentication and authorization apparatus supplied
by the Keystone project to give operators a rich set of default policies to
control how users interact with the Block Storage service API.

This document describes Cinder's part in an effort across OpenStack
services to provide a consistent and useful default RBAC configuration.
(This effort is referred to as "secure RBAC" for short.)

Vocabulary Note
---------------

We need to clarify some terms we'll be using below.

Project
    This is a grouping of users into a unit that can own cloud resources.
    (This is what used to be called a "tenant", but you should never call
    it that.)  Users, projects, and their associations are created in Keystone.

Service
    This is an OpenStack component that users interact with through an API it
    provides.  For example, "Cinder" is the OpenStack code name for the service
    that provides the Block Storage API version 3.  Cinder is also known
    as the OpenStack Block Storage service.

The point of making this distinction is that there's another use of the term
'project' that is relevant to the discussion, but that we're **not** going to
use.  Each OpenStack service is produced and maintained by a "project team".
*We will not be using the term 'project' in that sense in this document.  We'll
always use the term 'service'.* (If you are new to OpenStack, this won't be a
problem.  But if you're discussing this content with someone who's been around
OpenStack for a while, you'll want to be clear about this so that you're not
talking past each other.)

.. _cinder-personas:

The Cinder Personas
-------------------

This is easiest to explain if we introduce the five "personas" Cinder
recognizes.  In the list below, a "system" refers to the deployed system (that
is, Cinder and all its services), and a "project" refers to a container or
namespace for resources.

* In order to consume resources, a user must be assigned to a project by
  being given a role (for example, 'member') in that project.  That's done
  in Keystone; it's not a Cinder concern.

  See `Default Roles
  <https://docs.openstack.org/keystone/latest/admin/service-api-protection.html>`_
  in the Keystone documentation for more information.

.. list-table:: The Five Personas
   :header-rows: 1

   * - who
     - what
   * - project-reader
     - Has access to the API for read-only requests that affect only
       project-specific resources (that is, cannot create, update, or
       delete resources within a project)
   * - project-member
     - A normal user in a project.
   * - project-admin
     - All the normal stuff plus some minor administrative abilities
       in a particular project, for example, able to set the default
       volume type for a project.  (The administrative abilities are
       "minor" in the sense that they have no impact on the Cinder system,
       they only allow the project-admin to make system-safe changes
       isolated to that project.)
   * - system-reader
     - Has read only access to the API; like the project-reader, but
       can read any project recognized by cinder.
   * - system-admin
     - Has the highest level of authorization on the system and can
       perform any action in Cinder.  In most deployments, only the
       operator, deployer, or other highly trusted person will be
       assigned this persona.  This is a Cinder super-user who can do
       *everything*, both with respect to the Cinder system and all
       individual projects.

.. note::
   The Keystone project provides the ability to describe additional personas,
   but Cinder does not currently recognize them.  In particular:

   * Cinder does not recognize the ``domain`` scope at all.  So even if you
     successfully request a "domain-scoped" token from the Identity service,
     you won't be able to use it with Cinder.  Instead, request a
     "project-scoped" token for the particular project in your domain
     that you want to act upon.
   * Cinder does not recognize a "system-member" persona, that is,
     a user with the ``member`` role on a ``system``.  The default Cinder
     policy configuration treats such a user as identical to the
     *system-reader* persona described above.

   More information about roles and scope is available in the `Keystone
   Administrator Guides
   <https://docs.openstack.org/keystone/latest/admin/service-api-protection.html>`__.

.. note::
   **Privacy Expectations**

   Cinder's model of resources (volumes, backups, snapshots, etc.) is that they
   are owned by the *project*.  Thus, they are shared by all users who have a
   role assignment on that project, no matter what persona that user has been
   assigned.

   For example, if Alice and Bob are in Project P, and Alice has persona
   project-member while Bob has persona project-reader, if Alice creates volume
   V in Project P, Bob can see volume V in the volume-list response, and Bob
   can read all the volume metadata on volume V that Alice can read--even
   volume metadata that Alice may have added to the volume.  The key point here
   is that even though Alice created volume V, *it's not her volume*.  The
   volume is "owned" by Project P and is available to all users who have
   authorization on that project via role assignments in keystone.  What a user
   can do with volume V depends on whether that user has an admin, member, or
   reader role in project P.

   With respect to Project P, the personas with system scope (system-admin and
   system-reader) have access to the project in the sense that a cinder
   system-admin can do anything in Project P that the project-admin can do plus
   some additional powers.  A cinder system-reader has read-only access to
   everything in Project P that the system-admin can access.

   The above describe the default policy configuration for Cinder.  It is
   possible to modify policies to obtain different behavior, but that is beyond
   the scope of this document.

.. _cinder-s-rbac-schedule:

Implementation Schedule
-----------------------

For reasons that will become clear in this section, the secure RBAC effort
is being implemented in Cinder in two phases.  In Xena, there are three
personas.

.. list-table:: The 3 Xena Personas
   :header-rows: 1

   * - who
     - Keystone technical info
   * - project-reader
     - ``reader`` role on a ``project``, resulting in project-scope
   * - project-member
     - ``member`` role on a ``project``, resulting in project-scope
   * - system-admin
     - ``admin`` role on a ``project``, but recognized by Cinder
       as having permission to act on the cinder *system*

Note that you *cannot* create a project-admin persona on your own
simply by assigning the ``admin`` role to a user.  Such assignment
results in that user becoming a system-admin.

In the Yoga release, we plan to implement the full set of Cinder
personas:

.. list-table:: The 5 Yoga Personas
   :header-rows: 1

   * - who
     - Keystone technical info
   * - project-reader
     - ``reader`` role on a ``project``, resulting in project-scope
   * - project-member
     - ``member`` role on a ``project``, resulting in project-scope
   * - project-admin
     - ``admin`` role on a ``project``, resulting in project-scope
   * - system-reader
     - ``reader`` role on a ``system``, resulting in system-scope
   * - system-admin
     - ``admin`` role on a ``system``, resulting in system-scope

Note that although the underlying technical information changes for
the system-admin, the range of actions performable by that persona
does not change.

.. _cinder-permissions-matrix:

Cinder Permissions Matrix
-------------------------

Now that you know who the personas are, here's what they can do with respect
to the policies that are recognized by Cinder.  Keep in mind that only three
of the personas (project-reader, project-member, and system-admin) are
implemented in the Xena release.

NOTE: the columns in () will be deleted; they are here for comparison as the
matrix is validated by human beings.

.. list-table:: Attachments (Microversion 3.27)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - Create attachment
     - ``POST /attachments``
     - volume:attachment_create
     - empty
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Update attachment
     - ``PUT  /attachments/{attachment_id}``
     - volume:attachment_update
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Delete attachment
     - ``DELETE  /attachments/{attachment_id}``
     - volume:attachment_delete
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Mark a volume attachment process as completed (in-use)
     - | Microversion 3.44
       | ``POST  /attachments/{attachment_id}/action`` (os-complete)
     - volume:attachment_complete
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Allow multiattach of bootable volumes
     - | This is a secondary check on
       | ``POST  /attachments``
       | which is governed by another policy
     - volume:multiattach_bootable_volume
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes

.. list-table:: User Messages (Microversion 3.3)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - List messages
     - ``GET  /messages``
     - message:get_all
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Show message
     - ``GET  /messages/{message_id}``
     - message:get
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Delete message
     - ``DELETE  /messages/{message_id}``
     - message:delete
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes

.. list-table:: Clusters (Microversion 3.7)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - List clusters
     - | ``GET  /clusters``
       | ``GET  /clusters/detail``
     - clusters:get_all
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Show cluster
     - ``GET  /clusters/{cluster_id}``
     - clusters:get
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Update cluster
     - ``PUT  /clusters/{cluster_id}``
     - clusters:update
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes

.. list-table:: Workers (Microversion 3.24)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - Clean up workers
     - ``POST  /workers/cleanup``
     - workers:cleanup
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes

.. list-table:: Snapshots
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - List snapshots
     - | ``GET  /snapshots``
       | ``GET  /snapshots/detail``
     - volume:get_all_snapshots
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - List or show snapshots with extended attributes
     - | ``GET  /snapshots/{snapshot_id}``
       | ``GET  /snapshots/detail``
     - volume_extension:extended_snapshot_attributes
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Create snapshot
     - ``POST  /snapshots``
     - volume:create_snapshot
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Show snapshot
     - ``GET  /snapshots/{snapshot_id}``
     - volume:get_snapshot
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Update snapshot
     - ``PUT  /snapshots/{snapshot_id}``
     - volume:update_snapshot
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Delete snapshot
     - ``DELETE  /snapshots/{snapshot_id}``
     - volume:delete_snapshot
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Reset status of a snapshot.
     - ``POST  /snapshots/{snapshot_id}/action`` (os-reset_status)
     - volume_extension:snapshot_admin_actions:reset_status
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Update status (and optionally progress) of snapshot
     - ``POST  /snapshots/{snapshot_id}/action`` (os-update_snapshot_status)
     - snapshot_extension:snapshot_actions:update_snapshot_status
     - empty
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Force delete a snapshot
     - ``POST  /snapshots/{snapshot_id}/action`` (os-force_delete)
     - volume_extension:snapshot_admin_actions:force_delete
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - List (in detail) of snapshots which are available to manage
     - | ``GET  /manageable_snapshots``
       | ``GET  /manageable_snapshots/detail``
     - snapshot_extension:list_manageable
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Manage an existing snapshot
     - ``POST  /manageable_snapshots``
     - snapshot_extension:snapshot_manage
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Unmanage a snapshot
     - ``POST  /snapshots/{snapshot_id}/action`` (os-unmanage)
     - snapshot_extension:snapshot_unmanage
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes

.. list-table:: Snapshot Metadata
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - Show snapshot's metadata or one specified metadata with a given key
     - | ``GET  /snapshots/{snapshot_id}/metadata``
       | ``GET  /snapshots/{snapshot_id}/metadata/{key}``
     - volume:get_snapshot_metadata
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Update snapshot's metadata or one specified metadata with a given key
     - | ``PUT  /snapshots/{snapshot_id}/metadata``
       | ``PUT  /snapshots/{snapshot_id}/metadata/{key}``
     - volume:update_snapshot_metadata
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Delete snapshot's specified metadata with a given key
     - ``DELETE  /snapshots/{snapshot_id}/metadata/{key}``
     - volume:delete_snapshot_metadata
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes

..
   Backups: most of these are enforced in cinder/backup/api.py

.. list-table:: Backups
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - List backups
     - | ``GET  /backups``
       | ``GET  /backups/detail``
     - backup:get_all
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Include project attributes in the list backups, show backup responses
     - | Microversion 3.18
       | Adds ``os-backup-project-attr:project_id`` to the following responses:
       | ``GET  /backups/detail``
       | ``GET  /backups/{backup_id}``
       | The ability to make these API calls is governed by other policies.
     - backup:backup_project_attribute
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Create backup
     - ``POST  /backups``
     - backup:create
     - empty
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Show backup
     - ``GET  /backups/{backup_id}``
     - backup:get
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Update backup
     - | Microversion 3.9
       | ``PUT  /backups/{backup_id}``
     - backup:update
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Delete backup
     - ``DELETE  /backups/{backup_id}``
     - backup:delete
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Restore backup
     - ``POST  /backups/{backup_id}/restore``
     - backup:restore
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Import backup
     -  ``POST  /backups/{backup_id}/import_record``
     - backup:backup-import
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Export backup
     - ``POST  /backups/{backup_id}/export_record``
     - backup:export-import
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Reset status of a backup
     - ``POST  /backups/{backup_id}/action`` (os-reset_status)
     - volume_extension:backup_admin_actions:reset_status
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Force delete a backup
     - ``POST  /backups/{backup_id}/action`` (os-force_delete)
     - volume_extension:backup_admin_actions:force_delete
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes

.. list-table:: Groups (Microversion 3.13)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - List groups
     - | ``GET  /groups``
       | ``GET  /groups/detail``
     - group:get_all
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Create group, create group from src
     - | ``POST  /groups``
       | Microversion 3.14:
       | ``POST  /groups/action`` (create-from-src)
     - group:create
     - empty
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Show group
     - ``GET  /groups/{group_id}``
     - group:get
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Update group
     - ``PUT  /groups/{group_id}``
     - group:update
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Include project attributes in the list groups, show group responses
     - | Microversion 3.58
       | Adds ``project_id`` to the following responses:
       | ``GET  /groups/detail``
       | ``GET  /groups/{group_id}``
       | The ability to make these API calls is governed by other policies.
     - group:group_project_attribute
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes

.. list-table:: Group Types (Microversion 3.11)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - | **DEPRECATED**
       | Create, update or delete a group type
     - | (NOTE: new policies split POST, PUT, DELETE)
       | ``POST /group_types/``
       | ``PUT /group_types/{group_type_id}``
       | ``DELETE /group_types/{group_type_id}``
     - group:group_types_manage
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - | **NEW**
       | Create a group type
     - ``POST /group_types/``
     - group:group_types:create
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - n/a
     - n/a
   * - | **NEW**
       | Update a group type
     - ``PUT /group_types/{group_type_id}``
     - group:group_types:update
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - n/a
     - n/a
   * - | **NEW**
       | Delete a group type
     - ``DELETE /group_types/{group_type_id}``
     - group:group_types:delete
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - n/a
     - n/a
   * - Show group type with type specs attributes
     - | Adds ``group_specs`` to the following responses:
       | ``GET  /group_types``
       | ``GET  /group_types/default``
       | ``GET  /group_types/{group_type_id}``
       | These calls are not governed by a policy.
     - group:access_group_types_specs
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - | **DEPRECATED**
       | Create, show, update and delete group type spec
     - | (NOTE: new policies split GET, POST, PUT, DELETE)
       | ``GET /group_types/{group_type_id}/group_specs``
       | ``GET /group_types/{group_type_id}/group_specs/{g_spec_id}``
       | ``POST /group_types/{group_type_id}/group_specs``
       | ``PUT /group_types/{group_type_id}/group_specs/{g_spec_id}``
       | ``DELETE  /group_types/{group_type_id}/group_specs/{g_spec_id}``
     - group:group_types_specs
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - | **NEW**
       | Create group type spec
     - ``POST /group_types/{group_type_id}/group_specs``
     - group:group_types_specs:create
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - n/a
     - n/a
   * - | **NEW**
       | List group type specs
     - ``GET /group_types/{group_type_id}/group_specs``
     - group:group_types_specs:get_all
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - n/a
     - n/a
   * - | **NEW**
       | Show detail for a group type spec
     - ``GET /group_types/{group_type_id}/group_specs/{g_spec_id}``
     - group:group_types_specs:get
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - n/a
     - n/a
   * - | **NEW**
       | Update group type spec
     - ``PUT /group_types/{group_type_id}/group_specs/{g_spec_id}``
     - group:group_types_specs:update
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - n/a
     - n/a
   * - | **NEW**
       | Delete group type spec
     - ``DELETE /group_types/{group_type_id}/group_specs/{g_spec_id}``
     - group:group_types_specs:delete
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - n/a
     - n/a

.. list-table:: Group Snapshots (Microversion 3.14)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - List group snapshots
     - | ``GET  /group_snapshots``
       | ``GET  /group_snapshots/detail``
     - group:get_all_group_snapshots
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Create group snapshot
     - ``POST  /group_snapshots``
     - group:create_group_snapshot
     - empty
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Show group snapshot
     - ``GET  /group_snapshots/{group_snapshot_id}``
     - group:get_group_snapshot
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Delete group snapshot
     - ``DELETE  /group_snapshots/{group_snapshot_id}``
     - group:delete_group_snapshot
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Update group snapshot
     - | ``PUT  /group_snapshots/{group_snapshot_id}``
       | Note: even though the policy is defined, this call is not implemented
         in the Block Storage API.
     - group:update_group_snapshot
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Reset status of group snapshot
     - | Microversion 3.19
       | ``POST  /group_snapshots/{group_snapshot_id}/action`` (reset_status)
     - group:reset_group_snapshot_status
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Include project attributes in the list group snapshots, show group
       snapshot responses
     - | Microversion 3.58
       | Adds ``project_id`` to the following responses:
       | ``GET  /group_snapshots/detail``
       | ``GET  /group_snapshots/{group_snapshot_id}``
       | The ability to make these API calls is governed by other policies.
     - group:group_snapshot_project_attribute
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes

.. list-table:: Group Actions
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - Delete group
     - ``POST  /groups/{group_id}/action`` (delete)
     - group:delete
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Reset status of group
     - | Microversion 3.20
       | ``POST  /groups/{group_id}/action`` (reset_status)
     - group:reset_status
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Enable replication
     - | Microversion 3.38
       | ``POST  /groups/{group_id}/action`` (enable_replication)
     - group:enable_replication
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Disable replication
     - | Microversion 3.38
       | ``POST  /groups/{group_id}/action`` (disable_replication)
     - group:disable_replication
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Fail over replication
     - | Microversion 3.38
       | ``POST  /groups/{group_id}/action`` (failover_replication)
     - group:failover_replication
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - List failover replication
     - | Microversion 3.38
       | ``POST  /groups/{group_id}/action`` (list_replication_targets)
     - group:list_replication_targets
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes

.. list-table:: QOS specs
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - List qos specs or list all associations
     - | ``GET  /qos-specs``
       | ``GET  /qos-specs/{qos_id}/associations``
     - volume_extension:qos_specs_manage:get_all
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Show qos specs
     - ``GET  /qos-specs/{qos_id}``
     - volume_extension:qos_specs_manage:get
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Create qos specs
     - ``POST  /qos-specs``
     - volume_extension:qos_specs_manage:create
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Update qos specs: update key/values in the qos-spec or update
       the volume-types associated with the qos-spec
     - | ``PUT  /qos-specs/{qos_id}``
       | ``GET  /qos-specs/{qos_id}/associate?vol_type_id={volume_id}``
       | ``GET  /qos-specs/{qos_id}/disassociate?vol_type_id={volume_id}``
       | ``GET  /qos-specs/{qos_id}/disassociate_all``
       | (yes, these GETs are really updates)
     - volume_extension:qos_specs_manage:update
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Delete a qos-spec, or remove a list of keys from the qos-spec
     - | ``DELETE  /qos-specs/{qos_id}``
       | ``PUT  /qos-specs/{qos_id}/delete_keys``
     - volume_extension:qos_specs_manage:delete
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes

.. list-table:: Quotas
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - | **DEPRECATED**
       | Show or update project quota class
     - | (NOTE: new policies split GET and PUT)
       | ``GET  /os-quota-class-sets/{project_id}``
       | ``PUT  /os-quota-class-sets/{project_id}``
     - volume_extension:quota_classes
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - | **NEW**
       | Show project quota class
     - ``GET  /os-quota-class-sets/{project_id}``
     - volume_extension:quota_classes:get
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - n/a
     - n/a
   * - | **NEW**
       | Update project quota class
     - ``PUT  /os-quota-class-sets/{project_id}``
     - volume_extension:quota_classes:update
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - n/a
     - n/a
   * - Show project quota (including usage and default)
     - | ``GET  /os-quota-sets/{project_id}``
       | ``GET  /os-quota-sets/{project_id}/default``
       | ``GET  /os-quota-sets/{project_id}?usage=True``
     - volume_extension:quotas:show
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Update project quota
     - ``PUT  /os-quota-sets/{project_id}``
     - volume_extension:quotas:update
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Delete project quota
     - ``DELETE  /os-quota-sets/{project_id}``
     - volume_extension:quotas:delete
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes

.. list-table:: Capabilities
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - Show backend capabilities
     - ``GET  /capabilities/{host_name}``
     - volume_extension:capabilities
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes

.. list-table:: Services
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - List all services
     - ``GET  /os-services``
     - volume_extension:services:index
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Update service
     - | ``PUT  /os-services/enable``
       | ``PUT  /os-services/disable``
       | ``PUT  /os-services/disable-log-reason``
       | ``PUT  /os-services/freeze``
       | ``PUT  /os-services/thaw``
       | ``PUT  /os-services/failover_host``
       | ``PUT  /os-services/failover`` (microversion 3.26)
       | ``PUT  /os-services/set-log``
       | ``PUT  /os-services/get-log``
     - volume_extension:services:update
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Freeze a backend host.  Secondary check; must also satisfy
       volume_extension:services:update to make this call.
     - ``PUT  /os-services/freeze``
     - volume:freeze_host
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Thaw a backend host.  Secondary check; must also satisfy
       volume_extension:services:update to make this call.
     - ``PUT  /os-services/thaw``
     - volume:thaw_host
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Failover a backend host.  Secondary check; must also satisfy
       volume_extension:services:update to make this call.
     - | ``PUT  /os-services/failover_host``
       | ``PUT  /os-services/failover`` (microversion 3.26)
     - volume:failover_host
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - List all backend pools
     - ``GET  /scheduler-stats/get_pools``
     - scheduler_extension:scheduler_stats:get_pools
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - | List, update or show hosts for a project
       | (NOTE: will be deprecated in Yoga and new policies introduced
       | for GETs and PUT)
     - | ``GET  /os-hosts``
       | ``PUT  /os-hosts/{host_name}``
       | ``GET  /os-hosts/{host_id}``
     - volume_extension:hosts
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Show limits with used limit attributes
     - ``GET  /limits``
     - limits_extension:used_limits
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - List (in detail) of volumes which are available to manage
     - | ``GET  /manageable_volumes``
       | ``GET  /manageable_volumes/detail``
     - volume_extension:list_manageable
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Manage existing volumes
     - ``POST  /manageable_volumes``
     - volume_extension:volume_manage
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Unmanage a volume
     - ``POST  /volumes/{volume_id}/action`` (os-unmanage)
     - volume_extension:volume_unmanage
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes

.. list-table:: Volume Types
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - | **DEPRECATED**
       | Create, update and delete volume type
       | (new policies for create/update/delete)
     - | ``POST  /types``
       | ``PUT  /types/{type_id}``
       | ``DELETE  /types``
     - volume_extension:types_manage
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - | **NEW**
       | Create a volume type
     - ``POST  /types``
     - volume_extension:type_create
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - | **NEW**
       | Update a volume type
     - ``PUT  /types/{type_id}``
     - volume_extension:type_update
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - | **NEW**
       | Delete a volume type
     - ``DELETE  /types/{type_id}``
     - volume_extension:type_delete
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Show a specific volume type
     - ``GET  /types/{type_id}``
     - volume_extension:type_get
     - empty
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - List volume types
     - ``GET  /types``
     - volume_extension:type_get_all
     - empty
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - | **DEPRECATED**
       | Base policy for all volume type encryption type operations
       | (NOTE: can't use this anymore, because it gives GET and POST same
         permissions)
     - Convenience default policy for the situation where you don't want
       to configure all the ``volume_type_encryption`` policies separately
     - volume_extension:volume_type_encryption
     - rule:admin_api
     -
     -
     -
     -
     -
     - no
     - yes
   * - Create volume type encryption
     - ``POST  /types/{type_id}/encryption``
     - volume_extension:volume_type_encryption:create
     - rule:volume_extension:volume_type_encryption
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Show a volume type's encryption type, show an encryption specs item
     - | ``GET  /types/{type_id}/encryption``
       | ``GET  /types/{type_id}/encryption/{key}``
     - volume_extension:volume_type_encryption:get
     - rule:volume_extension:volume_type_encryption
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Update volume type encryption
     - ``PUT  /types/{type_id}/encryption/{encryption_id}``
     - volume_extension:volume_type_encryption:update
     - rule:volume_extension:volume_type_encryption
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Delete volume type encryption
     - ``DELETE  /types/{type_id}/encryption/{encryption_id}``
     - volume_extension:volume_type_encryption:delete
     - rule:volume_extension:volume_type_encryption
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - List or show volume type with extra specs attribute
     - | Adds ``extra_specs`` to the following responses:
       | ``GET  /types/{type_id}``
       | ``GET  /types``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:access_types_extra_specs
     - empty
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - List or show volume type with access type qos specs id attribute
     - | Adds ``qos_specs_id`` to the following responses:
       | ``GET  /types/{type_id}``
       | ``GET  /types``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:access_types_qos_specs_id
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Show whether a volume type is public in the type response
     - | Adds ``os-volume-type-access:is_public`` to the following responses:
       | ``GET  /types``
       | ``GET  /types/{type_id}``
       | ``POST  /types``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:volume_type_access
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - no
     - yes
   * - | **NEW**
       | List private volume type access detail, that is, list the projects
         that have access to this type
       | (was formerly controlled by volume_extension:volume_type_access)
     - ``GET  /types/{type_id}/os-volume-type-access``
     - volume_extension:volume_type_access:get_all_for_type
     - (new policy)
     - no
     - no
     - no
     - no
     - yes
     - n/a
     - n/a
   * - Add volume type access for project
     - ``POST  /types/{type_id}/action`` (addProjectAccess)
     - volume_extension:volume_type_access:addProjectAccess
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Remove volume type access for project
     - ``POST  /types/{type_id}/action`` (removeProjectAccess)
     - volume_extension:volume_type_access:removeProjectAccess
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes

.. list-table:: Volume Actions
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - Extend a volume
     - ``POST  /volumes/{volume_id}/action`` (os-extend)
     - volume:extend
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Extend an attached volume
     - | Microversion 3.42
       | ``POST  /volumes/{volume_id}/action`` (os-extend)
     - volume:extend_attached_volume
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Revert a volume to a snapshot
     - | Microversion 3.40
       | ``POST  /volumes/{volume_id}/action`` (revert)
     - volume:revert_to_snapshot
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Reset status of a volume
     - ``POST  /volumes/{volume_id}/action`` (os-reset_status)
     - volume_extension:volume_admin_actions:reset_status
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Retype a volume
     - ``POST  /volumes/{volume_id}/action`` (os-retype)
     - volume:retype
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Update a volume's readonly flag
     - ``POST  /volumes/{volume_id}/action`` (os-update_readonly_flag)
     -  volume:update_readonly_flag
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Force delete a volume
     - ``POST  /volumes/{volume_id}/action`` (os-force_delete)
     - volume_extension:volume_admin_actions:force_delete
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Upload a volume to image with public visibility
     - ``POST  /volumes/{volume_id}/action`` (os-volume_upload_image)
     - volume_extension:volume_actions:upload_public
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Upload a volume to image
     - ``POST  /volumes/{volume_id}/action`` (os-volume_upload_image)
     - volume_extension:volume_actions:upload_image
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Force detach a volume.
     - ``POST  /volumes/{volume_id}/action`` (os-force_detach)
     - volume_extension:volume_admin_actions:force_detach
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Migrate a volume to a specified host
     - ``POST  /volumes/{volume_id}/action`` (os-migrate_volume)
     - volume_extension:volume_admin_actions:migrate_volume
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Complete a volume migration
     - ``POST  /volumes/{volume_id}/action`` (os-migrate_volume_completion)
     - volume_extension:volume_admin_actions:migrate_volume_completion
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Initialize volume attachment
     - ``POST  /volumes/{volume_id}/action`` (os-initialize_connection)
     - volume_extension:volume_actions:initialize_connection
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Terminate volume attachment
     - ``POST  /volumes/{volume_id}/action`` (os-terminate_connection)
     - volume_extension:volume_actions:terminate_connection
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Roll back volume status to 'in-use'
     - ``POST  /volumes/{volume_id}/action`` (os-roll_detaching)
     - volume_extension:volume_actions:roll_detaching
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Mark volume as reserved
     - ``POST  /volumes/{volume_id}/action`` (os-reserve)
     - volume_extension:volume_actions:reserve
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Unmark volume as reserved
     - ``POST  /volumes/{volume_id}/action`` (os-unreserve)
     - volume_extension:volume_actions:unreserve
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Begin detach volumes
     - ``POST  /volumes/{volume_id}/action`` (os-begin_detaching)
     - volume_extension:volume_actions:begin_detaching
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Add attachment metadata
     - ``POST  /volumes/{volume_id}/action`` (os-attach)
     - volume_extension:volume_actions:attach
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Clear attachment metadata
     - ``POST  /volumes/{volume_id}/action`` (os-detach)
     - volume_extension:volume_actions:detach
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes

.. list-table:: Volume Transfers
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - List volume transfer
     - | ``GET  /os-volume-transfer``
       | ``GET  /os-volume-transfer/detail``
       | ``GET  /volume-transfers``
       | ``GET  /volume-transfers/detail``
     - volume:get_all_transfers
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Create a volume transfer
     - | ``POST  /os-volume-transfer``
       | ``POST  /volume-transfers``
     - volume:create_transfer
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Show one specified volume transfer
     - | ``GET  /os-volume-transfer/{transfer_id}``
       | ``GET  /volume-transfers/{transfer_id}``
     - volume:get_transfer
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Accept a volume transfer
     - | ``POST  /os-volume-transfer/{transfer_id}/accept``
       | ``POST  /volume-transfers/{transfer_id}/accept``
     - volume:accept_transfer
     - empty
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Delete volume transfer
     - | ``DELETE  /os-volume-transfer/{transfer_id}``
       | ``DELETE  /volume-transfers/{transfer_id}``
     - volume:delete_transfer
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes

.. list-table:: Volume Metadata
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - Show volume's metadata or one specified metadata with a given key.
     - | ``GET  /volumes/{volume_id}/metadata``
       | ``GET  /volumes/{volume_id}/metadata/{key}``
       | ``POST /volumes/{volume_id}/action`` (os-show_image_metadata)
     - volume:get_volume_metadata
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Create volume metadata
     - ``POST  /volumes/{volume_id}/metadata``
     - volume:create_volume_metadata
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Update volume's metadata or one specified metadata with a given key
     - | ``PUT  /volumes/{volume_id}/metadata``
       | ``PUT  /volumes/{volume_id}/metadata/{key}``
     - volume:update_volume_metadata
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Delete volume's specified metadata with a given key
     - ``DELETE  /volumes/{volume_id}/metadata/{key}``
     - volume:delete_volume_metadata
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - | **DEPRECATED**
       | Volume's image metadata related operation, create, delete, show and
         list
     - | (NOTE: new policies are introduced below to split GET and POST)
       | Microversion 3.4
       | ``GET  /volumes/detail``
       | ``GET  /volumes/{volume_id}``
       | ``POST  /volumes/{volume_id}/action`` (os-set_image_metadata)
       | ``POST  /volumes/{volume_id}/action`` (os-unset_image_metadata)
       | (NOTE: ``POST /volumes/{volume_id}/action`` (os-show_image_metadata)
         is governed by volume:get_volume_metadata
     - volume_extension:volume_image_metadata
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - | **NEW**
       | Include volume's image metadata in volume detail responses
     - | Microversion 3.4
       | ``GET  /volumes/detail``
       | ``GET  /volumes/{volume_id}``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:volume_image_metadata:show
     - (new policy)
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - | **NEW**
       | Set image metadata for a volume
     - | Microversion 3.4
       | ``POST  /volumes/{volume_id}/action`` (os-set_image_metadata)
     - volume_extension:volume_image_metadata:set
     - (new policy)
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - | **NEW**
       | Remove specific image metadata from a volume
     - | Microversion 3.4
       | ``POST  /volumes/{volume_id}/action`` (os-unset_image_metadata)
     - volume_extension:volume_image_metadata:remove
     - (new policy)
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Update volume admin metadata.
     - | This permission is required to complete the following operations:
       | ``POST  /volumes/{volume_id}/action`` (os-update_readonly_flag)
       | ``POST  /volumes/{volume_id}/action`` (os-attach)
       | The ability to make these API calls is governed by other policies.
     - volume:update_volume_admin_metadata
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes

.. list-table:: Volume Type Extra-Specs
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - List type extra specs
     - ``GET  /types/{type_id}/extra_specs``
     - volume_extension:types_extra_specs:index
     - empty
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Create type extra specs
     - ``POST  /types/{type_id}/extra_specs``
     - volume_extension:types_extra_specs:create
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Show one specified type extra specs
     - ``GET  /types/{type_id}/extra_specs/{extra_spec_key}``
     - volume_extension:types_extra_specs:show
     - empty
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Update type extra specs
     - ``PUT  /types/{type_id}/extra_specs/{extra_spec_key}``
     - volume_extension:types_extra_specs:update
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Delete type extra specs
     - ``DELETE  /types/{type_id}/extra_specs/{extra_spec_key}``
     - volume_extension:types_extra_specs:delete
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Include extra_specs fields that may reveal sensitive information about
       the deployment that should not be exposed to end users in various
       volume-type responses that show extra_specs.
     - | ``GET  /types``
       | ``GET  /types/{type_id}``
       | ``GET  /types/{type_id}/extra_specs``
       | ``GET  /types/{type_id}/extra_specs/{extra_spec_key}``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:types_extra_specs:read_sensitive
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes

.. list-table:: Volumes
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - Create volume
     - ``POST  /volumes``
     - volume:create
     - empty
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Create volume from image
     - ``POST  /volumes``
     - volume:create_from_image
     - empty
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Show volume
     - ``GET  /volumes/{volume_id}``
     - volume:get
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - List volumes or get summary of volumes
     - | ``GET  /volumes``
       | ``GET  /volumes/detail``
       | ``GET  /volumes/summary``
     - volume:get_all
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Update volume or update a volume's bootable status
     - | ``PUT  /volumes``
       | ``POST  /volumes/{volume_id}/action`` (os-set_bootable)
     - volume:update
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Delete volume
     - ``DELETE  /volumes/{volume_id}``
     - volume:delete
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes
   * - Force Delete a volume (Microversion 3.23)
     - ``DELETE  /volumes/{volume_id}?force=true``
     - volume:force_delete
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - List or show volume with host attribute
     - | Adds ``os-vol-host-attr:host`` to the following responses:
       | ``GET  /volumes/{volume_id}``
       | ``GET  /volumes/detail``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:volume_host_attribute
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - List or show volume with "tenant attribute" (actually, the project ID)
     - | Adds ``os-vol-tenant-attr:tenant_id`` to the following responses:
       | ``GET  /volumes/{volume_id}``
       | ``GET  /volumes/detail``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:volume_tenant_attribute
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - List or show volume with migration status attribute
     - | Adds ``os-vol-mig-status-attr:migstat`` to the following responses:
       | ``GET  /volumes/{volume_id}``
       | ``GET  /volumes/detail``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:volume_mig_status_attribute
     - rule:admin_api
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Show volume's encryption metadata
     - | ``GET  /volumes/{volume_id}/encryption``
       | ``GET  /volumes/{volume_id}/encryption/{encryption_key}``
     - volume_extension:volume_encryption_metadata
     - rule:admin_or_owner
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Create multiattach capable volume
     - | Indirectly affects the success of these API calls:
       | ``POST  /volumes``
       | ``POST  /volumes/{volume_id}/action`` (os-retype)
       | The ability to make these API calls is governed by other policies.
     - volume:multiattach
     - rule:admin_or_owner
     - no
     - yes
     - yes
     - no
     - yes
     - yes
     - yes

.. list-table:: Default Volume Types (Microversion 3.62)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - (old rule)
     - project-reader
     - project-member
     - project-admin
     - system-reader
     - system-admin
     - (old "owner")
     - (old "admin")
   * - Set or update default volume type for a project
     - ``PUT  /default-types``
     - volume_extension:default_set_or_update
     - rule:system_or_domain_or_project_admin
     - no
     - no
     - yes
     - no
     - yes
     - no
     - yes
   * - Get default type for a project
     - | ``GET  /default-types/{project-id}``
       | (Note: a project-\* persona can always determine their effective
         default-type by making the ``GET /v3/{project_id}/types/default``
         call, which is governed by the volume_extension:type_get policy.)
     - volume_extension:default_get
     - rule:system_or_domain_or_project_admin
     - no
     - no
     - yes
     - no
     - yes
     - no
     - yes
   * - Get all default types
     - ``GET  /default-types/``
     - volume_extension:default_get_all
     - role:admin and system_scope:all
     - no
     - no
     - no
     - no
     - yes
     - no
     - yes
   * - Unset default type for a project
     - ``DELETE  /default-types/{project-id}``
     - volume_extension:default_unset
     - rule:system_or_domain_or_project_admin
     - no
     - no
     - yes
     - no
     - yes
     - no
     - yes
