# This Lambda gets the userId/role from the GET endpoint URL, accesses the DynamoDB
# table for raw survey data, and gets the maximum timestamp for the userId/role.
# Return { 'completionTime': completionTime } .

import boto3
from boto3.dynamodb.conditions import Attr
from common.cibic_common import *

dynamoDbResource = boto3.resource('dynamodb')

def lambda_handler(event, context):
    surveysTable = dynamoDbResource.Table(CibicResources.DynamoDB.RawSurveyResponses)

    try:
        print('survey-completion-time event data: ' + str(event))

        stage = event['requestContext']['stage']
        userId = event['pathParameters']['userId']
        role = event['pathParameters']['role']
        print('Getting completion time for: ' + userId + '/' + role)

        response = surveysTable.scan(
          FilterExpression = Attr('userId').eq(userId) &
                             Attr('role').eq(role) &
                             Attr('processed').eq(True)
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
