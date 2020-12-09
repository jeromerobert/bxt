#! /usr/bin/env python3

import os
import io
import gzip
import boto3
import argparse
import subprocess
import time
import base64
import datetime
import copy
import json
import urllib.request
import urllib.parse


def _load_config(filename):
    # function level import to make yaml optional
    import yaml
    if filename is None:
        filename = 'cluster.yaml'
    if not os.path.isfile(filename):
        filename = os.path.join(os.path.expanduser('~'), '.cluster.yaml')
    with open(filename) as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    with open(config['cloud-init']) as f:
        config['cloud-init'] = yaml.load(f, Loader=yaml.FullLoader)
    return config


def _readfile(filename):
    with open(filename, "rb") as f:
        return f.read()


def _format_cloud_init(config, job_script, environ):
    for wf in config['cloud-init']['write_files']:
        if wf['content'] == '@bxt@':
            wf['content'] = _readfile(__file__)
        elif wf['content'] == '@id_rsa@' or wf['content'] == '@id_ed25519@':
            wf['content'] = _readfile(config['ssh-key'])
        elif wf['content'] == '@environ@':
            wf['content'] = '\n'.join(environ)
        elif wf['content'] == '@job@':
            wf['content'] = _readfile(job_script)


def _gzip(data):
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb") as f:
       f.write(data.encode())
    return out.getvalue()


def _s3region(url):
    s3 = boto3.resource("s3")
    bucket = urllib.parse.urlparse(url).netloc
    return s3.meta.client.get_bucket_location(Bucket=bucket)["LocationConstraint"]


def _print_ip(client, run_instance_resp):
    ids = [ x['InstanceId'] for x in run_instance_resp['Instances'] ]
    ips = []
    while len(ips) != len(ids):
        r = client.describe_instances(InstanceIds=ids)
        ips = [x['PrivateIpAddress'] for x in r['Reservations'][0]['Instances'] if x['PrivateIpAddress']]
    for i, ip in enumerate(ips):
        print(i, ip)


def _sub(job_script, job_name, environ, configfile):
    # function level import to make yaml optional
    import yaml
    conf = _load_config(configfile)
    environ = [] if environ is None else environ
    environ.append('BXT_JOB_NAME=' + job_name)
    # The region of the S3 bucket, not of the actual run
    environ.append('AWS_DEFAULT_REGION=' + _s3region(conf['s3-data']))
    environ.append('BXT_S3_URL=' + conf['s3-data'])
    environ.append('BXT_S3_OUTPUT_URL=' + conf['s3-output'])
    environ = ['export '+x for x in environ]
    _format_cloud_init(conf, job_script, environ)
    subprocess.call(['aws', 's3', 'sync', '--delete',
                     conf['localdata'], conf['s3-data']])
    client = boto3.client('ec2', region_name=conf['region'])
    instance_config = conf['instance-config']
    instance_config['UserData'] = _gzip('#cloud-config\n' +
        yaml.dump(conf['cloud-init']))
    instance_config['TagSpecifications'][0]['Tags'] = [
        {'Key': 'JobName', 'Value': job_name}
    ]
    _print_ip(client, client.run_instances(**instance_config))


def _getmeta(url):
    META_URL = 'http://169.254.169.254/latest/meta-data/'
    response = urllib.request.urlopen(META_URL+url)
    data = response.read()
    return data.decode('utf-8')


def _hosts():
    """
    Return the list of hosts in the cluster
    """
    region = _getmeta('placement/availability-zone')[:-1]
    client = boto3.client('ec2', region_name=region)
    reservation_id = _getmeta('reservation-id')
    job_name = 'unknown'
    response = client.describe_instances(
        Filters=[{'Name': 'reservation-id', 'Values': [reservation_id]}])
    instances = response['Reservations'][0]['Instances']
    names = [None] * len(instances)
    for tag in instances[0]['Tags']:
        if tag['Key'] == 'Name':
            job_name = tag['Value']
    for i in instances:
        names[i['AmiLaunchIndex']] = i['PrivateIpAddress']
    return names


def _rank():
    return int(_getmeta('ami-launch-index'))


def update_dns(zone_id, hostnames, action='UPSERT', ip=None, synchronous=False):
    """
    https://docs.aws.amazon.com/Route53/latest/APIReference/API_ChangeResourceRecordSets.html
    :param zone_id:
    :param hostname:
    :param action:
    :param ip:
    :param synchronous:
    :return: None
    """
    client = boto3.client('route53')
    if ip is None:
        ip = _getmeta('public-ipv4')
    cids = []
    for hostname in hostnames:
        response = client.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={
                'Changes': [{
                    'Action': action,
                    'ResourceRecordSet': {
                        'Name': hostname,
                        'Type': 'A',
                        'TTL': 60,
                        'ResourceRecords': [{'Value': ip}],
                    },
                }],
            },
        )
        cids.append(response['ChangeInfo']['Id'])
    if synchronous:
        time.sleep(30)
        while len(cids) > 0:
            newcids = []
            for cid in cids:
                response = client.get_change(Id=cid)
                if response['ChangeInfo']['Status'] == 'PENDING':
                    newcids.append(cid)
            cids = newcids
            time.sleep(5)


def parse_cli():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command')
    sub_parser = subparsers.add_parser('sub', help='Submit a new job.')
    sub_parser.add_argument('-e', '--env', action='append',
                            help='Set environment variables in the cluster')
    sub_parser.add_argument(
        'job_name', help='The name of the job (available as BXT_JOB_NAME in environment).')
    sub_parser.add_argument(
        'job_script', help='The script to execute on the master node of the cluster.')
    sub_parser.add_argument(
        '-c', '--config', help='The cluster.yaml file.', default=None)
    subparsers.add_parser('np',
                          help='Print the number of nodes in the cluster.')
    subparsers.add_parser('rank',
                          help='Print the rank of this node in the cluster.')
    subparsers.add_parser('hosts',
                          help='Print the comma separated list of nodes in this cluster.')
    nfs_parser = subparsers.add_parser('nfs',
                                       help='Export NFS from the master node and mount on other nodes.')
    nfs_parser.add_argument(
        '--user', help='User account to use to ssh other nodes (must be mount sudoer).', default="root")
    nfs_parser.add_argument('folder', help='The folder to export/mount.')
    nfs_parser.add_argument('--no-sync', help='Disable SSH synchronization/barrier before mount', action='store_false')
    subparsers.add_parser(
        'blkdev', help='List unmounted/unpartitionned block devices.')
    subparsers.add_parser('poweroff', help='Power off the cluster.')
    barrier_parser = subparsers.add_parser('barrier', help='Synchronize all nodes using ssh')
    barrier_parser.add_argument('--user', help='User account to use to ssh other nodes.', default="root")
    barrier_parser.add_argument('--cmd', help='Command to execute on each nodes (must return true for success).', default="true")
    rmlog_parser = subparsers.add_parser('rmlog', description='Remove all streams from a Cloudwatch log group.')
    rmlog_parser.add_argument('--region', help='The AWS region.')
    rmlog_parser.add_argument('loggroup', help='The log group name.')
    dns_parser = subparsers.add_parser('updatedns',
                                       help='Update a A DNS record in Route53 possibly synchronously.')
    dns_parser.add_argument('zoneid', help='A Route53 Zone ID')
    dns_parser.add_argument('hostname', help='The names to set', nargs='+')
    dns_parser.add_argument(
        '-a', '--action', help='<CREATE|DELETE|UPSERT>. Default is UPSERT', default='UPSERT')
    dns_parser.add_argument('--ip', help='The IP to set. The default is to use the public IP of the current instance.',
                            default=None)
    dns_parser.add_argument('-s', '--synchronous',
                            help='Wait until the change have propagated to all Amazon Route 53 DNS servers.',
                            action='store_true')
    return parser.parse_args(), parser


def nfs_exports(rank, names, folder, user, sync_cmd = "/sbin/mount.nfs4 -V"):
    if rank != 0:
        return
    master = names[0]
    others = names[1:]
    with open('/etc/exports', 'w') as f:
        f.write(folder)
        for on in others:
            f.write(' ' + on + '(rw,async,no_subtree_check)')
        f.write('\n')
    subprocess.check_call(['exportfs', '-ra'])
    if sync_cmd:
        _sync(rank, names, user, sync_cmd)
    for h in others:
        cmd = ['su', user, '-c',
               'ssh {} sudo mount {}:{} {}'.format(h, master, folder, folder)]
        print(cmd)
        subprocess.check_call(cmd)


def _poweroff(rank, names):
    if rank != 0:
        return
    others = names[1:]
    for h in others:
        subprocess.call(['ssh', h, 'sudo', 'poweroff'])
    subprocess.check_call(['sudo', 'poweroff'])


def _sync(rank, names, user, remote_cmd):
    """
    Test each nodes of the cluster with ssh mount.nfs4 and wait until
    each actually return true
    """
    TIMEOUT_MINUTES = 5
    if rank != 0:
        return
    names_to_keep = list(names)
    start = time.time()
    processes = []
    while len(names_to_keep) > 0 or len(processes) > 0:
        if time.time()-start > TIMEOUT_MINUTES * 60:
            raise TimeoutError(
                "Some cluster nodes still not up after {} minutes.".format(TIMEOUT_MINUTES))
        for name in names_to_keep:
            cmd = ['su', user, '-c', 'ssh {} "{}"'.format(name, remote_cmd)]
            print(' '.join(cmd))
            processes.append((name, subprocess.Popen(cmd),))
        names_to_keep = []
        process_to_keep = []
        for n, p in processes:
            p.poll()
            if p.returncode is None:
                # ssh has not yet return, we'll test it again at next iteration
                process_to_keep.append((n, p,))
            elif p.returncode != 0:
                print(p.args, "returned", p.returncode)
                # Return code is not 0 so ssh returned an error. The Popen object is discarded and we try again.
                names_to_keep.append(n)
            # default: p.returncode == 0 so the node is up
        processes = process_to_keep
        time.sleep(0.1)


def _blkdev():
    output = json.loads(subprocess.check_output(['lsblk', '-J']).decode())
    blockdevices = []
    for bdev in output['blockdevices']:
        if 'children' not in bdev:
            blockdevices.append('/dev/'+bdev['name'])
    print(len(blockdevices), ' '.join(blockdevices))


def rmlog(loggroup, region=None):
    client = aws.client('logs', region)
    while True:
        response = client.describe_log_streams(logGroupName=loggroup)
        toremove = [x['logStreamName'] for x in response['logStreams']]
        if len(toremove) == 0:
            break
        else:
            print("Deleting {} streams".format(len(toremove)))
            for n in toremove:
                client.delete_log_stream(logGroupName=loggroup, logStreamName=n)


def main():
    args, parser = parse_cli()
    cmd = args.command
    if cmd == 'updatedns':
        update_dns(args.zoneid, args.hostname,
                   args.action, args.ip, args.synchronous)
    elif args.command == 'rmlog':
        rmlog(args.loggroup, region=args.region)
    elif cmd == 'sub':
        _sub(args.job_script, args.job_name, args.env, args.config)
    elif cmd == 'blkdev':
        _blkdev()
    elif cmd == 'np':
        print(len(_hosts()))
    elif cmd == 'rank':
        print(_rank())
    elif cmd == 'nfs':
        nfs_exports(_rank(), _hosts(), args.folder, args.user)
    elif cmd == 'poweroff':
        _poweroff(_rank(), _hosts())
    elif cmd == 'hosts':
        print(','.join(_hosts()))
    elif cmd == 'barrier':
        _sync(_rank(), _hosts(), args.user, args.cmd)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
