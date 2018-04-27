#!/usr/bin/env python
import argparse

import yaml
import sys
import subprocess
import re
import os.path

import passlib.pwd
import passlib.hash

import jinja2

from cryptography.hazmat.primitives import serialization as crypto_serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend as crypto_default_backend


def render_template(file, **kwargs):
    env = jinja2.Environment(loader = jinja2.FileSystemLoader('.'))
    template = env.get_template(file)
    return template.render( **kwargs )


def create_ssh_key():
    key = rsa.generate_private_key(
        backend=crypto_default_backend(),
        public_exponent=65537,
        key_size=2048
    )
    private_key = key.private_bytes(
        crypto_serialization.Encoding.PEM,
        crypto_serialization.PrivateFormat.PKCS8,
        crypto_serialization.NoEncryption())
    public_key = key.public_key().public_bytes(
        crypto_serialization.Encoding.OpenSSH,
        crypto_serialization.PublicFormat.OpenSSH
    )
    return (public_key.decode('utf-8'), private_key.decode('utf-8'))


def create_users(args):
    users = args.users

    user_names = []

    if os.path.isfile(users):
        with open(users) as fh:
            for line in fh:
                user, *password = line.split()
                if not password:
                    password = [passlib.pwd.genword(length=10)]
                user_names.append([user, password[0]])
    else:
        for n in range(users):
            password = passlib.pwd.genword(length=10)
            user_names.append(["user{:0>3}".format(n), password])

    uid_start = 2000
    users = {}
    for n, user in enumerate(user_names):
        (username, password) = user
        num      = "{:0>3}".format(n)
        host     = "{}-node-{}".format(args.cluster_prefix, num)
        hash     = passlib.hash.sha512_crypt.using(rounds=5000).hash(password)
        uid      = uid_start + n

        public_key, private_key = create_ssh_key()

        users[host] = [{
            "host": host,
            "user": username,
            "password": password,
            "hash": hash,
            "uid": uid,
            "gid": uid,
            "private_key": private_key,
            "public_key": public_key,
            "num": num
        }]

    return users


def generate_config_file(**args):
    with open('config.tfvars', 'w') as fh:
        fh.write(render_template('config.tfvars.jj2', **args))


def generate_vars_file(args, users):
    data = {
        "cluster_prefix": args.cluster_prefix,
        "master_host": "{}-master-000".format(args.cluster_prefix),
        "master_ip": "{{ hostvars.get(master_host)[\"ansible_host\"] }}",
        "users": users,
    }

    vars_file = 'playbooks/group_vars/all'

    with open(vars_file, 'w') as fh:
        fh.write(yaml.dump(data, default_flow_style=False))


def generate_users_file(users):
    with open('passwords.txt', 'w') as fh:
        for u in [u for host in users.values() for u in host]:
            fh.write("{}\t{}\n".format(u['user'], u['password']))


def find_external_network():
    p = subprocess.run(['./kn', 'openstack', 'network', 'list', '--external'], stdout=subprocess.PIPE)
    for line in p.stdout.decode('utf8').split("\r\n"):
        m = re.search(r'([a-f0-9-]+) \| (Public External IPv4 network)', line, re.IGNORECASE)
        if m:
            id = m.group(1)
            name = m.group(2)
            return (id, name)
    return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--users',            dest='users',            type=str, required=True, help='The number of users to generate credentials for')
    parser.add_argument('--cluster-prefix',   dest='cluster_prefix',   type=str, default='virt-workshop')
    parser.add_argument('--master-flavor',    dest='master_flavor',    type=str, default='ssc.small')
    parser.add_argument('--master-disk-size', dest='master_disk_size', type=int, default=0)
    parser.add_argument('--node-flavor',      dest='node_flavor',      type=str, default='ssc.small')
    parser.add_argument('--node-disk-size',   dest='node_disk_size',   type=int, default=0)

    args = parser.parse_args()

    users = create_users(args)
    (id,name) = find_external_network()

    node_count = len(users)

    generate_config_file(**vars(args), external_network_id=id, external_network_name=name, node_count=node_count)
    generate_vars_file(args, users)
    generate_users_file(users)

    print("""Course setup is finished
 To spin up the cloud run: ./kn apply
 The usernames and passwords are in the file passwords.txt""")


if __name__ == '__main__':
    main()
