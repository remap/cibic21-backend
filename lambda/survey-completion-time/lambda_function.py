# This Lambda gets the userId/role from the GET endpoint URL, accesses the DynamoDB
# table for raw survey data, and gets the maximum timestamp for the userId/role.
# Return { 'completionTime': completionTime, 'surveyId': surveyId } .

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
                             Attr('processed').eq(True),
          # Limit each item to only the timestamp instead of fetching the entire survey.
          # We have to use ExpressionAttributeNames since timestamp is a reserved keyword.
          ProjectionExpression = '#c,surveyId',
          ExpressionAttributeNames = {'#c': 'timestamp'}
        )
        items = response['Items']
        
        completionTime = ''
        surveyId = ''
        if len(items) > 0:
            # Get the item with the max timestamp.
            maxItem = None
            for item in items:
                if maxItem == None or item['timestamp'] > maxItem['timestamp']:
                    maxItem = item
            completionTime = maxItem['timestamp']
            surveyId = maxItem['surveyId']

        return lambdaReply(200, {
          'completionTime': completionTime,
          'surveyId': surveyId
        })
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))
