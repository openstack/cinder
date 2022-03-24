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

.. note::
   The secure RBAC effort not only spans OpenStack services, it is also
   taking place over several OpenStack development cycles.  Thus it's
   important to make sure that you are looking at the version of this
   document that is applicable to the OpenStack release you have deployed.

   This document applies to the **Yoga** release.

   Additionally, keep in mind that different projects are implementing
   secure RBAC on different schedules.  This document applies *only* to
   Cinder.  To get an idea of the full scope of this effort, consult the
   `Consistent and Secure Default RBAC
   <https://governance.openstack.org/tc/goals/selected/consistent-and-secure-rbac.html>`_
   community goal document.

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

This is easiest to explain if we introduce the three "personas" Cinder
recognizes in the Xena and Yoga releases.
In the list below, a "system" refers to the deployed system (that is,
Cinder and all its services), and a "project" refers to a container or
namespace for resources.

* In order to consume resources, a user must be assigned to a project by
  being given a role (for example, 'member') in that project.  That's done
  in Keystone; it's not a Cinder concern.

  See `Default Roles
  <https://docs.openstack.org/keystone/latest/admin/service-api-protection.html>`_
  in the Keystone documentation for more information.

.. list-table:: The Cinder Personas in Xena and Yoga
   :header-rows: 1

   * - who
     - what
   * - project-reader
     - Has access to the API for read-only requests that affect only
       project-specific resources (that is, cannot create, update, or
       delete resources within a project)
   * - project-member
     - A normal user in a project.
   * - system-admin
     - Has the highest level of authorization on the system and can
       perform any action in Cinder.  In most deployments, only the
       operator, deployer, or other highly trusted person will be
       assigned this persona.  This is a Cinder super-user who can do
       *everything*, both with respect to the Cinder system and all
       individual projects.

       *Note that if you assign the 'admin' role to a user, that user can
       affect the entire Cinder system, not just the project that person
       is a member of.*  Please keep this in mind as you assign roles to
       users in the Identity service.

.. note::
   The Keystone project provides the ability to describe additional personas,
   but Cinder does not recognize them in Yoga.  In particular:

   * Cinder does not recognize the ``domain`` scope at all.  So even if you
     successfully request a "domain-scoped" token from the Identity service,
     you won't be able to use it with Cinder.  Instead, request a
     "project-scoped" token for the particular project in your domain
     that you want to act upon.
   * Cinder does not recognize a "system-member" persona, that is,
     a user with the ``member`` role on a ``system``.  Likewise, cinder
     does not recognize a "system-reader" persona, that is, a user with
     the ``reader`` role on a ``system``.

     Further, while the Cinder "system-admin" persona is implemented in
     Yoga, it is not implemented by using scope.

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
is being implemented in Cinder in two phases.  In Xena and Yoga, there are
three personas.

.. list-table:: The 3 Xena/Yoga Personas
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

In the Zed release, we plan to implement more Cinder personas that the default
policy configuration will recognize.  During the development of this OpenStack
wide effort, however, some complexities were discovered that have affected
exactly what this set of personas and their capabilities will be.  Please
consult the Zed version of this document (or the 'latest' version, if at the
time you are reading this, Zed is still under development) for more
information.

.. _cinder-permissions-matrix:

Cinder Permissions Matrix
-------------------------

Now that you know who the personas are, here's what they can do with respect
to the policies that are recognized by Cinder.

.. list-table:: Attachments (Microversion 3.27)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - Create attachment
     - ``POST /attachments``
     - volume:attachment_create
     - no
     - yes
     - yes
   * - Update attachment
     - ``PUT  /attachments/{attachment_id}``
     - volume:attachment_update
     - no
     - yes
     - yes
   * - Delete attachment
     - ``DELETE  /attachments/{attachment_id}``
     - volume:attachment_delete
     - no
     - yes
     - yes
   * - Mark a volume attachment process as completed (in-use)
     - | Microversion 3.44
       | ``POST  /attachments/{attachment_id}/action`` (os-complete)
     - volume:attachment_complete
     - no
     - yes
     - yes
   * - Allow multiattach of bootable volumes
     - | This is a secondary check on
       | ``POST  /attachments``
       | which is governed by another policy
     - volume:multiattach_bootable_volume
     - no
     - yes
     - yes

.. list-table:: User Messages (Microversion 3.3)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - List messages
     - ``GET  /messages``
     - message:get_all
     - yes
     - yes
     - yes
   * - Show message
     - ``GET  /messages/{message_id}``
     - message:get
     - yes
     - yes
     - yes
   * - Delete message
     - ``DELETE  /messages/{message_id}``
     - message:delete
     - no
     - yes
     - yes

.. list-table:: Clusters (Microversion 3.7)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - List clusters
     - | ``GET  /clusters``
       | ``GET  /clusters/detail``
     - clusters:get_all
     - no
     - no
     - yes
   * - Show cluster
     - ``GET  /clusters/{cluster_id}``
     - clusters:get
     - no
     - no
     - yes
   * - Update cluster
     - ``PUT  /clusters/{cluster_id}``
     - clusters:update
     - no
     - no
     - yes

.. list-table:: Workers (Microversion 3.24)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - Clean up workers
     - ``POST  /workers/cleanup``
     - workers:cleanup
     - no
     - no
     - yes

.. list-table:: Snapshots
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - List snapshots
     - | ``GET  /snapshots``
       | ``GET  /snapshots/detail``
     - volume:get_all_snapshots
     - yes
     - yes
     - yes
   * - List or show snapshots with extended attributes
     - | ``GET  /snapshots/{snapshot_id}``
       | ``GET  /snapshots/detail``
     - volume_extension:extended_snapshot_attributes
     - yes
     - yes
     - yes
   * - Create snapshot
     - ``POST  /snapshots``
     - volume:create_snapshot
     - no
     - yes
     - yes
   * - Show snapshot
     - ``GET  /snapshots/{snapshot_id}``
     - volume:get_snapshot
     - yes
     - yes
     - yes
   * - Update snapshot
     - ``PUT  /snapshots/{snapshot_id}``
     - volume:update_snapshot
     - no
     - yes
     - yes
   * - Delete snapshot
     - ``DELETE  /snapshots/{snapshot_id}``
     - volume:delete_snapshot
     - no
     - yes
     - yes
   * - Reset status of a snapshot.
     - ``POST  /snapshots/{snapshot_id}/action`` (os-reset_status)
     - volume_extension:snapshot_admin_actions:reset_status
     - no
     - no
     - yes
   * - Update status (and optionally progress) of snapshot
     - ``POST  /snapshots/{snapshot_id}/action`` (os-update_snapshot_status)
     - snapshot_extension:snapshot_actions:update_snapshot_status
     - no
     - yes
     - yes
   * - Force delete a snapshot
     - ``POST  /snapshots/{snapshot_id}/action`` (os-force_delete)
     - volume_extension:snapshot_admin_actions:force_delete
     - no
     - no
     - yes
   * - List (in detail) of snapshots which are available to manage
     - | ``GET  /manageable_snapshots``
       | ``GET  /manageable_snapshots/detail``
     - snapshot_extension:list_manageable
     - no
     - no
     - yes
   * - Manage an existing snapshot
     - ``POST  /manageable_snapshots``
     - snapshot_extension:snapshot_manage
     - no
     - no
     - yes
   * - Unmanage a snapshot
     - ``POST  /snapshots/{snapshot_id}/action`` (os-unmanage)
     - snapshot_extension:snapshot_unmanage
     - no
     - no
     - yes

.. list-table:: Snapshot Metadata
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - Show snapshot's metadata or one specified metadata with a given key
     - | ``GET  /snapshots/{snapshot_id}/metadata``
       | ``GET  /snapshots/{snapshot_id}/metadata/{key}``
     - volume:get_snapshot_metadata
     - yes
     - yes
     - yes
   * - Update snapshot's metadata or one specified metadata with a given key
     - | ``PUT  /snapshots/{snapshot_id}/metadata``
       | ``PUT  /snapshots/{snapshot_id}/metadata/{key}``
     - volume:update_snapshot_metadata
     - no
     - yes
     - yes
   * - Delete snapshot's specified metadata with a given key
     - ``DELETE  /snapshots/{snapshot_id}/metadata/{key}``
     - volume:delete_snapshot_metadata
     - no
     - yes
     - yes

..
   Backups: most of these are enforced in cinder/backup/api.py

.. list-table:: Backups
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - List backups
     - | ``GET  /backups``
       | ``GET  /backups/detail``
     - backup:get_all
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
     - no
     - no
     - yes
   * - Create backup
     - ``POST  /backups``
     - backup:create
     - no
     - yes
     - yes
   * - Show backup
     - ``GET  /backups/{backup_id}``
     - backup:get
     - yes
     - yes
     - yes
   * - Update backup
     - | Microversion 3.9
       | ``PUT  /backups/{backup_id}``
     - backup:update
     - no
     - yes
     - yes
   * - Delete backup
     - ``DELETE  /backups/{backup_id}``
     - backup:delete
     - no
     - yes
     - yes
   * - Restore backup
     - ``POST  /backups/{backup_id}/restore``
     - backup:restore
     - no
     - yes
     - yes
   * - Import backup
     -  ``POST  /backups/{backup_id}/import_record``
     - backup:backup-import
     - no
     - no
     - yes
   * - Export backup
     - ``POST  /backups/{backup_id}/export_record``
     - backup:export-import
     - no
     - no
     - yes
   * - Reset status of a backup
     - ``POST  /backups/{backup_id}/action`` (os-reset_status)
     - volume_extension:backup_admin_actions:reset_status
     - no
     - no
     - yes
   * - Force delete a backup
     - ``POST  /backups/{backup_id}/action`` (os-force_delete)
     - volume_extension:backup_admin_actions:force_delete
     - no
     - no
     - yes

.. list-table:: Groups (Microversion 3.13)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - List groups
     - | ``GET  /groups``
       | ``GET  /groups/detail``
     - group:get_all
     - yes
     - yes
     - yes
   * - Create group, create group from src
     - | ``POST  /groups``
       | Microversion 3.14:
       | ``POST  /groups/action`` (create-from-src)
     - group:create
     - no
     - yes
     - yes
   * - Show group
     - ``GET  /groups/{group_id}``
     - group:get
     - yes
     - yes
     - yes
   * - Update group
     - ``PUT  /groups/{group_id}``
     - group:update
     - no
     - yes
     - yes
   * - Include project attributes in the list groups, show group responses
     - | Microversion 3.58
       | Adds ``project_id`` to the following responses:
       | ``GET  /groups/detail``
       | ``GET  /groups/{group_id}``
       | The ability to make these API calls is governed by other policies.
     - group:group_project_attribute
     - no
     - no
     - yes

.. list-table:: Group Types (Microversion 3.11)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - | **DEPRECATED**
       | Create, update or delete a group type
     - | (NOTE: Yoga policies split POST, PUT, DELETE)
       | ``POST /group_types/``
       | ``PUT /group_types/{group_type_id}``
       | ``DELETE /group_types/{group_type_id}``
     - group:group_types_manage
     - no
     - no
     - yes
   * - Create a group type
     - ``POST /group_types/``
     - group:group_types:create
     - no
     - no
     - yes
   * - Update a group type
     - ``PUT /group_types/{group_type_id}``
     - group:group_types:update
     - no
     - no
     - yes
   * - Delete a group type
     - ``DELETE /group_types/{group_type_id}``
     - group:group_types:delete
     - no
     - no
     - yes
   * - Show group type with type specs attributes
     - | Adds ``group_specs`` to the following responses:
       | ``GET  /group_types``
       | ``GET  /group_types/default``
       | ``GET  /group_types/{group_type_id}``
       | These calls are not governed by a policy.
     - group:access_group_types_specs
     - no
     - no
     - yes
   * - | **DEPRECATED**
       | Create, show, update and delete group type spec
     - | (NOTE: Yoga policies split GET, POST, PUT, DELETE)
       | ``GET /group_types/{group_type_id}/group_specs``
       | ``GET /group_types/{group_type_id}/group_specs/{g_spec_id}``
       | ``POST /group_types/{group_type_id}/group_specs``
       | ``PUT /group_types/{group_type_id}/group_specs/{g_spec_id}``
       | ``DELETE  /group_types/{group_type_id}/group_specs/{g_spec_id}``
     - group:group_types_specs
     - no
     - no
     - yes
   * - Create group type spec
     - ``POST /group_types/{group_type_id}/group_specs``
     - group:group_types_specs:create
     - no
     - no
     - yes
   * - List group type specs
     - ``GET /group_types/{group_type_id}/group_specs``
     - group:group_types_specs:get_all
     - no
     - no
     - yes
   * - Show detail for a group type spec
     - ``GET /group_types/{group_type_id}/group_specs/{g_spec_id}``
     - group:group_types_specs:get
     - no
     - no
     - yes
   * - Update group type spec
     - ``PUT /group_types/{group_type_id}/group_specs/{g_spec_id}``
     - group:group_types_specs:update
     - no
     - no
     - yes
   * - Delete group type spec
     - ``DELETE /group_types/{group_type_id}/group_specs/{g_spec_id}``
     - group:group_types_specs:delete
     - no
     - no
     - yes

.. list-table:: Group Snapshots (Microversion 3.14)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - List group snapshots
     - | ``GET  /group_snapshots``
       | ``GET  /group_snapshots/detail``
     - group:get_all_group_snapshots
     - yes
     - yes
     - yes
   * - Create group snapshot
     - ``POST  /group_snapshots``
     - group:create_group_snapshot
     - no
     - yes
     - yes
   * - Show group snapshot
     - ``GET  /group_snapshots/{group_snapshot_id}``
     - group:get_group_snapshot
     - yes
     - yes
     - yes
   * - Delete group snapshot
     - ``DELETE  /group_snapshots/{group_snapshot_id}``
     - group:delete_group_snapshot
     - no
     - yes
     - yes
   * - Update group snapshot
     - | ``PUT  /group_snapshots/{group_snapshot_id}``
       | Note: even though the policy is defined, this call is not implemented
         in the Block Storage API.
     - group:update_group_snapshot
     - no
     - yes
     - yes
   * - Reset status of group snapshot
     - | Microversion 3.19
       | ``POST  /group_snapshots/{group_snapshot_id}/action`` (reset_status)
     - group:reset_group_snapshot_status
     - no
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
     - no
     - no
     - yes

.. list-table:: Group Actions
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - Delete group
     - ``POST  /groups/{group_id}/action`` (delete)
     - group:delete
     - no
     - yes
     - yes
   * - Reset status of group
     - | Microversion 3.20
       | ``POST  /groups/{group_id}/action`` (reset_status)
     - group:reset_status
     - no
     - no
     - yes
   * - Enable replication
     - | Microversion 3.38
       | ``POST  /groups/{group_id}/action`` (enable_replication)
     - group:enable_replication
     - no
     - yes
     - yes
   * - Disable replication
     - | Microversion 3.38
       | ``POST  /groups/{group_id}/action`` (disable_replication)
     - group:disable_replication
     - no
     - yes
     - yes
   * - Fail over replication
     - | Microversion 3.38
       | ``POST  /groups/{group_id}/action`` (failover_replication)
     - group:failover_replication
     - no
     - yes
     - yes
   * - List failover replication
     - | Microversion 3.38
       | ``POST  /groups/{group_id}/action`` (list_replication_targets)
     - group:list_replication_targets
     - no
     - yes
     - yes

.. list-table:: QOS specs
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - List qos specs or list all associations
     - | ``GET  /qos-specs``
       | ``GET  /qos-specs/{qos_id}/associations``
     - volume_extension:qos_specs_manage:get_all
     - no
     - no
     - yes
   * - Show qos specs
     - ``GET  /qos-specs/{qos_id}``
     - volume_extension:qos_specs_manage:get
     - no
     - no
     - yes
   * - Create qos specs
     - ``POST  /qos-specs``
     - volume_extension:qos_specs_manage:create
     - no
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
     - no
     - no
     - yes
   * - Delete a qos-spec, or remove a list of keys from the qos-spec
     - | ``DELETE  /qos-specs/{qos_id}``
       | ``PUT  /qos-specs/{qos_id}/delete_keys``
     - volume_extension:qos_specs_manage:delete
     - no
     - no
     - yes

.. list-table:: Quotas
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - | **DEPRECATED**
       | Show or update project quota class
     - | (NOTE: Yoga policies split GET and PUT)
       | ``GET  /os-quota-class-sets/{project_id}``
       | ``PUT  /os-quota-class-sets/{project_id}``
     - volume_extension:quota_classes
     - no
     - no
     - yes
   * - Show project quota class
     - ``GET  /os-quota-class-sets/{project_id}``
     - volume_extension:quota_classes:get
     - no
     - no
     - yes
   * - Update project quota class
     - ``PUT  /os-quota-class-sets/{project_id}``
     - volume_extension:quota_classes:update
     - no
     - no
     - yes
   * - Show project quota (including usage and default)
     - | ``GET  /os-quota-sets/{project_id}``
       | ``GET  /os-quota-sets/{project_id}/default``
       | ``GET  /os-quota-sets/{project_id}?usage=True``
     - volume_extension:quotas:show
     - yes
     - yes
     - yes
   * - Update project quota
     - ``PUT  /os-quota-sets/{project_id}``
     - volume_extension:quotas:update
     - no
     - no
     - yes
   * - Delete project quota
     - ``DELETE  /os-quota-sets/{project_id}``
     - volume_extension:quotas:delete
     - no
     - no
     - yes

.. list-table:: Capabilities
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - Show backend capabilities
     - ``GET  /capabilities/{host_name}``
     - volume_extension:capabilities
     - no
     - no
     - yes

.. list-table:: Services
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - List all services
     - ``GET  /os-services``
     - volume_extension:services:index
     - no
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
     - no
     - no
     - yes
   * - Freeze a backend host.  Secondary check; must also satisfy
       volume_extension:services:update to make this call.
     - ``PUT  /os-services/freeze``
     - volume:freeze_host
     - no
     - no
     - yes
   * - Thaw a backend host.  Secondary check; must also satisfy
       volume_extension:services:update to make this call.
     - ``PUT  /os-services/thaw``
     - volume:thaw_host
     - no
     - no
     - yes
   * - Failover a backend host.  Secondary check; must also satisfy
       volume_extension:services:update to make this call.
     - | ``PUT  /os-services/failover_host``
       | ``PUT  /os-services/failover`` (microversion 3.26)
     - volume:failover_host
     - no
     - no
     - yes
   * - List all backend pools
     - ``GET  /scheduler-stats/get_pools``
     - scheduler_extension:scheduler_stats:get_pools
     - no
     - no
     - yes
   * - | List, update or show hosts for a project
       | (NOTE: will be deprecated in Zed and new policies introduced
       | for GETs and PUT)
     - | ``GET  /os-hosts``
       | ``PUT  /os-hosts/{host_name}``
       | ``GET  /os-hosts/{host_id}``
     - volume_extension:hosts
     - no
     - no
     - yes
   * - Show limits with used limit attributes
     - ``GET  /limits``
     - limits_extension:used_limits
     - yes
     - yes
     - yes
   * - List (in detail) of volumes which are available to manage
     - | ``GET  /manageable_volumes``
       | ``GET  /manageable_volumes/detail``
     - volume_extension:list_manageable
     - no
     - no
     - yes
   * - Manage existing volumes
     - ``POST  /manageable_volumes``
     - volume_extension:volume_manage
     - no
     - no
     - yes
   * - Unmanage a volume
     - ``POST  /volumes/{volume_id}/action`` (os-unmanage)
     - volume_extension:volume_unmanage
     - no
     - no
     - yes

.. list-table:: Volume Types
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - | **DEPRECATED**
       | Create, update and delete volume type
       | (Yoga policies for create/update/delete)
     - | ``POST  /types``
       | ``PUT  /types/{type_id}``
       | ``DELETE  /types``
     - volume_extension:types_manage
     - no
     - no
     - yes
   * - Create a volume type
     - ``POST  /types``
     - volume_extension:type_create
     - no
     - no
     - yes
   * - Update a volume type
     - ``PUT  /types/{type_id}``
     - volume_extension:type_update
     - no
     - no
     - yes
   * - Delete a volume type
     - ``DELETE  /types/{type_id}``
     - volume_extension:type_delete
     - no
     - no
     - yes
   * - Show a specific volume type
     - ``GET  /types/{type_id}``
     - volume_extension:type_get
     - yes
     - yes
     - yes
   * - List volume types
     - ``GET  /types``
     - volume_extension:type_get_all
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
     -
     -
     -
   * - Create volume type encryption
     - ``POST  /types/{type_id}/encryption``
     - volume_extension:volume_type_encryption:create
     - no
     - no
     - yes
   * - Show a volume type's encryption type, show an encryption specs item
     - | ``GET  /types/{type_id}/encryption``
       | ``GET  /types/{type_id}/encryption/{key}``
     - volume_extension:volume_type_encryption:get
     - no
     - no
     - yes
   * - Update volume type encryption
     - ``PUT  /types/{type_id}/encryption/{encryption_id}``
     - volume_extension:volume_type_encryption:update
     - no
     - no
     - yes
   * - Delete volume type encryption
     - ``DELETE  /types/{type_id}/encryption/{encryption_id}``
     - volume_extension:volume_type_encryption:delete
     - no
     - no
     - yes
   * - List or show volume type with extra specs attribute
     - | Adds ``extra_specs`` to the following responses:
       | ``GET  /types/{type_id}``
       | ``GET  /types``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:access_types_extra_specs
     - yes
     - yes
     - yes
   * - List or show volume type with access type qos specs id attribute
     - | Adds ``qos_specs_id`` to the following responses:
       | ``GET  /types/{type_id}``
       | ``GET  /types``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:access_types_qos_specs_id
     - no
     - no
     - yes
   * - Show whether a volume type is public in the type response
     - | Adds ``os-volume-type-access:is_public`` to the following responses:
       | ``GET  /types``
       | ``GET  /types/{type_id}``
       | ``POST  /types``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:volume_type_access
     - no
     - yes
     - yes
   * - | List private volume type access detail, that is, list the projects
         that have access to this type
       | (was formerly controlled by volume_extension:volume_type_access)
     - ``GET  /types/{type_id}/os-volume-type-access``
     - volume_extension:volume_type_access:get_all_for_type
     - no
     - no
     - yes
   * - Add volume type access for project
     - ``POST  /types/{type_id}/action`` (addProjectAccess)
     - volume_extension:volume_type_access:addProjectAccess
     - no
     - no
     - yes
   * - Remove volume type access for project
     - ``POST  /types/{type_id}/action`` (removeProjectAccess)
     - volume_extension:volume_type_access:removeProjectAccess
     - no
     - no
     - yes

.. list-table:: Volume Actions
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - Extend a volume
     - ``POST  /volumes/{volume_id}/action`` (os-extend)
     - volume:extend
     - no
     - yes
     - yes
   * - Extend an attached volume
     - | Microversion 3.42
       | ``POST  /volumes/{volume_id}/action`` (os-extend)
     - volume:extend_attached_volume
     - no
     - yes
     - yes
   * - Revert a volume to a snapshot
     - | Microversion 3.40
       | ``POST  /volumes/{volume_id}/action`` (revert)
     - volume:revert_to_snapshot
     - no
     - yes
     - yes
   * - Reset status of a volume
     - ``POST  /volumes/{volume_id}/action`` (os-reset_status)
     - volume_extension:volume_admin_actions:reset_status
     - no
     - no
     - yes
   * - Retype a volume
     - ``POST  /volumes/{volume_id}/action`` (os-retype)
     - volume:retype
     - no
     - yes
     - yes
   * - Update a volume's readonly flag
     - ``POST  /volumes/{volume_id}/action`` (os-update_readonly_flag)
     -  volume:update_readonly_flag
     - no
     - yes
     - yes
   * - Force delete a volume
     - ``POST  /volumes/{volume_id}/action`` (os-force_delete)
     - volume_extension:volume_admin_actions:force_delete
     - no
     - no
     - yes
   * - Upload a volume to image with public visibility
     - ``POST  /volumes/{volume_id}/action`` (os-volume_upload_image)
     - volume_extension:volume_actions:upload_public
     - no
     - no
     - yes
   * - Upload a volume to image
     - ``POST  /volumes/{volume_id}/action`` (os-volume_upload_image)
     - volume_extension:volume_actions:upload_image
     - no
     - yes
     - yes
   * - Force detach a volume.
     - ``POST  /volumes/{volume_id}/action`` (os-force_detach)
     - volume_extension:volume_admin_actions:force_detach
     - no
     - no
     - yes
   * - Migrate a volume to a specified host
     - ``POST  /volumes/{volume_id}/action`` (os-migrate_volume)
     - volume_extension:volume_admin_actions:migrate_volume
     - no
     - no
     - yes
   * - Complete a volume migration
     - ``POST  /volumes/{volume_id}/action`` (os-migrate_volume_completion)
     - volume_extension:volume_admin_actions:migrate_volume_completion
     - no
     - no
     - yes
   * - Initialize volume attachment
     - ``POST  /volumes/{volume_id}/action`` (os-initialize_connection)
     - volume_extension:volume_actions:initialize_connection
     - no
     - yes
     - yes
   * - Terminate volume attachment
     - ``POST  /volumes/{volume_id}/action`` (os-terminate_connection)
     - volume_extension:volume_actions:terminate_connection
     - no
     - yes
     - yes
   * - Roll back volume status to 'in-use'
     - ``POST  /volumes/{volume_id}/action`` (os-roll_detaching)
     - volume_extension:volume_actions:roll_detaching
     - no
     - yes
     - yes
   * - Mark volume as reserved
     - ``POST  /volumes/{volume_id}/action`` (os-reserve)
     - volume_extension:volume_actions:reserve
     - no
     - yes
     - yes
   * - Unmark volume as reserved
     - ``POST  /volumes/{volume_id}/action`` (os-unreserve)
     - volume_extension:volume_actions:unreserve
     - no
     - yes
     - yes
   * - Begin detach volumes
     - ``POST  /volumes/{volume_id}/action`` (os-begin_detaching)
     - volume_extension:volume_actions:begin_detaching
     - no
     - yes
     - yes
   * - Add attachment metadata
     - ``POST  /volumes/{volume_id}/action`` (os-attach)
     - volume_extension:volume_actions:attach
     - no
     - yes
     - yes
   * - Clear attachment metadata
     - ``POST  /volumes/{volume_id}/action`` (os-detach)
     - volume_extension:volume_actions:detach
     - no
     - yes
     - yes
   * - Reimage a volume in ``available`` or ``error`` status
     - ``POST  /volumes/{volume_id}/action`` (os-reimage)
     - volume:reimage
     - no
     - yes
     - yes
   * - Reimage a volume in ``reserved`` status
     - ``POST  /volumes/{volume_id}/action`` (os-reimage)
     - volume:reimage_reserved
     - no
     - yes
     - yes

.. list-table:: Volume Transfers
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - List volume transfer
     - | ``GET  /os-volume-transfer``
       | ``GET  /os-volume-transfer/detail``
       | ``GET  /volume-transfers``
       | ``GET  /volume-transfers/detail``
     - volume:get_all_transfers
     - yes
     - yes
     - yes
   * - Create a volume transfer
     - | ``POST  /os-volume-transfer``
       | ``POST  /volume-transfers``
     - volume:create_transfer
     - no
     - yes
     - yes
   * - Show one specified volume transfer
     - | ``GET  /os-volume-transfer/{transfer_id}``
       | ``GET  /volume-transfers/{transfer_id}``
     - volume:get_transfer
     - yes
     - yes
     - yes
   * - Accept a volume transfer
     - | ``POST  /os-volume-transfer/{transfer_id}/accept``
       | ``POST  /volume-transfers/{transfer_id}/accept``
     - volume:accept_transfer
     - no
     - yes
     - yes
   * - Delete volume transfer
     - | ``DELETE  /os-volume-transfer/{transfer_id}``
       | ``DELETE  /volume-transfers/{transfer_id}``
     - volume:delete_transfer
     - no
     - yes
     - yes

.. list-table:: Volume Metadata
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - Show volume's metadata or one specified metadata with a given key.
     - | ``GET  /volumes/{volume_id}/metadata``
       | ``GET  /volumes/{volume_id}/metadata/{key}``
       | ``POST /volumes/{volume_id}/action`` (os-show_image_metadata)
     - volume:get_volume_metadata
     - yes
     - yes
     - yes
   * - Create volume metadata
     - ``POST  /volumes/{volume_id}/metadata``
     - volume:create_volume_metadata
     - no
     - yes
     - yes
   * - Update volume's metadata or one specified metadata with a given key
     - | ``PUT  /volumes/{volume_id}/metadata``
       | ``PUT  /volumes/{volume_id}/metadata/{key}``
     - volume:update_volume_metadata
     - no
     - yes
     - yes
   * - Delete volume's specified metadata with a given key
     - ``DELETE  /volumes/{volume_id}/metadata/{key}``
     - volume:delete_volume_metadata
     - no
     - yes
     - yes
   * - | **DEPRECATED**
       | Volume's image metadata related operation, create, delete, show and
         list
     - | (NOTE: Yoga policies split GET and POST)
       | Microversion 3.4
       | ``GET  /volumes/detail``
       | ``GET  /volumes/{volume_id}``
       | ``POST  /volumes/{volume_id}/action`` (os-set_image_metadata)
       | ``POST  /volumes/{volume_id}/action`` (os-unset_image_metadata)
       | (NOTE: ``POST /volumes/{volume_id}/action`` (os-show_image_metadata)
         is governed by volume:get_volume_metadata
     - volume_extension:volume_image_metadata
     - no
     - yes
     - yes
   * - Include volume's image metadata in volume detail responses
     - | Microversion 3.4
       | ``GET  /volumes/detail``
       | ``GET  /volumes/{volume_id}``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:volume_image_metadata:show
     - yes
     - yes
     - yes
   * - Set image metadata for a volume
     - | Microversion 3.4
       | ``POST  /volumes/{volume_id}/action`` (os-set_image_metadata)
     - volume_extension:volume_image_metadata:set
     - no
     - yes
     - yes
   * - Remove specific image metadata from a volume
     - | Microversion 3.4
       | ``POST  /volumes/{volume_id}/action`` (os-unset_image_metadata)
     - volume_extension:volume_image_metadata:remove
     - no
     - yes
     - yes
   * - Update volume admin metadata.
     - | This permission is required to complete the following operations:
       | ``POST  /volumes/{volume_id}/action`` (os-update_readonly_flag)
       | ``POST  /volumes/{volume_id}/action`` (os-attach)
       | The ability to make these API calls is governed by other policies.
     - volume:update_volume_admin_metadata
     - no
     - no
     - yes

.. list-table:: Volume Type Extra-Specs
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - List type extra specs
     - ``GET  /types/{type_id}/extra_specs``
     - volume_extension:types_extra_specs:index
     - yes
     - yes
     - yes
   * - Create type extra specs
     - ``POST  /types/{type_id}/extra_specs``
     - volume_extension:types_extra_specs:create
     - no
     - no
     - yes
   * - Show one specified type extra specs
     - ``GET  /types/{type_id}/extra_specs/{extra_spec_key}``
     - volume_extension:types_extra_specs:show
     - yes
     - yes
     - yes
   * - Update type extra specs
     - ``PUT  /types/{type_id}/extra_specs/{extra_spec_key}``
     - volume_extension:types_extra_specs:update
     - no
     - no
     - yes
   * - Delete type extra specs
     - ``DELETE  /types/{type_id}/extra_specs/{extra_spec_key}``
     - volume_extension:types_extra_specs:delete
     - no
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
     - no
     - no
     - yes

.. list-table:: Volumes
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - Create volume
     - ``POST  /volumes``
     - volume:create
     - no
     - yes
     - yes
   * - Create volume from image
     - ``POST  /volumes``
     - volume:create_from_image
     - no
     - yes
     - yes
   * - Show volume
     - ``GET  /volumes/{volume_id}``
     - volume:get
     - yes
     - yes
     - yes
   * - List volumes or get summary of volumes
     - | ``GET  /volumes``
       | ``GET  /volumes/detail``
       | ``GET  /volumes/summary``
     - volume:get_all
     - yes
     - yes
     - yes
   * - Update volume or update a volume's bootable status
     - | ``PUT  /volumes``
       | ``POST  /volumes/{volume_id}/action`` (os-set_bootable)
     - volume:update
     - no
     - yes
     - yes
   * - Delete volume
     - ``DELETE  /volumes/{volume_id}``
     - volume:delete
     - no
     - yes
     - yes
   * - Force Delete a volume (Microversion 3.23)
     - ``DELETE  /volumes/{volume_id}?force=true``
     - volume:force_delete
     - no
     - no
     - yes
   * - List or show volume with host attribute
     - | Adds ``os-vol-host-attr:host`` to the following responses:
       | ``GET  /volumes/{volume_id}``
       | ``GET  /volumes/detail``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:volume_host_attribute
     - no
     - no
     - yes
   * - List or show volume with "tenant attribute" (actually, the project ID)
     - | Adds ``os-vol-tenant-attr:tenant_id`` to the following responses:
       | ``GET  /volumes/{volume_id}``
       | ``GET  /volumes/detail``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:volume_tenant_attribute
     - yes
     - yes
     - yes
   * - List or show volume with migration status attribute
     - | Adds ``os-vol-mig-status-attr:migstat`` to the following responses:
       | ``GET  /volumes/{volume_id}``
       | ``GET  /volumes/detail``
       | The ability to make these API calls is governed by other policies.
     - volume_extension:volume_mig_status_attribute
     - no
     - no
     - yes
   * - Show volume's encryption metadata
     - | ``GET  /volumes/{volume_id}/encryption``
       | ``GET  /volumes/{volume_id}/encryption/{encryption_key}``
     - volume_extension:volume_encryption_metadata
     - yes
     - yes
     - yes
   * - Create multiattach capable volume
     - | Indirectly affects the success of these API calls:
       | ``POST  /volumes``
       | ``POST  /volumes/{volume_id}/action`` (os-retype)
       | The ability to make these API calls is governed by other policies.
     - volume:multiattach
     - no
     - yes
     - yes

.. list-table:: Default Volume Types (Microversion 3.62)
   :header-rows: 1

   * - functionality
     - API call
     - policy name
     - project-reader
     - project-member
     - system-admin
   * - Set or update default volume type for a project
     - ``PUT  /default-types``
     - volume_extension:default_set_or_update
     - no
     - no
     - yes
   * - Get default type for a project
     - | ``GET  /default-types/{project-id}``
       | (Note: a project-\* persona can always determine their effective
         default-type by making the ``GET /v3/{project_id}/types/default``
         call, which is governed by the volume_extension:type_get policy.)
     - volume_extension:default_get
     - no
     - no
     - yes
   * - Get all default types
     - ``GET  /default-types/``
     - volume_extension:default_get_all
     - no
     - no
     - yes
   * - Unset default type for a project
     - ``DELETE  /default-types/{project-id}``
     - volume_extension:default_unset
     - no
     - no
     - yes
