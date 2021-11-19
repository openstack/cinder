====================
Default Volume Types
====================

Beginning with the Train release, untyped volumes (that is, volumes with no
volume-type) have been disallowed. To facilitate this, a ``__DEFAULT__``
volume-type was included as part of the Train database migration.
Since the Train release, handling of the default volume-type has been
improved:

- The default_volume_type configuration option is required to have a value.
  The default value is ``__DEFAULT__``.

- A request to delete the currently configured default_volume_type will fail.
  (You can delete that volume-type, but you cannot do it while it is the value
  of the configuration option.)

- There must always be at least one volume-type defined in a Cinder
  installation. This is enforced by the type-delete call.

- If the default_volume_type is misconfigured (that is, if the value refers to
  a non-existent volume-type), requests that rely on the default volume-type
  (for example, a volume-create request that does not specify a volume-type)
  will result in a HTTP 500 response.

Default types per project
-------------------------

We have overriden the existing Cinder default Volume Type on a per project
basis to make it easier to manage complex deployments.

With the introduction of this new default volume type support, we’ll now
have 2 different default volume types. From more specific to more generic these
are:

- Per project

- Defined in cinder.conf (defaults to ``__DEFAULT__`` type)

So when a user creates a new volume that has no defined volume type
(explicit or in the source), Cinder will look for the appropriate default
first by checking if there’s one defined in the DB for the specific project
and use it, if there isn’t one, it will continue like it does today,
using the default type from cinder.conf.

Administrators and users must still be careful with the normal Cinder behavior
when creating volumes, as Cinder will still only resort to using the default
volume type if the user doesn’t select one on the request or if there’s no
volume type in the source, which means that Cinder will not use any of those
defaults if we:

- Create a volume providing a volume type

- Create a volume from a snapshot

- Clone a volume

- Create a volume from an image that has cinder_img_volume_type defined in its
  metadata.

There is a new set of commands in the python-cinderclient to match the new
REST API endpoints:

- Set default: ``cinder default-type-set <project-id> <type-name>``

- Unset default: ``cinder default-type-unset <project-id>``

- List defaults: ``cinder default-type-list [--project <project-id>]``

By default the policy restricting access to set, unset, get or list all
project default volume type is set to admins only.
