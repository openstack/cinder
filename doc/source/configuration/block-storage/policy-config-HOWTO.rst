.. Copyright (c) 2018 Red Hat Inc.
   All Rights Reserved.

   Licensed under the Apache License, Version 2.0 (the "License"); you may
   not use this file except in compliance with the License. You may obtain
   a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
   License for the specific language governing permissions and limitations
   under the License.

==========================
Policy configuration HowTo
==========================

You can use Cinder policies to control how your users and administrators
interact with the Block Storage Service.  In this HowTo, we'll discuss the user
model Cinder employs and how it can be modified by adjusting policies.

* Like most OpenStack services, Cinder uses the OpenStack ``oslo.policy``
  library as a base for its policy-related code.  For a discussion of "rules"
  and "roles", other vocabulary, and general information about OpenStack
  policies and the policy configuration file, see `Administering Applications
  that use oslo.policy
  <https://docs.openstack.org/oslo.policy/latest/admin/index.html>`_.

* See :doc:`policy` for the list of policy targets recognized by Cinder.

* Since the Queens release, the default way to run Cinder is without a policy
  file.  This is because sensible default values are defined in the code.  To
  run Cinder with a custom policy configuration, however, you'll need to write
  your changes into a policy file.

* Elsewhere in this documentation, you can find a copy of the :doc:`sample
  policy file <./samples/policy.yaml>` that contains all the default settings.

* Instructions for generating a sample ``policy.yaml`` file directly from the
  Cinder source code can be found in the file ``README-policy.generate.md``
  in the ``etc/cinder`` directory in the Cinder `source code repository
  <https://opendev.org/openstack/cinder>`_ (or its `github mirror
  <https://github.com/openstack/cinder>`_).

Vocabulary Note
~~~~~~~~~~~~~~~

We need to clarify some terms we'll be using below.

Project
    This is an administrative grouping of users into a unit that can own
    cloud resources.  (This is what used to be called a "tenant".)

Service
    This is an OpenStack component that users interact with through an API it
    provides.  For example, "Cinder" is the OpenStack code name for the service
    that provides the Block Storage API versions 2 and 3.  Cinder is also known
    as the OpenStack Block Storage Service.

The point of making this distinction is that there's another use of the term
'project' that is relevant to the discussion, but that we're **not** going to
use.  Each OpenStack service is produced and maintained by a "project team".
*We will not be using the term 'project' in that sense in this document.  We'll
always use the term 'service'.* (If you are new to OpenStack, this won't be a
problem.  But if you're discussing this content with someone who's been around
OpenStack for a while, you'll want to be clear about this so that you're not
talking past each other.)

.. _cinder-user-model:

The User Model
~~~~~~~~~~~~~~

The Cinder code is written with the expectation that there are two kinds of
users.

End users
    These are users who consume resources and (possibly) pay the bills.  End
    users are restricted to acting within a specific project and cannot perform
    operations on resources that are not owned by the project(s) they are in.

Administrative users ("admins")
    These are users who keep the lights on.  They have the ability to view all
    resources controlled by Cinder and can perform most operations on them.
    They also have access to other operations (for example, setting quotas)
    that cannot be performed by end users.

    Additionally, admins can view resource properties that cannot be seen by
    end users (for example, the migration status of a volume).  The technical
    term to describe this is that when a volume-show call is made in an
    *administrative context* it will contain additional properties than when
    the call is *not* made in an administrative context.  Similarly, when a
    volume-list call is made in an administrative context, the response may
    include volumes that are not owned by the project of the person making
    the call; this never happens when a call is *not* made in an administrative
    context.

Policies
~~~~~~~~

Broadly speaking, an operator can accomplish two things with policies:

1. The policy file can define the criteria for what users are granted the
   privilege to act in an administrative context.

2. The policy file can specify for specific *actions* (or *policy targets*),
   which users can perform those actions.

In general, while an operator can define *who* can make calls in an
administrative context, an operator cannot affect *what* can be done in an
administrative context (because that's already been decided when the code was
implemented).  For example, the boundaries between projects are strictly
enforced in Cinder, and only an admin can view resources across projects.
There is no way to grant a user the ability to "see" into another project (at
least not by policy configuration--this could be done by using the Identity
Service to add the user to the other project, but note that at that point, the
user is no longer *not* a member of the project owning the now visible
resources.)

Pre-Defined Policy Rules
~~~~~~~~~~~~~~~~~~~~~~~~

The default Cinder policy file contains three rules that are used as the basis
of policy file configuration.

"context_is_admin"
    This defines the administrative context in Cinder.  You'll notice that it's
    defined once at the beginning of the :doc:`sample policy file
    <./samples/policy.yaml>` and isn't referred to anywhere else in that file.
    To understand what this does, it's helpful to know something about the API
    implementation.

    A user's API request must be accompanied by an authentication token from
    the Identity Service.  (If you are using client software, for example, the
    python-cinderclient or python-openstack client, the token is being
    requested for you under the hood.)  The Block Storage API confirms that the
    token is unexpired and obtains other information about the requestor, for
    example, what roles the Identity Service recognizes the user to have.
    Cinder uses this information to create an internal context object that will
    be passed around the code as various functions and services are called to
    satisfy the user's request.

    When the request context object is created, Cinder uses the
    "context_is_admin" rule to decide whether this context object will be
    recognized as providing an administrative context.  It does this by setting
    the "is_admin" property to True on the context object.  Cinder code later
    in the call chain simply checks whether the "is_admin" property is true on
    the context object to determine whether the call is taking place in an
    administrative context.  Similarly, policies will refer to "is_admin:True"
    (either directly or indirectly) to require an administrative context.

    All of this is a long-winded way to say that in a Cinder policy file,
    you'll only see "context_is_admin" at the top; after that, you'll see
    "is_admin:True" whenever you want to refer to an administrative context.

"admin_or_owner"
    This is the default rule for most non-admin API calls.  As the name
    indicates, it allows an administrator or an owner to make the call.

"admin_api"
    This is the default rule for API calls that only administrators should
    be allowed to make.

    .. note:: For some API calls, there are checks way down in the code to
       ensure that a call is being made in an administrative context before the
       request is allowed to succeed.  Thus it is not always the case that
       simply changing a policy target whose value is "rule:admin_api" to
       "rule:admin_or_owner" (or "rule:admin_api or role:some-special-role")
       will give a non-admin user the ability to successfully make the call.
       Unfortunately, you can't tell which calls these are without
       experimenting with a policy file (or looking at the source code). A good
       rule of thumb, however, is that API calls governed by policies marked as
       "rule:admin_api" in the default policy configuration fall into this
       category.

Example: Configuring a Read-Only Administrator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A fairly common configuration request is to create a special category of
administrator who has only an *observer* ("look but don't touch") function.
The idea is that for security and stability reasons, it's a good idea to allow
all users, including administrators, the least amount of privileges they need
to successfully perform their job.  Someone whose job is to audit information
about Cinder (for example, to see what the current quota settings are) doesn't
need the ability to change these settings.  In this section, we'll discuss one
way to configure the Cinder policy file to accomplish this.

.. note:: To keep the discussion focused, this example assumes that you're
   working from the default policy file.  Hopefully the general strategy will
   be clear enough to be applied to clouds already using non-default
   configurations.  Additionally, there are other logically equivalent ways
   to configure the policy file to introduce a read-only administrator; this
   is not by any means the only way to do it.

Given the job requirements, the observer administrator (who we'll refer to as
the "observer-admin" for short) needs to operate in the administrative context.
Thus, we'll have to adjust the "context_is_admin" definition in the policy file
to include such a person.  Note that this will make such a person a **full
administrator** if we make no other changes to the policy file.  Thus the
strategy we'll use is to first make the observer-admin a full administrator,
and then block the observer-admin's access to those API calls that aren't
read-only.

.. warning:: Metaphorically, what we are doing is opening the floodgates and
   then plugging up the holes one by one.  That sounds alarming, and it should.
   We cannot emphasize strongly enough that any policy file changes should be
   **well-contained** (that is, you know exactly who has the new role or roles)
   and **tested** (you should have some kind of tests in place to determine
   that your changes have only the effects you intend).

   This is probably as good a place as any to remind you that the suggestions
   that follow are provided without warranty of any kind, either expressed or
   implied.  Like the OpenStack source code, they are covered by the `Apache
   License, version 2.0 <http://www.apache.org/licenses/LICENSE-2.0>`_.  In
   particular, we direct your attention to sections 7-9.

Step 0: Testing
```````````````

We mention testing first (even though you haven't made any changes yet) because
if we wait to mention it until after we've made the configuration changes, you
might get the impression that it's the last thing to do (or the least
important).  It will make your life much easier if you come up with a plan for
how you will test these changes before you start modifiying the policy
configuration.

We advise setting up automated tests because the Block Storage API has a lot
of API calls and you'll want to test each of them against an admin user, an
observer-admin user, and a "regular" end user.  Further, if you anticipate that
you may require finer-grained access than outlined in this example (for
example, you would like a "creator" role that can create and read, but not
delete), your configuration will be all the more complex and hence require more
extensive testing that you won't want to do by hand.

Step 1: Create a new role
`````````````````````````

In the Identity Service, create a new role.  It's a good idea to make this a
new, never before assigned role so that you can easily track who it's been
assigned to.  As you recall from the discussion above, this person will have
**full administrative powers** for any functions that are missed when we do the
"block up the holes" stage.

For this example, we'll use a role named ``cinder:reader-admin``.  There is
nothing special about this role name; you may use any name that makes sense to
the administrators who will be assigning the role and configuring the policies.
(The 'cinder:' part is to remind you that this role applies to the Block
Storage Service, the 'reader' part is from the role name that OpenStack has
converged upon for this type of observer role, and the '-admin' part is to
remind you that whoever has this role will be able to observe admin-type
stuff.)

.. note::
   Beginning with the Rocky release, the Identity Service (Keystone) creates
   three roles when the service is initiated: ``member``, ``reader``, and
   ``admin``.  By default, the ``reader`` role is not assigned to any users.
   Work is underway during the Stein cycle so that the Identity API will
   recognize users with the ``reader`` role as having read-only access to the
   Identity API.  See the Keystone spec `Basic Default Roles
   <http://specs.openstack.org/openstack/keystone-specs/specs/keystone/rocky/define-default-roles.html>`_
   for more information.

   We mention this so that you are aware that if you use a role named
   ``reader`` when doing the policy configuration described in this document,
   at some point users assigned the ``reader`` role may have read-only access
   to services other than the Block Storage Service.  The desirability of this
   outcome depends upon your particular use case.

Step 2: Open the floodgates
```````````````````````````

If your installation doesn't have an ``/etc/cinder/policy.yaml`` file, you
can generate one from the source code (see the introductory section of this
document).

.. note:: The default file is *completely commented out*.  For any of the
   changes you make below to be effective, don't forget to *uncomment* the
   line in which they occur.

To extend the administrative context to include the new role, change::

  "context_is_admin": "role:admin"

to::

  "context_is_admin": "role:admin or role:cinder:reader-admin"

Step 3: Plug the holes in the Admin API
```````````````````````````````````````

Now we make adjustments to the policy configuration so that the observer-admin
will in fact have only read-only access to Cinder resources.

3A: New Policy Rule
-------------------

First, we create a new policy rule for Admin API access that specifically
excludes the new role.  Find the line in the policy file that has
``"admin_api"`` on the left hand side.  Immediately after it, introduce a new
rule::

  "strict_admin_api": "not role:cinder:reader-admin and rule:admin_api"

3B: Plugging Holes
------------------

Now, plug up the holes we've opened in the Admin API by using this new rule.
Find each of the lines in the remainder of the policy file that look like::

  "target": "rule:admin_api"

and for each line, decide whether the observer-admin needs access to this
action or not.  For example, the target ``"volume_extension:services:index"``
specifies a read-only action, so it's appropriate for the observer-admin to
perform.  We'll leave that one in its default configuration of::

  "volume_extension:services:index": "rule:admin_api"

On the other hand, if the target is something that allows modification, we most
likely don't want to allow the observer-admin to perform it.  For such actions
we need to use the "strict" form of the admin rule.  For example, consider the
action ``"volume_extension:quotas:delete"``.  To exclude the observer-admin
from performing it, change the default setting of::

  "volume_extension:quotas:delete": "rule:admin_api"

to::

  "volume_extension:quotas:delete": "rule:strict_admin_api"

Do this on a case-by-case basis for the other policy targets that by default
are governed by the ``rule:admin_api``.

3C: Other Changes
-----------------

You've probably figured this out already, but there may be some other changes
that are implied by, but not explicitly mentioned in, the above instructions.
For example, you'll find the following policies in the sample file::

  "volume_extension:volume_type_encryption": "rule:admin_api"
  "volume_extension:volume_type_encryption:create": "rule:volume_extension:volume_type_encryption"
  "volume_extension:volume_type_encryption:get": "rule:volume_extension:volume_type_encryption"
  "volume_extension:volume_type_encryption:update": "rule:volume_extension:volume_type_encryption"
  "volume_extension:volume_type_encryption:delete": "rule:volume_extension:volume_type_encryption"

The first policy covers all of create/read/update/delete (and is deprecated for
removal during the Stein development cycle).  However, if you set it to
``"rule:strict_admin_api"``, the observer-admin won't be able to read the
volume type encryption.  So it should be left at ``"rule:admin_api"`` and the
create/update/delete policies should be changed to ``"rule:strict_admin_api"``.
Additionally, in preparation for the deprecated policy target's removal, it's
a good idea to change the value of the ``get`` policy to ``"rule:admin_api"``.

Step 4: Plug the holes in the "Regular" API
```````````````````````````````````````````

As stated earlier, a user with the role ``cinder:reader-admin`` is elevated
to full administrative powers.  That implies that such a user can perform
administrative functions on end-user resources.  Hence, we have another set of
holes to plug up.

4A: New Policy Rule
-------------------

As we did for the Admin API, we'll create a strict version of the
"admin_or_owner" rule so we can specifically exclude the observer-admin from
executing that action.  Find the line in the policy file where
``"admin_or_owner"`` appears on the left hand side.  It probably looks
something like this::

    "admin_or_owner": "is_admin:True or (role:admin and is_admin_project:True) or project_id:%(project_id)s"

Immediately following it, introduce a new rule::

    "strict_admin_or_owner": "(not role:cinder:reader-admin and (is_admin:True or (role:admin and is_admin_project:True))) or project_id:%(project_id)s"

.. note:: To understand what this change does, note that the "admin_or_owner"
   rule definition has the general structure::

     <admin-stuff> or <project-stuff>

   To construct the strict version, we need to make sure that the
   ``not cinder:reader-admin`` part applies only the left-hand side (the
   <admin-stuff>).  The easiest way to do that is to structure the new rule as
   follows::

     (not role:cinder:reader-admin and (<admin-stuff>)) or <project-stuff>

.. note:: If you don't need a user with the role ``cinder:reader-admin`` to
   manage resources in their own project, you could simplify this rule to::

      "strict_admin_or_owner": "not role:cinder:reader-admin and rule:admin_or_owner"

4B: Plugging Holes
------------------

Find each line in the policy file that looks like::

  "target": "rule:admin_or_owner"

and decide whether it represents an action that the observer-admin needs to
perform.  For those actions you *don't* want the observer-admin to do, change
the policy to::

  "target": "rule:strict_admin_or_owner"

4C: Unrestricted Policies
-------------------------

There are some policies in the default file that look like this::

  "target": ""

These are called *unrestricted policies* because the requirements are empty,
and hence can be satisfied by any authenticated user.  (Recall from the earlier
discussion of :ref:`cinder-user-model`, however, that this does *not* mean that
any user can see any other user's resources.)

Unrestricted policies may be found on GET calls that don't have a particular
resource to refer to (for example, the call to get all volumes) or a POST call
that creates a completely new resource (for example, the call to create a
volume).  You don't see them much in the Cinder policy file because the code
implementing the Block Storage API v2 and v3 always make sure there's a target
object containing at least the ``project_id`` and ``user_id`` that can be used
in evaluating whether the policy should allow the action or not.

Thus, obvious read-only targets (for example, ``volume_extension:type_get``)
can be left unrestricted.  Policy targets that are not read only (for example,
``volume:accept_transfer``), can be changed to ``rule:strict_admin_or_owner``.

Step 5: Testing
```````````````

We emphasized above that because of the nature of this change, it is extremely
important to test it carefully.  One thing to watch out for: because we're
using a clause like ``not role:cinder:reader-admin``, a typographical error
in the role name will cause problems.  (For example, if you enter it into the
file as ``not role:cinder_reader-admin``, it won't exclude the user we're
worried about, who has the role ``cinder:reader-admin``.)

As mentioned earlier, we advise setting up automated tests so that you can
prevent regressions if you have to modify your policy files at some point.
