.. _volume_multiattach:

=============================================
Enable attaching a volume to multiple servers
=============================================

When configured to allow it and for backends that support it, Cinder
allows a volume to be attached to more than one host/server at a time.

By default this feature is only enabled for administrators, and is
controlled by policy.  If the user is not an admin or the policy file
isn't modified only a single attachment per volume is allowed.

In addition, the ability to attach a volume to multiple hosts/servers
requires that the volume is of a special type that includes an extra-spec
capability setting of multiattach: True::

.. code-block:: console

   $ cinder type-create multiattach
   $ cinder type-key multiattach set multiattach="<is> True"

Now any volume of this type is capable of having multiple simultaneous
attachments.  You'll need to ensure you have a backend device that reports
support of the multiattach capability, otherwise scheduling will fail on
create.

At this point Cinder will no longer check in-use status when creating/updating
attachments.

.. note::

    This feature is only supported when using the new attachment API's,
    attachment-create, attachment-update etc.

In addition, it's possible to retype a volume to be multiattach capable.
Currently however we do NOT allow retyping a volume to multiattach:True or
multiattach:False if it's status is not ``avaialable``.  This is because some
consumers/hypervisors need to make special considerations at attach-time for
multiattach volumes (ie disable caching) and there's no mechanism currently to
go back to ``in-use`` volumes and update them.  While going from
``multiattach:True`` --> ``multiattach:False`` isn't as problematic, it is
error prone when it comes to special cases like shelve, migrate etc.  The bottom
line is it's *safer* to just avoid changing this setting on ``in-use`` volumes.

Finally, note that Cinder (nor its backends) does not do anything in terms of file
systems or control of the volumes.  In other words, it's up to the user to
ensure that a multiattach or clustered file system is used on the volumes.
Otherwise there may be a high probability of data corruption.
