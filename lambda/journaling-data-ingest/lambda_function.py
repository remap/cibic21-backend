import boto3
import os
import uuid
from common.cibic_common import *
from datetime import datetime

dynamoDbResource = boto3.resource('dynamodb')

def lambda_handler(event, context):
    requestsTable = dynamoDbResource.Table(CibicResources.DynamoDB.JournalingRequests)
    requestTimestamp = datetime.now().astimezone().strftime("%m/%d/%Y %H:%M:%S.%f UTC%z")
    requestId = str(uuid.uuid4()) # generate request uuid
    requestProcessed = False
    requestBody = ''
    requestReply = {}
    err = ''

    try:
        print ('event data ' + str(event))

        stage = event['requestContext']['stage']
        requestBody = json.loads(event['body'])
        print('body data ' + str(requestBody))

        requestProcessed = True
        requestReply = processedReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        requestReply = lambdaReply(420, str(err))

    # store request data in DynamoDB table
    requestsTable.put_item(Item = {
        'timestamp' : requestTimestamp,
        'requestId': requestId,
        'body' : json.dumps(requestBody),
        'processed' : requestProcessed,
        'error' : str(err)
    })

    return requestReply
