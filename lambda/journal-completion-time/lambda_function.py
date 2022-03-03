# This Lambda gets the userId/role from the GET endpoint URL, accesses the DynamoDB
# table for raw journal data, and gets the maximum timestamp for the userId/role.
# Return { 'completionTime': completionTime } .

import boto3
from boto3.dynamodb.conditions import Attr
from common.cibic_common import *

dynamoDbResource = boto3.resource('dynamodb')

def lambda_handler(event, context):
    journalsTable = dynamoDbResource.Table(CibicResources.DynamoDB.JournalingRequests)

    try:
        print('journal-completion-time event data: ' + str(event))

        stage = event['requestContext']['stage']
        userId = event['pathParameters']['userId']
        role = event['pathParameters']['role']
        print('Getting completion time for: ' + userId + '/' + role)

        response = journalsTable.scan(
          FilterExpression = Attr('userId').eq(userId) &
                             Attr('role').eq(role) &
                             Attr('processed').eq(True),
          # Limit each item to only the timestamp instead of fetching the entire journal entry.
          # We have to use ExpressionAttributeNames since timestamp is a reserved keyword.
          ProjectionExpression = '#c',
          ExpressionAttributeNames = {'#c': 'timestamp'}
        )
        items = response['Items']
        
        completionTime = ''
        if len(items) > 0:
            # Get the max timestamp. This uses a generator so is only iterated once.
            completionTime = max(item['timestamp'] for item in items)

        return lambdaReply(200, { 'completionTime': completionTime })
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))
