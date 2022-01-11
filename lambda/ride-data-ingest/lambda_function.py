import boto3
import os
from common.cibic_common import *
from datetime import datetime

dynamoDbClient = boto3.client('dynamodb')
dynamoDbResource = boto3.resource('dynamodb')

# resource ARNs must be defined as lambda environment variables
# see https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html#configuration-envvars-config
# requestTableArn = os.environ['ENV_DYNAMODB_ENDPOINT_REQUESTS_TABLE_NAME']

def lambda_handler(event, context):
    requestsTable = dynamoDbResource.Table(CibicResources.DynamoDB.EndpointRequests)
    requestTimestamp = datetime.now().astimezone().strftime("%m/%d/%Y %H:%M:%S.%f UTC%z")
    requestProcessed = False
    requestBody = ''

    try:
        print (event)
        requestBody = json.loads(event['body'])
        print(requestBody)

        # sns_client = boto3.client('sns')
        # sns_client.publish(TopicArn="arn:aws:sns:us-west-1:627943213575:test-new-ride",
        #   Message="New ride.", Subject="CiBiC notification")
    except:
        err = reportError()
        requestsTable.put_item(Item = { 'timestamp' : requestTimestamp,'body' : json.dumps(requestBody), 'processed' : False, 'error' : str(err)})

        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    # store request data in DynamoDB table
    requestsTable.put_item(Item = { 'timestamp' : requestTimestamp, 'body' : json.dumps(requestBody), 'processed' : requestProcessed })

    return processedReply()
