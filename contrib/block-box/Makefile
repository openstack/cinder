CINDER_BRANCH ?= master# master, stable/ocata, refs/changes/67/418167/1
NAME_PREFIX ?= ""
PLATFORM ?= debian:stretch# ubuntu:xenial, centos:7
TAG ?= debian-cinder:latest

all: base lvm
blockbox: base lvm

base:
	docker build https://git.openstack.org/openstack/loci.git \
		--build-arg PROJECT=cinder \
		--build-arg FROM=$(PLATFORM) \
		--build-arg PROJECT_REF=$(CINDER_BRANCH) \
		--tag $(TAG)
lvm:
	docker build https://git.openstack.org/openstack/loci.git \
		--build-arg PROJECT=cinder \
		--build-arg FROM=$(PLATFORM) \
		--build-arg PROJECT_REF=$(CINDER_BRANCH) \
		--build-arg PROFILES="lvm" \
		--tag lvm-$(TAG)
