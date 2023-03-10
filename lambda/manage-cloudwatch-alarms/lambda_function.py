# This Lambda iterates through all the log groups and sets up a metric filter
# and alarm to send an SNS if there is an error message in the log.
# This is meant to be run directly from the Lambda console.

import os
import boto3

AWS_REGION = 'us-west-1'
NAMESPACE = 'cibic21-cloudwatch-metric-namespace'
CLOUDWATCH_ERROR_TOPIC = os.environ['ENV_SNS_CLOUDWATCH_ERROR']

logs = boto3.client('logs', region_name=AWS_REGION)
cloudwatch = boto3.client('cloudwatch', region_name=AWS_REGION)

def lambda_handler(event, context):
    response = logs.describe_log_groups()
    for logGroup in response['logGroups']:
        logGroupName = logGroup['logGroupName']
        if not logGroupName.startswith('/aws/lambda/'):
            continue

        logGroupNameSuffix = logGroupName[logGroupName.rfind('/')+1:]
        print("Creating metric filter and alarm for " + logGroupNameSuffix)
        metricName = 'timeout-or-exception-count-for-' + logGroupNameSuffix
        logs.put_metric_filter(
            logGroupName=logGroupName,
            filterName='timeout-or-exception',
            filterPattern='?"Task timed out" ?"caught exception" ?"[ERROR]"',
            metricTransformations=[
                {
                    'metricName': metricName,
                    'metricNamespace': NAMESPACE,
                    'metricValue': '1',
                    'defaultValue': 0
                }
            ]
        )

        cloudwatch.put_metric_alarm(
            AlarmName='cibic21-cloudwatch-alarm-timeout-or-exception-for-' + logGroupNameSuffix,
            AlarmActions=[CLOUDWATCH_ERROR_TOPIC],
            ComparisonOperator='GreaterThanOrEqualToThreshold',
            EvaluationPeriods=1,
            MetricName=metricName,
            Namespace=NAMESPACE,
            Period=300,
            Statistic='Sum',
            Threshold=1,
            AlarmDescription='Web Traffic Monitoring'
        )

    return {
        'statusCode': 200,
        'body': 'processed'
    }
