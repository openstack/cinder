============================
So You Want to Contribute...
============================

For general information on contributing to OpenStack, please check out the
`contributor guide <https://docs.openstack.org/contributors/>`_ to get started.
It covers all the basics that are common to all OpenStack projects: the
accounts you need, the basics of interacting with our Gerrit review system, how
we communicate as a community, etc.

Below will cover the more project specific information you need to get started
with the Cinder project, which is responsible for the following OpenStack
deliverables:

cinder
    | The OpenStack Block Storage service.
    | code: https://opendev.org/openstack/cinder
    | docs: https://cinder.openstack.org
    | api-ref: https://docs.openstack.org/api-ref/block-storage
    | Launchpad: https://launchpad.net/cinder

os-brick
    | Shared library for managing local volume attaches.
    | code: https://opendev.org/openstack/os-brick
    | docs: https://docs.openstack.org/os-brick
    | Launchpad: https://launchpad.net/os-brick

python-cinderclient
    | Python client library for the OpenStack Block Storage API; includes
      a CLI shell.
    | code: https://opendev.org/openstack/python-cinderclient
    | docs: https://docs.openstack.org/python-cinderclient
    | Launchpad: https://launchpad.net/python-cinderclient

python-brick-cinderclient-ext
    | Extends the python-cinderclient library so that it can handle local
      volume attaches.
    | code: https://opendev.org/openstack/python-brick-cinderclient-ext
    | docs: https://docs.openstack.org/python-brick-cinderclient-ext
    | Launchpad: (doesn't have its own space, uses python-cinderclient's)

cinderlib
    | Library that allows direct usage of Cinder backend drivers without
      cinder services.
    | code: https://opendev.org/openstack/cinderlib
    | docs: https://docs.openstack.org/cinderlib
    | Launchpad: https://launchpad.net/cinderlib

rbd-iscsi-client
    | Library that provides a REST client that talks to ceph-isci's
      rbd-target-api to export rbd images/volumes to an iSCSI initiator.
    | code: https://opendev.org/openstack/rbd-iscsi-client
    | docs: https://docs.openstack.org/rbd-iscsi-client
    | Launchpad: https://launchpad.net/rbd-iscsi-client

cinder-tempest-plugin
    | Contains additional Cinder tempest-based tests beyond those in the
      main OpenStack Integration Test Suite (tempest).
    | code: https://opendev.org/openstack/cinder-tempest-plugin
    | Launchpad: https://launchpad.net/cinder-tempest-plugin

See the ``CONTRIBUTING.rst`` file in each code repository for more
information about contributing to that specific deliverable.  Additionally,
you should look over the docs links above; most components have helpful
developer information specific to that deliverable.  (The main cinder
documentation is especially thorough in this regard and you should read
through it, particularly :ref:`background-concepts` and
:ref:`programming-howtos`.)

Communication
~~~~~~~~~~~~~

IRC
    We use IRC *a lot*.  You will, too.  You can find infomation about what
    IRC network OpenStack uses for communication (and tips for using IRC)
    in the `Setup IRC
    <https://docs.openstack.org/contributors/common/irc.html>`_
    section of the main `OpenStack Contributor Guide`.

    People working on the Cinder project may be found in the
    ``#openstack-cinder`` IRC channel during working hours
    in their timezone.  The channel is logged, so if you ask a question
    when no one is around, you can check the log to see if it's been
    answered: http://eavesdrop.openstack.org/irclogs/%23openstack-cinder/

weekly meeting
    Wednesdays at 14:00 UTC in the ``#openstack-meeting-alt`` IRC channel.
    Meetings are logged: http://eavesdrop.openstack.org/meetings/cinder/

    More information (including some pointers on meeting etiquette and an
    ICS file to put the meeting on your calendar) can be found at:
    http://eavesdrop.openstack.org/#Cinder_Team_Meeting

    The meeting agenda for a particular development cycle is kept on an
    etherpad.  You can find a link to the current agenda from the Cinder
    Meetings wiki page:
    https://wiki.openstack.org/wiki/CinderMeetings

    The last meeting of each month is held simultaneously in videoconference
    and IRC.  Connection information is posted on the meeting agenda.

    weekly bug squad meeting
        This is a half-hour meeting on Wednesdays at 15:00 UTC (right after the
        Cinder weekly meeting) in the ``#openstack-cinder`` IRC channel.  At
        this meeting, led by the Cinder Bug Deputy, we discuss new bugs that
        have been filed against Cinder project deliverables (and, if there's
        time, discuss the relevance of old bugs that haven't seen any action
        recently).  Info about the meeting is here:
        http://eavesdrop.openstack.org/#Cinder_Bug_Squad_Meeting

mailing list
    We use the openstack-discuss@lists.openstack.org mailing list for
    asynchronous discussions or to communicate with other OpenStack teams.
    Use the prefix ``[cinder]`` in your subject line (it's a high-volume
    list, so most people use email filters).

    More information about the mailing list, including how to subscribe
    and read the archives, can be found at:
    http://lists.openstack.org/cgi-bin/mailman/listinfo/openstack-discuss

virtual meet-ups
    From time to time, the Cinder project will have video meetings to
    address topics not easily covered by the above methods.  These are
    announced well in advance at the weekly meeting and on the mailing
    list.

    Additionally, the Cinder project has been holding two virtual mid-cycle
    meetings during each development cycle, roughly at weeks R-18 and R-9.
    These are used to discuss follow-up issues from the PTG before the spec
    freeze, and to assess the development status of features and priorities
    roughly one month before the feature freeze.  The exact dates of these are
    announced at the weekly meeting and on the mailing list.

    cinder festival of XS reviews
        This is a standing video meeting held the third Friday of each month
        from 14:00-16:00 UTC in meetpad to review very small patches that
        haven't yet been merged.  It's held in video so we can quickly discuss
        issues and hand reviews back and forth.  It is not recorded.  Info
        about the meeting is here:
        http://eavesdrop.openstack.org/#Cinder_Festival_of_XS_Reviews

physical meet-ups
    The Cinder project usually has a presence at the OpenDev/OpenStack
    Project Team Gathering that takes place at the beginning of each
    development cycle.  Planning happens on an etherpad whose URL is
    announced at the weekly meetings and on the mailing list.

Contacting the Core Team
~~~~~~~~~~~~~~~~~~~~~~~~

The cinder-core team is an active group of contributors who are responsible
for directing and maintaining the Cinder project.  As a new contributor, your
interaction with this group will be mostly through code reviews, because
only members of cinder-core can approve a code change to be merged into the
code repository.

You can learn more about the role of core reviewers in the OpenStack
governance documentation:
https://docs.openstack.org/contributors/common/governance.html#core-reviewer

The membership list of cinder-core is maintained in gerrit:
https://review.opendev.org/#/admin/groups/83,members

You can also find the members of the cinder-core team at the Cinder weekly
meetings.


New Feature Planning
~~~~~~~~~~~~~~~~~~~~

The Cinder project uses both "specs" and "blueprints" to track new features.
Here's a quick rundown of what they are and how the Cinder project uses them.

specs
    | Exist in the cinder-specs repository.
      Each spec must have a Launchpad blueprint (see below) associated with
      it for tracking purposes.

    | A spec is required for any new Cinder core feature, anything that
      changes the Block Storage API, or anything that entails a mass change
      to existing drivers.

    | The specs repository is: https://opendev.org/openstack/cinder-specs
    | It contains a ``README.rst`` file explaining how to file a spec.

    | You can read rendered specs docs at:
    | https://specs.openstack.org/openstack/cinder-specs/

blueprints
    | Exist in Launchpad, where they can be targeted to release milestones.
    | You file one at https://blueprints.launchpad.net/cinder

    | Examples of changes that can be covered by a blueprint only are:

    * adding a new volume, backup, or target driver; or
    * adding support for a defined capability that already exists in the
      base volume, backup, or target drivers

Feel free to ask in ``#openstack-cinder`` or at the weekly meeting if you
have an idea you want to develop and you're not sure whether it requires
a blueprint *and* a spec or simply a blueprint.

The Cinder project observes the following deadlines.  For the current
development cycle, the dates of each (and a more detailed description)
may be found on the release schedule, which you can find from:
https://releases.openstack.org/

* spec freeze (all specs must be approved by this date)
* new driver merge deadline
* new target driver merge deadline
* new feature status checkpoint
* driver features declaration
* third-party CI compliance checkpoint

Additionally, the Cinder project observes the OpenStack-wide deadlines,
for example, final release of non-client libraries (os-brick), final
release for client libraries (python-cinderclient), feature freeze,
etc.  These are also noted and explained on the release schedule for the
current development cycle.

Task Tracking
~~~~~~~~~~~~~

We track our tasks in Launchpad.  See the top of the page for the URL of each
Cinder project deliverable.

If you're looking for some smaller, easier work item to pick up and get started
on, search for the 'low-hanging-fruit' tag in the Bugs section.

When you start working on a bug, make sure you assign it to yourself.
Otherwise someone else may also start working on it, and we don't want to
duplicate efforts.  Also, if you find a bug in the code and want to post a
fix, make sure you file a bug (and assign it to yourself!) just in case someone
else comes across the problem in the meantime.

Reporting a Bug
~~~~~~~~~~~~~~~

You found an issue and want to make sure we are aware of it? You can do so in
the Launchpad space for the affected deliverable:

* cinder: https://bugs.launchpad.net/cinder
* os-brick: https://bugs.launchpad.net/os-brick
* python-cinderclient: https://bugs.launchpad.net/python-cinderclient
* python-brick-cinderclient-ext: same as for python-cinderclient, but tag
  the bug with 'brick-cinderclient-ext'
* cinderlib: https://bugs.launchpad.net/cinderlib
* cinder-tempest-plugin: https://bugs.launchpad.net/cinder-tempest-plugin

Getting Your Patch Merged
~~~~~~~~~~~~~~~~~~~~~~~~~

Before your patch can be merged, it must be *reviewed* and *approved*.

The Cinder project policy is that a patch must have two +2s before it can
be merged.  (Exceptions are documentation changes, which require only a
single +2, and specs, for which the PTL may require more than two +2s,
depending on the complexity of the proposal.)  Only members of the
cinder-core team can vote +2 (or -2) on a patch, or approve it.

.. note::
   Although your contribution will require reviews by members of
   cinder-core, these aren't the only people whose reviews matter.
   Anyone with a gerrit account can post reviews, so you can ask
   other developers you know to review your code ... and you can
   review theirs.  (A good way to learn your way around the codebase
   is to review other people's patches.)

   If you're thinking, "I'm new at this, how can I possibly provide
   a helpful review?", take a look at `How to Review Changes the
   OpenStack Way
   <https://docs.openstack.org/project-team-guide/review-the-openstack-way.html>`_.

   There are also some Cinder project specific reviewing guidelines
   in the :ref:`reviewing-cinder` section of the Cinder Contributor Guide.

Patches lacking unit tests are unlikely to be approved.  Check out the
:ref:`testing-cinder` section of the Cinder Contributors Guide for a
discussion of the kinds of testing we do with cinder.

In addition, some changes may require a release note.  Any patch that
changes functionality, adds functionality, or addresses a significant
bug should have a release note.  You can find more information about
how to write a release note in the :ref:`release-notes` section of the
Cinder Contributors Guide.

  Keep in mind that the best way to make sure your patches are reviewed in
  a timely manner is to review other people's patches.  We're engaged in a
  cooperative enterprise here.

If your patch has a -1 from Zuul, you should fix it right away, because
people are unlikely to review a patch that is failing the CI system.

* If it's a pep8 issue, the job leaves sufficient information for you to fix
  the problems yourself.
* If you are failing unit or functional tests, you should look at the
  failures carefully.  These tests guard against regressions, so if
  your patch causing failures, you need to figure out exactly what is
  going on.
* The unit, functional, and pep8 tests can all be run locally before you
  submit your patch for review.  By doing so, you can help conserve gate
  resources.

How long it may take for your review to get attention will depend on the
current project priorities.  For example, the feature freeze is at the
third milestone of each development cycle, so feature patches have the
highest priority just before M-3.  Likewise, once the new driver freeze
is in effect, new driver patches are unlikely to receive timely reviews
until after the stable branch has been cut (this happens three weeks before
release).  Similarly, os-brick patches have review priority before the
nonclient library release deadline, and cinderclient patches have priority
before the client library release each cycle.  These dates are clearly
noted on the release schedule for the current release, which you can find
from https://releases.openstack.org/

You can see who's been doing what with Cinder recently in Stackalytics:
https://www.stackalytics.io/report/activity?module=cinder-group

Project Team Lead Duties
~~~~~~~~~~~~~~~~~~~~~~~~

All common PTL duties are enumerated in the `PTL guide
<https://docs.openstack.org/project-team-guide/ptl.html>`_.

Additional responsibilities for the Cinder PTL can be found by reading through
the :ref:`managing-development` section of the Cinder documentation.
