#! /usr/bin/env python3

import http.client as http
import boto3 as aws
import argparse
import time


def _get_public_ipv4():
    conn = http.HTTPConnection('169.254.169.254', 80)
    conn.request('GET', '/latest/meta-data/public-ipv4')
    ipr = conn.getresponse()
    return ipr.read().decode('utf-8')


def update_dns(zone_id, hostname, action='UPSERT', ip=None, synchronous=False):
    """
    https://docs.aws.amazon.com/Route53/latest/APIReference/API_ChangeResourceRecordSets.html
    :param zone_id:
    :param hostname:
    :param action:
    :param ip:
    :param synchronous:
    :return: None
    """
    client = aws.client('route53')
    if ip is None:
        ip = _get_public_ipv4()
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
    if synchronous:
        cid = response['ChangeInfo']['Id']
        response = client.get_change(Id=cid)
        while response['ChangeInfo']['Status'] == 'PENDING':
            response = client.get_change(Id=cid)
            time.sleep(5)


def cli():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command')
    dns_parser = subparsers.add_parser('updatedns',
                                       description='Update a A DNS record in Route53 possibly synchronously.')
    dns_parser.add_argument('zoneid', help='A Route53 Zone ID')
    dns_parser.add_argument('hostname', help='The hostname to set')
    dns_parser.add_argument('-a', '--action', help='<CREATE|DELETE|UPSERT>. Default is UPSERT', default='UPSERT')
    dns_parser.add_argument('--ip', help='The IP to set. The default is to use the public IP of the current instance.',
                            default=None)
    dns_parser.add_argument('-s', '--synchronous',
                            help='Wait until the change have propagated to all Amazon Route 53 DNS servers.',
                            action='store_true')
    args = parser.parse_args()
    if args.command == 'updatedns':
        update_dns(args.zoneid, args.hostname, args.action, args.ip, args.synchronous)
    else:
        parser.print_usage()