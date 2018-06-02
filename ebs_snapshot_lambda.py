#!/usr/bin/env python
"""
Name: ebs_snapshot_lambda.py
Purpose: Snapshot an ec2 EBS volume
Version: 1.0
Date: September 11, 2017
Author: Mark Saum
Email: mark@saum.net
GitHub: https://github.com/msaum

-------------------------------------------------------------------------------

Revisions:
1.0 - Initial build

-------------------------------------------------------------------------------

References:
Cleaning up AWS with Boto3
  http://blog.ranman.org/cleaning-up-aws-with-boto3/
Authoring Lambda Functions in Python
  http://docs.aws.amazon.com/lambda/latest/dg/python-lambda.html
AWS Snapshot Tool
  https://github.com/evannuil/aws-snapshot-tool/blob/master/makesnapshots.py
delete_snapshots.py (boto not boto3, but shows date filtering)
  https://gist.github.com/kjoconnor/7344485
Snapshot an EC2 Instance in Boto3
  https://gist.github.com/KitaitiMakoto/e7658b5f17cd0b0af4e2
-------------------------------------------------------------------------------

Set IAM Policy on Volumes
  http://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_examples.html#iam-policy-example-ec2-tag-permissions

Demystifying EC2 Resource-Level Permissions
  https://blogs.aws.amazon.com/security/post/Tx2KPWZJJ4S26H6/Demystifying-EC2-Resource-Level-Permissions

-------------------------------------------------------------------------------
"""

__author__ = 'msaum'

import argparse
import boto3
import json
import logging
import os
import pytz
from ConfigParser import SafeConfigParser
from datetime import date, datetime

# -------------------------------------------------------------------------------
# setup simple logging for INFO
# -------------------------------------------------------------------------------
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# -------------------------------------------------------------------------------
# Process Arguments
# -------------------------------------------------------------------------------
parser = argparse.ArgumentParser(description='Snapshot an arbitrary volume via Lambda..')
parser.add_argument("--debug", "-d", help="turn on debugging output", action="store_true")
parser.add_argument("--verbose", "-v", help="turn on program status information output", action="store_true")
args = parser.parse_args()
logger.setLevel('CRITICAL')
if args.verbose:
    logger.setLevel('INFO')
if args.debug:
    logger.setLevel('DEBUG')


# -------------------------------------------------------------------------------
# Lambda Entry Point
# -------------------------------------------------------------------------------
def lambda_handler(event, context):
    '''Program main entry point
    :param AWS Lambda event and context, if running under AWS Lambda
    :return: None
    '''

    logging.info('** ' + os.path.basename(__file__) + ' begin')

    # Read program configuration information
    parser = SafeConfigParser()
    try:
        parser.read('ebs_snapshot_lambda.ini')
        aging_days = parser.get('global', 'aging_days')
        tag_key = parser.get('global', 'tag_key')
        tag_value = parser.get('global', 'tag_value')
    except Exception, e:
        logging.error('Failed to parse ebs_snapshot_lambda.ini configuration file.', exc_info=True)
        raise

    # define the connection
    try:
        # Create an EC2 Service Resource (https://boto3.readthedocs.io/en/latest/reference/services/ec2.html#service-resource)
        # This is primarily for doing the snapshots
        ec2resource = boto3.resource('ec2')
        # Creates a low-level client representing Amazon Elastic Compute Cloud (EC2) (https://boto3.readthedocs.io/en/latest/reference/services/ec2.html#id612)
        # This is primarily for doing queries of the EC2 infrastructure data
        ec2client = boto3.client('ec2')

    except Exception, e:
        logging.error('Failed to open boto3 connection.', exc_info=True)
        raise

    instance_list = list_instances_by_tag_value(ec2client, tag_key, tag_value)
    for instance in instance_list:
        logging.info("** Processing instance: " + instance)
        volumes = list_volumes(ec2client, instance)
        for volume in volumes:
            logging.info("Processing volume: " + volume)
            snapshot_volid(ec2resource, volume, instance, aging_days)

    # Lambda Status Info
    if context != '':
        logging.info("Log stream name: %s", context.log_stream_name)
        logging.info("Log group name: %s", context.log_group_name)
        logging.info("Request ID: %s", context.aws_request_id)
        logging.info("Mem. limits(MB): %s", context.memory_limit_in_mb)
        logging.info("Time remaining (MS): %s", context.get_remaining_time_in_millis())
    logging.info('** ' + os.path.basename(__file__) + ' end')


def list_instances_by_tag_value(ec2client, tag_key, tag_value):
    '''Creates a list of EC2 instances, given a tag key and tag value
    :param ec2client connection, EC2 tag name, EC2 tag value
    :return: A simple list of instances
    :rtype: list
    '''
    response = ec2client.describe_instances(
        Filters=[
            {
                'Name': 'tag:' + tag_key,
                'Values': [tag_value]
            }
        ]
    )
    instancelist = []
    for reservation in (response["Reservations"]):
        for instance in reservation["Instances"]:
            instancelist.append(instance["InstanceId"])
    return instancelist


def list_volumes(ec2client, instance_id):
    '''Creates a list of volumes for an EC2 instance
    :param boto3 client ec2 object
    :return: A simple list of instances
    :rtype: list
    '''

    volume_list = []
    response = ec2client.describe_instances(
        Filters=[
            {'Name': 'instance-id', 'Values': [instance_id]}
        ]
    )

    for reservation in response["Reservations"]:
        for instances in reservation["Instances"]:
            for block_device_mappings in instances["BlockDeviceMappings"]:
                logging.debug(json.dumps(block_device_mappings, indent=2, default=str))
                volume_list.append(block_device_mappings["Ebs"]["VolumeId"])
    return volume_list


def snapshot_volid(ec2resource, vol_id, instance, aging_days):
    '''Creates a list of instances in the current EC2/AWS context
    :param1 boto3 client ec2 object
    :param2 volumeid to snapshot (string)
    :param3 number of days to age snapshots before deleting (integer)
    :return: None
    '''

    today = date.today()

    # -----------------
    # Create snapshot
    # -----------------
    try:
        if not args.debug:
            new_snapshot = ec2resource.create_snapshot(
                VolumeId=vol_id,
                Description='[' + instance + ']' + '[' + vol_id + '] ' + today.isoformat() + ' Snapshot'
            )
    except Exception, e:
        logging.error('Failed to create the volume snapshot.', exc_info=True)
        raise

    # -----------------
    # Set tags
    # -----------------
    try:
        if not args.debug:
            ec2resource.create_tags(
                Resources=[new_snapshot.id],
                Tags=[
                    {'Key': 'Name',
                     'Value': '[' + instance + ']' + '[' + vol_id + '] ' + today.isoformat() + ' Snapshot'},
                    {'Key': 'Date', 'Value': today.isoformat()}
                ])
    except Exception, e:
        logging.error('Failed to tag the volume snapshot we created.', exc_info=True)
        raise

    # -----------------
    # Find snapshots older than 10 days and delete them
    # -----------------
    try:
        snapshot_iterator = ec2resource.snapshots.filter(
            DryRun=False,
            Filters=[
                {
                    'Name': 'volume-id',
                    'Values': [
                        vol_id,
                    ]
                },
            ],
        )

    except Exception, e:
        logging.error('Failed to iterate the list of snapshots for the volume.', exc_info=True)
        raise

    utc = pytz.UTC

    for snapshot in snapshot_iterator:
        image_aging = snapshot.start_time - utc.localize(datetime.now())
        image_age = abs(image_aging.days)
        snapshot_start_time = snapshot.start_time.strftime("%Y/%m/%d")

        if (image_age > aging_days):
            log_string = "AGED: " + " Volume_id: " + snapshot.volume_id + ", Snap Date: " + snapshot_start_time + \
                         ", Aging: " + str(image_age) + ", ID: " + snapshot.snapshot_id
            logging.info(log_string)

            try:
                if not args.debug:
                    snapshot.delete()
            except Exception, e:
                logging.error('Failed to delete the aged snapshot.', exc_info=True)
                raise

        else:
            log_string = "CURRENT: " + " Volume_id: " + snapshot.volume_id + ", Snap Date: " + snapshot_start_time + \
                         ", Aging: " + str(image_age) + ", ID: " + snapshot.snapshot_id
            logging.info(log_string)


# -------------------------------------------------------------------------------
# Console Entry Point
# -------------------------------------------------------------------------------
if __name__ == "__main__":
    lambda_handler('', '')
