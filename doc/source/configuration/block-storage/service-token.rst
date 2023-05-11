====================
Using service tokens
====================

When a user initiates a request whose processing involves multiple services
(for example, a boot-from-volume request to the Compute Service will require
processing by the Block Storage Service, and may require processing by the
Image Service), the user's token is handed from service to service.  This
ensures that the requestor is tracked correctly for audit purposes and also
guarantees that the requestor has the appropriate permissions to do what needs
to be done by the other services.

There are several instances where we want to differentiate between a request
coming from the user to one coming from another OpenStack service on behalf of
the user:

- **For security reasons** There are some operations in the Block Storage
  service, required for normal operations, that could be exploited by a
  malicious user to gain access to resources belonging to other users.  By
  differentiating when the request comes directly from a user and when from
  another OpenStack service the Cinder service can protect the deployment.

- To prevent long-running job failures: If the chain of operations takes a long
  time, the user's token may expire before the action is completed, leading to
  the failure of the user's original request.

  One way to deal with this is to set a long token life in Keystone, and this
  may be what you are currently doing.  But this can be problematic for
  installations whose security policies prefer short user token lives.
  Beginning with the Queens release, an alternative solution is available.  You
  have the ability to configure some services (particularly Nova and Cinder) to
  send a "service token" along with the user's token.  When properly
  configured, the Identity Service will validate an expired user token *when it
  is accompanied by a valid service token*.  Thus if the user's token expires
  somewhere during a long running chain of operations among various OpenStack
  services, the operations can continue.

.. note::
   There's nothing special about a service token.  It's a regular token
   that has been requested by a service user.  And there's nothing special
   about a service user, it's just a user that has been configured in the
   Identity Service to have specific roles that identify that user as
   a service.

   The key point here is that the "service token" doesn't need to have
   an extra long life -- it can have the same short life as all the
   other tokens because it will be a **fresh** (and hence valid) token
   accompanying the (possibly expired) user's token.

.. _service-token-configuration:

Configuration
~~~~~~~~~~~~~

To configure Cinder to send a "service token" along with the user's
token when it makes a request to another service, you must do the
following:

1.  Find the ``[service_user]`` section in the Cinder configuration
    file (usually ``/etc/cinder/cinder.conf``, though it may be in a
    different location in your installation).

2.  In that section, set ``send_service_user_token = true``.

3.  Also in that section, fill in the appropriate configuration for
    your service user (``username``, ``project_name``, etc.)

4.  If Cinder is going to receive service tokens from other services
    it needs to have two options configured in the
    ``[keystone_authtoken]`` section of the configuration file:

    ``service_token_roles``
        The value is a list of roles; the service user passing the service
        token must have at least one of these roles or the token will be
        rejected. The default value is ``service``.

    ``service_token_roles_required``
        This is a boolean; the default value is ``False``.  It governs whether
        the keystone middleware used by the receiving service will pay any
        attention to the ``service_token_roles`` setting.  It should be set
        to ``True``.

.. _service-token-troubleshooting:

Troubleshooting
~~~~~~~~~~~~~~~

If you've configured this feature and are still having long-running
job failures, there are basically three degrees of freedom to take into
account: (1) each source service, (2) each receiving service, and (3) the
Identity Service (Keystone).

1.  Each source service (basically, Nova and Cinder) must have the
    ``[service_user]`` section in the **source service** configuration
    file filled in as described in the :ref:`service-token-configuration`
    section above.

    .. note::
       As of the Train release, Glance does not have the ability to pass
       service tokens.  It can receive them, though.  The place where you may
       still see a long running failure is when Glance is using a backend that
       requires Keystone validation (for example, the Swift backend) and the
       user token has expired.

2.  There are several things to pay attention to in Keystone:

    * When ``service_token_roles_required`` is enabled you must make sure that
      any service user who will be contacting that receiving service (and for
      whom you want to enable "service token" usage) has one of the roles
      specified in the receiving services's ``service_token_roles`` setting.
      (This is a matter of creating and assigning roles using the Identity
      Service API, it's not a configuration file issue.)

    * Even with a service token, an expired user token cannot be used
      indefinitely.  There's a Keystone configuration setting that controls
      this: ``[token]/allow_expired_window`` in the **Keystone** configuration
      file.  The default setting is 2 days, so some security teams may want to
      lower this just on general principles.  You need to make sure it's not
      set too low to be completely ineffective.

    * If you are using Fernet tokens, you need to be careful with your Fernet
      key rotation period.  Whoever sets up the key rotation has to pay
      attention to the ``[token]/allow_expired_window`` setting as well as the
      obvious ``[token]/expiration`` setting.  If keys get rotated faster than
      ``expiration`` + ``allow_expired_window`` seconds, an expired user
      token might not be decryptable, even though the request using it is
      being made within ``allow_expired_window`` seconds.

To summarize, you need to be aware of:

* Keystone: must allow a decent sized ``allow_expired_window`` (default is 2
  days)
* Each source service: must be configured to be able to create and send
  service tokens (default is OFF)
* Each receiving service: has to be configured to accept service tokens
  (default is ON) and require role verification (default is OFF)
